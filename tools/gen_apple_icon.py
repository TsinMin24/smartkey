#!/usr/bin/env python3
"""生成 32x32 苹果图标二进制数据（与板子 save_icon/load_icon 格式一致）"""
import struct
import os


def _crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


# 32x32 苹果图标，1-bit 掩码
# 1 = 前景(白色 logo)，0 = 背景(槽位底色)
ROWS = [
    "00000000000000011100000000000000",  # 0
    "00000000000000111100000000000000",  # 1
    "00000000000001111100000000000000",  # 2
    "00000000111111111111111000000000",  # 3
    "00000011111111111111111110000000",  # 4
    "00000111111111111111111111000000",  # 5
    "00001111111111111111111111100000",  # 6
    "00011111111111111111111111110000",  # 7
    "00011111111111111111111111110000",  # 8
    "00111111111111111111111111111000",  # 9
    "00111111111111111111111111111100",  # 10
    "01111111111111111111111111111100",  # 11
    "01111111111111111111111111111100",  # 12
    "01111111111111111111111111111100",  # 13
    "01111111111111111111111111111100",  # 14
    "01111111111111111111111111111100",  # 15
    "01111111111111111111111111111100",  # 16
    "00111111111111111111111111111100",  # 17
    "00111111111111111111111111111000",  # 18
    "00011111111111111111111111110000",  # 19
    "00011111111111111111111111110000",  # 20
    "00001111111111111111111111100000",  # 21
    "00000111111111111111111111000000",  # 22
    "00000011111111111111111110000000",  # 23
    "00000001111111111111111100000000",  # 24
    "00000000111111111111111000000000",  # 25
    "00000000011111111111110000000000",  # 26
    "00000000001111111111100000000000",  # 27
    "00000000000111111111000000000000",  # 28
    "00000000000001111100000000000000",  # 29
    "00000000000000111000000000000000",  # 30
    "00000000000000000000000000000000",  # 31
]

assert len(ROWS) == 32
for i, row in enumerate(ROWS):
    assert len(row) == 32, f"Row {i} has {len(row)} pixels, expected 32"


def rows_to_mask(rows):
    mask = bytearray()
    for row in rows:
        for byte_idx in range(4):  # 32 bits = 4 bytes
            val = 0
            for bit in range(8):
                px = byte_idx * 8 + bit
                if px < len(row) and row[px] == "1":
                    val |= 1 << (7 - bit)
            mask.append(val)
    return mask


def generate_icon_file(output_path):
    W, H = 32, 32
    FG_565 = 0xFFFF  # white
    BG_565 = 0x10A2  # 0x1A1A1A in RGB565 (neutral dark gray)

    mask = rows_to_mask(ROWS)
    assert len(mask) == 128, f"Mask has {len(mask)} bytes, expected 128"

    crc = _crc16(mask)
    header = struct.pack("<HHHHH", W, H, FG_565, BG_565, crc)
    assert len(header) == 10

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(header)
        f.write(mask)

    print(f"Written {len(header) + len(mask)} bytes to {output_path}")
    print(f"  {W}x{H}, fg=#FFFFFF, bg=#1A1A1A, crc16=0x{crc:04X}")
    print(f"  Mask ({len(mask)} bytes): {mask.hex()}")


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "firmware", "icon_1.bin")
    generate_icon_file(out)
