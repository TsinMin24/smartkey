# SmartKey —— BLE UART 无线按键板固件
# 协议：电脑端软件 ⇄ 板子
#   板子→电脑: DOWN,1..5 / UP,1..5         按键按下/释放
#   电脑→板子: PING → PONG
#              STATUS,<hex24>              状态窗颜色
#              SLOT,<n>,<名称>              记录槽位名称（显示用）
#              ICON,<x>,<y>,<w>,<h>\n<RGB565字节>  直绘位图
# 屏幕 76x284：顶部名称条 / 状态窗 / 5 个槽位（每槽 64x28，图标 56x20）
import gc
import time
import digitalio
import microcontroller
import _bleio
import adafruit_ble
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService

from display_driver import Display

# ═══ 配置 ═══
KEY_PINS = [microcontroller.pin.P0_31, microcontroller.pin.P0_29,
            microcontroller.pin.P1_15, microcontroller.pin.P1_13,
            microcontroller.pin.P1_11]
ICON_MAX_PIXELS = 48 * 48 * 4   # 单个 ICON 最大像素（48×48图标，4倍安全余量）
KEY_DEBOUNCE = 3                 # 按键去抖帧数（3×15ms≈45ms）
GC_INTERVAL = 30                 # 每 30 帧 gc.collect()（≈450ms）

# ═══ 屏幕 ═══
dm = Display()
gc.collect()
print(">>> 屏幕 OK <<<")

# ═══ 按键 ═══
buttons = []
for p in KEY_PINS:
    b = digitalio.DigitalInOut(p)
    b.direction = digitalio.Direction.INPUT
    b.pull = digitalio.Pull.UP
    buttons.append(b)
stable = [True] * 5   # 去抖后的稳定状态
count = [0] * 5       # 状态变化计数
gc.collect()
print(">>> 按键 OK <<<")
# ═══ BLE UART ═══
# 配对管理：不要每次开机都清配对！否则 macOS 端残留的旧绑定
# 会导致 "Peer removed pairing information" (Code=14) 连接被拒。
# 只有开机时按住「槽位1」键才清除配对（需配合 macOS 端 Forget 设备）。
if not buttons[0].value:
    _bleio.adapter.erase_bonding()
    print(">>> 已清除配对记录（macOS 端也需忘记该设备）<<<")
ble = adafruit_ble.BLERadio()
ble.name = "SmartKey"
uart = UARTService()
adv = ProvideServicesAdvertisement(uart)
adv.appearance = 0
# 名称放 scan_response：主包只含 UUID(25B)，否则 35B 超 BLE 31B 限制，
# 超限广播会被手机/电脑直接忽略（搜不到！）
from adafruit_ble.advertising import Advertisement
sr = Advertisement()
sr.complete_name = "SmartKey"
ble.start_advertising(adv, sr)
print(">>> 本机地址:", _bleio.adapter.address, "<<<")
print(">>> BLE UART 已广播 SmartKey <<<")
gc.collect()

# ═══ 主循环 ═══
was_conn = False
frame = 0

while True:
    frame += 1

    # BLE 维护（断线后重开广播，必须带 scan_response）
    if not ble.connected and not ble.advertising:
        ble.start_advertising(adv, sr)

    # 连接状态
    if ble.connected and not was_conn:
        dm.set_status(0x00FF00)
        print(">>> 已连接 <<<")
    elif not ble.connected and was_conn:
        dm.set_status(0xFFA500)
        print(">>> 已断开 <<<")
    was_conn = ble.connected

    # ── 接收电脑指令 ──
    if ble.connected and uart.in_waiting:
        line = uart.readline()
        if line:
            cmd = line.decode("utf-8", "ignore").strip()
            print("[UART]", repr(cmd))
            try:
                if cmd.startswith("ICON"):
                    # 新协议: ICON,<slot>,0,48,48  (slot=1..5)
                    parts = cmd.split(",")
                    slot = int(parts[1]) - 1   # slot 1-5 → 0-4
                    w = int(parts[3])          # 宽度
                    h = int(parts[4])          # 高度
                    # 尺寸保护：超大图标直接拒绝，防内存耗尽
                    if w * h > ICON_MAX_PIXELS or w <= 0 or h <= 0:
                        print("[ICON 拒绝] 尺寸超限", w, h)
                        continue
                    if slot < 0 or slot > 4:
                        print("[ICON 拒绝] slot 超限", slot + 1)
                        continue
                    target = w * h * 2
                    data = bytearray(target)   # 预分配固定缓冲，防OOM
                    rcvd = 0
                    while rcvd < target and ble.connected:
                        chunk = uart.read(min(256, target - rcvd))
                        if chunk:
                            n = len(chunk)
                            data[rcvd:rcvd + n] = chunk
                            rcvd += n
                    if rcvd >= target:
                        dm.draw_slot_icon(slot, w, h, data)
                        uart.write("OK\n".encode())
                elif cmd.startswith("SLOT"):
                    parts = cmd.split(",", 2)
                    idx = int(parts[1]) - 1
                    name = parts[2] if len(parts) > 2 else ""
                    dm.set_slot_name(idx, name)
                    uart.write("OK\n".encode())
                elif cmd == "PING":
                    uart.write("PONG\n".encode())
                elif cmd.startswith("STATUS"):
                    c = int(cmd.split(",")[1], 16)
                    dm.set_status(c)
                    uart.write("OK\n".encode())
            except Exception as e:
                print("[CMD err]", e)

    # ── 按键检测 → 去抖 + UART 通知 + 槽位高亮 ──
    cur = [b.value for b in buttons]
    for i in range(5):
        if cur[i] != stable[i]:
            count[i] += 1
            if count[i] >= KEY_DEBOUNCE:
                stable[i] = cur[i]
                count[i] = 0
                if not stable[i]:
                    # 稳定按下
                    dm.set_slot(i, True)
                    if ble.connected:
                        uart.write(("DOWN,%d\n" % (i + 1)).encode())
                else:
                    # 稳定释放
                    dm.set_slot(i, False)
                    if ble.connected:
                        uart.write(("UP,%d\n" % (i + 1)).encode())
        else:
            count[i] = 0

    # 降频 GC：每 GC_INTERVAL 帧一次
    if frame % GC_INTERVAL == 0:
        gc.collect()

    time.sleep(0.015)
