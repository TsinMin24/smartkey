//
//  ActionEngine.swift
//  按键动作引擎 —— 把板子的按键事件翻译成 macOS 系统操作
//  每个槽位可配置：模拟功能键 / 打开指定 app
//
import Foundation
import AppKit
import Carbon.HIToolbox

// macOS 功能键虚拟键码
enum FunctionKey {
    static let F13: CGKeyCode = 0x69
    static let F14: CGKeyCode = 0x6B
    static let F15: CGKeyCode = 0x71
    static let F16: CGKeyCode = 0x6A
    static let F17: CGKeyCode = 0x40
    static let F18: CGKeyCode = 0x4F
    static let F19: CGKeyCode = 0x50
    static let F20: CGKeyCode = 0x5A
}

/// 按键动作配置
struct SlotAction: Codable, Identifiable {
    var id: Int
    var name: String
    var mode: String       // "key" / "app" / "none"
    var keyCode: Int?
    var appPath: String?

    static func defaults() -> [SlotAction] {
        [
            SlotAction(id: 1, name: "功能键 F13", mode: "key", keyCode: Int(FunctionKey.F13), appPath: nil),
            SlotAction(id: 2, name: "功能键 F16", mode: "key", keyCode: Int(FunctionKey.F16), appPath: nil),
            SlotAction(id: 3, name: "功能键 F17", mode: "key", keyCode: Int(FunctionKey.F17), appPath: nil),
            SlotAction(id: 4, name: "功能键 F18", mode: "key", keyCode: Int(FunctionKey.F18), appPath: nil),
            SlotAction(id: 5, name: "功能键 F19", mode: "key", keyCode: Int(FunctionKey.F19), appPath: nil),
        ]
    }
}

/// 动作引擎
final class ActionEngine {
    private var actions: [Int: SlotAction] = [:]
    private var heldKeys: [Int: CGKeyCode] = [:]

    init(actions: [SlotAction] = SlotAction.defaults()) {
        setActions(actions)
    }

    func setActions(_ actions: [SlotAction]) {
        self.actions = Dictionary(uniqueKeysWithValues: actions.map { ($0.id, $0) })
    }

    func onKeyDown(slot: Int) {
        guard let action = actions[slot] else { return }
        switch action.mode {
        case "key":
            if let code = action.keyCode {
                let cgCode = CGKeyCode(code)
                simulateKey(cgCode, down: true)
                heldKeys[slot] = cgCode
            }
        case "app":
            if let path = action.appPath, !path.isEmpty {
                toggleApp(path: path)
            }
        default:
            break
        }
    }

    func onKeyUp(slot: Int) {
        if let code = heldKeys.removeValue(forKey: slot) {
            simulateKey(CGKeyCode(code), down: false)
        }
    }

    // MARK: - 功能键模拟
    private func simulateKey(_ keyCode: CGKeyCode, down: Bool) {
        let src = CGEventSource(stateID: .hidSystemState)
        let evt = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: down)
        evt?.post(tap: .cghidEventTap)
    }

    // MARK: - App 切换
    //
    //   判断依据：当前前台 app 是不是目标 app
    //   - 前台是目标 app → 隐藏
    //   - 前台不是目标 app（包括：后台、隐藏、最小化、被其他 app 盖住）→ 前置 + 还原最小化
    //   - 未运行 → 启动
    //
    private func toggleApp(path: String) {
        guard let app = resolveApp(path) else {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
            p.arguments = [path]
            try? p.run()
            return
        }

        let running = NSRunningApplication.runningApplications(
            withBundleIdentifier: app.bundleId ?? ""
        ).first

        // 未运行 → 启动
        if running == nil {
            NSWorkspace.shared.openApplication(
                at: app.url, configuration: .init(), completionHandler: nil)
            AppLog.log("启动 \(app.name)")
            return
        }

        // 关键判断：目标 app 是不是当前前台 app
        let frontmostPID = NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0
        let isTargetFront = (frontmostPID == running!.processIdentifier)

        if isTargetFront {
            // 目标在前台 → 隐藏
            running!.hide()
            AppLog.log("隐藏 \(app.name)")
        } else {
            // 目标不在前台（后台/隐藏/最小化/被其他 app 盖住）→ 前置 + 还原最小化
            let name = app.name.replacingOccurrences(of: "\"", with: "\\\"")
            let script = """
            tell application "\(name)" to activate
            tell application "System Events"
                tell process "\(name)"
                    repeat with w in windows
                        try
                            if value of attribute "AXMinimized" of w is true then
                                set value of attribute "AXMinimized" of w to false
                            end if
                        end try
                    end repeat
                end tell
            end tell
            """
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            p.arguments = ["-e", script]
            do { try p.run(); p.waitUntilExit() } catch {}
            AppLog.log("前置 \(app.name)")
        }
    }

    private func resolveApp(_ pathOrID: String) -> (name: String, url: URL, bundleId: String?)? {
        let url: URL?
        if pathOrID.hasSuffix(".app") {
            url = URL(fileURLWithPath: pathOrID)
        } else {
            url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: pathOrID)
        }
        guard let url = url else { return nil }
        let name = url.deletingPathExtension().lastPathComponent
        let bid = Bundle(url: url)?.bundleIdentifier
        return (name, url, bid)
    }
}
