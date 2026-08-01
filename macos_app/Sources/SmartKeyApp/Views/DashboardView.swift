//
//  DashboardView.swift
//  SwiftUI 视图层 —— 只做数据渲染与交互，不含任何协议逻辑
//
import SwiftUI

struct DashboardView: View {
    @StateObject private var viewModel = DashboardViewModel()

    var body: some View {
        VStack(spacing: 12) {
            HeaderBar(viewModel: viewModel)
            DeviceListSection(viewModel: viewModel)
            SlotConfigSection(viewModel: viewModel)
            LogTerminal(logs: viewModel.logs)
        }
        .padding()
        .frame(minWidth: 560, minHeight: 620)
        .onAppear { viewModel.scanDevices() }
    }
}

// MARK: - 顶部状态条
struct HeaderBar: View {
    @ObservedObject var viewModel: DashboardViewModel

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(statusColor)
                .frame(width: 12, height: 12)
            Text(statusText)
                .font(.headline)
                .textSelection(.enabled)
            Spacer()
            if case .connected = viewModel.connectionState {
                Button("断开") { viewModel.disconnect() }
            } else {
                Button(viewModel.isScanning ? "扫描中…" : "重新扫描") {
                    viewModel.scanDevices()
                }
                .disabled(viewModel.isScanning)
            }
        }
        .padding(10)
        .background(Color(nsColor: .windowBackgroundColor))
        .cornerRadius(8)
    }

    private var statusColor: Color {
        switch viewModel.connectionState {
        case .connected: return .green
        case .scanning, .connecting: return .orange
        case .error: return .red
        default: return .gray
        }
    }

    private var statusText: String {
        switch viewModel.connectionState {
        case .idle: return "未连接"
        case .scanning: return "正在扫描…"
        case .connecting: return "正在连接…"
        case .connected: return "已连接"
        case .error(let msg): return "错误: \(msg)"
        }
    }
}

// MARK: - 设备列表（选择连接）
struct DeviceListSection: View {
    @ObservedObject var viewModel: DashboardViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // 自动连接开关 + 已保存设备
            HStack {
                Toggle("自动连接", isOn: $viewModel.autoConnect)
                    .font(.caption)
                    .toggleStyle(.switch)
                    .labelsHidden()
                Text("自动连接")
                    .font(.caption)
                Spacer()
                if let saved = viewModel.savedDevice {
                    HStack(spacing: 4) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                            .font(.caption)
                        Text("已记住: \(saved.name)")
                            .font(.caption)
                            .lineLimit(1)
                            .textSelection(.enabled)
                        Button(action: { viewModel.clearSavedDevice() }) {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundColor(.secondary)
                        }
                        .buttonStyle(.plain)
                        .font(.caption)
                    }
                }
            }
            Text("设备列表（点选连接）")
                .font(.caption)
                .foregroundColor(.secondary)
            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(viewModel.devices) { device in
                        Button {
                            viewModel.connect(to: device)
                        } label: {
                            HStack {
                                Text(device.isUartService ? "🔷" : "  ")
                                Text(device.name)
                                    .lineLimit(1)
                                    .textSelection(.enabled)
                                // 已保存标记
                                if let saved = viewModel.savedDevice,
                                   saved.name == device.name {
                                    Image(systemName: "bookmark.fill")
                                        .foregroundColor(.orange)
                                        .font(.caption2)
                                }
                                Spacer()
                                Text("\(device.rssi)")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                                    .textSelection(.enabled)
                            }
                            .padding(6)
                            .background(Color(nsColor: .controlBackgroundColor))
                            .cornerRadius(6)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .frame(height: 130)
        }
        .padding(10)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.5))
        .cornerRadius(8)
    }
}

// MARK: - 槽位配置
struct SlotConfigSection: View {
    @ObservedObject var viewModel: DashboardViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("按键配置（默认 F13/F16/F17/F18/F19，可改为打开指定 App）")
                .font(.caption)
                .foregroundColor(.secondary)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 5), spacing: 8) {
                ForEach($viewModel.slots) { $slot in
                    SlotCard(slot: $slot, onUpdate: {
                        viewModel.updateSlotMode(slot, mode: slot.mode,
                                                 keyCode: slot.keyCode,
                                                 appPath: slot.appPath)
                    })
                }
            }
        }
        .padding(10)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.5))
        .cornerRadius(8)
    }
}

/// 单个槽位卡片：模式选择 + 名称 + 参数
struct SlotCard: View {
    @Binding var slot: SlotAction
    var onUpdate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("键 \(slot.id)")
                .font(.caption2)
                .foregroundColor(.secondary)
                .textSelection(.enabled)
            // 模式选择：功能键 / 打开App / 无
            Picker("", selection: $slot.mode) {
                Text("功能键").tag("key")
                Text("打开App").tag("app")
                Text("无").tag("none")
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .onChange(of: slot.mode) { _ in onUpdate() }
            TextField("名称", text: $slot.name)
                .textFieldStyle(.roundedBorder)
                .font(.caption)
                .onChange(of: slot.name) { _ in onUpdate() }
            if slot.mode == "key" {
                // 功能键选择
                Picker("", selection: Binding(
                    get: { slot.keyCode ?? 0 },
                    set: { slot.keyCode = $0; onUpdate() }
                )) {
                    Text("F13").tag(Int(FunctionKey.F13))
                    Text("F16").tag(Int(FunctionKey.F16))
                    Text("F17").tag(Int(FunctionKey.F17))
                    Text("F18").tag(Int(FunctionKey.F18))
                    Text("F19").tag(Int(FunctionKey.F19))
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .font(.caption)
            } else if slot.mode == "app" {
                let appPath = slot.appPath ?? ""
                HStack(spacing: 4) {
                    Text(appPath.isEmpty ? "未选择" : URL(fileURLWithPath: appPath).lastPathComponent)
                        .font(.caption)
                        .lineLimit(1)
                        .foregroundColor(appPath.isEmpty ? .secondary : .primary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Button("选择 App…") {
                        chooseApp { path in
                            slot.appPath = path
                            onUpdate()
                        }
                    }
                    .font(.caption)
                }
                if !appPath.isEmpty {
                    Button("清除选择") {
                        slot.appPath = nil
                        onUpdate()
                    }
                    .font(.caption2)
                    .foregroundColor(.red)
                }
            }
        }
        .padding(8)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(8)
    }

    /// 弹系统面板选择 .app，返回路径
    private func chooseApp(completion: @escaping (String) -> Void) {
        let panel = NSOpenPanel()
        panel.title = "选择应用"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.application]
        panel.directoryURL = URL(fileURLWithPath: "/Applications")
        panel.begin { response in
            if response == .OK, let url = panel.url {
                completion(url.path)
            }
        }
    }
}

// MARK: - 通信日志终端（可选中可复制）
struct LogTerminal: View {
    let logs: [String]
    @State private var logText: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("通信日志")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Button("复制全部") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(logText, forType: .string)
                }
                .font(.caption)
            }
            // TextEditor 原生支持选中 + 复制
            TextEditor(text: $logText)
                .font(.system(.caption, design: .monospaced))
                .foregroundColor(.green)
                .scrollContentBackground(.hidden)  // 显示自定义背景
                .background(Color.black.opacity(0.85))
                .frame(maxHeight: .infinity)
        }
        .padding(8)
        .background(Color.black.opacity(0.85))
        .foregroundColor(.green)
        .cornerRadius(8)
        .onAppear {
            logText = logs.joined(separator: "\n")
        }
        .onChange(of: logs) { newLogs in
            logText = newLogs.joined(separator: "\n")
        }
    }
}

// MARK: - App 入口
@main
struct SmartKeyApp: App {
    var body: some Scene {
        WindowGroup {
            DashboardView()
        }
        .windowResizability(.contentSize)
    }
}
