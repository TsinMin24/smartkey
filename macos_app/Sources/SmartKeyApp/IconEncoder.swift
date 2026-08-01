//
//  IconEncoder.swift
//  提取 macOS App 图标 → 24×24 2色掩码（1bit/像素）+ 前景/背景色
//  数据量极小：掩码 72B + 头部约 60B = 一个 BLE 包传完，板子不卡死
//
import AppKit
import CoreGraphics

enum IconEncoder {
    // 24x24 正方形，2色掩码（1bit/像素），完美嵌入板子 36x36 槽位
    static let size = 24

    /// 提取 App 图标 → (前景RGB565, 背景RGB565, 掩码数据)
    /// 掩码: 1bit/像素, 行优先, MSB first, 1=前景logo色
    static func encode(appPath: String) -> (fg565: UInt16, bg565: UInt16, mask: Data)? {
        guard let appUrl = URL(string: "file://\(appPath)"),
              let img = NSWorkspace.shared.icon(forFile: appUrl.path).cgImage(
                  forProposedRect: nil, context: nil, hints: nil
              ) else {
            return fallbackIcon()
        }
        return renderToMask(cgImage: img)
    }

    /// 渲染 CGImage → 24×24, 提取主色 + 掩码
    private static func renderToMask(cgImage: CGImage) -> (fg565: UInt16, bg565: UInt16, mask: Data)? {
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

        // 收集非透明像素的平均色作为前景(logo)主色
        var rSum = 0.0, gSum = 0.0, bSum = 0.0
        var count = 0
        for i in 0..<(w * h) {
            let off = i * 4
            let a = pixels[off + 3]
            if a > 32 {
                rSum += Double(pixels[off])
                gSum += Double(pixels[off + 1])
                bSum += Double(pixels[off + 2])
                count += 1
            }
        }
        // 前景色：非透明像素的平均色；背景色：固定深灰（槽位底色 RGB565）
        var fg = UInt16(0xFFFF)
        if count > 0 {
            let r = Int(rSum / Double(count))
            let g = Int(gSum / Double(count))
            let b = Int(bSum / Double(count))
            fg = UInt16(r >> 3) << 11 | UInt16(g >> 2) << 5 | UInt16(b >> 3)
        }
        let bg: UInt16 = 0x1A1A   // 深灰 RGB(0x1A,0x1A,0x1A) → 与槽位底色一致

        // 构建掩码：与平均色接近的像素 → 前景(1)，否则背景(0)
        let fgR = (fg >> 11) & 0x1F, fgG = (fg >> 5) & 0x3F, fgB = fg & 0x1F
        var mask = Data(capacity: (w * h + 7) / 8)
        var byte: UInt8 = 0
        var bit = 0
        for i in 0..<(w * h) {
            let off = i * 4
            let r = (pixels[off] >> 3), g = (pixels[off + 1] >> 2), b = (pixels[off + 2] >> 3)
            // 距离前景色主色在阈值内 → logo 像素
            let dr = abs(Int(r) - Int(fgR))
            let dg = abs(Int(g) - Int(fgG))
            let db = abs(Int(b) - Int(fgB))
            let alpha = pixels[off + 3]
            let isFg = (dr + dg + db < 18) && alpha > 64   // 色差阈值 + 不透明
            byte = (byte << 1) | (isFg ? 1 : 0)
            bit += 1
            if bit == 8 {
                mask.append(byte)
                byte = 0
                bit = 0
            }
        }
        if bit > 0 {
            mask.append(byte << (8 - bit))
        }
        return (fg, bg, mask)
    }

    /// 兜底图标：白色方块 + 深灰底
    private static func fallbackIcon() -> (fg565: UInt16, bg565: UInt16, mask: Data) {
        let fg = UInt16(0xFFFF)
        let bg = UInt16(0x1A1A) // 仅占位，实际背景同槽位
        let m = 8  // 内边距
        var mask = Data(capacity: (size * size + 7) / 8)
        var byte: UInt8 = 0
        var bit = 0
        for y in 0..<size {
            for x in 0..<size {
                let isFg = (x >= m && x < size - m && y >= m && y < size - m)
                byte = (byte << 1) | (isFg ? 1 : 0)
                bit += 1
                if bit == 8 {
                    mask.append(byte)
                    byte = 0
                    bit = 0
                }
            }
        }
        if bit > 0 {
            mask.append(byte << (8 - bit))
        }
        return (fg, bg, mask)
    }
}
