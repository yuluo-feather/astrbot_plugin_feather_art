"""转换编排：输入 → 管线 → 体积阶梯 → 审计 → 原子落盘。

本模块只做「把图画成 HTML」这一件事，不碰消息与发送（那是 main.py 的
职责）；所有参数收敛在 TraceConfig，所有结果收敛在报告 dict。

与算法层的关系：这里负责挑选档位、处理预算阶梯（--fit）与产出报告，
算法细节（量化/合并/轮廓/渲染/审计）全部在 feather_art 包里。
"""

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .feather_art import __version__
from .feather_art.audit import audit_html
from .feather_art.imaging import load_image
from .feather_art.merge import merge_regions
from .feather_art.presets import PRESETS, resolve
from .feather_art.quantize import quantize
from .feather_art.render import BudgetExceeded, render_document


class TraceError(ValueError):
    """转换失败；message 是可直接回给用户的中文文案。"""


@dataclass
class TraceConfig:
    """一次描摹的全部可调参数。"""

    background: tuple[int, int, int] = (255, 255, 255)
    title: str = "羽画 · 纯 CSS 描摹"
    max_mb: float = 64.0
    fit_mb: float = 0.0      # 0 = 不启用自动降档
    score: bool = True
    gradients: bool = True
    underpainting: bool = True
    progress: Callable[[str], None] = field(default=lambda _: None, repr=False)

    def __post_init__(self):
        """渗透发现修复：畸形 fit/max 值（字符串/负数）不得穿透到算数层。

        规则：转 float 失败回默认；负数钳回 0（0 的语义被上层尊重，
        立即熔断出中文文案，而不是 TypeError）。
        """
        for name, default in (("max_mb", 64.0), ("fit_mb", 40.0)):
            value = getattr(self, name)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = default
            setattr(self, name, max(0.0, value))


FIT_TOLERANCE = 1.02  # fit 预算容差：允许 2% 溢出，避免卡线触发整级重跑


def _fit_target(fit_mb: float, max_mb: float) -> int:
    """输出体积目标（字节）：fit 预算含容差，且不超 max_mb 硬上限。"""
    limit = int(max_mb * 1024 * 1024)
    if not fit_mb:
        return limit
    return min(limit, int(fit_mb * 1024 * 1024 * FIT_TOLERANCE))


def _fit_ladder(base: dict) -> list[dict]:
    """确定性降档阶梯：颜色优先（感知损失小），宽度兜底（保分辨率）。

    排列动机：宽度决定细节密度（轮廓形状数），颜色只影响色带层次；
    超预算时先削颜色、保留宽度，让精细档在小预算里仍然拉开差距。
    整条阶梯宽度单调不增、颜色单调不增，第一次不超预算的档即为最优档。
    """
    width, colors = base["max_width"], base["colors"]
    ladder = [dict(base)]
    cur_colors = colors
    # 1) 保宽度，先降颜色：÷2 → ÷4（下限 48）
    for divisor in (2, 4):
        next_colors = max(48, colors // divisor)
        if next_colors >= cur_colors:
            continue
        cur_colors = next_colors
        ladder.append({**base, "colors": cur_colors})
    # 2) 颜色到底后，宽度按 3/4 台阶降到 512 地板（保持已降的颜色）
    step_width = width
    while step_width > 512:
        step_width = max(512, round(step_width * 3 / 4 / 4) * 4)
        ladder.append({**base, "max_width": step_width, "colors": cur_colors})
    # 3) 终极替补：窄幅 + 颜色逐档稀释，任何图都装得下
    for width_floor, divisor in ((512, 2), (384, 4), (300, 8), (256, 16)):
        shrunk = max(2, min(cur_colors, cur_colors // divisor))
        ladder.append({**base, "max_width": min(base["max_width"], width_floor), "colors": shrunk})
    return ladder


def atomic_write(text: str, path: Path, force: bool) -> None:
    """原子落盘：先写临时文件再改名；force=False 时拒绝覆盖已有文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
                delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        if force:
            os.replace(temporary, path)
        else:
            # 先用硬链接占位（原子且拒绝并发覆盖），不支持硬链接的文件系统
            # 回退到排他创建，同样拒绝覆盖已存在的文件。
            try:
                os.link(temporary, path)
            except OSError:
                if path.exists():
                    raise
                with open(path, "xb") as target:
                    target.write(temporary.read_bytes())
        temporary.unlink(missing_ok=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def trace_image(image_bytes: bytes, preset_key: str, out_path: Path, *,
                config: TraceConfig | None = None, force: bool = False,
                report_path: Path | None = None) -> dict:
    """执行一次完整描摹，返回报告 dict；输出 HTML 写 out_path。

    流程：定档 → 逐档尝试（fit 阶梯）→ 量化 → 合并 → 渲染 → 契约审计 →
    原子落盘。任何一步失败都抛出 TraceError（面向用户的文案）。
    """
    traced = config or TraceConfig()
    preset = resolve(preset_key)
    start = time.perf_counter()
    if out_path.suffix.lower() != ".html":
        raise TraceError("输出文件必须是 .html 结尾。")
    if out_path.exists() and not force:
        raise TraceError(f"文件已存在：{out_path.name}，已拒绝覆盖。")
    if report_path is not None and report_path.exists() and not force:
        raise TraceError("报告文件已存在，已拒绝覆盖。")

    import cv2
    import numpy as np
    from PIL import __version__ as pillow_version

    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)

    first = PRESETS[preset.key]
    base = {"max_width": first.max_width, "colors": first.colors,
            "epsilon": first.epsilon, "passes": first.passes}
    target = _fit_target(traced.fit_mb, traced.max_mb)
    ladder = _fit_ladder(base) if traced.fit_mb else [base]
    attempts: list[dict] = []
    document = stats = reference = original = None
    chosen = base
    seen = set()
    for candidate in ladder:
        key = (candidate["max_width"], candidate["colors"])
        if key in seen:
            continue
        seen.add(key)
        chosen = candidate
        try:
            reference, original = load_image(image_bytes, candidate["max_width"], traced.background)
        except ValueError as exc:
            raise TraceError(str(exc)) from exc
        labels, palette = quantize(reference, candidate["colors"])
        labels = merge_regions(labels, palette, candidate["passes"], traced.progress)
        try:
            document, stats = render_document(
                reference, labels, palette, original,
                background=traced.background, title=traced.title,
                epsilon=candidate["epsilon"], gradients=traced.gradients,
                underpainting=traced.underpainting, max_bytes=target,
                progress=traced.progress, score=traced.score,
            )
        except BudgetExceeded as exceeded:
            if not traced.fit_mb:
                raise TraceError("输出体积超预算，减小图片或换低一档精度再来。") from exceeded
            attempts.append({"max_width": candidate["max_width"], "colors": candidate["colors"],
                             "bytes": exceeded.byte_count, "exceeded": True})
            traced.progress(f"Fit attempt {len(attempts)}: width {candidate['max_width']}, "
                            f"colors {candidate['colors']} exceeded; stepping down")
            continue
        audit = audit_html(document)
        if not audit["valid"]:
            raise TraceError("生成的 HTML 未通过契约审计：" + "、".join(audit["errors"][:3]))
        attempts.append({"max_width": candidate["max_width"], "colors": candidate["colors"],
                         "bytes": audit["bytes"], "exceeded": False})
        break
    else:
        raise TraceError(f"即便降到最粗的档也装不下 {traced.fit_mb} MiB，这张图可能太花了。")

    report: dict = {
        "version": __version__,
        "preset": {"key": preset.key, "name": preset.name},
        "settings": chosen,
        "original_size": list(original),
        "trace_size": list(reference.shape[1::-1]),
        "shapes": stats["shapes"],
        "gradient_fills": stats["gradient_fills"],
        "polygon_vertices": stats["polygon_vertices"],
        "interior_holes": stats["interior_holes"],
        "underpainting_shapes": stats["underpainting_shapes"],
        "similarity": stats.get("similarity"),
        "bytes": audit["bytes"],
        "sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "audit": {"valid": audit["valid"], "errors": audit["errors"]},
        "seconds": round(time.perf_counter() - start, 3),
        "dependencies": {"numpy": np.__version__, "opencv": cv2.__version__,
                         "pillow": pillow_version},
    }
    if traced.fit_mb:
        report["fit"] = {"target_mb": traced.fit_mb, "tolerance": FIT_TOLERANCE, "attempts": attempts}
    atomic_write(document, out_path, force)
    if report_path is not None:
        atomic_write(json.dumps(report, ensure_ascii=False, indent=2) + "\n", report_path, force)
    return report
