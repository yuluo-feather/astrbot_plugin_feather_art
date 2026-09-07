"""测试辅助：确定性小图生成（不依赖外部素材）。"""

from io import BytesIO

from PIL import Image


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
