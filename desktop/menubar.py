"""SmartKey 菜单栏常驻 App
在 macOS 菜单栏显示 SmartKey 状态图标，后台线程运行 BLE 控制器。
菜单栏提供：扫描设备列表 → 用户选择连接；连接状态显示；断开；退出。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import rumps

# 打包为 .app 后，入口脚本位于 Contents/Resources/，
# 兄弟模块（controller/actions/...）也复制到该目录，确保可导入。
_res_dir = os.path.dirname(os.path.abspath(__file__))
if _res_dir not in sys.path:
    sys.path.insert(0, _res_dir)

from controller import SmartKeyController, load_config
from smartkey_protocol import DEVICE_NAME

log = logging.getLogger("smartkey.menubar")

# 连接状态 → 菜单栏图标（实际 PNG 文件，rumps 用文件名）
_STATUS_ICON = {
    "offline": "menu_offline.png",
    "searching": "menu_searching.png",
    "connecting": "menu_connecting.png",
    "connected": "menu_connected.png",
}
_STATUS_TEXT = {
    "offline": "SmartKey 未连接",
    "searching": "正在扫描…",
    "connecting": "正在连接…",
    "connected": "已连接",
}


class SmartKeyMenubar(rumps.App):
    def __init__(self, base: Path, cfg_path: Path) -> None:
        # 图标文件在打包后的 Resources/icons/ 下，用绝对路径
        self.icon_dir = base / "icons"
        super().__init__("SmartKey", icon=str(self.icon_dir / "menu_offline.png"))
        self.base = base
        self.cfg_path = cfg_path
        self.cfg = load_config(cfg_path)
        self.controller: Optional[SmartKeyController] = None
        self._thread: Optional[threading.Thread] = None

        # 菜单项
        self._status = rumps.MenuItem(_STATUS_TEXT["offline"])
        self._status.set_callback(None)  # 纯显示，不可点击
        self._scan_item = rumps.MenuItem("🔍 扫描设备…", callback=self._on_scan)
        self._device_menu = rumps.MenuItem("设备列表")
        self._disconnect = rumps.MenuItem("断开连接", callback=self._on_disconnect)
        self._disconnect.set_callback(None)  # 默认禁用，连上后启用
        self._config = rumps.MenuItem("打开配置", callback=self._on_open_config)
        self._icons = rumps.MenuItem("图标文件夹", callback=self._on_open_icons)
        self._quit = rumps.MenuItem("退出", callback=self._on_quit)
        self.menu = [
            self._status,
            None,
            self._scan_item,
            self._device_menu,
            None,
            self._disconnect,
            self._config,
            self._icons,
            None,
            self._quit,
        ]

        self.title = DEVICE_NAME  # 菜单栏标题显示设备名

        # 后台启动控制器
        self._start_controller()

    # ── 控制器生命周期 ──
    def _start_controller(self) -> None:
        self.controller = SmartKeyController(self.cfg, self.base, status_cb=self._on_status)
        self._thread = threading.Thread(
            target=self._run_loop, args=(self.controller,), daemon=True
        )
        self._thread.start()

    def _run_loop(self, controller: SmartKeyController) -> None:
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        log.info("BLE 事件循环已创建")
        controller.attach_loop(loop)  # 让菜单栏线程能投递任务
        log.info("attach_loop 已调用")
        try:
            loop.run_until_complete(controller.run())
        except Exception as e:  # noqa: BLE001
            log.error("控制器异常退出: %s", e)
            self._on_status("offline")

    # ── 状态回调（BLE 线程 → 菜单栏，rumps 线程安全）──
    def _on_status(self, status: str) -> None:
        icon = _STATUS_ICON.get(status, "menu_offline.png")
        text = _STATUS_TEXT.get(status, f"SmartKey {status}")
        icon_path = self.icon_dir / icon
        try:
            self.icon = str(icon_path)
            self._status.title = text
            if status == "connected":
                self._disconnect.set_callback(self._on_disconnect)
            else:
                self._disconnect.set_callback(None)
        except Exception:  # noqa: BLE001
            pass

    # ── 扫描设备（后台线程执行，不阻塞菜单栏）──
    def _on_scan(self, _=None) -> None:
        # 清空旧列表
        self._device_menu.clear()
        self._device_menu.add(rumps.MenuItem("扫描中…"))
        self._status.title = _STATUS_TEXT["searching"]
        # 后台线程跑扫描，完成后更新菜单
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self) -> None:
        log.info("_do_scan 开始")
        if not self.controller:
            log.info("_do_scan: controller 为 None")
            return
        fut = self.controller.run_coro(self.controller.scan_devices(timeout=6.0))
        if fut is None:
            log.error("_do_scan: run_coro 返回 None（事件循环未就绪）")
            return
        log.info("_do_scan: 已投递扫描协程，等待结果…")
        try:
            devices = fut.result(timeout=20.0)
            log.info("_do_scan: 扫描结果 %d 台", len(devices))
        except Exception as e:  # noqa: BLE001
            log.error("扫描异常: %s", e)
            devices = []
        # 回到主线程更新菜单（rumps 需要主线程）
        try:
            self._show_devices(devices)
        except Exception as e:  # noqa: BLE001
            log.error("更新设备菜单失败: %s", e)

    def _show_devices(self, devices: list[dict]) -> None:
        self._device_menu.clear()
        if not devices:
            self._device_menu.add(rumps.MenuItem("未发现设备", callback=None))
            self._status.title = _STATUS_TEXT["offline"]
            return
        for d in devices[:12]:  # 最多显示 12 个
            tag = "🔷" if d["is_uart"] else "  "
            label = f'{tag} {d["name"]}  ({d["rssi"]})'
            item = rumps.MenuItem(label, callback=self._on_pick_device)
            item.address = d["address"]
            item.name = d["name"]
            self._device_menu.add(item)
        self._device_menu.add(None)
        self._device_menu.add(rumps.MenuItem(f"共 {len(devices)} 台设备", callback=None))
        self._status.title = _STATUS_TEXT["offline"]

    def _on_pick_device(self, sender) -> None:
        addr = getattr(sender, "address", "")
        name = getattr(sender, "name", addr)
        if not addr or not self.controller:
            return
        log.info("用户选择连接: %s (%s)", name, addr)
        self._status.title = f"正在连接 {name}…"
        # 先断开现有连接
        self.controller.run_coro(self.controller.disconnect())
        # 后台连接
        threading.Thread(
            target=self._do_connect, args=(addr, name), daemon=True
        ).start()

    def _do_connect(self, addr: str, name: str) -> None:
        fut = self.controller.run_coro(self.controller.connect_to(addr))
        if fut is None:
            return
        try:
            ok = fut.result(timeout=25.0)
        except Exception as e:  # noqa: BLE001
            log.error("连接异常: %s", e)
            ok = False
        if ok:
            try:
                self._status.title = f"已连接 {name}"
            except Exception:
                pass
        else:
            try:
                self._status.title = f"连接失败 {name}"
                rumps.notification(
                    "SmartKey",
                    "连接失败",
                    "请确认设备在广播，并检查 macOS 蓝牙里是否已忘记旧设备",
                )
            except Exception:
                pass

    # ── 断开 ──
    def _on_disconnect(self, _=None) -> None:
        if self.controller:
            self.controller.run_coro(self.controller.disconnect())

    # ── 菜单动作 ──
    def _on_open_config(self, _=None) -> None:
        subprocess.run(["open", "-R", str(self.cfg_path)])

    def _on_open_icons(self, _=None) -> None:
        icons_dir = self.base / "icons"
        if icons_dir.exists():
            subprocess.run(["open", str(icons_dir)])

    def _on_quit(self, _=None) -> None:
        rumps.quit_application()


def run_app(base: Path, cfg_path: Path) -> None:
    SmartKeyMenubar(base, cfg_path).run()


def setup_logging() -> str:
    """配置日志：stdout + 文件（用户目录，App 可写），返回日志文件路径"""
    log_dir = Path.home() / "Library" / "Logs" / "SmartKey"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "smartkey.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    return str(log_file)


if __name__ == "__main__":
    base = Path(__file__).parent
    cfg = base / "config.json"
    log_file = setup_logging()
    print(f"日志文件: {log_file}", flush=True)
    run_app(base, cfg)
