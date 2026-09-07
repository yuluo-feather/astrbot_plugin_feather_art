"""感知均匀量化：在 Oklab 空间做无抖动的盒式中位切分。

为什么是 Oklab：人眼对亮度的偏心远比对通道的线性混色大，RGB 里画的
「等距」，出来就是肉眼可见的色带；Oklab 的欧氏距离更贴感知，切出来的
色带边缘才顺眼。

实现要点（也守确定性）：
- 分裂顺序：成员最多的桶先分，按最宽轴从盒中点切开，并列时先到先得；
- 每桶只重算落在分裂轴上的坐标，不白费力气；
- float32 精度磨没了就把该轴钉死（high=low），绝不空转。

吐出来的 labels 是像素归属的桶号，palette 是各桶 sRGB 均值；
都是规整的 int32 / uint8，后面的步骤好复现。
"""

import numpy as np

# sRGB → 线性 RGB → LMS → Oklab 的两步矩阵（标准 2019 系数，float32 精度）
OKLAB_FROM_LINEAR = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
], np.float32)
OKLAB_FROM_LMS_PRIME = np.array([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
], np.float32)


def oklab_of(rgb: np.ndarray) -> np.ndarray:
    """把 (n, 3) 的 sRGB uint8 数组映射为 Oklab 浮点坐标（batch 版）。"""
    linear = rgb.astype(np.float32) / 255
    linear = np.where(linear <= 0.04045, linear / 12.92,
                      ((linear + 0.055) / 1.055) ** 2.4)
    lms = linear @ OKLAB_FROM_LINEAR.T
    return np.cbrt(lms, out=lms) @ OKLAB_FROM_LMS_PRIME.T


def _pick_split_target(buckets: list[list]) -> "list | None":
    """挑成员最多、且仍有轴可裂的桶；全不可裂返回 None。"""
    best = None
    best_size = 1
    for bucket in buckets:
        members, low, high = bucket
        if members.size > best_size and bool(((high - low) > 0).any()):
            best, best_size = bucket, members.size
    return best


def quantize(reference: np.ndarray, colors: int) -> tuple[np.ndarray, np.ndarray]:
    """盒式 Oklab 中位切分（无抖动）。

    reference: HxWx3 uint8；colors: 目标色数（调用方保证 2..256）。
    返回 (labels HxW uint8, palette Cx3 uint8)。palette 每行是该桶像素的 sRGB 均值。
    """
    height, width = reference.shape[:2]
    flat = reference.reshape(-1, 3)
    coordinates = oklab_of(flat)
    labels = np.zeros(flat.shape[0], np.int32)
    lo = coordinates.min(axis=0)
    hi = coordinates.max(axis=0)
    buckets: list[list] = [[np.arange(flat.shape[0]), lo, hi]]

    while len(buckets) < colors:
        target = _pick_split_target(buckets)
        if target is None:
            break
        members, low, high = target
        axis = int(np.argmax(high - low))
        midpoint = np.float32((float(low[axis]) + float(high[axis])) / 2)
        if not low[axis] < midpoint < high[axis]:
            high[axis] = low[axis]
            continue
        column = coordinates[members, axis]
        upper = members[column > midpoint]
        if upper.size == 0:
            high[axis] = midpoint
            continue
        lower = members[column <= midpoint]
        if lower.size == 0:
            low[axis] = midpoint
            continue
        target[0] = lower
        target[2] = high.copy()
        target[2][axis] = midpoint
        buckets.append([upper, low.copy(), high])
        buckets[-1][1][axis] = midpoint
        labels[upper] = len(buckets) - 1

    palette = np.zeros((len(buckets), 3), np.float32)
    for index, bucket in enumerate(buckets):
        palette[index] = flat[bucket[0]].mean(axis=0)
    palette = np.clip(np.rint(palette), 0, 255).astype(np.uint8)
    return labels.reshape(height, width).astype(np.uint8), palette
