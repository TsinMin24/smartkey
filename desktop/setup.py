"""SmartKey macOS App 打包配置（py2app）

构建方法：
    cd smartkey/desktop
    ../.venv/bin/python setup.py py2app --clean

产物：
    desktop/dist/SmartKey.app
"""
import os
import sys

from setuptools import setup

APP_NAME = "SmartKey"
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

# App 资源：config + 图标 + 本地模块（py2app 收集不可靠，直接作为数据打入 Resources）
ICON_FILES = [
    os.path.join(BASE, "icons", f)
    for f in os.listdir(os.path.join(BASE, "icons"))
    if f.endswith((".png", ".bin"))
]
DATA_FILES = [
    (".", ["config.json"]),
    (".", ["controller.py", "actions.py", "smartkey_protocol.py"]),
    ("icons", ICON_FILES),
]

# macOS 系统图标名（菜单栏状态用）
INFO_PLIST = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": "com.smartkey.desktop",
    "CFBundleVersion": "1.0.0",
    "CFBundleShortVersionString": "1.0.0",
    "LSMinimumSystemVersion": "12.0",
    # ── 蓝牙权限声明：解决 macOS TCC 崩溃的关键 ──
    "NSBluetoothAlwaysUsageDescription": "SmartKey 需要蓝牙连接按键设备以收发按键事件。",
    "NSBluetoothPeripheralUsageDescription": "SmartKey 需要蓝牙连接按键设备以收发按键事件。",
    # 菜单栏 App：无 Dock 图标
    "LSUIElement": True,
    # App 图标
    "CFBundleIconFile": "SmartKey",
    # 权限：pynput 需要辅助功能
    "NSAppleEventsUsageDescription": "SmartKey 需要控制键盘以执行按键动作。",
    "NSAccessibilityUsageDescription": "SmartKey 需要辅助功能权限以模拟键盘输入。",
}

APP = [
    os.path.join(BASE, "menubar.py"),
]

setup(
    name=APP_NAME,
    app=APP,
    py_modules=["controller", "actions", "smartkey_protocol"],
    data_files=DATA_FILES,
    options={
        "py2app": {
            "argv_emulation": False,
            "packages": ["bleak", "rumps", "pynput"],
            "iconfile": os.path.join(ROOT, "app_assets", "SmartKey.icns"),
            "plist": INFO_PLIST,
            "includes": [
                "controller",
                "actions",
                "smartkey_protocol",
                "menubar",
                "bleak.backends.corebluetooth",
            ],
        }
    },
)
