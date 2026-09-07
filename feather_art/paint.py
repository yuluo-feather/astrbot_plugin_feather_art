"""区域涂色：纯色或一阶局部渐变（linear-gradient 两停点）。

较大的色块（>= 45 像素且短边 >= 5）在参考图里往往藏着平滑的明暗过渡，
用单色会比原图生硬。这里对区域样本做最小二乘平面拟合：
- 平面梯度方向（SVD 主轴）即渐变方向；
- 两端颜色按 3/97 分位数截断后再 clip，防单点噪色撑爆；
- 渐变幅度 < 3 时退回纯色——细微过渡不值得引入渐变。

角度定义沿用 CSS：0deg = 向上，顺时针为正。
"""

import math

import numpy as np

from .geometry import hex_color, number

MIN_SAMPLES = 45       # 少于该样本数不做渐变
MIN_SIDE = 5           # 区域短边少于该值不做渐变
MAX_SAMPLES = 6000     # 回归样本上限（超采样）
MIN_RAMP = 3.0         # 渐变幅度阈值（单通道最大差）


def paint_for_region(reference, mask, x, y, width, height, gradients: bool):
    """区域 → (CSS 涂色, 是否渐变)。

    reference: 已合成的参考图（HxWx3 uint8）；mask: 区域内布尔掩码；
    x/y/width/height: 区域在参考图中的位置与尺寸。
    """
    ys, xs = np.nonzero(mask)
    samples = reference[y + ys, x + xs].astype(float)
    solid = hex_color(samples.mean(axis=0))
    if not gradients or len(xs) < MIN_SAMPLES or min(width, height) < MIN_SIDE:
        return solid, False
    if len(xs) > MAX_SAMPLES:
        step = math.ceil(len(xs) / MAX_SAMPLES)
        xs, ys, samples = xs[::step], ys[::step], samples[::step]

    # 设计矩阵 [dx, dy, 1]：拟合平面 color ≈ a*dx + b*dy + c
    design = np.column_stack((xs + .5 - width / 2, ys + .5 - height / 2, np.ones(len(xs))))
    coeff, _, _, _ = np.linalg.lstsq(design, samples, rcond=None)
    # 主梯度方向 = 平面系数的 SVD 主轴（幅值待定）
    axes, _, _ = np.linalg.svd(coeff[:2], full_matrices=False)
    direction = axes[:, 0]
    slope = direction @ coeff[:2]
    length = abs(direction[0]) * width + abs(direction[1]) * height
    low, high = np.percentile(samples, (3, 97), axis=0)
    start = np.clip(coeff[2] - slope * length / 2, low, high)
    end = np.clip(coeff[2] + slope * length / 2, low, high)
    if np.max(np.abs(end - start)) < MIN_RAMP:
        return solid, False
    angle = math.degrees(math.atan2(direction[0], -direction[1])) % 360
    return f"linear-gradient({number(angle, 1)}deg,{hex_color(start)},{hex_color(end)})", True
