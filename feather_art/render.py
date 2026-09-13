"""静态描摹的编排入口：造中间表示 → 交给渲染后端 → 结算相似度。

本模块只剩三件事：挑后端、把几何算成 Illustration、把离线相似度记进统计。
几何与涂色在 regions.py，写成哪种文档在 backends.py——换方言只换后端，
上游一行都不用动。

预算纪律见 backends.CssShapeWriter：拼接过程只记账不抛，超预算由后端末尾
终检抛出 BudgetExceeded（携带真实完整字节数），给上层的 fit 跳档精确信号。
"""

from .backends import DocumentConfig, get_backend
from .regions import build_illustration
from .score import Rasterizer


def render_document(reference, labels, palette, original_size, *, background, title,
                    epsilon, gradients, underpainting, max_bytes, progress, score=False,
                    backend: str = "css"):
    """全量渲染；返回 (HTML 文档字符串, 统计 dict)。"""
    raster = Rasterizer((reference.shape[1], reference.shape[0]), background) if score else None
    illustration = build_illustration(
        reference, labels, palette, background=background, epsilon=epsilon,
        gradients=gradients, underpainting=underpainting, progress=progress, raster=raster)
    document, stats = get_backend(backend).render_static(
        illustration, DocumentConfig(title=title, original_size=tuple(original_size),
                                     max_bytes=max_bytes))
    stats = {**illustration.stats, **stats}
    if raster is not None:
        detail, thumbnail = raster.errors(reference)
        stats["similarity"] = {"mae": detail, "mae_thumbnail": thumbnail}
    return document, stats
