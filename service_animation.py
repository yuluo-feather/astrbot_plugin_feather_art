"""动画编排：动图 → 纯 CSS 动画（@keyframes 时间线）。

与 service.py 的分工：
- service.py 负责静态图描摹（trace_image / fit 阶梯 / 公共底座）；
- 本模块做动画线：采样后按 style 分流——scanline（默认，行渐变扫描线，
  见 feather_art/scanline.py）或 vector（逐帧量化/实例跟踪，旧管线）；
  tween 补间仅 vector 支持；渲染 → 审计 → 报告。
公共底座（TraceConfig / TraceError / atomic_write）从 service 引入，
依赖单向（service ← 本模块），无环。
"""

import hashlib
import json
import time
from pathlib import Path

from .feather_art import __version__
from .feather_art.animate import extract_shapes, track_shapes
from .feather_art.audit import audit_html
from .feather_art.imaging import decode_frames
from .feather_art.merge import merge_regions
from .feather_art.presets import resolve
from .feather_art.quantize import quantize
from .feather_art.render_animation import AnimationConfig, render_animation
from .feather_art.scanline import ScanlineConfig, render_scanline
from .service import TraceConfig, TraceError, atomic_write


def trace_animation(image_bytes: bytes, preset_key: str, out_path: Path,
                    config: TraceConfig | None = None, *, frame_limit: int = 48,
                    sample_frames: int = 0, tween: bool = False,
                    style: str = "scanline", force: bool = True,
                    report_path: Path | None = None) -> dict:
    """动图 → 纯 CSS 动画单文件 HTML（@keyframes 时间线）。

    管线：均匀采样 →（scanline 扫描线 | vector 实例跟踪）→ 渲染 → 审计。
    与 trace_image 共用 presets 与预算哲学；动画档默认 motion（512 宽 / 96 色）。
    sample_frames > 0 时固定采样帧数（指令 --sample / 配置 motion_sample 传入），
    否则按时长自适应（上限 frame_limit）。
    style=scanline 走扫描线渲染（默认；逐像素还原、无碎块、无缝）；
    style=vector 走实例矢量轨迹（旧管线，tween 补间仅此路径支持）。
    """
    start = time.perf_counter()
    traced = config or TraceConfig()
    preset = resolve(preset_key)
    import cv2
    import numpy as np
    try:
        from PIL import __version__ as pillow_version
    except Exception:
        pillow_version = "?"

    frames, original_size, avg_duration, total_frames = decode_frames(
        image_bytes, preset.max_width, traced.background,
        sample_limit=frame_limit, fixed_frames=sample_frames)
    size = (frames[0].shape[1], frames[0].shape[0])
    traced.progress(f"采样 {len(frames)} 帧 · {preset.name}档")

    if style == "scanline" and not tween:
        # 扫描线：逐像素行渐变，覆盖 100%、任意缩放无缝；tween 只有矢量轨迹
        # 才有意义——要求补间时自动落回 vector。
        traced.progress(f"扫描线渲染 {len(frames)} 帧")
        document, stats = render_scanline(
            frames,
            ScanlineConfig(title="羽画 · 纯 CSS 动画（扫描线）",
                           background=traced.background,
                           duration=len(frames) * avg_duration if avg_duration > 0 else 1.0,
                           progress=traced.progress))
        shapes_total = 0
    else:
        max_bytes = int(traced.max_mb * 1024 * 1024)
        seq: list[list] = []
        for index, ref in enumerate(frames):
            labels, palette = quantize(ref, preset.colors)
            labels = merge_regions(labels, palette, preset.passes, traced.progress)
            seq.append(extract_shapes(labels, palette, ref, index, preset.epsilon,
                                      min_area=max(8, preset.max_width // 64)))
            traced.progress(f"帧 {index + 1}/{len(frames)}: {len(seq[-1])} 个实例")

        tracks = [t for t in track_shapes(seq, size) if len(t.keys) >= 2]
        # 短轨迹过滤：闪现 1-2 帧的碎片是「诡异闪烁」的主源（90 秒长片会产生
        # 上千条碎片轨迹互相叠着跳），只保留 >=2 帧的稳定轨迹。
        traced.progress(f"图层跟踪: {len(tracks)} 条轨迹（过滤闪现碎片）")

        document, stats = render_animation(
            tracks, size, len(frames),
            AnimationConfig(title="羽画 · 纯 CSS 动画", background=traced.background,
                            fps=1.0 / avg_duration if avg_duration > 0 else 8.0,
                            tween=tween, max_bytes=max_bytes,
                            progress=traced.progress))
        shapes_total = sum(len(x) for x in seq)
    audit = audit_html(document)
    if not audit["valid"]:
        raise TraceError("生成的 HTML 未通过契约审计：" + "、".join(audit["errors"][:3]))

    report: dict = {
        "version": __version__,
        "preset": {"key": preset.key, "name": preset.name},
        "animation": {
            "style": stats.get("style", "vector"),
            "rows": stats.get("rows", 0),  # 仅 scanline 有意义（行数）
            "frames": len(frames),
            "original_frames": int(total_frames),
            "fps": round(1.0 / avg_duration, 2) if avg_duration > 0 else 8.0,
            "layers": stats["layers"],
            "keyframe_total": stats["keyframe_total"],
            "duration": stats["duration"],
            "tween": tween,
        },
        "original_size": list(original_size),
        "trace_size": list(size),
        "shapes": shapes_total,
        "bytes": audit["bytes"],
        "sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "audit": {"valid": audit["valid"], "errors": audit["errors"]},
        "seconds": round(time.perf_counter() - start, 3),
        "dependencies": {"numpy": np.__version__, "opencv": cv2.__version__,
                         "pillow": pillow_version},
    }
    atomic_write(document, out_path, force)
    if report_path is not None:
        atomic_write(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                     report_path, force)
    return report
