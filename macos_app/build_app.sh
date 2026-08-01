#!/bin/bash
# SmartKey macOS 上位机构建脚本
# 用 swift build 编译，然后组装成 .app 包（含 Info.plist 蓝牙权限）
set -e

cd "$(dirname "$0")"

APP_NAME="SmartKeyHost"
BUILD_DIR=".build/release"
APP_DIR="$BUILD_DIR/$APP_NAME.app"

echo "=== 编译 release 版本 ==="
swift build -c release

echo "=== 组装 .app ==="
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"

# 可执行文件
cp "$BUILD_DIR/SmartKeyApp" "$APP_DIR/Contents/MacOS/$APP_NAME"

# Info.plist（含蓝牙权限）
cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>SmartKeyHost</string>
    <key>CFBundleDisplayName</key>
    <string>SmartKey 上位机</string>
    <key>CFBundleIdentifier</key>
    <string>com.smartkey.host</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleExecutable</key>
    <string>SmartKeyHost</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSBluetoothAlwaysUsageDescription</key>
    <string>SmartKey 上位机需要蓝牙连接按键设备以收发按键事件。</string>
    <key>NSBluetoothPeripheralUsageDescription</key>
    <string>SmartKey 上位机需要蓝牙连接按键设备以收发按键事件。</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# 代码签名（ad-hoc，本地运行需要）
codesign --force --deep --sign - "$APP_DIR" 2>/dev/null || true

echo ""
echo "✅ 构建完成: $APP_DIR"
echo "   双击即可运行，首次会弹蓝牙授权框"
