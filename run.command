#!/bin/bash
# SmartKey 电脑端启动器（macOS 双击运行）
# 必须从 GUI 会话启动，macOS 才能弹出蓝牙授权
cd "$(dirname "$0")"

# 使用项目 venv
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    echo "未找到 venv，正在创建..."
    /opt/homebrew/bin/python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
    .venv/bin/pip install --quiet bleak pynput Pillow
fi

cd desktop
exec ../.venv/bin/python controller.py "$@"
