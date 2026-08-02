//
//  DashboardViewModel.swift
//  业务逻辑与状态机 —— 监听传输层，解析协议，维护 UI 状态
//
import Foundation
import Combine
import AppKit

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
    @Published var iconPreviews: [Int: NSImage] = [:]

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
    /// 自动重连计时器
    private var reconnectTimer: Timer?
    /// 是否正在自动重连流程中（避免重复触发）
    private var isAutoReconnecting = false
    /// 上次日志提示时间（避免刷屏）
    private var lastAutoLogTime: Date?
    /// 目标设备名（已保存的）
    private var autoTargetName: String?
    /// 连续重连次数（用于指数退避，连接成功后重置）
    private var reconnectAttempts = 0

    init(transport: DeviceTransportProtocol = BLEManager()) {
        self.transport = transport
        loadSlots()
        loadBLEConfig()
        engine.setActions(slots)
        generateIconPreviews()
        bindTransport()
        // 启动后自动连接（如果启用且有保存的设备）
        if autoConnect, savedDevice != nil {
            autoTargetName = savedDevice?.name
            // 立即扫描 + 调度重连（只要没连上就持续重试）
            transport.scan()
            scheduleReconnect()
        }
    }

    // MARK: - 自动连接机制
    /// 停止自动扫描
    private func stopAutoScan() {
        reconnectTimer?.invalidate()
        reconnectTimer = nil
        isAutoReconnecting = false
        transport.stopScan()
    }

    /// 意外断开后自动重连
    private func handleUnexpectedDisconnect() {
        guard autoConnect, savedDevice != nil else { return }
        appendLog("🔄 连接意外断开，自动重连…")
        scheduleReconnect()
    }

    /// 用户主动断开后停止自动重连
    private func handleUserDisconnect() {
        stopAutoScan()
    }

    /// 只要用户想连接（自动连接开启或手动点过），任何非连接状态都持续重试
    private var userWantsConnection: Bool {
        autoConnect && savedDevice != nil
    }

    /// 调度一次重连（延迟递增，避免骚扰蓝牙栈）。连接失败后越来越慢。
    private func scheduleReconnect() {
        guard userWantsConnection else { return }
        // 正在连接/已连接则不重复调度
        if case .connected = connectionState { return }
        if case .connecting = connectionState { return }
        // 已有定时器在跑就不重复创建
        if reconnectTimer?.isValid == true { return }

        // 指数退避：2s → 4s → 8s → 16s → 30s 封顶
        reconnectAttempts += 1
        let delay = min(pow(2.0, Double(reconnectAttempts - 1)) * 2.0, 30.0)

        reconnectTimer?.invalidate()
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            self.reconnectTimer = nil
            guard self.userWantsConnection else { return }
            if case .connected = self.connectionState { return }
            if case .connecting = self.connectionState { return }
            // 从扫描结果找目标，找到就连接
            if let targetName = self.autoTargetName,
               let target = self.devices.first(where: { $0.name == targetName }) {
                self.appendLog("🔄 重连 \(targetName)（第\(self.reconnectAttempts)次）…")
                self.connect(to: target)
            } else {
                // 没找到 → 重新扫描，下一轮再试
                self.transport.scan()
                self.scheduleReconnect()
            }
        }
        // 确保扫描在跑（BLEManager.scan 幂等，会先停止再开始）
        transport.scan()
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
        transport.onReady = { [weak self] in
            // 特征就绪后才同步，避免发送失败
            self?.syncSlotsToBoard()
        }
        transport.onUnexpectedDisconnect = { [weak self] in
            self?.handleUnexpectedDisconnect()
        }
        transport.connectionStateSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                self?.connectionState = state
                switch state {
                case .connected:
                    self?.appendLog("✅ 已连接")
                    AppLog.log("ViewModel: 已连接")
                    self?.onConnected()
                    self?.reconnectAttempts = 0   // 连接成功，重置退避计数
                case .error(let msg):
                    self?.appendLog("❌ \(msg)")
                    AppLog.log("ViewModel: 错误 \(msg)")
                    // 连接失败（加密/超时等）→ 自动重连
                    self?.scheduleReconnect()
                case .idle:
                    self?.appendLog("连接断开")
                    // 只要用户想连接且没连上，就自动重连
                    self?.scheduleReconnect()
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
        // 特征就绪后由 transport.onReady 触发 syncSlotsToBoard
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
        autoTargetName = device.name   // 记住目标，便于失败后重连
        transport.connect(to: device)
    }

    func disconnect() {
        handleUserDisconnect()   // 停止自动重连流程（用户主动断开）
        transport.disconnect()
        appendLog("已断开")
    }

    func toggleAutoConnect() {
        autoConnect.toggle()
        if autoConnect {
            // 打开自动连接：若已保存设备，启动自动连接流程
            if savedDevice != nil {
                autoTargetName = savedDevice?.name
                appendLog("🔄 自动连接已开启，寻找 \(savedDevice?.name ?? "设备")…")
                transport.scan()
                scheduleReconnect()
            }
        } else {
            // 关闭自动连接：停止流程
            stopAutoScan()
            reconnectTimer?.invalidate()
            reconnectTimer = nil
        }
    }

    func clearSavedDevice() {
        savedDevice = nil
        autoConnect = false
        persistBLEConfig()
        stopAutoScan()
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
        generateIconPreviews()
    }

    // MARK: - 图标预览
    func generateIconPreviews() {
        var previews: [Int: NSImage] = [:]
        for slot in slots {
            let rgbData: Data?
            if slot.mode == "app", let path = slot.appPath, !path.isEmpty {
                rgbData = IconEncoder.encode(appPath: path)
            } else {
                rgbData = IconEncoder.keyIcon()
            }
            if let data = rgbData {
                previews[slot.id] = Self.rgbToNSImage(data)
            }
        }
        iconPreviews = previews
    }

    /// RGB565 原始数据 → NSImage（用于 UI 预览）
    private static func rgbToNSImage(_ data: Data) -> NSImage {
        let s = IconEncoder.size
        let bmp = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: s, pixelsHigh: s,
                                   bitsPerSample: 8, samplesPerPixel: 3,
                                   hasAlpha: false, isPlanar: false,
                                   colorSpaceName: .deviceRGB,
                                   bytesPerRow: s * 3, bitsPerPixel: 24)!
        let px = bmp.bitmapData!
        for i in 0..<(s * s) {
            let c = UInt16(data[i*2]) | UInt16(data[i*2+1]) << 8
            let off = i * 3
            px[off]     = UInt8(((c >> 11) & 0x1F) << 3)
            px[off + 1] = UInt8(((c >> 5) & 0x3F) << 2)
            px[off + 2] = UInt8((c & 0x1F) << 3)
        }
        let img = NSImage(size: NSSize(width: s, height: s))
        img.addRepresentation(bmp)
        return img
    }

    // MARK: - 手动推送图标（USB MSC：全色 RGB565）
    /// 推送单个槽位图标到板子
    func pushSlotIcon(_ slot: SlotAction) {
        let ok = writeIconFile(slot.id)
        if ok, case .connected = connectionState {
            transport.send(data: Data("REFRESH\n".utf8))
            appendLog("📤 已发送 REFRESH")
        }
    }

    /// 一键推送全部 5 个槽位图标到板子
    func pushAllIcons() {
        appendLog("⬆️ 一键推送全部图标…")
        var allOK = true
        for slot in slots {
            if !writeIconFile(slot.id) { allOK = false }
        }
        if allOK {
            appendLog("✅ 全部图标已写入")
        } else {
            appendLog("⚠️ 部分图标写入失败")
        }
        if case .connected = connectionState {
            transport.send(data: Data("REFRESH\n".utf8))
            appendLog("📤 已发送 REFRESH")
        }
    }

    /// 生成并写入单个槽位图标 .bin 到 CIRCUITPY 卷，返回是否成功
    private func writeIconFile(_ slotId: Int) -> Bool {
        guard let slot = slots.first(where: { $0.id == slotId }) else { return false }
        let rgbData: Data?
        if slot.mode == "app", let path = slot.appPath, !path.isEmpty {
            rgbData = IconEncoder.encode(appPath: path)
        } else {
            rgbData = IconEncoder.keyIcon()
        }
        guard let data = rgbData else {
            appendLog("❌ slot\(slotId) 图标生成失败")
            return false
        }
        let volumes = FileManager.default.mountedVolumeURLs(includingResourceValuesForKeys: nil)
        let circuiTPY = volumes?.first(where: { $0.lastPathComponent == "CIRCUITPY" })
        guard let vol = circuiTPY else {
            appendLog("❌ 未找到 CIRCUITPY 卷")
            return false
        }
        let fileName = "icon_\(slotId).bin"
        let dest = vol.appendingPathComponent(fileName)
        do {
            try data.write(to: dest)
            appendLog("  ✅ \(fileName) 已写入（\(data.count)B 全色RGB565）")
            return true
        } catch {
            appendLog("  ❌ \(fileName) 写入失败: \(error.localizedDescription)")
            return false
        }
    }

    /// 连接后把槽位名称推给板子屏幕（图标由用户手动推送）
    private func syncSlotsToBoard() {
        let slots = self.slots
        for (idx, slot) in slots.enumerated() {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(idx) * 0.05) { [weak self] in
                self?.transport.send(data: HostCommand.slot(slot.id, name: slot.name))
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + Double(slots.count) * 0.05) { [weak self] in
            self?.transport.send(data: HostCommand.status(hex: "00FF00"))
            self?.appendLog("已推送槽位名称到板子（图标请点击推送到板子）")
        }
    }

    // MARK: - 日志
    func clearLogs() {
        DispatchQueue.main.async {
            self.logs.removeAll()
        }
    }

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
