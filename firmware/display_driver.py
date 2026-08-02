# SmartKey 屏幕驱动 —— 完全基于 displayio（无任何裸 SPI 命令）
# 界面 = 背景/状态细条/槽位 各自的 Bitmap+TileGrid 叠加；
# 图标 = 2色掩码（1bit/像素）或 全色RGB565（displayio Palette），居中放槽位。
# 不直接调用 bus.send()，与 displayio 刷新机制零冲突，不卡死。
import gc
import digitalio
import displayio
import busio
import microcontroller

try:
    from displayio import FourWire
except ImportError:
    from fourwire import FourWire

from adafruit_st7789 import ST7789

W, H = 76, 284

# ST7789 内存偏移
COLSTART = 82
ROWSTART = 18

# ═══ 槽位布局：44x44 等距填满 ═══
# 284 - 4(状态条) = 280px；5×44 + 6×10 = 280
_SLOT_W = 44
_SLOT_H = 44
_SLOT_X = (W - _SLOT_W) // 2 - 6   # 左移 6px
_SLOT_Y0 = 14                       # 4(状态条) + 10(间隔)
_SLOT_GAP = 54                      # 44(槽位) + 10(间隔)

# 基础颜色（24 位）
_COL_BG = 0x1A1A1A             # 槽位底色
_COL_ORANGE = 0xFFA500         # 状态条（断开）
_COL_GREEN = 0x00FF00          # 状态条（连接）
_COL_BLACK = 0x000000


class Display:
    def __init__(self):
        gc.collect()
        displayio.release_displays()
        gc.collect()

        # 背光
        blk = digitalio.DigitalInOut(microcontroller.pin.P1_04)
        blk.direction = digitalio.Direction.OUTPUT
        blk.value = True

        # SPI → ST7789 displayio 对象
        spi = busio.SPI(clock=microcontroller.pin.P0_17,
                        MOSI=microcontroller.pin.P0_20)
        self.bus = FourWire(spi, command=microcontroller.pin.P0_24,
                            chip_select=microcontroller.pin.P1_00,
                            reset=microcontroller.pin.P0_22,
                            baudrate=8000000)
        self.display = ST7789(self.bus, width=W, height=H,
                              colstart=COLSTART, rowstart=ROWSTART,
                              rotation=0, invert=False)

        # 根视图组：唯一内容来源，不挂任何终端/控制台图层
        self._root = displayio.Group()
        self.display.root_group = self._root
        self.display.auto_refresh = True

        # 全屏黑色背景
        bg = displayio.Bitmap(W, H, 1)
        bg.fill(0)
        bg_pal = displayio.Palette(1)
        bg_pal[0] = _COL_BLACK
        self._root.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

        # 顶部状态细条 (y=0..3) 76x4
        self._status_pal = displayio.Palette(1)
        self._status_pal[0] = _COL_ORANGE
        st = displayio.Bitmap(W, 4, 1)
        st.fill(0)
        self._root.append(displayio.TileGrid(st, pixel_shader=self._status_pal, x=0, y=0))

        # 5 个正方形槽位：改 palette 颜色即可压暗/恢复，图标层独立不受影响
        self._slot_pals = []
        for i in range(5):
            bm = displayio.Bitmap(_SLOT_W, _SLOT_H, 1)
            bm.fill(0)
            pal = displayio.Palette(1)
            pal[0] = _COL_BG
            self._slot_pals.append(pal)
            self._root.append(displayio.TileGrid(bm, pixel_shader=pal,
                                                 x=_SLOT_X,
                                                 y=_SLOT_Y0 + i * _SLOT_GAP))
        # 图标层：slot → TileGrid
        self._icon_grids = [None] * 5
        gc.collect()

    # ── 界面更新 ──
    def set_status(self, color24):
        """状态条变色：0xFFA500 断开 / 0x00FF00 连接"""
        self._status_pal[0] = color24

    def set_slot(self, idx, sel):
        """按键压暗/恢复"""
        if 0 <= idx <= 4:
            if sel:
                r = ((_COL_BG >> 16) & 0xFF) * 2 // 3
                g = ((_COL_BG >> 8) & 0xFF) * 2 // 3
                b = (_COL_BG & 0xFF) * 2 // 3
                self._slot_pals[idx][0] = (r << 16) | (g << 8) | b
            else:
                self._slot_pals[idx][0] = _COL_BG

    def set_slot_name(self, idx, name):
        pass  # 无字体渲染，槽位名称仅上位机记录

    # ── 图标（2色掩码）──
    @staticmethod
    def _rgb565_to_24(c):
        r = ((c >> 11) & 0x1F) << 3
        g = ((c >> 5) & 0x3F) << 2
        b = (c & 0x1F) << 3
        return (r << 16) | (g << 8) | b

    def draw_slot_icon(self, slot, w, h, mask, fg565, bg565):
        """2色掩码图标：mask 1bit/像素(1=前景色 0=背景色)，居中放进槽位。
        数据量 = w*h/8 字节，单包 BLE 即可传完，板端只建 2 色 Palette。
        """
        if slot < 0 or slot > 4:
            return
        old = self._icon_grids[slot]
        if old is not None:
            try:
                self._root.remove(old)
            except Exception:
                pass
            self._icon_grids[slot] = None
            gc.collect()
        if w <= 0 or h <= 0:
            return

        pal = displayio.Palette(2)
        pal[0] = self._rgb565_to_24(bg565)   # 背景
        pal[1] = self._rgb565_to_24(fg565)   # 前景(logo色)

        bm = displayio.Bitmap(w, h, 2)
        nb = (w * h + 7) // 8
        for i in range(nb):
            m = mask[i]
            for k in range(8):
                px = i * 8 + k
                if px >= w * h:
                    break
                x = px % w
                y = px // w
                bm[x, y] = 1 if (m >> (7 - k)) & 1 else 0

        ix = _SLOT_X + (_SLOT_W - w) // 2
        iy = _SLOT_Y0 + slot * _SLOT_GAP + (_SLOT_H - h) // 2
        if ix < 0:
            ix = 0
        if iy < 0:
            iy = 0
        grid = displayio.TileGrid(bm, pixel_shader=pal, x=ix, y=iy)
        self._icon_grids[slot] = grid
        self._root.append(grid)

    # ── 全色 RGB565 图标（displayio，16×16，256 色）──
    def draw_slot_icon_rgb(self, slot, w, h, rgb565_data):
        if slot < 0 or slot > 4 or w <= 0 or h <= 0:
            return
        old = self._icon_grids[slot]
        if old is not None:
            try:
                self._root.remove(old)
            except Exception:
                pass
            self._icon_grids[slot] = None
            gc.collect()
        np = w * h
        pal = displayio.Palette(np)
        bm = displayio.Bitmap(w, h, np)
        for y in range(h):
            for x in range(w):
                i = y * w + x
                off = i * 2
                c565 = rgb565_data[off] | (rgb565_data[off + 1] << 8)
                pal[i] = self._rgb565_to_24(c565)
                bm[x, y] = i
        ix = _SLOT_X + (_SLOT_W - w) // 2
        iy = _SLOT_Y0 + slot * _SLOT_GAP + (_SLOT_H - h) // 2
        if ix < 0: ix = 0
        if iy < 0: iy = 0
        grid = displayio.TileGrid(bm, pixel_shader=pal, x=ix, y=iy)
        self._icon_grids[slot] = grid
        self._root.append(grid)
        gc.collect()
