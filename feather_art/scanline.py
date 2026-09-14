"""扫描线动画渲染：每行 = 一条横向色带渐变（linear-gradient 硬色带）。

动画从「实例矢量轨迹」换成「行渐变扫描线」：逐像素还原、100% 覆盖、
任意缩放无缝隙、帧间稳定不闪。

保真档（2026-09-14 拍板「画质优先，体积无所谓」后定）：ROW_PX=1 逐行不
合并、QUANT_STEP=8、DENOISE_KERNEL=1 不做中值滤波——抖动颗粒不再被抹平。
三张真实动图实测关键区 MAE 从 7.5/9.6/9.7 降到 1.3/5.9/1.2，体积 2.1~2.6 倍。
**SEG_TOL 不能跟着调小**：它是体积的非线性炸弹——ab7479 上 20→12 段/行
230 → 755、体积 +543%，而画质只多换一点点；保持不变是量出来的最优性价比。

结构：
- 静止行 → div.shape（矩形 inline clip-path + 行渐变背景；audit 要求
  shape 的 clip-path 必须在 inline style 里，类里不算）；
- 动态行 → div.layer（@keyframes 逐帧 background 切换 + 100% 回环首帧）；
- 行高 = 行距% + OVERLAP_PCT：亚像素重叠，根治「非整数设备缩放下的
  取整缝隙」（Windows 125%/文本缩放场景实测 0 白线）。

三笔省字节的改动（动图线专用的 2026-09-14 那轮）：行合并取真实像素行而不是
均值（均值把两行色带边界求并集，段数反涨 13~24%）、相邻帧 stop 折叠、
紧凑写法（色值三位缩写 + 帧百分比去尾零，浏览器逐像素验收差 0）。
**注意：任何按帧变化的自适应参数都会污染 changed 判定**——两帧逐像素相同时，
quant 16 vs 24 会让 46/60~169/169 行的渐变串不同，静止区被整块拖进 keyframes，
体积反向爆炸。
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from .contract import FALLSAFE_MESSAGE, BudgetExceeded
from .geometry import hex_color

DENOISE_KERNEL = 1   # 去抖动中值滤波核（1 = 不滤波，保住 dithering 颗粒）
QUANT_STEP = 8       # 颜色量化步长（跨帧收敛，帧间色不漂移）
SEG_TOL = 20         # 行分段色差阈值（单通道）——调小是体积的非线性炸弹
ROW_PX = 1           # 行合并：原图纵向 ROW_PX 像素并为一行（1 = 逐行还原）
MERGE_MODE = "take"  # 行合并取法："take"=取区间首行那一行，"mean"=均值
OVERLAP_PCT = 0.17   # 行高超出行距的百分比（防取整缝隙）
RECT_POLY = "polygon(0 0,100% 0,100% 100%,0 100%)"


@dataclass
class ScanlineConfig:
    """渲染配置（由 service_animation 组装）。"""

    title: str = "羽画 · 纯 CSS 动画"
    background: str | tuple = "#ffffff"   # "#hex" 或 (r, g, b) 三元组
    duration: float = 1.0      # 单轮循环总时长（秒）
    loop: bool = True
    max_bytes: int = 32 * 1024 * 1024   # 体积上限，超了抛 BudgetExceeded
    progress: Callable | None = None


def _bg_color(value) -> str:
    """背景色转 CSS：#开头的字符串原样透传，数值三元组走 hex_color。"""
    if isinstance(value, str) and value.startswith("#"):
        return value
    return hex_color(value)


def prepare_frame(frame: np.ndarray) -> np.ndarray:
    """单帧预处理：可选去抖动 → QUANT_STEP 步量化（uint8）。

    DENOISE_KERNEL ≤ 1 时完全不滤——中值滤波会抹平动图的 dithering 颗粒，
    那是「纹理保真」，画质优先档不拿它换体积。
    """
    blurred = frame if DENOISE_KERNEL <= 1 else cv2.medianBlur(frame, DENOISE_KERNEL)
    quant = ((blurred.astype(np.int16) + QUANT_STEP // 2)
             // QUANT_STEP * QUANT_STEP)
    return quant.clip(0, 255).astype(np.uint8)


def row_segments(row: np.ndarray, tol: int = SEG_TOL) -> list:
    """一行像素 → 同色段 [(x0, rgb), ...]；段间单通道色差 > tol 才分段。"""
    segs = [(0, tuple(int(v) for v in row[0]))]
    for x in range(1, row.shape[0]):
        c = tuple(int(v) for v in row[x])
        if max(abs(c[i] - segs[-1][1][i]) for i in range(3)) > tol:
            segs.append((x, c))
    return segs


def _compact_hex(c) -> str:
    """色值能缩成三位就缩（#aabbcc → #abc），颜色本身分毫不差。"""
    r, g, b = int(c[0]), int(c[1]), int(c[2])
    if r >> 4 == r & 15 and g >> 4 == g & 15 and b >> 4 == b & 15:
        return f"#{r & 15:x}{g & 15:x}{b & 15:x}"
    return f"#{r:02x}{g:02x}{b:02x}"


def frame_pct(index: int, count: int) -> str:
    """帧序号 → keyframes 百分比（去尾随零：0.00% → 0%，12.50% → 12.5%）。

    小数点一定挡在尾零之前（"%.2f" 保底两位），所以 rstrip 不会误伤
    "100.00" 这类整数——它是 100%，不是 1%。
    """
    return f"{index / count * 100:.2f}".rstrip("0").rstrip(".") + "%"


def seg_gradient(segs: list, width: int) -> str:
    """同色段 → CSS 横向渐变串（双位置 stop，Chromium 71+）。"""
    parts = []
    for i, (x0, c) in enumerate(segs):
        x1 = segs[i + 1][0] if i + 1 < len(segs) else width
        parts.append(f"{_compact_hex(c)} {x0}px {x1}px")
    return "linear-gradient(90deg," + ",".join(parts) + ")"


def merge_rows(frame: np.ndarray, row_h: int, mode: str = MERGE_MODE) -> np.ndarray:
    """纵向 row_h 像素合成一行（行数 = max(1, h // row_h)）。

    mode="take"（默认）取区间首行那一行**真实像素**——均值合并会把两行的
    色带边界求并集：六张真实动图实测段/行 38.0 → 30.9、每行渐变串只剩 80%
    （最狠的一张 66.7 → 50.5，省 24%）。取哪一行是量出来的，不是拍的：
    首行 80% / 次行 94%（六张里五张首行更省），且所有帧用同一下标——
    逐帧挑行会让同一区域在帧间跳行，画面闪。这个性质也对上了模块头那句
    「颜色 16 步收敛、帧间色不漂移」：合成出来的中间色不落在量化网格上。
    mode="mean" 保留旧口径，供对照与回退。

    不足一行也要留一行：h < row_h 时 h // row_h 是 0，而 render_scanline
    那边用的是 max(1, ...)——两处口径必须一致，否则 1 像素高的帧会在取值时
    越界。宽扁动图（横幅、取景条）降采样后就会落到这一档，不是理论边界。
    """
    hh = max(1, frame.shape[0] // row_h)
    if mode == "take":
        rows = [frame[i * row_h] for i in range(hh)]
    else:
        rows = [frame[i * row_h:(i + 1) * row_h].astype(np.int16).mean(axis=0)
                .astype(np.uint8) for i in range(hh)]
    return np.stack(rows)


def render_scanline(frames: list, config: ScanlineConfig) -> tuple:
    """帧列表 → (HTML 文档, stats)。

    帧尺寸须一致（采样管线保证）；stats 字段与 render_animation 对齐：
    layers（动态行数）、static_rows、frames、duration、keyframe_total、
    rows、bytes。
    """
    h, w = frames[0].shape[:2]
    frame_count = len(frames)
    progress = config.progress or (lambda _: None)

    prepared = [prepare_frame(f) for f in frames]
    hh = max(1, h // ROW_PX)
    merged = [merge_rows(f, ROW_PX, MERGE_MODE) for f in prepared]

    grads: list = []
    for t, m in enumerate(merged):
        row_g = []
        for y in range(hh):
            row_g.append(seg_gradient(row_segments(m[y]), w))
        grads.append(row_g)
        progress(f"预分段 帧 {t + 1}/{frame_count}")

    changed = [y for y in range(hh)
               if any(grads[t][y] != grads[0][y] for t in range(1, frame_count))]
    row_h_pct = 100.0 / hh + OVERLAP_PCT

    css = [
        ".illustration{position:relative;isolation:isolate;overflow:hidden;"
        "width:100%;max-width:" + str(w) + "px;margin:0 auto;background:"
        + _bg_color(config.background) + ";contain:layout paint}",
        '.illustration::before{content:"";display:block;padding-top:'
        + f"{h / w * 100:.5f}%" + "}",
        ".shape{position:absolute;left:0;right:0;height:"
        + f"{row_h_pct:.4f}%" + ";pointer-events:none}",
        ".layer{position:absolute;left:0;top:0;right:0;height:"
        + f"{row_h_pct:.4f}%" + ";animation-duration:"
        + f"{config.duration:.2f}" + "s;animation-timing-function:step-end;"
        "animation-iteration-count:" + ("infinite" if config.loop else "1")
        + "}",
        ".fallsafe{display:block;position:fixed;top:0;left:0;right:0;bottom:0;"
        "z-index:2147483647;background:" + _bg_color(config.background)
        + ";color:#333;padding:24px;font:15px/1.8 sans-serif;box-sizing:border-box}",
        '.fallsafe::after{content:"' + FALLSAFE_MESSAGE + '"}',
        "@supports (clip-path: polygon(0 0)){.fallsafe{display:none}}",
    ]

    body = []
    for y in range(hh):
        top = y / hh * 100
        if y not in changed:
            body.append(f'<div class="shape" style="top:{top:.4f}%;'
                        f'background:{grads[0][y]};clip-path:{RECT_POLY}"></div>')
    keyframe_total = 0
    for idx, y in enumerate(changed):
        top = y / hh * 100
        # 相邻帧渐变串相同就折叠那一帧的 stop：step-end 下该区间自动延续
        # 前一值，折叠后渲染逐像素不变（实测省 0.01~5.98% 的 stop）。
        steps, last = [], None
        for t in range(frame_count):
            gradient = grads[t][y]
            if gradient != last:
                steps.append(
                    f"{frame_pct(t, frame_count)}{{background:{gradient}}}")
                last = gradient
        if last != grads[0][y]:
            steps.append(f"100%{{background:{grads[0][y]}}}")
        steps = "".join(steps)
        css.append(f".l{idx}{{animation-name:k{idx}}}")
        css.append(f"@keyframes k{idx}{{{steps}}}")
        body.append(f'<div class="layer l{idx}" style="top:{top:.4f}%"></div>')
        keyframe_total += frame_count + 1
        if idx and idx % 10 == 0:
            progress(f"行 {idx}/{hh}（动态 {len(changed)}）")

    label = html.escape(config.title, quote=True)
    document = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta http-equiv="Content-Security-Policy" content="default-src '
        "'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; "
        "connect-src 'none'; font-src 'none'; object-src 'none'; base-uri "
        "'none'; form-action 'none'\">"
        '<title>' + label + "</title><style>"
        + chr(10).join(css) + "</style></head><body>"
        '<main class="illustration" role="img" aria-label="'
        + label + '"><div class="fallsafe"></div>'
        + chr(10).join(body) + "</main></body></html>"
    )
    size_bytes = len(document.encode("utf-8"))
    if size_bytes > config.max_bytes:
        # 预算纪律与静态线一致：拼完再终检，抛出的字节数是真实完整值。
        # 扫描线一行一渐变，长动图的体积能到几十上百 MiB——缺这条终检时
        # max_mb 对它完全无效，超限成品会照样发出去。
        raise BudgetExceeded(size_bytes)
    stats = {
        "style": "scanline",
        "rows": hh,
        "static_rows": hh - len(changed),
        "layers": len(changed),
        "frames": frame_count,
        "duration": round(config.duration, 2),
        "keyframe_total": keyframe_total,
        "bytes": size_bytes,
    }
    return document, stats
