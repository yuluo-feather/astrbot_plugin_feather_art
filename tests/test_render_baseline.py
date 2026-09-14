"""P0 基线红线：同一输入必须逐位复现同一份文档。

为什么单独钉一条：接下来的渲染后端重构（结构化中间表示 + 可插拔后端）是
等价改造，判据不是「看着一样」而是文档 sha256 逐位相同——重构后对不上
就是重构错了，不是「在阈值内可以接受」。

三层分开报错，好定位是谁动了：
1. 输入指纹（fixture md5）——生成器漂了；
2. 结构统计（形状数/渐变数/顶点数/洞数）——管线中段漂了；
3. 文档 sha256——序列化漂了。

基线只锁在当前依赖环境（轮廓提取与量化吃 numpy / opencv 的版本实现），
换依赖版本就得重取基线；这是有意的取舍：跨版本一致性靠不住，靠得住的是
「同一环境内逐字节可复现」这条产品承诺。
"""
import hashlib

import pytest
import util
from data.plugins.astrbot_plugin_feather_art import service

FIXTURE_MD5 = "56a7fd17e8a6ec201edf33b71f3bb46d"
DOCUMENT_SHA256 = "6c32ff9d7fedc7a79e92296d9ac941123589b38381d60b76400aa0a094d46c13"
STRUCTURE = {"shapes": 430, "gradient_fills": 205, "polygon_vertices": 10124,
             "interior_holes": 4, "underpainting_shapes": 48, "bytes": 197883}


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """整条静态管线跑一遍（模块级只跑一次，约 0.5 秒）。"""
    image = util.png_photo_like()
    out = tmp_path_factory.mktemp("baseline") / "baseline.html"
    report = service.trace_image(image, "freehand", out,
                                 config=service.TraceConfig(progress=lambda _: None),
                                 force=True)
    return image, report, out


def test_baseline_fixture_is_stable(rendered):
    """输入指纹：生成器一动，下面的失败就该先怀疑这里。"""
    image, _, _ = rendered
    assert hashlib.md5(image).hexdigest() == FIXTURE_MD5


def test_baseline_structure_frozen(rendered):
    """结构统计：管线中段（量化 / 合并 / 轮廓 / 涂色）的冻结值。"""
    _, report, _ = rendered
    actual = {key: report[key] for key in STRUCTURE}
    assert actual == STRUCTURE, "管线中段产出的形状结构变了"


def test_baseline_document_bit_identical(rendered):
    """文档逐位一致：重构的验收判据本体。"""
    _, report, path = rendered
    assert report["audit"]["valid"], report["audit"]["errors"]
    assert report["sha256"] == DOCUMENT_SHA256
    assert hashlib.sha256(path.read_bytes()).hexdigest() == DOCUMENT_SHA256


def test_baseline_distinguishes_inputs(tmp_path):
    """反向对照：换一张图必须得出不同的文档——否则这条红线对谁都是绿的。"""
    report = service.trace_image(util.png_photo_like(seed=8), "freehand",
                                 tmp_path / "other.html",
                                 config=service.TraceConfig(progress=lambda _: None),
                                 force=True)
    assert report["sha256"] != DOCUMENT_SHA256
