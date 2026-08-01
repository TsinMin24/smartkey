//
//  Protocol.swift
//  协议与数据解析层 —— SmartKey 行文本协议 + ICON 二进制负载
//
//  板子→电脑:  DOWN,1..5 \n  按键按下
//              UP,1..5 \n    按键释放
//              PONG \n
//  电脑→板子:  PING \n  STATUS,<hex24> \n  SLOT,<n>,<name> \n  ICON,x,y,w,h\n<RGB565>
//
import Foundation

/// 从板子解析出的命令
enum DeviceCommand {
    case keyDown(slot: Int)
    case keyUp(slot: Int)
    case pong
    case unknown(String)
}

/// 电脑发往板子的命令（封装为 Data）
enum HostCommand {
    /// PING → 期待 PONG
    static func ping() -> Data { Data("PING\n".utf8) }
    /// 设置状态窗颜色，hex 如 "00FF00"
    static func status(hex: String) -> Data { Data("STATUS,\(hex)\n".utf8) }
    /// 设置槽位名称
    static func slot(_ n: Int, name: String) -> Data { Data("SLOT,\(n),\(name)\n".utf8) }
    /// 完整 ICON 消息：单行 hex（含掩码），整行一个 BLE 包传完
    /// 格式: ICON,<slot>,<w>,<h>,<fg565hex>,<bg565hex>,<crc16hex>,<hex掩码>\n
    static func iconMessage(slot: Int, fg565: UInt16, bg565: UInt16, mask: Data) -> Data {
        let crc = crc16(mask)
        let hexMask = mask.map { String(format: "%02X", $0) }.joined()
        let head = "ICON,\(slot),\(IconEncoder.size),\(IconEncoder.size),"
            + String(format: "%04X,%04X,%04X,", fg565, bg565, crc)
        return Data((head + hexMask + "\n").utf8)
    }

    /// CRC16-CCITT：与板子校验一致，坏数据会被板子拒绝
    static func crc16(_ data: Data) -> UInt16 {
        var crc: UInt16 = 0xFFFF
        for byte in data {
            crc ^= UInt16(byte) << 8
            for _ in 0..<8 {
                if crc & 0x8000 != 0 {
                    crc = (crc << 1) ^ 0x1021
                } else {
                    crc <<= 1
                }
            }
        }
        return crc
    }
}

/// 帧解码器：处理半包/粘包，按行切分文本协议
final class FrameDecoder {
    private var buffer = Data()
    private let maxLine = 1024

    /// 输入原始字节，输出解析出的命令数组
    func appendAndDecode(_ newData: Data) -> [DeviceCommand] {
        buffer.append(newData)
        var commands: [DeviceCommand] = []
        // 保护：缓冲过长说明协议错位，丢弃旧数据
        if buffer.count > maxLine * 4 {
            buffer.removeFirst(buffer.count - maxLine)
        }

        while let newline = buffer.firstIndex(of: 0x0A) {
            let lineData = buffer.subdata(in: buffer.startIndex..<newline)
            buffer.removeSubrange(buffer.startIndex...newline)

            guard let line = String(data: lineData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines), !line.isEmpty else { continue }

            commands.append(parse(line: line))
        }
        return commands
    }

    private func parse(line: String) -> DeviceCommand {
        if line == "PONG" {
            return .pong
        }
        if line.hasPrefix("DOWN,"), let slot = Int(line.dropFirst(5)) {
            return .keyDown(slot: slot)
        }
        if line.hasPrefix("UP,"), let slot = Int(line.dropFirst(3)) {
            return .keyUp(slot: slot)
        }
        return .unknown(line)
    }
}
