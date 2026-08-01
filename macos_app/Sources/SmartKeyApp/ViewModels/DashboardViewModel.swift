//
//  DashboardViewModel.swift
//  业务逻辑与状态机 —— 监听传输层，解析协议，维护 UI 状态
//
import Foundation
import Combine

/// 已保存的 BLE 设备信息
struct SavedDevice: Codable {
    let name: String
    let identifier: String   // CBPeripheral.identifier UUID string
    let savedAt: Date
}

/// BLE 连接配置（持久化）
struct BLEConfig: Codable {
    var device: SavedDevice?
    var autoConnect: Bool = false
}

/// UI 状态（由 ViewModel 驱动，View 只读）
final class DashboardViewModel: ObservableObject {
    // MARK: - Published（驱动 SwiftUI）
    @Published var connectionState: ConnectionState = .idle
    @Published var devices: [ScannedDevice] = []
    @Published var isScanning = false
    @Published var logs: [String] = []
    @Published var slots: [SlotAction] = SlotAction.defaults() {
        didSet { persistSlots() }
    }
    @Published var savedDevice: SavedDevice? = nil
    @Published var autoConnect: Bool = false {
        didSet { persistBLEConfig() }
    }

    // MARK: - 依赖
    let transport: DeviceTransportProtocol
    private let decoder = FrameDecoder()
    private let engine = ActionEngine()
    private var cancellables = Set<AnyCancellable>()
    private let configDir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
        .first!.appendingPathComponent("SmartKeyHost", isDirectory: true)
    private var slotsURL: URL { configDir.appendingPathComponent("slots.json") }
    private var bleConfigURL: URL { configDir.appendingPathComponent("ble_config.json") }
    private var lastConnectedDevice: ScannedDevice?

    init(transport: DeviceTransportProtocol = BLEManager()) {
        self.transport = transport
        loadSlots()
        loadBLEConfig()
        engine.setActions(slots)
        bindTransport()
        // 启动后自动连接（如果启用且有保存的设备）
        if autoConnect, savedDevice != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                self.scanDevices()
                DispatchQueue.main.asyncAfter(deadline: .now() + 10.0) {
                    self.autoConnectIfPossible()
                }
            }
        }
    }

    // MARK: - BLE 配置持久化
    private func loadBLEConfig() {
        guard let data = try? Data(contentsOf: bleConfigURL),
              let cfg = try? JSONDecoder().decode(BLEConfig.self, from: data) else { return }
        savedDevice = cfg.device
        autoConnect = cfg.autoConnect
    }

    private func persistBLEConfig() {
        try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
        let cfg = BLEConfig(device: savedDevice, autoConnect: autoConnect)
        if let data = try? JSONEncoder().encode(cfg) {
            try? data.write(to: bleConfigURL)
        }
    }

    /// 扫描完成后尝试自动连接已保存设备
    private func autoConnectIfPossible() {
        guard let saved = savedDevice else { return }
        // 在扫描结果里找已保存的设备（按名称匹配，identifier 跨重启会变）
        if let target = devices.first(where: { $0.name == saved.name }) {
            appendLog("自动连接 \(saved.name)…")
            connect(to: target)
        } else {
            appendLog("未找到已保存设备 \(saved.name)")
        }
    }

    // MARK: - 槽位配置持久化
    private func loadSlots() {
        guard let data = try? Data(contentsOf: slotsURL),
              let decoded = try? JSONDecoder().decode([SlotAction].self, from: data),
              decoded.count == 5 else {
            slots = SlotAction.defaults()
            return
        }
        slots = decoded
    }

    private func persistSlots() {
        try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
        if let data = try? JSONEncoder().encode(slots) {
            try? data.write(to: slotsURL)
        }
    }

    // MARK: - 绑定传输层
    private func bindTransport() {
        transport.connectionStateSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                self?.connectionState = state
                switch state {
                case .connected:
                    self?.appendLog("✅ 已连接")
                    AppLog.log("ViewModel: 已连接")
                    self?.onConnected()
                case .error(let msg):
                    self?.appendLog("❌ \(msg)")
                    AppLog.log("ViewModel: 错误 \(msg)")
                case .idle:
                    self?.appendLog("连接断开")
                default:
                    break
                }
            }
            .store(in: &cancellables)

        transport.discoveredDevicesSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] devices in
                self?.devices = devices
            }
            .store(in: &cancellables)

        transport.receivedDataSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] data in
                self?.handleReceived(data)
            }
            .store(in: &cancellables)
    }

    /// 连接成功后：保存设备 + 推送槽位
    private func onConnected() {
        if let device = lastConnectedDevice {
            let saved = SavedDevice(name: device.name, identifier: device.id.uuidString, savedAt: Date())
            savedDevice = saved
            persistBLEConfig()
            appendLog("已记住设备 \(device.name)")
        }
        syncSlotsToBoard()
    }

    // MARK: - 接收数据处理
    private func handleReceived(_ data: Data) {
        let commands = decoder.appendAndDecode(data)
        for cmd in commands {
            switch cmd {
            case .keyDown(let slot):
                appendLog("🔽 按键\(slot) 按下")
                engine.onKeyDown(slot: slot)
            case .keyUp(let slot):
                appendLog("🔼 按键\(slot) 释放")
                engine.onKeyUp(slot: slot)
            case .pong:
                appendLog("PONG 响应正常")
            case .unknown(let line):
                appendLog("收到: \(line)")
            }
        }
    }

    // MARK: - 用户动作
    func scanDevices() {
        appendLog("开始扫描…")
        isScanning = true
        transport.scan()
        // 12 秒后停止扫描
        DispatchQueue.main.asyncAfter(deadline: .now() + 12.0) { [weak self] in
            self?.isScanning = false
        }
    }

    func stopScan() {
        transport.stopScan()
        isScanning = false
    }

    func connect(to device: ScannedDevice) {
        appendLog("连接 \(device.name)…")
        lastConnectedDevice = device
        transport.connect(to: device)
    }

    func disconnect() {
        transport.disconnect()
        appendLog("已断开")
    }

    func toggleAutoConnect() {
        autoConnect.toggle()
    }

    func clearSavedDevice() {
        savedDevice = nil
        autoConnect = false
        persistBLEConfig()
        appendLog("已清除已保存设备")
    }

    func updateSlotName(_ slot: SlotAction, name: String) {
        if let idx = slots.firstIndex(where: { $0.id == slot.id }) {
            slots[idx].name = name
        }
        engine.setActions(slots)
        if case .connected = connectionState {
            transport.send(data: HostCommand.slot(slot.id, name: name))
        }
    }

    func updateSlotMode(_ slot: SlotAction, mode: String, keyCode: Int?, appPath: String?) {
        if let idx = slots.firstIndex(where: { $0.id == slot.id }) {
            slots[idx].mode = mode
            slots[idx].keyCode = keyCode
            slots[idx].appPath = appPath
        }
        engine.setActions(slots)
    }

    /// 连接后把槽位名称推给板子屏幕
    private func syncSlotsToBoard() {
        for slot in slots {
            transport.send(data: HostCommand.slot(slot.id, name: slot.name))
            Thread.sleep(forTimeInterval: 0.05)
        }
        transport.send(data: HostCommand.status(hex: "00FF00"))
        appendLog("已推送槽位配置到板子")
        // 连接后推送所有 App 模式槽位的图标
        syncIconsToBoard()
    }

    /// 提取并发送 App 图标到板子（slot=1~5）
    func sendSlotIcon(slotId: Int, appPath: String) {
        guard case .connected = connectionState else {
            appendLog("⚠️ 未连接，跳过图标发送")
            return
        }
        guard let rgb565 = IconEncoder.encode(appPath: appPath) else {
            appendLog("❌ 图标提取失败")
            return
        }
        let msg = HostCommand.iconMessage(slot: slotId, rgb565: rgb565)
        appendLog("📤 发送图标到 slot \(slotId)（\(rgb565.count)B RGB565）")
        transport.send(data: msg)
    }

    /// 连接后同步所有 App 槽位图标到板子
    private func syncIconsToBoard() {
        for slot in slots where slot.mode == "app" {
            if let path = slot.appPath, !path.isEmpty {
                Thread.sleep(forTimeInterval: 0.2)
                sendSlotIcon(slotId: slot.id, appPath: path)
            }
        }
    }

    // MARK: - 日志
    private func appendLog(_ text: String) {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        let ts = formatter.string(from: Date())
        let line = "[\(ts)] \(text)"
        DispatchQueue.main.async {
            self.logs.append(line)
            if self.logs.count > 500 { self.logs.removeFirst(self.logs.count - 500) }
        }
    }
}
