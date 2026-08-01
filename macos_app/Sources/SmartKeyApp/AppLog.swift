//
//  AppLog.swift
//  简单文件日志，调试用（写到 ~/Library/Logs/SmartKeyHost/)
//
import Foundation

enum AppLog {
    private static let fileURL: URL = {
        let dir = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Logs", isDirectory: true)
            .appendingPathComponent("SmartKeyHost", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("host.log")
    }()

    private static let lock = NSLock()

    static func log(_ message: String) {
        lock.lock()
        defer { lock.unlock() }
        let ts = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        let line = "[\(ts)] \(message)\n"
        guard let data = line.data(using: .utf8) else { return }
        // 追加写，文件不存在则创建
        if !FileManager.default.fileExists(atPath: fileURL.path) {
            try? data.write(to: fileURL)
            return
        }
        guard let handle = try? FileHandle(forWritingTo: fileURL) else { return }
        defer { try? handle.close() }
        handle.seekToEndOfFile()
        handle.write(data)
    }
}
