# SmartKey boot.py —— 开机早期设置固定随机静态地址
# 目的：让 macOS 把板子当成全新设备，绕开旧配对绑定
# （旧绑定 E2:27:A2:83:A5:63 导致 "Peer removed pairing information"）
import supervisor
import _bleio

# 必须先禁用 BLE workflow，否则设置地址报 BluetoothError
supervisor.disable_ble_workflow()

# RANDOM_STATIC 地址：最高字节高 2 位必须为 11 (0xC0)
b = bytearray([0xC0, 0x5A, 0x3C, 0xA5, 0x11, 0x22])
try:
    _bleio.adapter.address = _bleio.Address(bytes(b), _bleio.Address.RANDOM_STATIC)
    print(">>> 地址已设为:", _bleio.adapter.address, "<<<")
except Exception as e:
    print(">>> 设置地址失败:", e, "（使用默认地址）<<<")
