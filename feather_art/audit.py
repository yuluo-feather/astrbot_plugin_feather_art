"""输出契约审计：检查生成的文档是否守羽画的家规。

说清楚：这是「生成器契约检查」，不是通用消毒器——只管我们自己产出的文档
合不合规，防的是哪天不经意把涂色写成 url() 这种事故，不负责抵御外面的恶意 HTML。

按方言分两套规矩，公共部分只此一份：
- 公共：元素与属性白名单、恰好一个 main.illustration、restrictive CSP、
  无脚本无图片无外链无 base64、CSS 里不许注释与转义序列；
- css 方言：div.shape 必须带 clip-path:polygon(...)、class 只许
  shape/underpainting/p<数字>/layer（l<数字> 与 @keyframes 配对）、url() 一律不许；
- svg 方言：只许 svg/g/defs/clipPath/path/linearGradient/stop，path 必须带 d，
  涂色只走 class（fill 类声明在 style 里），url() 只许同文档锚点 url(#id)
  且该 id 必须真的存在（悬空引用 = 画不出来的渐变）。

为什么写成一个 audit_html 加方言参数、而不是拆三份文件：公共规则一旦拆开就会
各存一份，改一处忘另一处就是静默失效——那种失效不会报错，只会安静地放过违规。
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

CSP_REQUIRED = ("default-src 'none'", "script-src 'none'", "img-src 'none'")
FORBIDDEN_CSS = (
    r"@import\b", r"base64", r"data\s*:",
    r"expression\s*\(", r"javascript\s*:",
)
URL_REF = re.compile(r"url\s*\(\s*#([^)\s'\"]+)\s*\)")   # 组里不含 #：锚点名直接与 id 比
ANY_URL = re.compile(r"url\s*\(", re.IGNORECASE)
VOID_ELEMENTS = {"meta"}
CSS_CLASS_TOKEN = re.compile(r"shape|underpainting|p\d+|layer|l\d+|fallsafe")
CSS_ALLOWED_ELEMENTS = frozenset({"html", "head", "meta", "title", "style", "body", "main", "div"})
CSS_ALLOWED_ATTRS = {
    "html": {"lang"},
    "head": set(),
    "meta": {"charset", "name", "content", "http-equiv"},
    "title": set(),
    "style": set(),
    "body": set(),
    "main": {"class", "role", "aria-label"},
    "div": {"class", "style", "aria-hidden"},
}
SVG_ALLOWED_ELEMENTS = frozenset({"html", "head", "meta", "title", "style", "body", "main",
                                  "svg", "g", "defs", "clippath", "path",
                                  "lineargradient", "stop"})
# 存小写名：HTMLParser 一律把元素名与属性名小写，浏览器解析内联 SVG 时再按
# foreign content 规则调回 camelCase——所以白名单里的小写名对两边都成立。
SVG_ALLOWED_ATTRS = {
    "html": {"lang"},
    "head": set(),
    "meta": {"charset", "name", "content", "http-equiv"},
    "title": set(),
    "style": set(),
    "body": set(),
    "main": {"class", "role", "aria-label"},
    "svg": {"viewbox", "class", "aria-hidden"},
    "g": {"clip-path", "aria-hidden"},
    "defs": set(),
    "clippath": {"id"},
    "path": {"class", "d"},
    "lineargradient": {"id", "gradientunits", "x1", "y1", "x2", "y2"},
    "stop": {"offset", "stop-color"},
}
# 用 class 承载涂色时，类声明形如 .f3{fill:#rrggbb} 或 .f4{fill:url(#g0)}
FILL_RULE = re.compile(r"\.([\w-]+)\s*\{fill:([^}]+)\}")


@dataclass(frozen=True)
class _Dialect:
    """一套方言的规矩：元素与属性白名单、class 词法、url() 的许可形态。"""

    name: str
    elements: frozenset
    attributes: dict
    class_token: "re.Pattern | None" = None      # None = 该方言不按词法查 class
    allow_internal_url: bool = False             # 只许 url(#锚点)，且锚点必须存在


DIALECTS = {
    "css": _Dialect("css", CSS_ALLOWED_ELEMENTS, CSS_ALLOWED_ATTRS, CSS_CLASS_TOKEN),
    "svg": _Dialect("svg", SVG_ALLOWED_ELEMENTS, SVG_ALLOWED_ATTRS, None, True),
}


class ContractParser(HTMLParser):
    """一边解析一边收集违规项。"""

    def __init__(self, dialect: _Dialect):
        super().__init__(convert_charrefs=True)
        self.dialect = dialect
        self.errors = []
        self.stack = []
        self.styles = []
        self.ids: set[str] = set()
        self.url_refs: set[str] = set()
        self.shapes = 0
        self.paths: list[str] = []
        self.mains = 0
        self.has_csp = False
        self.layers = 0
        self.layer_anims: set[str] = set()
        self.keyframes: set[str] = set()

    def handle_decl(self, decl):
        if decl.lower() != "doctype html":
            self.errors.append("Unexpected document declaration")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = [(name.lower(), value) for name, value in attrs]
        if tag not in self.dialect.elements:
            self.errors.append(f"Forbidden element: {tag}")
        values = dict(attrs)
        if len(values) != len(attrs):
            self.errors.append(f"Duplicate attributes on {tag}")
        for name, value in attrs:
            if name not in self.dialect.attributes.get(tag, set()):
                self.errors.append(f"Forbidden attribute: {tag}.{name}")
            if name == "style":
                self.styles.append(value or "")
            if name == "id" and value:
                self.ids.add(value)
            if value:
                self.url_refs.update(URL_REF.findall(value))
        if tag == "meta":
            if values.get("http-equiv", "").lower() == "content-security-policy":
                policy = values.get("content", "")
                self.has_csp = all(part in policy for part in CSP_REQUIRED)
            elif "http-equiv" in values:
                self.errors.append("Only the Content-Security-Policy http-equiv is permitted")
        if tag == "main":
            self.mains += 1
        if self.dialect.name == "css":
            self._css_element(tag, values)
        else:
            self._svg_element(tag, values)
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def _css_element(self, tag, values):
        if tag != "div":
            return
        classes = (values.get("class") or "").split()
        for token in classes:
            if not self.dialect.class_token.fullmatch(token):
                self.errors.append(f"Unexpected class token: {token}")
        if "shape" in classes:
            self.shapes += 1
            if "clip-path:polygon(" not in values.get("style", ""):
                self.errors.append("Shape lacks a CSS polygon")
        if "layer" in classes:
            self.layers += 1
            for token in classes:
                match = re.fullmatch(r"l(\d+)", token)
                if match:
                    self.layer_anims.add(f"k{match.group(1)}")

    def _svg_element(self, tag, values):
        if tag == "path":
            self.shapes += 1
            if not values.get("d", "").strip():
                self.errors.append("Path lacks a d attribute")
            self.paths.append(values.get("class") or "")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"Unbalanced closing tag: {tag}")
        else:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1] == "style":
            self.styles.append(data)
        elif self.stack and self.stack[-1] != "title" and data.strip():
            self.errors.append("Unexpected visible text outside the title")


def _check_urls(dialect: _Dialect, css: str, refs: set, ids: set, errors: list) -> None:
    """url() 的用法：css 方言一律不许；svg 方言只许同文档锚点，且锚点必须存在。"""
    if not dialect.allow_internal_url:
        if ANY_URL.search(css):
            errors.append("Forbidden CSS construct: url(")
        return
    for match in ANY_URL.finditer(css):
        fragment = URL_REF.match(css, match.start())
        if fragment is None:
            errors.append("Only same-document url(#id) references are permitted")
            break
    for target in refs:
        if target not in ids:
            errors.append(f"Dangling url reference: #{target}")


def audit_html(document: str, dialect: str = "css") -> dict:
    """把一段文档拿来过堂。

    返回 {valid, errors, shapes, gradient_fills, bytes, layers, keyframes}；
    shapes / gradient_fills 按方言口径：css 方言数 div.shape 与内联渐变，
    svg 方言数 path 与「用渐变涂色的 path」。
    """
    if dialect not in DIALECTS:
        raise ValueError(f"未知的审计方言：{dialect}（可选：{'、'.join(sorted(DIALECTS))}）")
    parser = ContractParser(DIALECTS[dialect])
    parser.feed(document)
    parser.close()
    errors = parser.errors
    if parser.stack:
        errors.append("Unclosed elements")
    if parser.mains != 1:
        errors.append("Expected exactly one illustration main")
    if not parser.has_csp:
        errors.append("Missing restrictive Content-Security-Policy")
    # parser.styles 同时收 <style> 内容与元素的 style 属性（见 handle_starttag），
    # 所以内联样式一样要过 url() 与禁用构造检查——它不是「只含 <style> 的串」。
    css = "\n".join(parser.styles)
    if "\\" in css or "/*" in css:
        errors.append("CSS escapes/comments are outside the generator contract")
    for pattern in FORBIDDEN_CSS:
        if re.search(pattern, css, re.IGNORECASE):
            errors.append(f"Forbidden CSS construct: {pattern}")
    refs = set(parser.url_refs)
    refs.update(URL_REF.findall(css))
    _check_urls(parser.dialect, css, refs, parser.ids, errors)
    parser.keyframes = set(re.findall(r"@keyframes\s+([\w-]+)", css))
    if parser.layers:
        for name in parser.layer_anims:
            if name not in parser.keyframes:
                errors.append(f"Layer animation references missing keyframes: {name}")
    if dialect == "svg":
        fills = dict(FILL_RULE.findall(css))
        # class 可能不止一个 token（如 class="f0 extra"）：逐 token 查。只取
        # 最后一个会把带额外 token 的渐变 path 漏掉，统计悄悄偏低却不报错。
        gradient_fills = sum(1 for token in parser.paths
                             if any(ANY_URL.search(fills.get(part, ""))
                                    for part in token.split()))
    else:
        gradient_fills = css.count("linear-gradient(")
    return {"valid": not errors, "errors": sorted(set(errors)), "shapes": parser.shapes,
            "gradient_fills": gradient_fills,
            "layers": parser.layers,
            "keyframes": len(parser.keyframes),
            "bytes": len(document.encode("utf-8"))}


def audit_file(path: Path, dialect: str = "css") -> dict:
    return audit_html(path.read_text(encoding="utf-8"), dialect)
