"""动画编排：动图 → 纯 CSS 动画（@keyframes 时间线）。

与 service.py 的分工：
- service.py 负责静态图描摹（trace_image / fit 阶梯 / 公共底座）；
- 本模块只做动画这一条线：采样 → 逐帧量化/合并/实例特征 →
  帧间图层跟踪 → 动画渲染 → 审计 → 报告。
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
from .service import TraceConfig, TraceError, atomic_write


def trace_animation(image_bytes: bytes, preset_key: str, out_path: Path,
                    config: TraceConfig | None = None, *, frame_limit: int = 48,
                    tween: bool = False, force: bool = True,
                    report_path: Path | None = None) -> dict:
    """动图 → 纯 CSS 动画单文件 HTML（@keyframes 时间线）。

    管线：均匀采样 → 逐帧量化/合并/实例特征 → 帧间图层跟踪 → 动画渲染 → 审计。
    与 trace_image 共用 presets 与预算哲学；动画档默认 motion（512 宽 / 96 色）。
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
        image_bytes, preset.max_width, traced.background, sample_limit=frame_limit)
    size = (frames[0].shape[1], frames[0].shape[0])
    traced.progress(f"采样 {len(frames)} 帧 · {preset.name}档")

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

    max_bytes = int(traced.max_mb * 1024 * 1024)
    document, stats = render_animation(
        tracks, size, len(frames),
        AnimationConfig(title="羽画 · 纯 CSS 动画", background=traced.background,
                        fps=1.0 / avg_duration if avg_duration > 0 else 8.0,
                        tween=tween, max_bytes=max_bytes,
                        progress=traced.progress))
    audit = audit_html(document)
    if not audit["valid"]:
        raise TraceError("生成的 HTML 未通过契约审计：" + "、".join(audit["errors"][:3]))

    report: dict = {
        "version": __version__,
        "preset": {"key": preset.key, "name": preset.name},
        "animation": {
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
        "shapes": sum(len(x) for x in seq),
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
