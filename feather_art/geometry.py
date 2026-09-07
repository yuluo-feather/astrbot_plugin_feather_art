"""轮廓几何：亚像素平滑、多边形简化、nonzero 填充与 CSS 坐标序列化。

坐标在「画布空间」里一律 float（单位 = 参考图像素），进 CSS 前按形状
包围盒归一化成百分比。孔洞和孤岛走 nonzero 绕数规则：多环共用一个
polygon，环之间用零面积桥相连，洞环方向翻到与外环相反——这样即便
旧内核不认 `clip-path: polygon(evenodd, ...)` 的 fill-rule 参数
（Chromium 88 之前整条声明会失效、形状退化成整矩形），桥接拓扑依然
完整，等价于偶奇填充。
"""

import cv2
import numpy as np

# 轮廓采样网格放大倍数与半像素偏移：4x 采样把锯齿压到亚像素
SUPERSAMPLE = 4
HALF_PIXEL = 0.125


def number(value: float, digits: int = 3) -> str:
    """CSS 数字压缩：去尾零，去前导零（.5 而非 0.5），0 兜底。"""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    if text.startswith("0."):
        text = text[1:]
    elif text.startswith("-0."):
        text = "-" + text[2:]
    return "0" if text in ("", "-0", "-.") else text


def hex_color(rgb) -> str:
    """RGB 数组/元组 → #rrggbb（小写，四舍五入后夹在 0-255）。"""
    return "#" + "".join(f"{int(v):02x}" for v in np.clip(np.rint(rgb), 0, 255))


def _signed_area(points: np.ndarray) -> float:
    """鞋带公式有向面积：y 向下图像坐标系里顺时针为正。"""
    x, y = points[:, 0], points[:, 1]
    return float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) / 2.0


def _flip_ring(ring: np.ndarray) -> np.ndarray:
    """环方向反转（返回副本），用于把洞环翻到与外环相反。"""
    return ring[::-1].copy()


def bridge_rings(rings: list[np.ndarray]) -> np.ndarray:
    """多环 → 单条点序列：环间加零面积桥，nonzero 下照样挖孔。

    桥的路径是「环起点 → 环上每点 → 回到环起点 → 回锚点」的重描，
    面积严格为零，绕数填充里去回两条桥的贡献互相抵消。
    调用方须保证洞环方向与外环相反（见 component_rings / mask_polygon）。
    """
    points = list(rings[0])
    if len(rings) > 1:
        anchor = rings[0][0]
        points.append(anchor)
        for ring in rings[1:]:
            points.extend(ring)
            points.extend((ring[0], anchor))
    return np.asarray(points)


def polygon_css(points: np.ndarray, origin: np.ndarray, size: np.ndarray,
                digits: int = 3) -> str:
    """画布空间点集 → CSS clip-path polygon(...) 字符串（归一化到包围盒）。

    故意不写 evenodd 参数：fill-rule 在 Chromium 88 之前的 WebView 里
    不被解析，整条 clip-path 会失效。桥接 + 反向洞环在 nonzero 下
    效果等价，兼容面反而更宽。多环请先 bridge_rings。
    """
    normalized = (points - origin) / size * 100
    coords = ",".join(f"{number(x, digits)}% {number(y, digits)}%" for x, y in normalized)
    return f"polygon({coords})"


def smooth_ring(contour: np.ndarray, x: int, y: int, epsilon: float) -> np.ndarray:
    """一条轮廓 → 亚像素平滑后的折线（float32 点集）。

    contour 来自 4x 采样网格：还原到画布空间除以 4，加半像素偏移；
    长度超 8 的点做 [1,2,1] 加权平滑（首尾回绕），再用 approxPolyDP 简化。
    """
    points = contour[:, 0, :].astype(np.float32) / SUPERSAMPLE
    points += np.array([x + HALF_PIXEL, y + HALF_PIXEL], np.float32)
    if len(points) > 8:
        points = (np.roll(points, 1, axis=0) + 2 * points + np.roll(points, -1, axis=0)) / 4
    return cv2.approxPolyDP(points[:, None, :], epsilon, True)[:, 0, :]


def component_rings(mask: np.ndarray, x: int, y: int, area: int, epsilon: float):
    """单个组件掩码 → (外环 [ , 内洞 ...]) 的生成器。

    流程：2px 填充 → 4x 最近邻放大 → 按面积选膨胀核（>=24 用 5x5 椭圆，
    否则 3x3 十字，保住细线）→ RETR_CCOMP 找轮廓 → 外环 + child 链上的洞。
    空洞面积阈值 0.25 像素，比 1 更宽容，微小的咬边不再算洞。
    """
    padded = np.pad(mask, 2)
    expanded = cv2.resize(padded, None, fx=SUPERSAMPLE, fy=SUPERSAMPLE,
                          interpolation=cv2.INTER_NEAREST)
    kind, size = (cv2.MORPH_ELLIPSE, 5) if area >= 24 else (cv2.MORPH_CROSS, 3)
    expanded = cv2.dilate(expanded, cv2.getStructuringElement(kind, (size, size)))
    contours, hierarchy = cv2.findContours(expanded, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return
    for index, contour in enumerate(contours):
        if hierarchy[0, index, 3] != -1:
            continue
        outer = smooth_ring(contour, x - 2, y - 2, epsilon)
        if len(outer) < 3:
            continue
        rings = [outer]
        outer_sign = _signed_area(outer)
        child = int(hierarchy[0, index, 2])
        while child != -1:
            hole = smooth_ring(contours[child], x - 2, y - 2, epsilon)
            if len(hole) >= 3 and abs(cv2.contourArea(hole)) >= .25:
                if _signed_area(hole) * outer_sign > 0:
                    hole = _flip_ring(hole)
                rings.append(hole)
            child = int(hierarchy[0, child, 0])
        yield rings


def mask_polygon(mask: np.ndarray, epsilon: float, min_area: float):
    """整幅掩码 → (polygon CSS, 顶点数)。孔洞走方向归一化 + nonzero 填充。

    用 RETR_CCOMP 拿父子关系（RETR_LIST 无层级，桥接顺序会乱套）；
    洞环方向翻到与外环相反——旧内核不认 evenodd 也能正确挖孔。
    与 component_rings 的用途不同：这里处理的是「底板剪影」这类大而整的
    掩码（含孔洞），输出直接是 CSS 片段。
    """
    contours, hierarchy = cv2.findContours(np.pad(mask, 1), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None, 0
    outer_rings, hole_rings = [], []
    for index, contour in enumerate(contours):
        if abs(cv2.contourArea(contour)) < min_area:
            continue
        points = cv2.approxPolyDP(contour, epsilon, True)[:, 0, :].astype(float) - 1
        if len(points) >= 3:
            if hierarchy[0, index, 3] == -1:
                outer_rings.append(points)
            else:
                hole_rings.append(points)
    if not outer_rings:
        return None, 0
    rings = list(outer_rings)
    outer_sign = _signed_area(outer_rings[0])
    for hole in hole_rings:
        rings.append(_flip_ring(hole) if _signed_area(hole) * outer_sign > 0 else hole)
    points = bridge_rings(rings)
    return polygon_css(points, np.zeros(2), np.array(mask.shape[::-1]), 4), len(points)
