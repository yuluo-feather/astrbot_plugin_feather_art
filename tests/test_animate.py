"""animate：帧间图层跟踪（确定性贪心）+ 实例特征提取。"""
import numpy as np
import pytest

from data.plugins.astrbot_plugin_feather_art.feather_art.animate import (  # noqa: E402
    ShapeKey, Track, _iou, _color_sim, extract_shapes, match_score,
    track_shapes, anchor_track,
)

SIZE = (100, 100)


def _key(frame, x=10, y=10, w=20, h=20, color=(100, 100, 100), label=1):
    return ShapeKey(
        frame=frame, label=label,
        poly=np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float32),
        bbox=(x, y, w, h), centroid=(x + w / 2, y + h / 2),
        area=w * h, color=color)


# ---------- 打分 ----------

def test_iou_full_overlap():
    assert _iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)


def test_iou_disjoint():
    assert _iou((0, 0, 10, 10), (20, 0, 10, 10)) == 0.0


def test_color_sim_same():
    assert _color_sim((50, 50, 50), (50, 50, 50)) == 1.0


def test_color_sim_black_white():
    assert _color_sim((0, 0, 0), (255, 255, 255)) == pytest.approx(0.0)


def test_match_score_moves_penalty():
    near = match_score(_key(0, x=10), _key(1, x=14), SIZE)
    far = match_score(_key(0, x=10), _key(1, x=80), SIZE)
    assert near > far
    assert near > 0.6


# ---------- 跟踪 ----------

def test_track_stable_object():
    """同一个物体小步移动 → 一条轨迹贯穿三帧。"""
    seq = [
        [_key(0, x=10), _key(0, x=60, color=(200, 0, 0), label=2)],
        [_key(1, x=12), _key(1, x=62, color=(200, 0, 0), label=2)],
        [_key(2, x=14), _key(2, x=64, color=(200, 0, 0), label=2)],
    ]
    tracks = track_shapes(seq, SIZE)
    assert len(tracks) == 2
    for t in tracks:
        assert len(t.keys) == 3
        assert [k.frame for k in t.keys] == [0, 1, 2]


def test_track_new_object_opens_new_track():
    """第二帧冒出一个新物体 → 新轨迹。"""
    seq = [
        [_key(0, x=10)],
        [_key(1, x=12), _key(1, x=70)],
        [_key(2, x=14), _key(2, x=72)],
    ]
    tracks = track_shapes(seq, SIZE)
    assert len(tracks) == 2
    assert len(tracks[1].keys) == 2 and tracks[1].keys[0].frame == 1


def test_track_gap_anchors_then_reopens():
    """物体被别的物体顶替一帧后重现 → 分两条轨迹（确定性行为）。"""
    seq = [
        [_key(0, x=10)],
        [_key(1, x=60, color=(9, 9, 9), label=7)],  # 原物体消失，来了别的
        [_key(2, x=14)],  # 原物体重现（位置接近）
    ]
    tracks = track_shapes(seq, SIZE)
    assert len(tracks) == 3
    frames = sorted(k.frame for k in tracks[0].keys)
    assert frames == [0]
    frames2 = sorted(k.frame for k in tracks[-1].keys)
    assert frames2 == [2]


def test_anchor_track_expands_with_none():
    """anchor_track：缺失帧填 None，占用帧填 ShapeKey。"""
    t = Track(keys=[_key(0), _key(2)])
    out = anchor_track(t, 4)
    assert len(out) == 4
    assert out[0] is not None and out[1] is None and out[2] is not None and out[3] is None


# ---------- 特征提取 ----------

def test_extract_shapes_instances():
    """两个同 label 的不连通区域 → 两个实例 + 背景分量，颜色取均值。"""
    labels = np.zeros((20, 20), np.int32)
    labels[2:8, 2:8] = 1
    labels[12:18, 2:8] = 1
    palette = np.array([[255, 255, 255], [100, 100, 100]], np.uint8)
    ref = np.full((20, 20, 3), 255, np.uint8)
    ref[2:8, 2:8] = (90, 90, 90)
    ref[12:18, 2:8] = (110, 110, 110)
    shapes = extract_shapes(labels, palette, ref, frame=0, epsilon=0.4)
    # 背景分量（覆盖画布边缘）也算一个，共 3 个
    assert len(shapes) == 3
    areas = sorted(s.area for s in shapes)
    assert areas == [36, 36, 328]
    colors = sorted(s.color for s in shapes)
    assert colors[0][0] in (90, 91)  # 均值近似整数
    assert colors[1][0] in (110, 111)


def test_extract_shapes_min_area_filter():
    labels = np.zeros((10, 10), np.int32)
    labels[1:3, 1:3] = 1   # 4px
    labels[5:9, 5:9] = 1   # 16px
    palette = np.array([[0, 0, 0], (50, 50, 50)], np.uint8)
    ref = np.zeros((10, 10, 3), np.uint8)
    shapes = extract_shapes(labels, palette, ref, frame=0, epsilon=0.4, min_area=8)
    assert len(shapes) == 2  # 背景(80px) + 16px 方块；4px 被过滤
    areas = sorted(s.area for s in shapes)
    assert areas == [16, 80]
