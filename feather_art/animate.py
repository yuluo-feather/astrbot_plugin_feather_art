"""动画层：多帧采样 + 跨帧图层跟踪。

羽画的做法，不照搬 css-video 的「帧内聚块 + 序号对齐」：
- 复用自家的量化/合并/轮廓管线，动画只管「多帧」这一件事；
- 帧间图层 = 确定性贪心匹配（IoU + 颜色相近 + 质心距离 加权打分），
  同一物体跨帧串成轨迹，某帧短了就用上一帧锚定，不闪；
- 全是纯函数，不碰随机，结果可复现。

与静态管线接缝：这里产出「每帧形状集合 + 图层轨迹」，
怎么渲染、颜色怎么取，交给 render（复用 geometry/paint）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import cv2
import numpy as np

@dataclass(frozen=True)
class ShapeKey:
    """一帧里一个连通分量（实例）的身份与特征。"""

    frame: int      # 帧下标
    label: int      # 量化色板 label
    poly: np.ndarray  # 亚像素轮廓点（float32, Nx2，画布像素坐标）
    bbox: tuple[int, int, int, int]  # x, y, w, h
    centroid: tuple[float, float]
    area: int
    color: tuple[int, int, int]  # 该实例区域内像素均值（int 0-255）

@dataclass
class Track:
    """一条图层轨迹：跨帧的同一实例。"""

    keys: list[ShapeKey] = field(default_factory=list)

    @property
    def first(self) -> ShapeKey:
        return self.keys[0]


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _color_sim(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """颜色相似度 0..1：距离 0 → 1，距离 ≥ 255√3 → 0。"""
    dist = float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float)))
    return max(0.0, 1.0 - dist / (255.0 * np.sqrt(3.0)))


def _centroid_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def match_score(a: ShapeKey, b: ShapeKey, size: tuple[int, int]) -> float:
    """两帧间两个形状的匹配分：IoU 为主、颜色其次、质心距离惩罚。"""
    diag = float(np.hypot(*size))
    iou = _iou(a.bbox, b.bbox)
    color = _color_sim(a.color, b.color)
    dist_penalty = 1.0 - min(1.0, _centroid_dist(a.centroid, b.centroid) / (0.5 * diag))
    return 0.6 * iou + 0.25 * color + 0.15 * dist_penalty


def track_shapes(seq: Sequence[Sequence[ShapeKey]], size: tuple[int, int],
                 min_score: float = 0.30) -> list[Track]:
    """把多帧形状序列串成图层轨迹（确定性贪心）。

    - 帧 t 的每个形状，在帧 t+1 里挑分最高、且 ≥ min_score、且未被占用的形状匹配；
    - 匹配不上的形状开新轨迹（出现）；轨迹在下一帧无匹配 → 该帧锚定上一帧（不闪烁）；
    - 返回的轨迹按「首次出现帧」排序，保证输出确定。
    """
    tracks: list[Track] = []
    # 上帧所有形状 → 当前轨迹槽位（每槽位放一个 ShapeKey 或 None=锚定）
    prev_keys: list[tuple[int, ShapeKey | None]] = []  # (track_idx, key or None)
    for frame_idx, shapes in enumerate(seq):
        if frame_idx == 0:
            for shape in shapes:
                tracks.append(Track(keys=[shape]))
            prev_keys = [(i, tracks[i].keys[0]) for i in range(len(tracks))]
            continue
        used: set[int] = set()
        current: list[tuple[int, ShapeKey | None]] = [(i, None) for i, _ in prev_keys]
        for shape in shapes:
            best_track, best_score = -1, -1.0
            for track_idx, (_, prev_key) in enumerate(prev_keys):
                if track_idx in used or prev_key is None:
                    continue
                score = match_score(prev_key, shape, size)
                if score > best_score:
                    best_track, best_score = track_idx, score
            if best_track >= 0 and best_score >= min_score:
                used.add(best_track)
                tracks[best_track].keys.append(shape)
                current[best_track] = (best_track, shape)
            else:
                # 新出现的物体 → 开新轨迹
                tracks.append(Track(keys=[shape]))
                current.append((len(tracks) - 1, shape))
        for track_idx, key in current:
            if key is None:
                # 轨迹本帧无匹配：锚定上一帧特征（不闪烁），不新增 ShapeKey
                pass
        prev_keys = current
    return tracks


def extract_shapes(labels: np.ndarray, palette: np.ndarray, ref: np.ndarray,
                   frame: int, epsilon: float, min_area: int = 2) -> list[ShapeKey]:
    """一帧合并后的 label 图 → 实例级形状集合（连通分量）。

    轮廓取简化折线（动画专用精简实现：不做 4x 亚像素采样与平滑，帧多
    求快，细节保真交给静态管线）；颜色取该实例像素均值（对动画帧更稳：
    不吃色板代表色偏差）。
    """
    shapes: list[ShapeKey] = []
    for label in np.unique(labels):
        # 包围盒裁剪：只在该 label 的包围盒内做连通域（分量必在盒内），
        # 省掉全图扫描；坐标回移后结果与全图扫描一致。注意：裁剪后组件
        # 编号会重排，取特征要用 stats/centroids 的值，别按编号对应。
        ys, xs = np.nonzero(labels == label)
        if ys.size == 0:
            continue
        y0, x0 = int(ys.min()), int(xs.min())
        y1, x1 = int(ys.max()), int(xs.max())
        sub = (labels[y0:y1 + 1, x0:x1 + 1] == label).astype(np.uint8)
        n, _, stats, centroids = cv2.connectedComponentsWithStats(sub, connectivity=8)
        for comp in range(1, n):
            lx, ly, cw, ch, area = stats[comp]
            if area < min_area:
                continue
            x, y = x0 + int(lx), y0 + int(ly)  # 回到画布坐标
            cx = float(centroids[comp][0]) + x0
            cy = float(centroids[comp][1]) + y0
            # 该分量内像素均值色
            comp_mask = (labels[y:y + ch, x:x + cw] == label)
            region = ref[y:y + ch, x:x + cw][comp_mask]
            if region.size == 0:
                mean_rgb = tuple(palette[label])
            else:
                mean_rgb = tuple(np.round(region.mean(axis=0)).astype(int))
            # 轮廓：分量掩码 → 简化折线（动画专用：不做 4x 亚像素采样，帧多求快）
            sub_mask = sub[ly:ly + ch, lx:lx + cw]
            padded = np.pad(sub_mask, 1)
            contours, _ = cv2.findContours(padded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            pts = None
            for contour in contours:
                approx = cv2.approxPolyDP(contour, epsilon, True)[:, 0, :].astype(float) - 1
                if len(approx) >= 3 and (pts is None or len(approx) > len(pts)):
                    pts = approx + np.array([x, y], float)  # 回到画布坐标
            if pts is None or len(pts) < 3:
                continue
            shapes.append(ShapeKey(
                frame=frame, label=int(label), poly=pts.astype(np.float32),
                bbox=(int(x), int(y), int(cw), int(ch)),
                centroid=(float(cx), float(cy)), area=int(area), color=mean_rgb))
    shapes.sort(key=lambda s: (s.centroid[1], s.centroid[0], s.label))
    return shapes


def anchor_track(track: Track, frame_count: int) -> list[ShapeKey | None]:
    """轨迹按帧展开：缺失帧用 None 表示（渲染时锚定上一帧特征）。"""
    out: list[ShapeKey | None] = [None] * frame_count
    for key in track.keys:
        out[key.frame] = key
    return out
