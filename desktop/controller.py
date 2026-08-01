#!/usr/bin/env python3
"""SmartKey 电脑端控制器
扫描并连接 BLE 设备 "SmartKey"，订阅 UART notify，处理按键事件，
执行 config.json 定义的动作，并把图标/状态推送到板子屏幕。

用法:
    python controller.py            # 正常连接
    python controller.py --scan     # 只扫描列出设备
    python controller.py --fake     # 模拟板子，无 BLE 自测
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import bleak

from actions import ActionRunner, execute
from smartkey_protocol import (
    DEVICE_NAME,
    UART_RX_UUID,
    UART_SERVICE_UUID,
    UART_TX_UUID,
    SLOT_COUNT,
    SLOT_ICON_W,
    SLOT_ICON_H,
    slot_icon_y,
    slot_y,
)

log = logging.getLogger("smartkey")


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _slot_actions(cfg: dict) -> dict[int, dict]:
    """把 config['slots'] 转成 {slot编号: {name, action}}，slot 1..5"""
    out = {}
    for k, v in cfg.get("slots", {}).items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= SLOT_COUNT:
            out[idx] = v
    return out


class IconLoader:
    """从 desktop/icons/icons.bin 读取 5 个 56x20 RGB565 图标"""

    def __init__(self, base: Path) -> None:
        self.base = base
        self._data: Optional[bytes] = None

    def _bin(self) -> Optional[bytes]:
        if self._data is None:
            p = self.base / "icons" / "icons.bin"
            try:
                self._data = p.read_bytes()
            except OSError:
                self._data = b""
        return self._data or None

    def get(self, idx: int) -> Optional[bytes]:
        """idx 0..4，返回 56*20*2 字节"""
        b = self._bin()
        if b is None:
            return None
        size = SLOT_ICON_W * SLOT_ICON_H * 2
        off = idx * size
        if off + size > len(b):
            return None
        return b[off:off + size]


class SmartKeyController:
    def __init__(self, cfg: dict, base: Path, status_cb=None) -> None:
        self.cfg = cfg
        self.base = base
        self.status_cb = status_cb  # 回调(status: str)，供 GUI 显示状态
        self.actions = ActionRunner(
            long_press_ms=cfg.get("long_press_ms", 600),
            repeat_ms=cfg.get("repeat_ms", 300),
        )
        self.icons = IconLoader(base)
        self.client: Optional[bleak.BleakClient] = None
        self._wanted = cfg.get("device_name", DEVICE_NAME)
        self._last_down: dict[int, float] = {}
        self._status = "offline"
        self._reconnect_requested = False
        # 跨线程执行 async 任务的通道（菜单栏线程 → BLE 线程）
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """由 BLE 线程设置事件循环，供菜单栏线程投递任务"""
        self._loop = loop
        self._ready.set()

    def run_coro(self, coro):
        """从任意线程投递协程到 BLE 事件循环，返回 concurrent future"""
        if self._loop is None:
            return None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def request_reconnect(self) -> None:
        """手动触发立即重连（GUI 菜单用）"""
        self._reconnect_requested = True

    def _set_status(self, status: str) -> None:
        """更新状态并通知 GUI"""
        self._status = status
        log.info("状态: %s", status)
        if self.status_cb:
            try:
                self.status_cb(status)
            except Exception:
                pass

    # ── 设备发现 ──
    async def scan_devices(self, timeout: float = 6.0) -> list[dict]:
        """扫描并返回设备列表（name/address/rssi），供菜单栏显示"""
        try:
            devices = await bleak.BleakScanner.discover(timeout=timeout, return_adv=True)
        except Exception as e:  # noqa: BLE001
            log.error("扫描失败: %s", e)
            return []
        out = []
        for addr, (dev, adv) in devices.items():
            name = (adv.local_name or dev.name or "(无名)").strip()
            out.append({
                "name": name,
                "address": addr,
                "rssi": adv.rssi,
                "is_uart": any(
                    u.lower() == UART_SERVICE_UUID.lower()
                    for u in (adv.service_uuids or [])
                ),
            })
        # 有 UART 服务的排前面，其次按 RSSI（信号强在前）
        out.sort(key=lambda d: (not d["is_uart"], -d["rssi"]))
        log.info("扫描到 %d 台设备", len(out))
        return out

    async def find_device(self) -> Optional[bleak.BLEDevice]:
        # return_adv=True 拿完整广告数据：名称可能在主包或扫描响应，
        # 只靠 d.name 匹配会漏掉名称在扫描响应里的设备
        devices = await bleak.BleakScanner.discover(timeout=8, return_adv=True)
        wanted_l = self._wanted.lower()
        for addr, (dev, adv) in devices.items():
            # 名称来源：主包名 / 扫描响应 local_name / 设备名
            names = {n.lower() for n in (dev.name, adv.local_name) if n}
            if wanted_l in names:
                log.info("找到 %s: %s rssi=%s", self._wanted, addr, adv.rssi)
                return dev
            # 兜底：匹配 UART Service UUID
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            if UART_SERVICE_UUID.lower() in uuids:
                log.info("找到 %s (UUID): %s rssi=%s", self._wanted, addr, adv.rssi)
                return dev
        log.warning("未找到设备 %s，共扫描到 %d 台", self._wanted, len(devices))
        for addr, (dev, adv) in list(devices.items())[:10]:
            log.info("  看到: %s (%s)", adv.local_name or dev.name or "(无名)", addr)
        return None

    # ── 连接与收发 ──
    def _rx_char(self) -> Optional[str]:
        """找到板子发→电脑收的 notify characteristic（TX）"""
        if self.client is None:
            return None
        for c in self.client.services.characteristics.values():
            if c.uuid.lower() == UART_TX_UUID.lower():
                return c.uuid
        return None

    async def _notification_handler(self, sender, data: bytearray) -> None:
        try:
            text = bytes(data).decode("utf-8", "ignore").strip()
        except Exception:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            log.info("[BLE] %s", line)
            if line.startswith("DOWN,"):
                try:
                    slot = int(line.split(",")[1])
                except (IndexError, ValueError):
                    continue
                self._on_key_down(slot)
            elif line.startswith("UP,"):
                try:
                    slot = int(line.split(",")[1])
                except (IndexError, ValueError):
                    continue
                self._on_key_up(slot)
            elif line == "PONG":
                pass

    def _on_key_down(self, slot: int) -> None:
        a = self._slot_action(slot)
        self.actions.on_press(slot, a, time.time())

    def _on_key_up(self, slot: int) -> None:
        self.actions.on_release(slot)

    def _slot_action(self, slot: int) -> dict:
        slots = self.cfg.get("slots", {})
        item = slots.get(str(slot), {})
        return item.get("action", {"type": "none"})

    async def _write(self, msg: str) -> bool:
        if self.client is None or not self.client.is_connected:
            return False
        try:
            await self.client.write_gatt_char(UART_RX_UUID, msg.encode(), response=False)
            return True
        except Exception:
            return False

    # ── 开机同步：状态 + 图标 + 槽位名 ──
    async def sync_display(self) -> None:
        if not await self._write("PING\n"):
            return
        await asyncio.sleep(0.05)
        # 状态窗
        await self._write("STATUS,00FF00\n")
        # 每个槽位：图标 + 名称
        slots = self.cfg.get("slots", {})
        for idx in range(1, SLOT_COUNT + 1):
            item = slots.get(str(idx), {})
            name = item.get("name", "")
            await self._write(f"SLOT,{idx},{name}\n")
            await asyncio.sleep(0.02)
            icon = self.icons.get(idx - 1)
            if icon:
                y = slot_icon_y(idx - 1)
                hdr = f"ICON,{SLOT_ICON_W + 4},{y},{SLOT_ICON_W},{SLOT_ICON_H}"
                await self._write(hdr)
                await asyncio.sleep(0.05)
                await self.client.write_gatt_char(UART_RX_UUID, icon, response=True)
                await asyncio.sleep(0.05)
        log.info("屏幕同步完成")

    async def connect_to(self, address: str) -> bool:
        """连接指定地址的设备，成功返回 True"""
        self._set_status("connecting")
        try:
            self.client = bleak.BleakClient(address, timeout=15.0, pair=False)
            await self.client.connect()
            log.info("已连接 %s", address)
            await self.client.start_notify(UART_TX_UUID, self._notification_handler)
            self._set_status("connected")
            await self.sync_display()
            return True
        except Exception as e:  # noqa: BLE001
            log.error("连接失败 %s: %s", address, e)
            if self.client:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
            self.client = None
            self._set_status("offline")
            return False

    async def disconnect(self) -> None:
        """主动断开连接"""
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self._set_status("offline")

    # ── 主循环：等待用户指令 ──
    async def run(self) -> None:
        # 不再自动扫描/重连——改为用户通过菜单栏选择设备
        self._set_status("offline")
        while True:
            # 若已连接，保持；否则等菜单栏指令
            if self.client and self.client.is_connected:
                while self.client.is_connected:
                    await asyncio.sleep(1)
                self._set_status("offline")
            await asyncio.sleep(1)


# ── 自测：无 BLE 模拟板子 ──
async def fake_device(controller: SmartKeyController) -> None:
    """模拟板子发按键事件，验证电脑端逻辑"""
    log.info("[FAKE] 模拟板子：按下/释放 槽位 1-5")
    for i in range(1, SLOT_COUNT + 1):
        controller._on_key_down(i)
        await asyncio.sleep(0.1)
        controller._on_key_up(i)
        await asyncio.sleep(0.2)


async def scan_only() -> None:
    devices = await bleak.BleakScanner.discover(timeout=8)
    log.info("扫描到 %d 台设备：", len(devices))
    for d in devices:
        log.info("  %-18s %s  rssi=%s", d.name or "(无名)", d.address, d.rssi)


def main() -> int:
    ap = argparse.ArgumentParser(description="SmartKey 电脑端控制器")
    ap.add_argument("--base", default=Path(__file__).parent)
    ap.add_argument("--config", default=None, help="配置文件路径")
    ap.add_argument("--scan", action="store_true", help="只扫描设备")
    ap.add_argument("--fake", action="store_true", help="模拟板子自测")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    base: Path = args.base if isinstance(args.base, Path) else Path(args.base)
    cfg_path = Path(args.config) if args.config else base / "config.json"
    cfg = load_config(cfg_path)

    if args.scan:
        asyncio.run(scan_only())
        return 0

    controller = SmartKeyController(cfg, base)

    if args.fake:
        async def _fake():
            await fake_device(controller)
        asyncio.run(_fake())
        return 0

    asyncio.run(controller.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
