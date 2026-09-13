"""测试辅助：确定性小图生成（不依赖外部素材）。"""

from io import BytesIO

from PIL import Image


def png_photo_like(size=(180, 140), seed=7) -> bytes:
    """确定性「照片感」PNG：平滑渐变 + 三块彩色团块 + 挖孔圆环 + 细线 + 颗粒。

    存在的理由：小块纯色图碰不到管线的分支（渐变拟合、孔洞桥接、碎块合并、
    精度降位），基线也就锁不住东西。这张图刻意把几条路都走一遍——
    平滑渐变喂 paint 的平面拟合、圆环喂 component_rings 的洞链、
    2px 细线喂碎块分组、颗粒喂 merge 的保守策略。

    确定性由三件事保证：seeded 生成器、固定顺序的绘制调用、固定编码参数；
    跨依赖版本（numpy / opencv）不保证一致，故基线只在同一环境内当红线。
    """
    import cv2
    import numpy as np

    width, height = size
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    canvas = np.empty((height, width, 3), np.float32)
    canvas[..., 0] = 90 + 60 * np.sin(xs / 23.0) + 40 * np.cos(ys / 19.0)
    canvas[..., 1] = 120 + 50 * np.cos(ys / 14.0) + 30 * np.sin((xs + ys) / 31.0)
    canvas[..., 2] = 150 + 45 * np.sin((xs - ys) / 21.0)
    for cx, cy, radius, color in ((width * .25, height * .35, width * .18, (220, 120, 90)),
                                  (width * .70, height * .30, width * .14, (70, 160, 200)),
                                  (width * .50, height * .78, width * .20, (200, 200, 120))):
        distance = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        weight = np.clip(1 - distance / radius, 0, 1)[..., None]
        canvas = canvas * (1 - weight) + np.asarray(color, np.float32) * weight
    ring = (int(width * .82), int(height * .72))
    cv2.circle(canvas, ring, int(width * .09), (40, 40, 60), -1)
    cv2.circle(canvas, ring, int(width * .05), (230, 230, 235), -1)
    cv2.line(canvas, (10, height - 12), (width - 10, height - 30), (25, 25, 25), 2)
    canvas += np.random.default_rng(seed).normal(0, 6, canvas.shape)
    ok, buffer = cv2.imencode(".png", np.clip(canvas, 0, 255).astype(np.uint8))
    assert ok
    return buffer.tobytes()


def png_dots_like(size=(200, 150)) -> bytes:
    """确定性「碎点」PNG：浅底 + 40 个散得开的深色小点 + 一块大色块。

    存在的理由：散点会被「碎块聚组」并成同一个多环区域，而环与环之间的
    连接线是桥接填法的软肋（桥本身被当成环壁涂上）。这张图专门喂那条路，
    喂不到就没法用相似度当判据。
    """
    import cv2
    import numpy as np

    width, height = size
    canvas = np.full((height, width, 3), 240, np.uint8)
    for index in range(40):
        x, y = 10 + (index % 8) * 23, 10 + (index // 8) * 20
        cv2.rectangle(canvas, (x, y), (x + 3, y + 3), (36, 34, 52), -1)
    cv2.rectangle(canvas, (55, 100), (165, 138), (150, 92, 70), -1)
    ok, buffer = cv2.imencode(".png", canvas)
    assert ok
    return buffer.tobytes()


def png_bytes(size=(64, 64), color=(255, 255, 255), mode="RGB") -> bytes:
    """纯色 PNG 字节流。"""
    buf = BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def png_gradient(size=(32, 32)) -> bytes:
    """双轴渐变 PNG：R 沿 x、G 沿 y 变化（有明确的渐变方向）。"""
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (min(255, x * 8), min(255, y * 8), 128)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def png_rgba(number=1) -> bytes:
    """带透明角的 RGBA PNG（默认 1 张 12x10，左上角透明）。"""
    img = Image.new("RGBA", (12, 10), (0, 0, 0, 0))
    for _ in range(number):
        img.putpixel((3, 4), (255, 100, 50, 255))
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def gif_two_frames() -> bytes:
    """两帧 GIF（应被拒绝）。"""
    img1 = Image.new("RGB", (8, 8), (10, 10, 10))
    img2 = Image.new("RGB", (8, 8), (200, 200, 200))
    buf = BytesIO()
    img1.save(buf, "GIF", save_all=True, append_images=[img2], duration=100)
    return buf.getvalue()


def gif_n_frames(n: int, size=(8, 8)) -> bytes:
    """n 帧小 GIF（帧间颜色变化，长动图防线测试用）。"""
    frames = [Image.new("RGB", size, (i * 3 % 256, i * 7 % 256, 128)) for i in range(n)]
    buf = BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    return buf.getvalue()


def png_big_pixels(w=7000, h=7000) -> bytes:
    """大像素数、小体积的纯色 PNG（像素炸弹样例）。"""
    buf = BytesIO()
    Image.new("RGB", (w, h), (250, 250, 250)).save(buf, "PNG")
    return buf.getvalue()
