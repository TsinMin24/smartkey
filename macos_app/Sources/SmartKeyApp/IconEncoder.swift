//
//  IconEncoder.swift
//  提取 macOS App 图标 → 48×48 RGB565 像素数据
//
import AppKit
import CoreGraphics

enum IconEncoder {
    private static let size = 48

    /// 从 .app 路径提取图标，输出 RGB565 原始字节（48×48×2 = 4608B）
    static func encode(appPath: String) -> Data? {
        guard let appUrl = URL(string: "file://\(appPath)"),
              let img = NSWorkspace.shared.icon(forFile: appUrl.path).cgImage(
                  forProposedRect: nil, context: nil, hints: nil
              ) else {
            return fallbackIcon()
        }
        return renderToRGB565(cgImage: img)
    }

    /// 渲染 CGImage → 48×48 RGB565
    private static func renderToRGB565(cgImage: CGImage) -> Data? {
        let w = size, h = size
        guard let ctx = CGContext(
            data: nil, width: w, height: h,
            bitsPerComponent: 8, bytesPerRow: w * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return nil }

        ctx.interpolationQuality = .high
        ctx.draw(cgImage, in: CGRect(x: 0, y: 0, width: w, height: h))

        guard let data = ctx.data else { return nil }
        let pixels = data.bindMemory(to: UInt8.self, capacity: w * h * 4)

        var rgb565 = Data(capacity: w * h * 2)
        var buf = [UInt8](repeating: 0, count: 2)
        for i in 0..<(w * h) {
            let off = i * 4
            let r = pixels[off]
            let g = pixels[off + 1]
            let b = pixels[off + 2]
            let c = UInt16(r >> 3) << 11 | UInt16(g >> 2) << 5 | UInt16(b >> 3)
            buf[0] = UInt8(c >> 8)
            buf[1] = UInt8(c & 0xFF)
            rgb565.append(contentsOf: buf)
        }
        return rgb565
    }

    /// 兜底图标：灰色背景 + 白色方块（图标提取失败时用）
    private static func fallbackIcon() -> Data {
        let bg = UInt16(0x2104)   // 深灰 RGB565
        let fg = UInt16(0xFFFF)   // 白色
        let m = 8  // 内边距
        var data = Data(capacity: size * size * 2)
        for y in 0..<size {
            for x in 0..<size {
                let c = (x >= m && x < size - m && y >= m && y < size - m) ? fg : bg
                data.append(UInt8(c >> 8))
                data.append(UInt8(c & 0xFF))
            }
        }
        return data
    }
}
