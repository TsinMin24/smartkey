#!/usr/bin/env python3
"""BLE 文件传输测试脚本 —— 通过 FileTransferService 推送 icon_1.bin 到板子"""
import asyncio
import struct
import sys
from bleak import BleakClient, BleakScanner

DEVICE_NAME = "SmartKey"
# FileTransferService UUID
FT_SERVICE_UUID = "0000FEBB-0000-1000-8000-00805F9B34FB"
FT_CHAR_UUID = "ADAF0200-4669-6C65-5472-616E73666572"

# 协议常量
CMD_WRITE = 0x20
CMD_WRITE_PACING = 0x21
CMD_WRITE_DATA = 0x22
STATUS_OK = 0x01

CHUNK_SIZE = 490  # 与 adafruit_ble_file_transfer 一致


async def main():
    icon_path = sys.argv[1] if len(sys.argv) > 1 else "firmware/icon_1.bin"
    remote_path = "icon_1.bin"

    with open(icon_path, "rb") as f:
        data = f.read()
    print(f"本地文件: {icon_path} ({len(data)}B)")

    # 扫描设备
    print(f"扫描 {DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if not device:
        print("❌ 找不到设备")
        return
    print(f"找到: {device.name} ({device.address})")

    async with BleakClient(device) as client:
        print(f"已连接: {client.is_connected}")

        # 获取特征
        char = client.services.get_characteristic(FT_CHAR_UUID)
        if not char:
            # 尝试通过 service 发现
            for svc in client.services:
                print(f"  服务: {svc.uuid}")
                for c in svc.characteristics:
                    print(f"    特征: {c.uuid} props={c.properties}")
                    if c.uuid.lower() == FT_CHAR_UUID.lower():
                        char = c
        if not char:
            print("❌ 找不到 FileTransfer 特征")
            return
        print(f"FileTransfer 特征: {char.uuid}")

        # 启用 notify
        await client.start_notify(char.uuid, lambda _: None)

        # ── 发送 WRITE 命令 ──
        path_bytes = remote_path.encode("utf-8")
        mod_time = int(asyncio.get_event_loop().time() * 1e9) & 0xFFFFFFFFFFFFFFFF
        total_len = len(data)

        cmd = struct.pack("<BxHIQI", CMD_WRITE, len(path_bytes), 0, mod_time, total_len) + path_bytes
        print(f"发送 WRITE: path={remote_path} total={total_len}B")
        await client.write_gatt_char(char.uuid, cmd, response=False)

        # 等待 WRITE_PACING 响应
        pacing_event = asyncio.Event()
        pacing_data = bytearray()

        def on_notify(_, data_raw):
            nonlocal pacing_data
            pacing_data = bytearray(data_raw)
            pacing_event.set()

        await client.stop_notify(char.uuid)
        await client.start_notify(char.uuid, on_notify)

        print("等待 pacing 响应...")
        try:
            await asyncio.wait_for(pacing_event.wait(), timeout=5)
        except asyncio.TimeoutError:
            print("❌ 等待 pacing 超时")
            return

        cmd_r, status = struct.unpack_from("<BB", pacing_data)
        print(f"收到 pacing: cmd=0x{cmd_r:02X} status={status} data={pacing_data.hex()}")

        if cmd_r != CMD_WRITE_PACING or status != STATUS_OK:
            print(f"❌ pacing 异常: cmd=0x{cmd_r:02X} status={status}")
            return

        # ── 发送数据 ──
        offset = 0
        while offset < total_len:
            chunk_end = min(offset + CHUNK_SIZE, total_len)
            chunk = data[offset:chunk_end]

            pkt = struct.pack("<BBxxII", CMD_WRITE_DATA, STATUS_OK, offset, len(chunk)) + chunk
            print(f"发送 DATA: {offset}..{chunk_end} ({len(chunk)}B)")
            await client.write_gatt_char(char.uuid, pkt, response=False)
            offset = chunk_end

            # 等待下一个 pacing（如果有更多数据要发）
            if offset < total_len:
                pacing_event.clear()
                try:
                    await asyncio.wait_for(pacing_event.wait(), timeout=5)
                    cmd_r, status = struct.unpack_from("<BB", pacing_data)
                    if cmd_r != CMD_WRITE_PACING or status != STATUS_OK:
                        print(f"❌ pacing 异常: 0x{cmd_r:02X} {status}")
                        return
                except asyncio.TimeoutError:
                    print("❌ 等待 pacing 超时")
                    return

        # 等待最终确认
        pacing_event.clear()
        try:
            await asyncio.wait_for(pacing_event.wait(), timeout=5)
            cmd_r, status = struct.unpack_from("<BB", pacing_data)
            if cmd_r == CMD_WRITE_PACING and status == STATUS_OK:
                print(f"✅ {remote_path} 写入成功!")
            else:
                print(f"❌ 确认失败: 0x{cmd_r:02X} {status}")
        except asyncio.TimeoutError:
            print("❌ 等待确认超时")


if __name__ == "__main__":
    asyncio.run(main())
