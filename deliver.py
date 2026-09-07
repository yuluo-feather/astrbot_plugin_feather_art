"""发送编排：把转换报告变成用户看得懂的文案与交付链。

画是画出来了，怎么端到桌前——文案说人话、文件带好名字，这两件事都在这里。
"""

from pathlib import Path


def _mb(size: int) -> str:
    return f"{size / 1024 / 1024:.2f} MiB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KB"


def report_to_text(report: dict) -> str:
    """报告 → 摘要文案（不含原始路径，纯人话）。"""
    preset_name = report.get("preset", {}).get("name", "写意")
    lines = [
        f"羽画 · {preset_name}档 · {report.get('seconds', 0):.1f}s 描摹完成",
    ]
    original = report.get("original_size", [0, 0])
    animation = report.get("animation")
    if animation:
        lines.append(
            f"动图 {animation.get('original_frames')} 帧 → 采样 {animation.get('frames')} 帧 · "
            f"{animation.get('fps')} fps · {animation.get('duration')}s 循环· "
            f"图层 {animation.get('layers')} 条（{'补间' if animation.get('tween') else '硬切' }）")
        lines.append(f"原图 {original[0]}×{original[1]}")
    else:
        trace = report.get("trace_size", original)
        if trace != original:
            lines.append(f"原图 {original[0]}×{original[1]}，描摹尺度 {trace[0]}×{trace[1]}")
        else:
            lines.append(f"原图 {original[0]}×{original[1]}")
        detail = [f"{report.get('shapes', 0)} 个轮廓形状"]
        if report.get("interior_holes"):
            detail.append(f"{report['interior_holes']} 处孔洞")
        if report.get('underpainting_shapes'):
            detail.append(f"{report['underpainting_shapes']} 块底板")
        if report.get("gradient_fills"):
            detail.append(f"{report['gradient_fills']} 处渐变")
        lines.append("、".join(detail))
        tail = [f"单文件 {_mb(report.get('bytes', 0))}"]
        similarity = report.get("similarity")
        if similarity:
            tail.append(f"与参考图 MAE {similarity.get('mae')}")
        lines.append(" · ".join(tail))
    lines.append("浏览器直接打开即可，无图片无脚本无外链。")
    return "\n".join(lines)


def build_chain(report: dict, html_path: Path) -> list:
    """交付链：摘要文案 + HTML 文件。"""
    from astrbot.api.message_components import File, Plain
    name = f"羽画_{report['preset']['name']}_{html_path.stem}.html"
    return [Plain(report_to_text(report)), File(name=name, file=str(html_path))]
