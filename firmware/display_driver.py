# SmartKey 屏幕驱动 —— 纯直接 SPI 直绘（无 displayio 帧缓存）
# 绘制速度是 for 循环逐像素的 ~100 倍；不占帧缓存；图标/色块随意叠加
import gc
import digitalio
import displayio
import busio
import microcontroller
import struct

from fourwire import FourWire
from adafruit_st7789 import ST7789

W, H = 76, 284

# ST7789 内存偏移
COLSTART = 82
ROWSTART = 18

# 槽位布局
_SLOT_X = 6
_SLOT_W = 64
_SLOT_H = 28
_SLOT_Y0 = 82
_SLOT_GAP = 38

_COL_BG = 0x1A1A1A
_COL_SEL = 0xFFFFFF

# 单次 SPI 传输块大小：避免一次性分配大缓冲区导致 MemoryError
_CHUNK = 1024  # 每次最多发 1024 字节（512 像素）


def _c565(c24):
    """24 位颜色 → RGB565"""
    r = (c24 >> 16) & 0xFF
    g = (c24 >> 8) & 0xFF
    b = c24 & 0xFF
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


class Display:
    def __init__(self):
        gc.collect()
        # 释放上一次运行残留的显示实例，否则 SPI 引脚被占用
        displayio.release_displays()
        gc.collect()
        blk = digitalio.DigitalInOut(microcontroller.pin.P1_04)
        blk.direction = digitalio.Direction.OUTPUT
        blk.value = True

        spi = busio.SPI(clock=microcontroller.pin.P0_17,
                        MOSI=microcontroller.pin.P0_20)
        self.bus = FourWire(spi, command=microcontroller.pin.P0_24,
                            chip_select=microcontroller.pin.P1_00,
                            reset=microcontroller.pin.P0_22,
                            baudrate=8000000)
        self.display = ST7789(self.bus, width=W, height=H,
                              colstart=COLSTART, rowstart=ROWSTART,
                              rotation=0, invert=False)
        self._status_color = 0xFFA500
        self._draw_frame()

    # ── 底层原语 ──
    def _window(self, x0, y0, x1, y1):
        # 直接发 0x2A/0x2B 必须自己补 colstart/rowstart 偏移
        self.bus.send(0x2A, struct.pack(">HH", x0 + COLSTART, x1 + COLSTART))
        self.bus.send(0x2B, struct.pack(">HH", y0 + ROWSTART, y1 + ROWSTART))

    def _fill_rect(self, x0, y0, x1, y1, c24):
        """x1,y1 包含边界；c24 为 24 位颜色；分块发送避免 MemoryError"""
        n = (x1 - x0 + 1) * (y1 - y0 + 1)
        c565 = _c565(c24)
        pix = bytes((c565 >> 8, c565 & 0xFF))
        self._window(x0, y0, x1, y1)
        block = pix * (_CHUNK // 2)
        rem = n * 2
        while rem > 0:
            take = _CHUNK if rem >= _CHUNK else rem
            self.bus.send(0x2C, block if take == _CHUNK else pix * (take // 2))
            rem -= take

    # ── 界面 ──
    def _draw_frame(self):
        self._fill_rect(0, 0, W - 1, H - 1, 0x0000)      # 清黑
        self._fill_rect(0, 14, W - 1, 17, 0x0088FF)       # 顶部蓝色条
        self._fill_rect(18, 28, 57, 67, self._status_color)  # 状态窗
        self._fill_rect(58, 28, 61, 67, 0x000000)
        self._fill_rect(18, 68, 61, 71, 0x000000)
        for i in range(5):
            self._fill_slot(i, False)

    def _fill_slot(self, i, sel):
        y0 = _SLOT_Y0 + i * _SLOT_GAP
        self._fill_rect(_SLOT_X, y0, _SLOT_X + _SLOT_W - 1, y0 + _SLOT_H - 1,
                        _COL_SEL if sel else _COL_BG)

    def set_slot(self, idx, sel):
        """按键高亮/恢复"""
        if 0 <= idx <= 4:
            self._fill_slot(idx, sel)

    def set_slot_name(self, idx, name):
        """槽位名称（占位：当前无字体渲染，仅记录）"""
        pass

    def set_status(self, color):
        self._status_color = color
        self._fill_rect(18, 28, 57, 67, color)

    def draw_icon(self, x, y, w, h, data):
        """RGB565 位图直推（2B/像素），分块发送。"""
        n = w * h
        if len(data) < n * 2:
            return
        self._window(x, y, x + w - 1, y + h - 1)
        rem = n * 2
        off = 0
        while rem > 0:
            take = _CHUNK if rem >= _CHUNK else rem
            self.bus.send(0x2C, data[off:off + take])
            off += take
            rem -= take

    def draw_slot_icon(self, slot, w, h, data):
        """将图标绘制到纵向槽位 slot(0-4) 内居中"""
        if slot < 0 or slot > 4:
            return
        # 槽位区域: x=6, y=82+slot*38, 尺寸64x28
        sx = _SLOT_X
        sy = _SLOT_Y0 + slot * _SLOT_GAP
        ix = sx + (_SLOT_W - w) // 2
        iy = sy + (_SLOT_H - h) // 2
        if iy < 0:
            iy = 0
        self.draw_icon(ix, iy, w, h, data)
