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
    /// ICON 头部，后接 RGB565 像素数据
    static func iconHeader(x: Int, y: Int, w: Int, h: Int) -> Data {
        Data("ICON,\(x),\(y),\(w),\(h)\n".utf8)
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
