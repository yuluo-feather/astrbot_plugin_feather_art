"""输出契约审计：检查生成的 HTML 是否守羽画的家规。

说清楚：这是「生成器契约检查」，不是通用消毒器——只管我们自己
产出的文档合不合规，防的是哪天不经意把渐变写成 url() 这种事故，
不负责抵御外面的恶意 HTML。

家规要点：
- 元素白名单：html/head/meta/title/style/body/main/div；
- div 的 class 只许 shape / underpainting / p<数字> / layer（l<数字> 配对）；
- 恰好一个 main.illustration（role="img" + aria-label）；
- 必须带 restrictive CSP（default-src/script-src/img-src 全 none）；
- CSS 里禁止 url()/@import/base64/data:/expression/javascript:，
  注释和转义序列也不行（不给混淆和外链留缝）；
- 形状必须带 clip-path:polygon(...)。
"""

from html.parser import HTMLParser
from pathlib import Path
import re

ALLOWED_ELEMENTS = {"html", "head", "meta", "title", "style", "body", "main", "div"}
ALLOWED_ATTRS = {
    "html": {"lang"},
    "head": set(),
    "meta": {"charset", "name", "content", "http-equiv"},
    "title": set(),
    "style": set(),
    "body": set(),
    "main": {"class", "role", "aria-label"},
    "div": {"class", "style", "aria-hidden"},
}
VOID_ELEMENTS = {"meta"}
CLASS_TOKEN = re.compile(r"shape|underpainting|p\d+|layer|l\d+|fallsafe")
CSP_REQUIRED = ("default-src 'none'", "script-src 'none'", "img-src 'none'")
FORBIDDEN_CSS = (
    r"url\s*\(", r"@import\b", r"base64", r"data\s*:",
    r"expression\s*\(", r"javascript\s*:",
)


class ContractParser(HTMLParser):
    """一边解析一边收集违规项。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors = []
        self.stack = []
        self.styles = []
        self.shapes = 0
        self.mains = 0
        self.has_csp = False
        self.layers = 0
        self.layer_anims: set[str] = set()
        self.keyframes: set[str] = set()

    def handle_decl(self, decl):
        if decl.lower() != "doctype html":
            self.errors.append("Unexpected document declaration")

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_ELEMENTS:
            self.errors.append(f"Forbidden element: {tag}")
        values = dict(attrs)
        if len(values) != len(attrs):
            self.errors.append(f"Duplicate attributes on {tag}")
        for name, value in attrs:
            if name not in ALLOWED_ATTRS.get(tag, set()):
                self.errors.append(f"Forbidden attribute: {tag}.{name}")
            if name == "style":
                self.styles.append(value or "")
        if tag == "meta":
            if values.get("http-equiv", "").lower() == "content-security-policy":
                policy = values.get("content", "")
                self.has_csp = all(part in policy for part in CSP_REQUIRED)
            elif "http-equiv" in values:
                self.errors.append("Only the Content-Security-Policy http-equiv is permitted")
        if tag == "main":
            self.mains += 1
        if tag == "div":
            classes = (values.get("class") or "").split()
            for token in classes:
                if not CLASS_TOKEN.fullmatch(token):
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
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"Unbalanced closing tag: {tag}")
        else:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1] == "style":
            self.styles.append(data)
        elif self.stack and self.stack[-1] != "title" and data.strip():
            self.errors.append("Unexpected visible text outside the title")


def audit_html(document: str) -> dict:
    """把一段 HTML 拿来过堂：返回 {valid, errors, shapes, gradient_fills, bytes, layers, keyframes}。"""
    parser = ContractParser()
    parser.feed(document)
    parser.close()
    errors = parser.errors
    if parser.stack:
        errors.append("Unclosed elements")
    if parser.mains != 1:
        errors.append("Expected exactly one illustration main")
    if not parser.has_csp:
        errors.append("Missing restrictive Content-Security-Policy")
    css = "\n".join(parser.styles)
    if "\\" in css or "/*" in css:
        errors.append("CSS escapes/comments are outside the generator contract")
    for pattern in FORBIDDEN_CSS:
        if re.search(pattern, css, re.IGNORECASE):
            errors.append(f"Forbidden CSS construct: {pattern}")
    parser.keyframes = set(re.findall(r"@keyframes\s+([\w-]+)", css))
    if parser.layers:
        for name in parser.layer_anims:
            if name not in parser.keyframes:
                errors.append(f"Layer animation references missing keyframes: {name}")
    return {"valid": not errors, "errors": sorted(set(errors)), "shapes": parser.shapes,
            "gradient_fills": css.count("linear-gradient("),
            "layers": parser.layers,
            "keyframes": len(parser.keyframes),
            "bytes": len(document.encode("utf-8"))}


def audit_file(path: Path) -> dict:
    return audit_html(path.read_text(encoding="utf-8"))
