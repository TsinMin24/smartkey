//
//  FileTransferClient.swift
//  BLE 文件传输客户端 —— 通过 FileTransferService 推送文件到板子
//  协议参考：adafruit_ble_file_transfer (PacketBuffer, 自带分包+流控)
//
import Foundation
import CoreBluetooth

/// BLE 文件传输客户端
final class FileTransferClient: NSObject {
    // FileTransferService UUID (StandardUUID 0xFEBB)
    private let serviceUUID = CBUUID(string: "FEBB")
    // 传输特征 UUID (VendorUUID: "FileTransfer\x00\x00\xAF\xAD" with 0x0200)
    private let transferCharUUID = CBUUID(string: "ADAF0200-4669-6C65-5472-616E73666572")

    // 命令码
    private let CMD_WRITE: UInt8 = 0x20
    private let CMD_WRITE_PACING: UInt8 = 0x21
    private let CMD_WRITE_DATA: UInt8 = 0x22
    private let STATUS_OK: UInt8 = 0x01

    private var peripheral: CBPeripheral?
    private var transferChar: CBCharacteristic?
    private var pendingData = Data()
    private var currentOffset: UInt = 0
    private var totalLength: UInt = 0
    private var completionHandler: ((Bool) -> Void)?

    // MARK: - Public

    /// 通过已连接的外设写入文件
    func writeFile(peripheral: CBPeripheral, path: String, contents: Data,
                   completion: @escaping (Bool) -> Void) {
        self.peripheral = peripheral
        self.completionHandler = completion
        peripheral.delegate = self

        // 先发现 FileTransferService
        peripheral.discoverServices([serviceUUID])
    }

    // MARK: - Protocol

    private func startWrite(path: String, contents: Data) {
        guard let char = transferChar, let p = peripheral else {
            completionHandler?(false)
            return
        }

        pendingData = contents
        currentOffset = 0
        totalLength = UInt(contents.count)

        let pathBytes = path.data(using: .utf8)!
        let modTime = UInt64(Date().timeIntervalSince1970 * 1_000_000_000)

        // WRITE 命令: [cmd:1][pad:1][pathLen:2LE][offset:4LE][modTime:8LE][totalLen:4LE][path...]
        var cmd = Data(count: 20 + pathBytes.count)
        cmd[0] = CMD_WRITE
        cmd[1] = 0
        cmd[2] = UInt8(pathBytes.count & 0xFF)
        cmd[3] = UInt8((pathBytes.count >> 8) & 0xFF)
        // offset (4 bytes LE)
        cmd[4] = 0; cmd[5] = 0; cmd[6] = 0; cmd[7] = 0
        // modification_time (8 bytes LE)
        withUnsafeBytes(of: modTime.littleEndian) { raw in
            for i in 0..<8 { cmd[8 + i] = raw[i] }
        }
        // total_length (4 bytes LE)
        let tl = UInt32(contents.count)
        withUnsafeBytes(of: tl.littleEndian) { raw in
            for i in 0..<4 { cmd[16 + i] = raw[i] }
        }
        cmd.replaceSubrange(20..<(20 + pathBytes.count), with: pathBytes)

        AppLog.log("FileTransfer: WRITE \(path) (\(contents.count)B)")
        p.writeValue(cmd, for: char, type: .withoutResponse)
        // 等待 WRITE_PACING 响应（通过 didUpdateValueFor）
        p.setNotifyValue(true, for: char)
    }

    private func handlePacing(_ data: Data) {
        guard data.count >= 12, let p = peripheral, let char = transferChar else {
            completionHandler?(false)
            return
        }

        let cmd = data[0]
        let status = data[1]
        guard cmd == CMD_WRITE_PACING, status == STATUS_OK else {
            AppLog.log("FileTransfer: unexpected cmd=0x\(String(cmd, radix: 16)) status=\(status)")
            completionHandler?(false)
            return
        }

        // pacing: [cmd:1][status:1][pad:2][offset:4LE][freeSpace:4LE]
        let offset = UInt(data[4]) | UInt(data[5]) << 8 | UInt(data[6]) << 16 | UInt(data[7]) << 24
        let freeSpace = UInt(data[8]) | UInt(data[9]) << 8 | UInt(data[10]) << 16 | UInt(data[11]) << 24

        if currentOffset >= totalLength {
            // 所有数据已发完，等最终确认
            return
        }

        // 发送 WRITE_DATA 头 + 数据
        let chunkEnd = min(currentOffset + freeSpace, totalLength)
        let chunk = pendingData[Int(currentOffset)..<Int(chunkEnd)]

        // WRITE_DATA: [cmd:1][status:1][pad:2][offset:4LE][chunkLen:4LE][data...]
        var header = Data(count: 12)
        header[0] = CMD_WRITE_DATA
        header[1] = STATUS_OK
        header[2] = 0; header[3] = 0
        let off32 = UInt32(offset)
        withUnsafeBytes(of: off32.littleEndian) { raw in
            for i in 0..<4 { header[4 + i] = raw[i] }
        }
        let chunkLen = UInt32(chunk.count)
        withUnsafeBytes(of: chunkLen.littleEndian) { raw in
            for i in 0..<4 { header[8 + i] = raw[i] }
        }

        var pkt = header
        pkt.append(chunk)
        AppLog.log("FileTransfer: DATA \(currentOffset)..<\(chunkEnd) (\(chunk.count)B)")
        p.writeValue(pkt, for: char, type: .withoutResponse)
        currentOffset = chunkEnd
    }

    private func handleConfirm(_ data: Data) {
        guard data.count >= 2 else { return }
        let cmd = data[0]
        let status = data[1]
        if cmd == CMD_WRITE_PACING && status == STATUS_OK {
            AppLog.log("FileTransfer: ✅ 写入完成")
            completionHandler?(true)
        } else {
            AppLog.log("FileTransfer: ❌ 确认失败 cmd=\(cmd) status=\(status)")
            completionHandler?(false)
        }
    }
}

// MARK: - CBPeripheralDelegate
extension FileTransferClient: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let services = peripheral.services else {
            completionHandler?(false)
            return
        }
        for svc in services where svc.uuid == serviceUUID {
            peripheral.discoverCharacteristics([transferCharUUID], for: svc)
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        guard let chars = service.characteristics else {
            completionHandler?(false)
            return
        }
        for c in chars where c.uuid == transferCharUUID {
            transferChar = c
            // 触发实际写入（startWrite 在 writeFile 流程中延迟调用）
            if let path = pendingWritePath, let data = pendingWriteData {
                startWrite(path: path, contents: data)
            }
            return
        }
        completionHandler?(false)
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard let data = characteristic.value else { return }
        if currentOffset < totalLength {
            handlePacing(data)
        } else {
            handleConfirm(data)
        }
    }

    // 暂存参数（因为 discover 是异步的）
    private static var _pendingPath: String?
    private static var _pendingData: Data?
    private var pendingWritePath: String? { Self._pendingPath }
    private var pendingWriteData: Data? { Self._pendingData }
}

extension FileTransferClient {
    /// 便捷入口：发现服务后自动写入
    func sendFile(peripheral: CBPeripheral, path: String, contents: Data,
                  completion: @escaping (Bool) -> Void) {
        Self._pendingPath = path
        Self._pendingData = contents
        self.completionHandler = completion
        self.peripheral = peripheral
        peripheral.delegate = self
        peripheral.discoverServices([serviceUUID])
    }
}
