# SmartKey — BLE 无线按键板

nRF52840 (nice!nano) + ST7789 76×284 屏幕 + 5 按键，通过 BLE UART 与电脑通信。
电脑端软件把「按键」翻译成任意动作（快捷键 / 输入文字 / 启动程序 / 打开网址），
类似 Stream Deck / TourBox 的架构。

```
nRF52840 (SmartKey)                      电脑端软件 (常驻后台)
┌──────────────────┐    BLE UART     ┌──────────────────────────┐
│ 5 个按键          │ ──────────────► │ 收到 "DOWN,3"            │
│ DOWN,3 / UP,3    │                 │ 查 config.json 里 slot3   │
│ 屏幕显示图标/状态  │ ◄────────────── │ 执行动作(快捷键/启动app等)  │
│ 接收图标/名称     │   SLOT/ICON命令  │ 推送图标/名称到屏幕         │
└──────────────────┘                 └──────────────────────────┘
```

---

## 目录结构

```
smartkey/
├── SmartKey.app            # ★ 打包好的 macOS 菜单栏 App（双击运行）
├── firmware/                # 板子固件（部署到 /Volumes/CIRCUITPY）
│   ├── code.py              # 主程序：BLE + 按键 + 协议
│   ├── display_driver.py    # 屏幕驱动（纯 SPI 直绘）
│   └── adafruit_ble_py.bak  # 旧 .py 库备份（已换 .mpy）
├── desktop/                 # 电脑端软件（Python + bleak）
│   ├── controller.py        # 主控制器：连接/事件/重连
│   ├── actions.py           # 动作执行器
│   ├── menubar.py           # 菜单栏常驻入口（rumps）
│   ├── smartkey_protocol.py # 双端共享协议常量
│   ├── setup.py             # py2app 打包配置
│   ├── config.json          # 按键动作配置
│   └── icons/               # 生成的图标
├── app_assets/              # App 图标（SmartKey.icns）
├── tools/
│   └── make_icons.py        # 图标生成器（56×20 RGB565）
└── run.command              # 命令行启动器（调试用）
```

---

## 一、板子部署（已完成）

固件文件在 `firmware/`，直接复制到板子的 CIRCUITPY 根目录：

| 文件 | 说明 |
|------|------|
| `code.py` | BLE UART 主程序 |
| `display_driver.py` | 屏幕驱动 |
| `lib/adafruit_ble/` | BLE 库（`.mpy` 编译版） |

lib 使用 Adafruit CircuitPython Bundle 的 `.mpy` 编译库（10.x-mpy-20260725），
比 `.py` 源码省一半 flash。缺失的 `services/nordic.mpy` 已补齐。

### 板子端协议

```
板子 → 电脑:
  DOWN,1..5      按键按下
  UP,1..5        按键释放

电脑 → 板子:
  PING              → 板子回 PONG
  STATUS,<hex24>    设置状态窗颜色（如 00FF00）
  SLOT,<n>,<名称>   设置槽位名称
  ICON,<x>,<y>,<w>,<h>\n<RGB565字节>  直绘位图
```

BLE 细节：

| 项 | 值 |
|----|-----|
| 设备名 | `SmartKey` |
| 服务 UUID | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| 电脑→板子 | `6E400002-…` |
| 板子→电脑 | `6E400003-…` (notify) |

---

## 二、电脑端运行

### 首次安装依赖

```bash
cd smartkey
/opt/homebrew/bin/python3.12 -m venv .venv    # 或 python3.12 -m venv .venv
.venv/bin/pip install bleak pynput Pillow
```

> 建议用 Python 3.12（Homebrew：`brew install python@3.12`）。
> bleak 在 macOS 上 3.12 最稳定。

### 启动（macOS App，推荐）

**直接双击项目根目录的 `SmartKey.app`**。这是打包好的菜单栏常驻应用：

- 启动后在**菜单栏**（屏幕右上角）显示 SmartKey 状态图标
- 点图标可看到：连接状态、重连设备、打开配置、图标文件夹、退出
- 后台自动连接板子，断线自动重连
- 无 Dock 图标，不占 Dock 空间

> ⚠️ **首次运行**：macOS 会弹「SmartKey 想要使用蓝牙」授权框，
> 点**允许**。如果误拒，去 **系统设置 → 隐私与安全性 → 蓝牙** 手动授权。
> App 的 Info.plist 已内置蓝牙权限描述，不会再出现命令行那种 TCC 崩溃。

> 快捷键 / 输入文字依赖 pynput 模拟键盘，还需要授权：
> **系统设置 → 隐私与安全性 → 辅助功能 → 勾选 SmartKey**。

### 重新打包（改代码后）

```bash
cd smartkey/desktop
../.venv/bin/python setup.py py2app --clean   # 或 rm -rf build dist && python setup.py py2app
```

### 命令行方式（调试用）

```bash
cd smartkey/desktop
../.venv/bin/python controller.py --scan     # 扫描设备
../.venv/bin/python controller.py            # 正常运行
../.venv/bin/python controller.py --fake     # 模拟板子自测（无需 BLE）
../.venv/bin/python controller.py --debug    # 调试日志
```

---

## 三、按键配置（config.json）

每个按键是一个 slot，动作类型：

```json
{
  "slots": {
    "1": { "name": "复制",          "action": { "type": "shortcut", "keys": ["cmd", "c"] } },
    "2": { "name": "粘贴",          "action": { "type": "shortcut", "keys": ["cmd", "v"] } },
    "3": { "name": "截屏",          "action": { "type": "shortcut", "keys": ["cmd", "shift", "3"] } },
    "4": { "name": "打开Safari",    "action": { "type": "launch", "path": "/Applications/Safari.app" } },
    "5": { "name": "打开网址",      "action": { "type": "open_url", "url": "https://www.google.com" } }
  },
  "long_press_ms": 600,
  "repeat_ms": 300
}
```

| 类型 | 字段 | 说明 |
|------|------|------|
| `shortcut` | `keys` | 快捷键组合，如 `["cmd", "shift", "3"]` |
| `type` | `text` | 输入一段文字 |
| `launch` | `path` | 启动应用（`/Applications/XXX.app`） |
| `open_url` | `url` | 打开网址 |
| `media` | `key` | 媒体键：play_pause / next_track / previous_track / volume_up / volume_down / mute |
| `command` | `command` | 执行 shell 命令 |

`long_press_ms`：按住超过该时长进入连续触发模式（适合音量/翻页）。
`repeat_ms`：连续触发间隔。

---

## 四、屏幕布局

```
┌────────────────────────┐
│ (顶部名称条, 蓝色线)      │  0-17
│  ■■■ 状态窗 ■■■          │  18-71  连接=绿 / 断开=橙
│ ┌────────────┐ 槽位1    │  82-110  ← 图标区
│ │ 图标 + 名称 │          │
│ ├────────────┤ 槽位2    │  120-148
│ │            │          │
│ ├────────────┤ ...     │
│ └────────────┘ 槽位5    │  272-300
└────────────────────────┘
```

槽位尺寸：64×28，内部图标区 56×20（白图形 + 深底）。
连接时状态窗变绿，断开变橙；按键按下对应槽位高亮。

---

## 五、自定义图标

默认图标是工具生成的简单图形（复制/粘贴/文档/消息/电源）。

想换图标：
1. 准备 PNG（建议 56×20，RGB 色）；
2. 写一个小脚本把 PNG 转成 RGB565 大端字节流，替换
   `desktop/icons/icons.bin`（5 个图标连续拼接，每个 2240 字节）；
3. 重启 controller.py，自动推送到屏幕。

`tools/make_icons.py` 展示了转换逻辑（`rgb565()` / `rgb565_to_rgb888()`）。

---

## 六、故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| controller.py 启动即崩 (exit 134) | macOS 蓝牙 TCC 权限 | 从 GUI 会话启动，系统设置授权蓝牙 |
| 快捷键无效 | pynput 无辅助功能权限 | 系统设置 → 辅助功能 授权 |
| 搜不到 SmartKey | 板子断电 / 广播中断 | 检查板子电源，串口看日志确认广播 |
| 按键无反应 | 连接断了 / controller 没跑 | 看 controller 日志，等自动重连 |
| 屏幕图标错位 | RGB565 字节序 | 确认大端（高位在前），重跑 make_icons |
