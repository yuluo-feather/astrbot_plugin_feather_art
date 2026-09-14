"""算法核心测试：量化 / 合并 / 几何 / 渐变 / 成像。"""

import numpy as np

from data.plugins.astrbot_plugin_feather_art.feather_art import (
    geometry,
    imaging,
    merge,
    paint,
    presets,
    quantize,
)
import util


# ---------- quantize ----------

def _gradient_array() -> np.ndarray:
    img = np.zeros((6, 8, 3), np.uint8)
    img[:, :, 0] = np.linspace(0, 255, 8, dtype=np.uint8)[None, :]
    img[:, :, 1] = np.linspace(20, 200, 6, dtype=np.uint8)[:, None]
    return img


def test_quantize_buckets():
    labels, palette = quantize.quantize(_gradient_array(), 4)
    assert labels.shape == (6, 8)
    assert labels.dtype == np.uint8
    assert set(np.unique(labels).tolist()) <= {0, 1, 2, 3}
    assert palette.shape[0] <= 4
    assert palette.max() <= 255 and palette.min() >= 0


def test_quantize_single_color():
    img = np.full((10, 10, 3), 200, np.uint8)
    labels, palette = quantize.quantize(img, 8)
    assert np.unique(labels).tolist() == [0]
    assert np.allclose(palette[0], [200, 200, 200], atol=1)


def test_quantize_deterministic():
    img = _gradient_array()
    l1, p1 = quantize.quantize(img, 5)
    l2, p2 = quantize.quantize(img, 5)
    assert np.array_equal(l1, l2) and np.array_equal(p1, p2)


def test_oklab_of_shape():
    out = quantize.oklab_of(np.array([[128, 64, 255]], np.uint8))
    assert out.shape == (1, 3)
    assert np.isfinite(out).all()


# ---------- merge ----------

def test_tiny_adjacent_merged():
    labels = np.zeros((24, 24), np.uint8)
    labels[:, :] = 1
    labels[20:22, 20:22] = 2
    palette = np.array([[0, 0, 0], [100, 100, 100], [115, 115, 115]], np.uint8)
    merged = merge.merge_regions(labels, palette, passes=2)
    assert merged[20, 20] == 1


def test_distant_color_kept():
    labels = np.zeros((24, 24), np.uint8)
    labels[:, :] = 1
    labels[20:22, 20:22] = 3
    palette = np.array([[0, 0, 0], [100, 100, 100], [0, 0, 0], [200, 200, 200]], np.uint8)
    merged = merge.merge_regions(labels, palette, passes=2)
    assert merged[20, 20] == 3


def test_merge_flat_no_change():
    labels = np.zeros((16, 16), np.uint8)
    palette = np.array([[0, 0, 0], [50, 50, 50]], np.uint8)
    merged = merge.merge_regions(labels, palette, passes=4)
    assert np.array_equal(merged, labels)


def test_label_components_index0_placeholder():
    labels = np.zeros((8, 8), np.uint8)
    labels[1:5, 1:5] = 1
    ids, colors, areas, boxes, centers = merge.label_components(labels)
    assert ids.shape == (8, 8)
    assert colors[0] == 0 and areas[0] == 0
    assert centers[0].tolist() == [0.0, 0.0]


# ---------- geometry ----------

def test_number_compression():
    assert geometry.number(0.5) == ".5"
    assert geometry.number(-0.5) == "-.5"
    assert geometry.number(12.0) == "12"
    assert geometry.number(0.0) == "0"
    assert geometry.number(0.333, 3) == ".333"
    # digits=0 是整数位（无小数点）：250 不能被去尾零啃成 25
    assert geometry.number(250.0, 0) == "250"
    assert geometry.number(250.4, 0) == "250"
    assert geometry.number(-100.6, 0) == "-101"
    assert geometry.number(0.2, 0) == "0"


def test_hex_color_rounding():
    assert geometry.hex_color([10.6, 255, 0]) == "#0bff00"
    assert geometry.hex_color([0, 0, 0]) == "#000000"


def test_polygon_css_square():
    pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    out = geometry.polygon_css(pts, np.zeros(2), np.array([10.0, 10.0]))
    assert out.startswith("polygon(")


def test_component_rings_circle():
    import cv2
    mask = np.zeros((30, 30), np.uint8)
    cv2.circle(mask, (15, 15), 10, 1, -1)
    rings = list(geometry.component_rings(mask, 0, 0, 500, 0.3))
    assert len(rings) == 1
    assert len(rings[0][0]) >= 3


def test_mask_rings_output():
    import cv2
    mask = np.zeros((30, 30), np.uint8)
    cv2.circle(mask, (15, 15), 10, 1, -1)
    rings = geometry.mask_rings(mask, 0.5, 8)
    assert len(rings) == 1 and len(rings[0]) >= 8
    assert geometry.mask_rings(np.zeros((30, 30), np.uint8), 0.5, 8) == []


def test_bridge_rings_keeps_order():
    ring1 = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
    ring2 = np.array([[20.0, 20.0], [30.0, 20.0], [30.0, 30.0]])
    bridged = geometry.bridge_rings([ring1, ring2])
    assert len(bridged) == len(ring1) + 1 + len(ring2) + 2


# ---------- paint ----------

def test_vertical_gradient_angle():
    ref = np.zeros((40, 40, 3), np.uint8)
    for yy in range(40):
        ref[yy, :, :] = yy * 6
    mask = np.ones((40, 40), bool)
    result = paint.paint_for_region(ref, mask, 0, 0, 40, 40, True)
    assert isinstance(result, paint.Gradient)
    assert result.to_css().startswith("linear-gradient(180deg,")


def test_horizontal_gradient_angle():
    ref = np.zeros((40, 40, 3), np.uint8)
    for xx in range(40):
        ref[:, xx, :] = xx * 6
    mask = np.ones((40, 40), bool)
    result = paint.paint_for_region(ref, mask, 0, 0, 40, 40, True)
    # 左暗右亮 → 90deg（终点在右）；解析特征向量符号自定，与旧 SVD 的
    # 270deg（终点在左、端点色互换）是同一渐变，视觉等价。
    assert isinstance(result, paint.Gradient)
    assert result.to_css().startswith("linear-gradient(90deg,")


def test_tiny_region_solid():
    ref = np.zeros((10, 10, 3), np.uint8)
    ref[:, :, 0] = 100
    mask = np.ones((10, 10), bool)
    result = paint.paint_for_region(ref, mask, 0, 0, 10, 10, True)
    assert isinstance(result, paint.Solid)
    assert result.to_css() == "#640000"  # 只有 R=100 → (100,0,0)


def test_flat_region_solid():
    ref = np.full((30, 30, 3), 90, np.uint8)
    mask = np.ones((30, 30), bool)
    result = paint.paint_for_region(ref, mask, 0, 0, 30, 30, True)
    assert isinstance(result, paint.Solid)
    assert result.to_css() == "#5a5a5a"


def test_min_ramp_returns_solid():
    ref = np.zeros((30, 30, 3), np.uint8)
    for yy in range(30):
        ref[yy, :, :] = yy // 30  # 通道差仅 1，远小于渐变阈值 3
    mask = np.ones((30, 30), bool)
    result = paint.paint_for_region(ref, mask, 0, 0, 30, 30, True)
    assert isinstance(result, paint.Solid)
    assert result.to_css().startswith("#")


def test_gradients_disabled_solid():
    ref = np.zeros((40, 40, 3), np.uint8)
    for yy in range(40):
        ref[yy, :, :] = yy * 6
    mask = np.ones((40, 40), bool)
    result = paint.paint_for_region(ref, mask, 0, 0, 40, 40, False)
    assert isinstance(result, paint.Solid)
    assert result.to_css().startswith("#")


# ---------- imaging ----------

def test_load_image_composites_transparency():
    ref, original = imaging.load_image(util.png_rgba(), 768, (255, 255, 255))
    assert original == (12, 10)
    assert ref.shape == (10, 12, 3)
    assert ref.dtype == np.uint8
    assert ref[0, 0].tolist() == [255, 255, 255]  # 透明角落合成白
    assert ref[4, 3].tolist() == [255, 100, 50]   # 实心像素保留


def test_load_image_rejects_animated():
    try:
        imaging.load_image(util.gif_two_frames(), 768, (255, 255, 255))
        assert False, "应当拒绝动图"
    except ValueError as exc:
        assert "动图" in str(exc)


def test_load_image_keeps_small_size():
    ref, original = imaging.load_image(util.png_bytes((20, 30)), 768, (255, 255, 255))
    assert original == (20, 30)
    assert ref.shape == (30, 20, 3)


def test_load_image_downscales():
    ref, _ = imaging.load_image(util.png_bytes((2000, 1000)), 800, (255, 255, 255))
    assert ref.shape[1] <= 800  # 宽度受限
    assert ref.shape[0] <= 1600  # 长边受限 2x


# ---------- presets ----------

def test_preset_resolve():
    assert presets.resolve("工笔").key == "finebrush"
    assert presets.resolve("sketch").key == "sketch"
    assert presets.resolve("不存在的档").key == presets.DEFAULT_KEY


def test_preset_parameters_are_locked():
    """档位参数是公开契约：动一个数字，线上所有产出都会跟着变样。

    分开锁的两种：
    - freehand 是基线红线的基准档（tests/test_render_baseline.py），
      它一动基线就整体作废，所以逐值锁死；
    - finebrush 2026-09-14 提宽 1600 → 2000，只动宽度、判据一律不动
      （实测像素 ×1.56 → 字节 ×1.26、MAE −0.50；同步挪阈值反而画质更差）。

    另加一条范围：档位宽度必须落在 WIDTH_LIMITS 内，否则 presets 的声明
    与 load_image 的死限会各说各话。
    """
    freehand = presets.PRESETS["freehand"]
    assert (freehand.max_width, freehand.colors, freehand.epsilon, freehand.passes) \
        == (1200, 160, 0.30, 3)
    finebrush = presets.PRESETS["finebrush"]
    assert (finebrush.max_width, finebrush.colors, finebrush.epsilon, finebrush.passes) \
        == (2000, 256, 0.24, 4)
    for preset in presets.PRESETS.values():
        assert presets.WIDTH_LIMITS[0] <= preset.max_width <= presets.WIDTH_LIMITS[1], preset.key


# ---------- 兼容性回归：nonzero 填充（旧 WebView 不认 evenodd） ----------

def test_polygon_css_never_evenodd():
    """多环桥接后也输出纯 polygon(...)：evenodd 参数在 Chromium 88 前的
    WebView 里不被解析，整条 clip-path 会失效、形状退化成整矩形。"""
    rect = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    hole = np.array([[2.0, 2.0], [2.0, 8.0], [8.0, 8.0], [8.0, 2.0]])
    bridged = geometry.bridge_rings([rect, hole])
    out = geometry.polygon_css(bridged, np.zeros(2), np.array([10.0, 10.0]))
    assert out.startswith("polygon(")
    assert "evenodd" not in out


def test_component_rings_hole_opposite_direction():
    """圆环 → 外环与洞环有向面积符号相反（nonzero 挖孔的前提）。"""
    import cv2
    mask = np.zeros((60, 60), np.uint8)
    cv2.circle(mask, (30, 30), 20, 1, -1)
    cv2.circle(mask, (30, 30), 9, 0, -1)
    rings = list(geometry.component_rings(mask, 0, 0, 900, 0.5))
    assert len(rings) == 1
    outer, hole = rings[0]
    assert geometry._signed_area(outer) * geometry._signed_area(hole) < 0


def test_bridged_polygon_fills_ring_under_nonzero():
    """桥接路径用 nonzero 填充（cv2.fillPoly）仍是圆环：孔洞没被填死。"""
    import cv2
    mask = np.zeros((60, 60), np.uint8)
    cv2.circle(mask, (30, 30), 20, 1, -1)
    cv2.circle(mask, (30, 30), 9, 0, -1)
    rings = list(geometry.component_rings(mask, 0, 0, 900, 0.5))[0]
    pts = geometry.bridge_rings(rings).astype(np.int32)[:, None, :]
    filled = np.zeros_like(mask)
    cv2.fillPoly(filled, [pts], 1)
    assert filled[30, 30] == 0          # 内部孔洞未被填
    assert filled[30, 12] == 1          # 外壁被填
    assert filled[12, 30] == 1
    assert filled.sum() > 600           # 圆环量级，不是被填死的实心圆


def test_mask_rings_hole_orientation():
    """底板剪影：含孔洞时给出外环 + 洞环，且两者方向相反——nonzero 挖孔的前提。"""
    import cv2
    mask = np.zeros((40, 40), np.uint8)
    cv2.circle(mask, (20, 20), 15, 1, -1)
    cv2.circle(mask, (20, 20), 6, 0, -1)
    rings = geometry.mask_rings(mask, 0.5, 8)
    assert len(rings) == 2
    assert geometry._signed_area(rings[0]) * geometry._signed_area(rings[1]) < 0


def test_version_sources_agree():
    """版本号四处必须一致：metadata.yaml、包内 __version__、两份 README 的版本勋章。

    发版最容易漏的就是只改一处——metadata 动了、README 勋章忘改，用户一眼看到旧版号。
    勋章写成 shields 的 `badge/version-vX.Y.Z` 形式，两种语言各一处。
    """
    import pathlib
    import re

    from data.plugins.astrbot_plugin_feather_art.feather_art import __version__

    root = pathlib.Path(__file__).resolve().parents[1]
    meta = (root / "metadata.yaml").read_text(encoding="utf-8")
    declared = re.search(r"^version:\s*(\S+)", meta, re.M).group(1)
    assert declared == __version__, (
        "metadata.yaml 声明 " + declared + "，包内 __version__ 是 " + __version__)
    for name in ("README.md", "README.en.md"):
        badge = re.search(r"badge/version-v([\d.]+)-", (root / name).read_text(encoding="utf-8"))
        assert badge, name + " 里找不到版本勋章"
        assert badge.group(1) == __version__, (
            name + " 的版本勋章是 v" + badge.group(1) + "，应为 v" + __version__)
