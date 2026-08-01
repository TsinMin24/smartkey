"""SmartKey 双端共享协议常量
电脑端软件 和 板子固件 遵循同一套行文本协议：

  板子 → 电脑:
    DOWN,<1..5>      按键按下
    UP,<1..5>        按键释放

  电脑 → 板子:
    PING              → 板子回 PONG
    STATUS,<hex24>    设置状态窗颜色（如 00FF00）
    SLOT,<n>,<名称>   设置槽位名称（显示用）
    ICON,<x>,<y>,<w>,<h>\n<RGB565字节>  直绘位图
"""
from __future__ import annotations

import enum

# BLE 服务 UUID（Nordic UART Service，与 adafruit_ble UARTService 一致）
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # 电脑写 → 板子收
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # 板子发 → 电脑收(notify)

DEVICE_NAME = "SmartKey"
SERVICE_CHAR_NAMES = {UART_SERVICE_UUID, UART_RX_UUID, UART_TX_UUID}

# 屏幕尺寸
DISPLAY_W = 76
DISPLAY_H = 284

# 槽位布局（与固件 display_driver.py 一致）
SLOT_X = 6
SLOT_Y0 = 82
SLOT_GAP = 38
SLOT_W = 64
SLOT_H = 28
SLOT_ICON_X = SLOT_X + 4
SLOT_ICON_Y0 = SLOT_Y0 + 4
SLOT_ICON_W = 56
SLOT_ICON_H = 20

SLOT_COUNT = 5

# 槽位数量上限
MAX_SLOTS = 5


def slot_y(idx: int) -> int:
    return SLOT_Y0 + idx * SLOT_GAP


def slot_icon_y(idx: int) -> int:
    return SLOT_ICON_Y0 + idx * SLOT_GAP


class ActionType(str, enum.Enum):
    """按键可执行的动作类型（电脑端定义）"""

    SHORTCUT = "shortcut"      # 发送键盘快捷键
    TYPE = "type"              # 输入一段文字
    LAUNCH = "launch"          # 启动程序
    OPEN_URL = "open_url"      # 打开网址
    MEDIA = "media"            # 媒体键
    COMMAND = "command"        # 执行 shell 命令
    NONE = "none"              # 无动作


# macOS 上媒体键的 pynput 名称（仅供文档参考，跨平台时用按键码）
MEDIA_KEYS = {
    "play_pause": "play_pause",
    "next": "next_track",
    "prev": "previous_track",
    "volume_up": "volume_up",
    "volume_down": "volume_down",
    "mute": "volume_mute",
}
