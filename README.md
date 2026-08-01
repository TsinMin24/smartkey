# SmartKey — BLE 无线按键板

nRF52840 (nice!nano) + ST7789 76×284 屏幕 + 5 按键，通过 BLE UART 与电脑通信。
电脑端软件把「按键」翻译成任意动作（快捷键 / 启动程序），类似 Stream Deck / TourBox 的架构。

```
nRF52840 (SmartKey)                      电脑端 Swift 上位机 (macOS 菜单栏 App)
┌──────────────────┐    BLE UART     ┌──────────────────────────┐
│ 5 个按键          │ ──────────────► │ 收到 "DOWN,3"            │
│ DOWN,3 / UP,3    │                 │ 查 slot3 配置            │
│ 屏幕显示图标/状态  │ ◄────────────── │ 执行动作(快捷键/启动app)   │
│ 接收 App 图标     │   SLOT/ICON命令 │ 提取 App 图标 → 2色掩码    │
└──────────────────┘                 └──────────────────────────┘
```

---

## 目录结构

```
smartkey/
├── macos_app/                # ★ 当前上位机（Swift + SwiftUI）
│   ├── Package.swift          # SwiftPM 配置
│   ├── build_app.sh           # 构建脚本 → SmartKeyHost.app
│   └── Sources/SmartKeyApp/
│       ├── AppLog.swift           # 文件日志（~/Library/Logs/SmartKeyHost/）
│       ├── ActionEngine.swift     # 动作执行器（快捷键/启动 App）
│       ├── IconEncoder.swift      # App 图标 → 2色掩码（24×24, 1bit/像素）
│       ├── Protocol/Protocol.swift # 行文本协议 + CRC16 + 掩码打包
│       ├── Transport/BLEManager.swift      # CoreBluetooth 传输层（NUS）
│       ├── Transport/DeviceTransport.swift # 传输层抽象协议
│       ├── ViewModels/DashboardViewModel.swift # 业务逻辑与状态机
│       └── Views/DashboardView.swift       # SwiftUI 界面（设备/槽位/日志）
├── firmware/                 # 板子固件（部署到 /Volumes/CIRCUITPY）
│   ├── code.py               # 主程序：BLE + 按键 + 协议
│   ├── display_driver.py     # 屏幕驱动（纯 displayio，无裸 SPI）
│   └── boot.py               # 开机脚本
├── desktop/                  # 旧 Python 版（已废弃，保留参考）
├── app_assets/               # App 图标资源
├── tools/                    # 工具脚本
└── README.md
```

---

## 一、板子部署

固件文件在 `firmware/`，直接复制到板子的 CIRCUITPY 根目录：

| 文件 | 说明 |
|------|------|
| `code.py` | BLE UART 主程序 |
| `display_driver.py` | 屏幕驱动（纯 displayio） |
| `lib/adafruit_ble/` | BLE 库（`.mpy` 编译版） |

lib 使用 Adafruit CircuitPython Bundle 的 `.mpy` 编译库（10.x-mpy），
比 `.py` 源码省一半 flash。缺失的 `services/nordic.mpy` 已补齐。

### 屏幕驱动（display_driver.py）

**完全基于 displayio** —— 界面元素（背景 / 蓝条 / 状态窗 / 槽位）是独立的
`Bitmap + TileGrid` 叠加，图标是独立 `Bitmap + 2色 Palette`。**不直接调用
`bus.send()`**，与 displayio 刷新机制零冲突，不会卡死。

- 屏幕 76×284（非标准面板：COLSTART=82, ROWSTART=18，纵向）
- 5 个 36×36 正方形槽位，水平居中（x=20），垂直间距 40（y 起 82）
- 槽位选中变白、恢复变暗灰；状态窗连接绿 / 断开橙
- 图标 24×24 或 32×32，2 色掩码（1bit/像素），居中嵌入槽位

### 板子端协议

```
板子 → 电脑:
  DOWN,1..5      按键按下
  UP,1..5        按键释放
  OK / ERR_CRC   图标接收结果

电脑 → 板子:
  PING              → 板子回 PONG
  STATUS,<hex24>    设置状态窗颜色（如 00FF00）
  SLOT,<n>,<名称>   设置槽位名称
  ICON,<slot>,<w>,<h>,<fg565>,<bg565>,<crc16>,<hex掩码>
                    2色掩码图标（单行文本，整行一个 BLE 包传完）
```

### 图标协议（2色掩码，单包传输）

为避免多包传输导致板子内存/时序问题，图标编码为**单行文本命令**：

- 图标 24×24，提取「前景主色（logo色）」+「背景色（槽位底色）」
- 1bit/像素掩码：`1` = 前景 logo 像素，`0` = 背景（露出槽位底色）
- 掩码 72 字节 → hex 编码 → 拼进一行命令（约 170B）
- 整行**一个 BLE 数据包传完**，无分块、无接收循环、无半包
- CRC16 校验：坏数据直接丢弃，绝不写入 flash / 屏幕
- 板子收到后存 flash（`icon_N.bin`），立即渲染，并开机时从 flash 恢复

BLE 细节：

| 项 | 值 |
|----|-----|
| 设备名 | `SmartKey` |
| 服务 UUID | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| 电脑→板子 | `6E400002-…` |
| 板子→电脑 | `6E400003-…` (notify) |

---

## 二、上位机运行（Swift 版）

### 构建

```bash
cd macos_app
./build_app.sh        # 编译并组装 SmartKeyHost.app
```

产物在 `.build/release/SmartKeyHost.app`，复制到 `/Applications` 运行。

### 使用

- 扫描并连接板子（名字 `SmartKey`，带 NUS 服务）
- 配置 5 个槽位：快捷键 / 启动 App（可选图标）
- 连接后自动同步槽位配置 + App 图标到板子
- 日志窗口显示收发记录，支持「清空」

> ⚠️ **首次运行**：macOS 会弹「SmartKeyHost 想要使用蓝牙」授权框，点**允许**。
> 重新安装 App（ad-hoc 签名）会重置蓝牙授权，需重新授权。
> 快捷键依赖辅助功能授权：系统设置 → 隐私与安全性 → 辅助功能。

---

## 三、屏幕布局

```
┌────────────────────────┐
│ (顶部蓝色条)             │  0-17
│ ■■■ 状态窗 ■■■           │  18-71  连接=绿 / 断开=橙
│  ┌──────┐ 槽位1 (36×36) │  82-117  ← 图标区
│  │ 图标  │              │
│  ├──────┤ 槽位2         │  122-157
│  │      │              │
│  ├──────┤ ...          │
│  └──────┘ 槽位5         │  242-277
└────────────────────────┘
```

5 个 36×36 正方形槽位，水平居中，间距 40。图标（24×24 / 32×32）居中嵌入。
按键按下对应槽位高亮变白。

---

## 四、故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| 上位机扫描「蓝牙未开启」 | macOS 蓝牙 TCC 授权被重置 | 重新授权：系统设置 → 隐私与安全性 → 蓝牙 |
| 连接后图标不上屏 | 板子 safe mode / 未运行固件 | 重新插拔板子退出 safe mode，确认 USB 卷挂载 |
| 板子卡死 | 驱动用裸 SPI 与 displayio 冲突 | 已改用纯 displayio 驱动，不再直接 bus.send |
| 屏幕显示命令行乱码 | 坏图标数据被渲染 / 终端镜像 | 固件加 CRC 校验丢弃坏数据；清空 root_group |
| 按键无反应 | 连接断了 | 上位机自动重连，检查日志 |

---

## 五、开发备忘

- **部署固件**：`cp firmware/code.py /Volumes/CIRCUITPY/`，保存后板子 auto-reload
- **串口调试**：`screen /dev/cu.usbmodem101 115200`，Ctrl-C 进 REPL，Ctrl-D 软重启
- **构建上位机**：`cd macos_app && ./build_app.sh`
- **日志位置**：`~/Library/Logs/SmartKeyHost/host.log`
- **槽位配置**：`~/Library/Application Support/SmartKeyHost/slots.json`
