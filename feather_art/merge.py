"""小色块合并：把面积太小的碎块塞进相邻且颜色相近的大块。

量化之后那些细碎的杂色（< TINY_AREA 像素）多半是抗锯齿边或噪点，
留着就是视觉噪音。这里是「邻接 + 色差小 + 只进大块」的保守策略逐轮来：
- 只准并入面积更大的邻块（平手时编号大者），合并方向收敛、不震荡；
- 色差上限 COLOR_TOLERANCE、累计漂移上限 DRIFT_LIMIT——太贪会把细线
  吃没，眼线、发丝全靠这两道闸保命；
- 每轮基于当前状态重标组件，决策索引不陈旧。
"""

import cv2
import numpy as np

TINY_AREA = 16        # 小于此面积的组件被视为碎块
COLOR_TOLERANCE = 18  # 单通道最大色差
DRIFT_LIMIT = 23      # 与原始标签的最大累计漂移


def label_components(labels: np.ndarray):
    """8 连通同色组件编号（一次扫描）。

    编号按颜色值升序、再按 crop 扫描序递增——同一依赖环境下结果确定，
    是全管线确定性的组成部分。

    返回 (ids, colors, areas, boxes, centers)：
    - ids: int32 HxW 的组件图（0 = 不属于任何组件）；
    - colors / areas / boxes / centers: 与组件编号平行的数组，下标 0 占位。

    实现上按颜色分组后，只在每个颜色的包围盒内跑连通域标记，
    比每色全图掩码快得多。
    """
    height, width = labels.shape
    ids = np.zeros(labels.shape, np.int32)
    flat = labels.ravel()
    order = np.argsort(flat, kind="stable")
    grouped = flat[order]
    starts = np.flatnonzero(np.concatenate(([True], grouped[1:] != grouped[:-1])))
    colors = grouped[starts]
    ends = np.concatenate((starts[1:], [grouped.size]))

    component_colors, component_areas = [0], [0]
    component_boxes, component_centers = [(0, 0, 0, 0)], [(0.0, 0.0)]
    offset = 0
    for color, start, end in zip(colors, starts, ends):
        span = order[start:end]
        ys = span // width
        xs = span - ys * width
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        crop = (labels[y0:y1 + 1, x0:x1 + 1] == color).astype(np.uint8)
        count, local, stats, centers = cv2.connectedComponentsWithStats(crop, connectivity=8)
        if count == 1:
            continue
        region = ids[y0:y1 + 1, x0:x1 + 1]
        region[local > 0] = local[local > 0] + offset
        component_colors.extend([int(color)] * (count - 1))
        component_areas.extend(stats[1:, cv2.CC_STAT_AREA].tolist())
        component_boxes.extend(zip(
            stats[1:, cv2.CC_STAT_LEFT] + x0,
            stats[1:, cv2.CC_STAT_TOP] + y0,
            stats[1:, cv2.CC_STAT_WIDTH],
            stats[1:, cv2.CC_STAT_HEIGHT],
        ))
        component_centers.extend(zip(centers[1:, 0] + x0, centers[1:, 1] + y0))
        offset += count - 1
    return (ids, np.asarray(component_colors), np.asarray(component_areas),
            np.asarray(component_boxes, dtype=np.int32),
            np.asarray(component_centers, dtype=np.float64))


def merge_regions(labels: np.ndarray, palette: np.ndarray,
                  passes: int = 4, progress=lambda _: None) -> np.ndarray:
    """逐轮把碎块并入相邻大块，返回新的标签图（uint8）。

    轮内候选收集：
    1. 四个方向（右、下、右下、左下）扫描相邻像素对，只保留跨组件的；
    2. 碎块只能并入面积更大或平手时编号更大的邻块；
    3. 色差按 palette 单通道最大差 <= COLOR_TOLERANCE；
    4. 候选按 (src, 色差平方和, dst) 排序，每个 src 只取最优；
    5. 轮末漂移超限的像素回退到原始标签，防止连环并色把小色带吞没。
    """
    labels = labels.copy()
    original = labels.copy()
    for iteration in range(passes):
        ids, component_colors, component_areas, _, _ = label_components(labels)
        component_colors = np.asarray(component_colors)
        component_areas = np.asarray(component_areas)
        proposals = []
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            ya, yb = (slice(0, -1), slice(1, None)) if dy else (slice(None), slice(None))
            if dx == 1:
                xa, xb = slice(0, -1), slice(1, None)
            elif dx == -1:
                xa, xb = slice(1, None), slice(0, -1)
            else:
                xa, xb = slice(None), slice(None)
            one, two = ids[ya, xa].ravel(), ids[yb, xb].ravel()
            boundary = one != two
            one, two = one[boundary], two[boundary]
            for src, dst in ((one, two), (two, one)):
                candidate = (component_areas[src] < TINY_AREA) & (
                    (component_areas[dst] > component_areas[src])
                    | ((component_areas[dst] == component_areas[src]) & (dst > src))
                )
                src, dst = src[candidate], dst[candidate]
                if not len(src):
                    continue
                diff = palette[component_colors[src]].astype(np.float32) - palette[
                    component_colors[dst]
                ].astype(np.float32)
                accepted = np.max(np.abs(diff), axis=1) <= COLOR_TOLERANCE
                src, dst, diff = src[accepted], dst[accepted], diff[accepted]
                if len(src):
                    proposals.append(np.column_stack((src, dst, np.sum(diff * diff, axis=1))))
        if not proposals:
            break
        candidates = np.concatenate(proposals)
        ordered = candidates[np.lexsort((candidates[:, 1], candidates[:, 2], candidates[:, 0]))]
        _, first = np.unique(ordered[:, 0], return_index=True)
        best = ordered[first]
        new_colors = component_colors.copy()
        new_colors[best[:, 0].astype(int)] = component_colors[best[:, 1].astype(int)]
        updated = new_colors[ids].astype(np.uint8)
        drift = np.abs(palette[updated].astype(np.int16) - palette[original].astype(np.int16)).max(axis=2)
        updated[drift > DRIFT_LIMIT] = labels[drift > DRIFT_LIMIT]
        changes = int(np.count_nonzero(updated != labels))
        labels = updated
        progress(f"Merge {iteration + 1}/{passes}: {changes} pixels")
        if not changes:
            break
    return labels
