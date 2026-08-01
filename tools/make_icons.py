#!/usr/bin/env python3
"""SmartKey 图标生成器
为 5 个槽位生成 56x20 RGB565 图标（白图形 + 深色底），输出：
  icons/*.png           预览图（RGB888）
  icons/icons.bin       拼接的 RGB565 数据（5 * 56*20*2 = 11200 字节）
  icons/icons_check.png 从 RGB565 转回的校验预览
"""
import os
import struct
from PIL import Image, ImageDraw

SLOT_W, SLOT_H = 56, 20
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "desktop", "icons")
BG = (26, 26, 26)      # 0x1A1A1A 深底
FG = (240, 240, 240)   # 白色图形


def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _draw_slot(d, n):
    cx, cy = SLOT_W // 2, SLOT_H // 2
    if n == 1:   # 复制：两个错开矩形
        d.rectangle([10, 4, 38, 15], outline=FG, width=1)
        d.rectangle([18, 5, 46, 16], outline=FG, width=1)
    elif n == 2:  # 粘贴：剪贴板+文档
        d.rectangle([14, 3, 42, 17], outline=FG, width=1)
        d.line([18, 3, 18, 8], fill=FG)
        d.line([38, 3, 38, 8], fill=FG)
        d.rectangle([21, 11, 35, 13], fill=FG)
        d.rectangle([21, 14, 35, 15], fill=FG)
    elif n == 3:  # 文本：文档+文字行
        d.rectangle([12, 3, 44, 17], outline=FG, width=1)
        d.line([16, 8, 40, 8], fill=FG)
        d.line([16, 12, 40, 12], fill=FG)
    elif n == 4:  # 消息：圆角气泡+省略点
        d.rounded_rectangle([8, 4, 48, 14], radius=3, outline=FG, width=1)
        d.line([16, 14, 12, 17], fill=FG)
        d.ellipse([16, 7, 19, 10], fill=FG)
        d.ellipse([26, 7, 29, 10], fill=FG)
        d.ellipse([36, 7, 39, 10], fill=FG)
    elif n == 5:  # 电源：圆+竖线
        d.arc([16, 2, 40, 18], 200, 340, fill=FG, width=2)
        d.line([28, 2, 28, 10], fill=FG, width=2)
    else:
        d.text((cx - 4, cy - 4), str(n), fill=FG)


def make_icons():
    icons = []
    for i in range(5):
        img = Image.new("RGB", (SLOT_W, SLOT_H), BG)
        d = ImageDraw.Draw(img)
        _draw_slot(d, i + 1)
        # 预览 PNG
        img.save(os.path.join(ICON_DIR, f"slot{i + 1}.png"))
        # RGB565 字节（大端）
        data = bytearray()
        for y in range(SLOT_H):
            for x in range(SLOT_W):
                r, g, b = img.getpixel((x, y))
                c = rgb565(r, g, b)
                data += struct.pack(">H", c)
        icons.append(bytes(data))
    with open(os.path.join(ICON_DIR, "icons.bin"), "wb") as f:
        f.write(b"".join(icons))
    return icons


def rgb565_to_rgb888(c):
    r = ((c >> 11) & 0x1F) << 3
    g = ((c >> 5) & 0x3F) << 2
    b = (c & 0x1F) << 3
    return (r, g, b)


def check_roundtrip(icons):
    """从 RGB565 转回 RGB888，验证往返一致"""
    img = Image.new("RGB", (SLOT_W * 5, SLOT_H), (0, 0, 0))
    for i, ic in enumerate(icons):
        for y in range(SLOT_H):
            for x in range(SLOT_W):
                hi, lo = ic[(y * SLOT_W + x) * 2], ic[(y * SLOT_W + x) * 2 + 1]
                c = (hi << 8) | lo
                img.putpixel((i * SLOT_W + x, y), rgb565_to_rgb888(c))
    img.save(os.path.join(ICON_DIR, "icons_check.png"))


if __name__ == "__main__":
    icons = make_icons()
    check_roundtrip(icons)
    print("生成 5 个图标 + icons.bin (%.1f KB)" % (len(b"".join(icons)) / 1024))
