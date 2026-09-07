"""离线相似度估计：把生成的形状堆栅格化，与参考图比 MAE。

量的是「逼近程度」本身，不是浏览器抗锯齿——所以它只能当作者阶段
的参考，登不了台面替我们亲眼验收。只在调用方要（score=True）时算。
"""

import math
import re

import cv2
import numpy as np

# 我们方言里的渐变只有这一种形态：两停点、无空格
GRADIENT = re.compile(r"linear-gradient\(([-\d.]+)deg,(#[0-9a-f]{6}),(#[0-9a-f]{6})\)")


def rgb_of(hex_color: str) -> np.ndarray:
    return np.array([int(hex_color[index:index + 2], 16) for index in (1, 3, 5)], np.float32)


def paint_layer(paint: str, width: int, height: int) -> "np.ndarray | None":
    """把一种 CSS 涂色渲染成 HxWx3 浮点层；无法解析返回 None。"""
    layer = np.empty((height, width, 3), np.float32)
    if paint.startswith("#"):
        layer[:] = rgb_of(paint)
        return layer
    match = GRADIENT.fullmatch(paint)
    if match is None:
        return None
    angle, start, end = float(match.group(1)), rgb_of(match.group(2)), rgb_of(match.group(3))
    radians = math.radians(angle)
    # CSS 角度从「上」起顺时针：图像坐标 (x 右, y 下) 里的方向是 (sin, -cos)
    direction = np.array([math.sin(radians), -math.cos(radians)])
    length = abs(direction[0]) * width + abs(direction[1]) * height
    ys, xs = np.mgrid[0:height, 0:width]
    position = (direction[0] * (xs + .5 - width / 2) + direction[1] * (ys + .5 - height / 2)) / length
    layer[:] = start + (end - start) * np.clip(position + .5, 0, 1)[..., None]
    return layer


class Rasterizer:
    """按绘制顺序把形状合成到底色上（形状在画布空间以掩码/环表示）。"""

    def __init__(self, shape_wh, background):
        self.composite = np.empty((shape_wh[1], shape_wh[0], 3), np.float32)
        self.composite[:] = np.asarray(background, np.float32)

    def fill_mask(self, mask, x, y, paint):
        """整幅布尔掩码直接涂色。"""
        height, width = mask.shape
        layer = paint_layer(paint, width, height)
        if layer is not None:
            region = self.composite[y:y + height, x:x + width]
            region[mask] = layer[mask]

    def fill_rings(self, points, origin, size, paint):
        """偶奇环（画布空间 float 点集）涂色：先栅格化环内掩码再上色。"""
        x0 = max(0, int(math.floor(origin[0])))
        y0 = max(0, int(math.floor(origin[1])))
        x1 = min(self.composite.shape[1], int(math.ceil(origin[0] + size[0])))
        y1 = min(self.composite.shape[0], int(math.ceil(origin[1] + size[1])))
        if x1 <= x0 or y1 <= y0:
            return
        local = np.asarray(points) - (x0, y0)
        mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(mask, [np.round(local).astype(np.int32)], 1)
        layer = paint_layer(paint, x1 - x0, y1 - y0)
        if layer is not None:
            region = self.composite[y0:y1, x0:x1]
            region[mask > 0] = layer[mask > 0]

    def errors(self, reference):
        """全尺寸 MAE + 64px 缩略图 MAE（0-255，越低越贴近）。"""
        detail = float(np.abs(self.composite - reference.astype(np.float32)).mean())
        scale = 64 / max(reference.shape[:2])
        small_ref = cv2.resize(reference, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        small_out = cv2.resize(self.composite, (small_ref.shape[1], small_ref.shape[0]),
                               interpolation=cv2.INTER_AREA)
        small = float(np.abs(small_out - small_ref.astype(np.float32)).mean())
        return round(detail, 2), round(small, 2)
