"""离线相似度镜像的口径：只涂环本身，底板按剪影裁。

镜像存在的意义是给作者一个「这次改动的画质是涨是跌」的参考数，所以它的
口径错一天，参考就误导一天。这里钉两条口径：

1. 多环形状逐环异或上色，不做「桥接成单条多边形再 fillPoly」。桥是给
   clip-path 的单多边形语法补的（序列化层的事），拿它去栅格化会把连接线
   当环壁涂上——碎块区域环多又散得开，实测碎点图相似度 14.35 对 3.08。
2. 底板按剪影裁，和文档里那层 clip-path 一致。

判据来源：同一份 CSS 文档的浏览器截图。按旧口径离线镜像与它差 38.28，
按新口径 7.31（浏览器自己与参考图 3.78，余量是抗锯齿与小数位）。
"""
import cv2
import numpy as np
import util

from data.plugins.astrbot_plugin_feather_art import service
from data.plugins.astrbot_plugin_feather_art.feather_art.geometry import bridge_rings
from data.plugins.astrbot_plugin_feather_art.feather_art.paint import Solid
from data.plugins.astrbot_plugin_feather_art.feather_art.score import Rasterizer

WHITE = (255, 255, 255)
# 碎点图实测：逐环异或 3.08、桥接 14.35。阈值取中间，留给依赖版本的浮动。
DOTS_MAE_CEILING = 6.0


def _square(x, y, side, flip=False):
    """左上方起笔的方环；flip 给反向环（洞）。"""
    ring = np.array([[x, y], [x + side, y], [x + side, y + side], [x, y + side]], np.float32)
    return ring[::-1] if flip else ring


def test_fragmented_region_paints_only_its_rings():
    """散开的碎块：多出来的像素只能是连接线，一条都不该出现。"""
    fragments = [_square(4 + 38 * (index % 5), 4 + 38 * (index // 5), 6) for index in range(25)]
    raster = Rasterizer((200, 200), (0, 0, 0))
    raster.fill_rings(fragments, np.zeros(2), np.array([200, 200], float), Solid(WHITE))
    painted = int((raster.composite[..., 0] > 128).sum())
    assert painted <= 25 * 36 * 2, f"涂了 {painted} px，碎块本身才 {25 * 36} px"
    bridged = np.zeros((200, 200), np.uint8)
    cv2.fillPoly(bridged, [np.round(bridge_rings(fragments)).astype(np.int32)], 1)
    assert int(bridged.sum()) > 25 * 36 * 2, "反向对照：桥接填法本来就会超（这条红线才有意义）"


def test_hole_ring_is_not_painted():
    """洞环把环心让出来：偶奇语义，别按「外环减洞」另算。"""
    raster = Rasterizer((80, 80), (0, 0, 0))
    raster.fill_rings([_square(10, 10, 60), _square(30, 30, 20, flip=True)],
                      np.zeros(2), np.array([80, 80], float), Solid(WHITE))
    assert raster.composite[40, 40, 0] <= 128, "环心是洞，不该上色"
    assert raster.composite[35, 15, 0] > 128, "环壁该上色"


def test_clip_to_restores_background_outside_silhouette():
    """底板按剪影裁：剪影外回底色，剪影内一个字不动。"""
    raster = Rasterizer((80, 80), (0, 0, 0))
    raster.composite[:] = (10, 200, 30)
    raster.clip_to([_square(20, 20, 40)], (0, 0, 0))
    assert raster.composite[0, 0].tolist() == [0, 0, 0]
    assert raster.composite[40, 40].tolist() == [10, 200, 30]


def test_similarity_stays_trustworthy_on_fragmented_art(tmp_path):
    """端到端：碎点图的相似度得落在浏览器能证实的量级上。"""
    report = service.trace_image(util.png_dots_like(), "freehand", tmp_path / "dots.html",
                                 config=service.TraceConfig(progress=lambda _: None),
                                 force=True)
    assert report["interior_holes"] >= 20, "这张图的意义就是喂多环，环没了红线也就空了"
    assert report["similarity"]["mae"] <= DOTS_MAE_CEILING, report["similarity"]
