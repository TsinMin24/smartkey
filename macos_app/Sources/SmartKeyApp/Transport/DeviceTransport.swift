//
//  DeviceTransport.swift
//  传输层抽象协议 —— 只负责收发原始字节，不懂业务含义
//
import Foundation
import Combine

/// 连接状态机
enum ConnectionState: Equatable {
    case idle
    case scanning
    case connecting
    case connected
    case error(String)
}

/// 发现的设备
struct ScannedDevice: Identifiable, Equatable {
    let id: UUID
    let name: String
    let peripheral: AnyObject   // 传输层专用句柄，View 层不解析
    let rssi: Int
    let isUartService: Bool

    static func == (lhs: ScannedDevice, rhs: ScannedDevice) -> Bool {
        lhs.id == rhs.id
    }
}

/// 统一传输协议：任何底层（BLE/USB 串口/HID/Mock）都实现它
protocol DeviceTransportProtocol: AnyObject {
    /// 连接状态（Combine 发布）
    var connectionStateSubject: CurrentValueSubject<ConnectionState, Never> { get }

    /// 收到的原始字节流
    var receivedDataSubject: PassthroughSubject<Data, Never> { get }

    /// 扫描结果列表
    var discoveredDevicesSubject: CurrentValueSubject<[ScannedDevice], Never> { get }

    /// 传输就绪回调：连接且特征/通道就绪后可发送
    var onReady: (() -> Void)? { get set }

    /// 非主动断连回调：连接意外断开时触发（用于自动重连）
    var onUnexpectedDisconnect: (() -> Void)? { get set }

    func scan()
    func stopScan()
    func connect(to device: ScannedDevice)
    func disconnect()
    func send(data: Data)
}
