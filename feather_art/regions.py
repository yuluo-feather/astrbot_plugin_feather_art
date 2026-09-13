"""结构化中间表示：把标签图与调色板变成「带涂色的环集合」。

做到这一层为止，下游只管把环写成自己那套语法；纯色还是渐变、洞往哪边转、
碎块怎么聚组都已经算完。这是渲染后端可插拔的前提——换书写方式不必重算轮廓。

顺序即绘制顺序，且是确定性的：
- 颜色按亮度高者先垫底（同亮度按编号升序）；
- 同色内先出大块、再出按网格聚组的碎块（碎块多而小，聚成一组省元素）；
- 底板剪影先于前景，它住在降采样网格里，专治缩小观看时的浅色接缝。

两个盒子别混：环住在自己的网格里（前景 = 画布像素，底板 = 降采样网格），
Region.box 是「归一化基准盒」——百分比与绝对坐标都由它推，两边不必互换。
底板层的基准盒还兼着「拉伸」的语义：同一串百分比铺到整幅画布上，等于把
粗网格拉开，所以底板用不着额外的缩放系数。

相似度栅格化在这一层顺手做掉：它镜像的是「谁盖住谁」，与写成哪家语法无关；
塞进中间表示反而会把评分细节漏进本该干净的几何层。
"""

from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import bridge_rings, component_rings, mask_rings
from .merge import label_components
from .paint import Solid, paint_for_region
from .quantize import quantize

SMALL_GROUP_GRID = 160   # 碎块分组网格（逻辑像素）
SMALL_AREA = 24          # 小于该面积的组件算碎块：只涂纯色、按网格聚组
UNDERPAINT_COLORS = 48   # 底板剪影的调色板规模
UNDERPAINT_SCALE = 516   # 底板宽度上限（再与 1/3 尺寸取小）
MATTE_TOLERANCE = 3      # 与底色单通道差 <= 该值的颜色不画（看不见的层）


@dataclass(frozen=True, eq=False)
class Region:
    """一块要涂色的区域。

    rings: 外环 + 洞环（洞环方向与外环相反，配合 nonzero 绕数填充挖孔）；
    paint: Solid 或 Gradient；
    box: (origin, size) 归一化基准盒——序列化时按它把环换算成百分比或绝对坐标。
    前景形状的 box 就是环自己的包围盒；底板层的 box 是降采样网格的整幅尺寸
    （环住在那张网格里，盒子于是不等于环的包围盒）。
    """

    rings: list
    paint: object
    box: tuple


@dataclass(frozen=True, eq=False)
class Clip:
    """剪影：一组环 + 归一化基准盒（底板用它裁掉外头的部分）。"""

    rings: list
    box: tuple


@dataclass(frozen=True, eq=False)
class Foundation:
    """底板：一张剪影，里面住着若干分色层，先垫底压住接缝。"""

    clip: Clip
    regions: list


@dataclass(frozen=True, eq=False)
class Illustration:
    """一张画的全套数据：画布尺寸、底色、前景区域、可选底板、产出统计。"""

    width: int
    height: int
    background: np.ndarray
    foreground: list
    foundation: object          # Foundation 或 None
    stats: dict


def color_order(labels: np.ndarray, palette: np.ndarray) -> list[int]:
    """颜色绘制顺序：亮度高者先垫底，亮度相同按编号升序（确定性）。"""
    return sorted(np.unique(labels),
                  key=lambda i: (-float(palette[i] @ np.array([.2126, .7152, .0722])), int(i)))


def same_as_matte(rgb, background) -> bool:
    """与底色几乎同色（单通道差 <= MATTE_TOLERANCE）则不必画。"""
    return int(np.abs(np.asarray(rgb, np.int16) - background).max()) <= MATTE_TOLERANCE


class _Producer:
    """标签图 → 区域；几何与涂色都在这层，一行 CSS 都不写。"""

    def __init__(self, reference, background, epsilon, gradients, progress, raster):
        self.reference = reference
        self.height, self.width = reference.shape[:2]
        self.background = np.asarray(background)
        self.epsilon = epsilon
        self.gradients = gradients
        self.progress = progress
        self.raster = raster
        self.stats = {"interior_holes": 0}
        self.foundation_shapes = 0

    # ---- 底板 ----

    def foundation(self):
        """低分辨率底板：剪影 + 分色层；画布太小时不做。"""
        if min(self.width, self.height) < 8:
            return None
        difference = np.abs(self.reference.astype(np.int16) - self.background).max(axis=2)
        silhouette = cv2.medianBlur((difference > 9).astype(np.uint8), 3)
        silhouette = cv2.erode(silhouette, np.ones((5, 5), np.uint8))
        clip_rings = mask_rings(silhouette, .5, 8)
        if not clip_rings:
            return None
        clip = Clip(clip_rings, (np.zeros(2), np.array(silhouette.shape[::-1], float)))
        scale = min(1, UNDERPAINT_SCALE / self.width, 1 / 3)
        small = cv2.resize(self.reference,
                           (max(2, round(self.width * scale)), max(2, round(self.height * scale))),
                           interpolation=cv2.INTER_AREA)
        small = cv2.medianBlur(small, 3)
        labels, palette = quantize(small, UNDERPAINT_COLORS)
        box = (np.zeros(2), np.array(small.shape[1::-1], float))
        regions = []
        for color in color_order(labels, palette):
            rgb = palette[color]
            if same_as_matte(rgb, self.background):
                continue
            mask = cv2.dilate((labels == color).astype(np.uint8),
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
            rings = mask_rings(mask, .26, 1)
            if not rings:
                continue
            regions.append(Region(rings, Solid(rgb), box))
            if self.raster is not None:
                # 底板按「膨胀后的整幅掩码」参与评分，而不是按简化后的多边形——
                # 这是既有口径，改了 MAE 就跟着变
                full = cv2.resize(mask, (self.width, self.height), interpolation=cv2.INTER_NEAREST)
                self.raster.fill_mask(full > 0, 0, 0, Solid(rgb))
        return Foundation(clip, regions)

    # ---- 前景 ----

    def foreground(self, labels, palette) -> list:
        """逐色产出区域：大块按组件顺序，碎块按网格聚在每色末尾。"""
        regions = []
        ids, colors_by_component, areas, boxes, centers = label_components(labels)
        components_of = {}
        for component in range(1, len(colors_by_component)):
            components_of.setdefault(int(colors_by_component[component]), []).append(component)
        order = color_order(labels, palette)
        for position, color in enumerate(order):
            rgb = palette[color]
            if same_as_matte(rgb, self.background):
                continue
            small_groups = {}
            for component in components_of.get(int(color), ()):
                x, y, width, height = map(int, boxes[component])
                area = int(areas[component])
                mask = (ids[y:y + height, x:x + width] == component).astype(np.uint8)
                if area >= SMALL_AREA:
                    paint = paint_for_region(
                        self.reference, mask, x, y, width, height, self.gradients)
                else:
                    paint = Solid(rgb)
                for rings in component_rings(mask, x, y, area, self.epsilon):
                    self.stats["interior_holes"] += len(rings) - 1
                    if area < SMALL_AREA:
                        key = tuple((centers[component] // SMALL_GROUP_GRID).astype(int))
                        small_groups.setdefault(key, []).extend(rings)
                    else:
                        region = self._region(rings, paint)
                        if region is not None:
                            regions.append(region)
            for rings in small_groups.values():
                region = self._region(rings, Solid(rgb))
                if region is not None:
                    regions.append(region)
            if position % 32 == 0:
                self.progress(f"Trace {position + 1}/{len(order)} colors: "
                              f"{self.foundation_shapes + len(regions)} shapes")
        return regions

    def _region(self, rings, paint):
        """一组环 → Region；零尺寸的退化区域直接丢掉（写出来也是白写）。"""
        points = np.concatenate(rings)
        origin = points.min(axis=0)
        size = points.max(axis=0) - origin
        if np.any(size <= 0):
            return None
        if self.raster is not None:
            self.raster.fill_rings(bridge_rings(rings), origin, size, paint)
        return Region(rings, paint, (origin, size))


def build_illustration(reference, labels, palette, *, background, epsilon, gradients,
                       underpainting: bool = True, progress: Callable = None,
                       raster=None) -> Illustration:
    """标签图 + 调色板 → Illustration。

    reference: 已合成的参考图（HxWx3 uint8，画布像素）；
    raster: 可选的 Rasterizer；给了就按绘制顺序把涂色镜像进去，供离线相似度用。
    """
    producer = _Producer(reference, background, epsilon, gradients,
                         progress or (lambda _: None), raster)
    foundation = producer.foundation() if underpainting else None
    producer.foundation_shapes = len(foundation.regions) if foundation else 0
    return Illustration(width=producer.width, height=producer.height,
                        background=producer.background,
                        foreground=producer.foreground(labels, palette),
                        foundation=foundation, stats=producer.stats)
