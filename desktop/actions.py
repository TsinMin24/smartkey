"""SmartKey 动作执行器
把 config.json 里每个按键的动作定义，翻译成真实系统操作。
当前平台：macOS（pynput 模拟键盘 / subprocess 启动与命令）。
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Optional

from smartkey_protocol import ActionType

log = logging.getLogger("smartkey.actions")

try:
    from pynput.keyboard import Controller as _KeyController, Key, KeyCode

    _keyboard = _KeyController()
    _PYNPUT_OK = True
except Exception:  # pragma: no cover - 无显示环境
    _keyboard = None
    _PYNPUT_OK = False
    log.warning("pynput 不可用，键盘动作将被禁用")

# 修饰键映射：pynput Key 常量
_MODS = {
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "cmd": Key.cmd,
    "command": Key.cmd,
    "super": Key.cmd,
    "meta": Key.cmd,
    "alt": Key.alt,
    "option": Key.alt,
    "shift": Key.shift,
    "caps": Key.caps_lock,
    "tab": Key.tab,
    "esc": Key.esc,
    "escape": Key.esc,
    "enter": Key.enter,
    "return": Key.enter,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.backspace,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "f1": Key.f1,
    "f2": Key.f2,
    "f3": Key.f3,
    "f4": Key.f4,
    "f5": Key.f5,
    "f6": Key.f6,
    "f7": Key.f7,
    "f8": Key.f8,
    "f9": Key.f9,
    "f10": Key.f10,
    "f11": Key.f11,
    "f12": Key.f12,
    "f13": Key.f13,
    "f14": Key.f14,
    "f15": Key.f15,
    "f16": Key.f16,
    "f17": Key.f17,
    "f18": Key.f18,
    "f19": Key.f19,
    "f20": Key.f20,
}

# macOS 系统键盘码（媒体键）
_MAC_MEDIA_KEYCODES = {
    "play_pause": 16,
    "next_track": 17,
    "previous_track": 18,
    "volume_up": 24,
    "volume_down": 25,
    "mute": 26,
}


def _to_key(name: str):
    """把配置里的键名转成 pynput Key / KeyCode"""
    k = _MODS.get(name.lower())
    if k is not None:
        return k
    if len(name) == 1:
        return KeyCode.from_char(name)
    if name.startswith("0x"):
        return KeyCode.from_vk(int(name, 16))
    return KeyCode.from_char(name)


def _shortcut(keys: list[str]) -> None:
    """按下修饰键组合，再松开。eg: [ctrl, c]"""
    if not _PYNPUT_OK:
        return
    mods, rest = [], []
    for n in keys:
        k = _to_key(n)
        (mods if k in _MODS.values() else rest).append(k)
    for m in mods:
        _keyboard.press(m)
    for r in rest:
        _keyboard.press(r)
        _keyboard.release(r)
    for m in mods:
        _keyboard.release(m)


def _type_text(text: str) -> None:
    if not _PYNPUT_OK:
        return
    for ch in text:
        _keyboard.type(ch)
    time.sleep(0.05)


def _launch(path: str) -> None:
    if os.name == "posix":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen([path])


def _open_url(url: str) -> None:
    if os.name == "posix":
        subprocess.Popen(["open", url])
    elif os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", url])
    else:
        subprocess.Popen(["xdg-open", url])


def _run_command(cmd: str) -> None:
    subprocess.Popen(cmd, shell=True)


def _media(key: str) -> None:
    """媒体键：macOS 用 osascript（最可靠），其他平台暂不支持"""
    code = _MAC_MEDIA_KEYCODES.get(key)
    if os.name == "posix" and code is not None:
        script = (
            'tell application "System Events" to '
            "key code %d" % code
        )
        subprocess.run(["osascript", "-e", script], capture_output=True)


def execute(action: dict) -> bool:
    """执行一个动作定义，返回是否成功"""
    atype = action.get("type", ActionType.NONE.value)
    try:
        if atype == ActionType.SHORTCUT.value:
            _shortcut(action.get("keys", []))
        elif atype == ActionType.TYPE.value:
            _type_text(action.get("text", ""))
        elif atype == ActionType.LAUNCH.value:
            _launch(action.get("path", ""))
        elif atype == ActionType.OPEN_URL.value:
            _open_url(action.get("url", ""))
        elif atype == ActionType.MEDIA.value:
            _media(action.get("key", ""))
        elif atype == ActionType.COMMAND.value:
            _run_command(action.get("command", ""))
        else:
            log.info("动作 %s 无实现", atype)
            return False
        log.info("执行动作: %s %s", atype, action.get("keys") or action.get("text") or action.get("path") or action.get("url") or action.get("key") or action.get("command") or "")
        return True
    except Exception as e:  # noqa: BLE001
        log.error("动作执行失败: %s", e)
        return False


class ActionRunner:
    """动作执行：按键释放时执行一次，避免抖动重复触发。

    长按逻辑：如果按住超过 long_press_ms 未释放，则在按住期间每
    repeat_ms 执行一次（适合音量/翻页等连续动作），释放时停止。
    """

    def __init__(self, long_press_ms: int = 600, repeat_ms: int = 300) -> None:
        self._lock = threading.Lock()
        self._held: dict[int, dict] = {}
        self._stop: dict[int, threading.Event] = {}
        self._long_press_ms = long_press_ms
        self._repeat_ms = repeat_ms

    def on_press(self, slot: int, action: dict, t: float) -> None:
        with self._lock:
            self._held[slot] = action
        ev = threading.Event()
        with self._lock:
            self._stop[slot] = ev

        def _loop():
            try:
                # 等待长按阈值；若期间已释放（ev set），直接结束
                if ev.wait(self._long_press_ms / 1000.0):
                    return
                while not ev.is_set():
                    execute(action)
                    if ev.wait(self._repeat_ms / 1000.0):
                        break
            except Exception:
                pass

        threading.Thread(target=_loop, daemon=True).start()

    def on_release(self, slot: int) -> None:
        with self._lock:
            action = self._held.pop(slot, None)
            ev = self._stop.pop(slot, None)
        if ev:
            ev.set()
        if action is not None:
            execute(action)  # 释放时执行一次
