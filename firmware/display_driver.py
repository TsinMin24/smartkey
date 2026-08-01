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

W, H = 284, 76   # 横向模式：旋转后逻辑尺寸

# ST7789 内存偏移（横向模式：COLSTART/ROWSTART 互换）
COLSTART = 18
ROWSTART = 82

# 横向5槽布局：每slot宽56px, 图标48×48居中
_SLOT_W = 56      # 每个 slot 的宽度（284÷5=56，余4px右边留白）
_SLOT_H = H       # slot 高度 = 整个屏幕高度
_SLOT_X0 = 0      # 第一个 slot 起始 x
_SLOT_STRIDE = 56 # slot 间距
_ICON_SIZE = 48   # 图标尺寸（正方形）
_ICON_Y = (H - _ICON_SIZE) // 2  # 图标垂直居中 y=14

_COL_BG = 0x000000   # 背景黑色
_COL_SEL = 0xFFFFFF  # 选中高亮白色
_COL_STATUS = 0x222222  # 连接状态条颜色

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
        # 发送 MADCTL 切换为横向模式（顺时针90°）
        self.bus.send(0x36, bytes([0x60]))  # MV=1, MX=1 → 顺时针旋转90°
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
        self._fill_rect(0, 0, W - 1, H - 1, _COL_BG)     # 全屏黑色背景
        # 5个 slot 边框分隔线
        for i in range(1, 5):
            x = i * _SLOT_STRIDE
            self._fill_rect(x - 1, 0, x - 1, H - 1, 0x333333)
        # 底部连接状态指示（右侧2px宽竖条）
        self._fill_rect(W - 2, 0, W - 1, H - 1, _COL_STATUS)
        # 每个 slot 绘制空图标占位框
        for i in range(5):
            self._draw_slot_bg(i)

    def _draw_slot_bg(self, i):
        """绘制第i个slot的空图标占位框"""
        sx = i * _SLOT_STRIDE
        ix = sx + (_SLOT_STRIDE - _ICON_SIZE) // 2
        iy = _ICON_Y
        # 浅灰色占位框
        self._fill_rect(ix, iy, ix + _ICON_SIZE - 1, iy + _ICON_SIZE - 1, 0x222222)

    def _fill_slot(self, i, sel):
        """高亮/恢复 slot 边框"""
        sx = i * _SLOT_STRIDE
        c = _COL_SEL if sel else _COL_BG
        # 上下边框高亮
        self._fill_rect(sx, 0, sx + _SLOT_STRIDE - 1, 1, c)
        self._fill_rect(sx, H - 2, sx + _SLOT_STRIDE - 1, H - 1, c)

    def set_slot(self, idx, sel):
        """按键高亮/恢复"""
        if 0 <= idx <= 4:
            self._fill_slot(idx, sel)

    def set_slot_name(self, idx, name):
        """槽位名称（占位：当前无字体渲染，仅记录）"""
        pass

    def set_status(self, color):
        self._status_color = color
        self._fill_rect(W - 2, 0, W - 1, H - 1, color)

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
        """将图标绘制到指定 slot（0-4）的居中位置"""
        if slot < 0 or slot > 4:
            return
        sx = slot * _SLOT_STRIDE
        x = sx + (_SLOT_STRIDE - w) // 2
        y = _ICON_Y
        self.draw_icon(x, y, w, h, data)
