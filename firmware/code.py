# SmartKey —— 静音运行固件（零控制台字符弹窗）
import _bleio
import adafruit_ble
import digitalio
import gc
import microcontroller
import time
from adafruit_ble.advertising import Advertisement
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService

from display_driver import Display

# ═══ 配置 ═══
KEY_PINS = [
    microcontroller.pin.P0_31,
    microcontroller.pin.P0_29,
    microcontroller.pin.P1_15,
    microcontroller.pin.P1_13,
    microcontroller.pin.P1_11,
]
# 图标最大像素数（RGB565 16x16=512B / 2色掩码 32x32=128B）
ICON_MAX_PIXELS = 44 * 44
KEY_DEBOUNCE = 3
GC_INTERVAL = 30


# ═══ Flash 存取 ═══
# 2色掩码格式: [w:2][h:2][fg565:2][bg565:2][crc16:2][掩码数据]
# RGB565 格式: 512B 原始像素（16x16）
def _icon_path(slot):
    return "icon_%d.bin" % (slot + 1)


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


def save_icon(slot, w, h, fg, bg, mask):
    try:
        crc = _crc16(mask)
        header = bytes([
            w & 0xFF, (w >> 8) & 0xFF,
            h & 0xFF, (h >> 8) & 0xFF,
            (fg >> 8) & 0xFF, fg & 0xFF,
            (bg >> 8) & 0xFF, bg & 0xFF,
            crc & 0xFF, (crc >> 8) & 0xFF,
        ])
        with open(_icon_path(slot), "wb") as f:
            f.write(header)
            f.write(mask)
        return True
    except Exception:
        return False


def load_icon(slot):
    try:
        with open(_icon_path(slot), "rb") as f:
            d = f.read()
            if len(d) == 512:  # 16x16 RGB565 全色
                return ("rgb", 16, 16, d)
            if len(d) >= 10:
                w = d[0] | (d[1] << 8)
                h = d[2] | (d[3] << 8)
                fg = d[4] | (d[5] << 8)
                bg = d[6] | (d[7] << 8)
                crc = d[8] | (d[9] << 8)
                mask = d[10:]
                nb = (w * h + 7) // 8
                if len(mask) == nb and _crc16(mask) == crc:
                    return ("mask", w, h, fg, bg, mask)
    except Exception:
        pass
    return None


def render_saved_icons():
    for slot in range(5):
        ic = load_icon(slot)
        if ic:
            if ic[0] == "rgb":
                dm.draw_slot_icon_rgb(slot, ic[1], ic[2], ic[3])
            else:
                dm.draw_slot_icon(slot, ic[1], ic[2], ic[5], ic[3], ic[4])
        gc.collect()
    gc.collect()


# ═══ 初始化屏幕 ═══
dm = Display()
gc.collect()
render_saved_icons()
gc.collect()

# ═══ 按键初始化 ═══
buttons = []
for p in KEY_PINS:
    b = digitalio.DigitalInOut(p)
    b.direction = digitalio.Direction.INPUT
    b.pull = digitalio.Pull.UP
    buttons.append(b)
stable = [True] * 5
count = [0] * 5

if not buttons[0].value:
    _bleio.adapter.erase_bonding()

# ═══ BLE UART 广播 ═══
ble = adafruit_ble.BLERadio()
ble.name = "SmartKey"
uart = UARTService()
adv = ProvideServicesAdvertisement(uart)
adv.appearance = 0

sr = Advertisement()
sr.complete_name = "SmartKey"
ble.start_advertising(adv, sr)
gc.collect()

# ═══ 主循环 ═══
was_conn = False
frame = 0

while True:
    frame += 1

    if not ble.connected and not ble.advertising:
        ble.start_advertising(adv, sr)

    if ble.connected and not was_conn:
        dm.set_status(0x00FF00)  # 连接成功变绿
    elif not ble.connected and was_conn:
        dm.set_status(0xFFA500)  # 断开变橙
    was_conn = ble.connected

    # ── 接收 BLE UART 命令 ──
    if ble.connected and uart.in_waiting:
        line = uart.readline()
        if line:
            cmd = line.decode("utf-8", "ignore").strip()
            try:
                if cmd == "REFRESH":
                    # USB 推送图标后重载
                    render_saved_icons()
                    uart.write("OK\n".encode())
                elif cmd.startswith("ICON"):
                    # 协议(单行): ICON,<slot>,<w>,<h>,<fg565>,<bg565>,<crc16>,<hex掩码>
                    parts = cmd.split(",")
                    slot = int(parts[1]) - 1
                    w = int(parts[2])
                    h = int(parts[3])
                    fg = int(parts[4], 16)
                    bg = int(parts[5], 16)
                    crc = int(parts[6], 16)

                    if slot < 0 or slot > 4 or w <= 0 or h <= 0:
                        continue
                    if w * h > ICON_MAX_PIXELS:
                        continue

                    mask = bytearray(bytes.fromhex(parts[7]))
                    if len(mask) < (w * h + 7) // 8:
                        continue
                    if _crc16(mask) != crc:
                        uart.write("ERR_CRC\n".encode())
                        continue

                    if save_icon(slot, w, h, fg, bg, mask):
                        dm.draw_slot_icon(slot, w, h, mask, fg, bg)
                        uart.write("OK\n".encode())

            except Exception:
                pass

    # ── 按键检测 ──
    cur = [b.value for b in buttons]
    for i in range(5):
        if cur[i] != stable[i]:
            count[i] += 1
            if count[i] >= KEY_DEBOUNCE:
                stable[i] = cur[i]
                count[i] = 0
                if not stable[i]:
                    dm.set_slot(i, True)
                    if ble.connected:
                        uart.write(("DOWN,%d\n" % (i + 1)).encode())
                else:
                    dm.set_slot(i, False)
                    if ble.connected:
                        uart.write(("UP,%d\n" % (i + 1)).encode())
        else:
            count[i] = 0

    if frame % GC_INTERVAL == 0:
        gc.collect()

    time.sleep(0.015)
