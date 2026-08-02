// test_ft.swift —— 独立测试 FileTransfer 协议
import Foundation
import CoreBluetooth

let FT_SERVICE = CBUUID(string: "FEBB")
let FT_CHAR = CBUUID(string: "ADAF0200-4669-6C65-5472-616E73666572")

class Transfer: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    var central: CBCentralManager!
    var peripheral: CBPeripheral?
    var ftChar: CBCharacteristic?
    var iconData = Data()
    var written: UInt = 0
    var done = false

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func centralManagerDidUpdateState(_ c: CBCentralManager) {
        guard c.state == .poweredOn else { print("蓝牙未就绪"); return }
        print("扫描中...")
        c.scanForPeripherals(withServices: nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { c.stopScan() }
    }

    func centralManager(_ c: CBCentralManager, didDiscover p: CBPeripheral,
                        advertisementData: [String: Any], rssi: NSNumber) {
        let name = (advertisementData[CBAdvertisementDataLocalNameKey] as? String) ?? p.name ?? ""
        guard name == "SmartKey" else { return }
        print("找到 \(name)，连接中...")
        c.stopScan()
        peripheral = p
        p.delegate = self
        c.connect(p)
    }

    func centralManager(_ c: CBCentralManager, didConnect p: CBPeripheral) {
        print("已连接，发现服务...")
        p.discoverServices([FT_SERVICE])
    }

    func peripheral(_ p: CBPeripheral, didDiscoverServices e: Error?) {
        for svc in p.services ?? [] where svc.uuid == FT_SERVICE {
            print("发现 FileTransfer 服务")
            p.discoverCharacteristics([FT_CHAR], for: svc)
        }
    }

    func peripheral(_ p: CBPeripheral, didDiscoverCharacteristicsFor s: CBService, e: Error?) {
        for c in s.characteristics ?? [] where c.uuid == FT_CHAR {
            ftChar = c
            print("发现特征: \(c.uuid)")
            p.setNotifyValue(true, for: c)
            startTransfer()
        }
    }

    func startTransfer() {
        guard let char = ftChar, let p = peripheral else { return }
        let path = "icon_1.bin".data(using: .utf8)!
        let total = UInt32(iconData.count)
        let modTime = UInt64(Date().timeIntervalSince1970 * 1e9)

        var cmd = Data(count: 20 + path.count)
        cmd[0] = 0x20; cmd[1] = 0x00
        cmd[2] = UInt8(path.count & 0xFF); cmd[3] = UInt8(path.count >> 8)
        withUnsafeBytes(of: modTime.littleEndian) { r in for i in 0..<8 { cmd[8+i] = r[i] } }
        withUnsafeBytes(of: total.littleEndian) { r in for i in 0..<4 { cmd[16+i] = r[i] } }
        cmd.replaceSubrange(20..<(20+path.count), with: path)

        print("发送 WRITE (\(iconData.count)B)")
        p.writeValue(cmd, for: char, type: .withoutResponse)
    }

    func peripheral(_ p: CBPeripheral, didUpdateValueFor c: CBCharacteristic, e: Error?) {
        guard let data = c.value, data.count >= 2 else { return }
        let cmd = data[0], status = data[1]
        print("收到: cmd=0x\(String(cmd,radix:16)) status=\(status) len=\(data.count) hex=\(data.prefix(16).map{String(format:"%02X",$0)}.joined())")

        guard let char = ftChar, let p = peripheral else { return }

        if cmd == 0x21 && status == 0x01 {  // WRITE_PACING + OK
            if written >= UInt(iconData.count) {
                print("✅ 写入完成!")
                done = true
                central.cancelPeripheralConnection(p)
                return
            }
            let freeSpace: UInt = data.count >= 12 ? (UInt(data[8]) | UInt(data[9])<<8 | UInt(data[10])<<16 | UInt(data[11])<<24) : 490
            let chunkEnd = min(written + freeSpace, UInt(iconData.count))
            let chunk = iconData[Int(written)..<Int(chunkEnd)]

            var pkt = Data(count: 12 + chunk.count)
            pkt[0] = 0x22; pkt[1] = 0x01
            let off32 = UInt32(written)
            withUnsafeBytes(of: off32.littleEndian) { r in for i in 0..<4 { pkt[4+i] = r[i] } }
            let cl = UInt32(chunk.count)
            withUnsafeBytes(of: cl.littleEndian) { r in for i in 0..<4 { pkt[8+i] = r[i] } }
            pkt.replaceSubrange(12..<(12+chunk.count), with: chunk)

            print("发送 DATA \(written)..<\(chunkEnd) (\(chunk.count)B)")
            p.writeValue(pkt, for: char, type: .withoutResponse)
            written = chunkEnd
        } else {
            print("❌ 异常响应")
            done = true
        }
    }

    func centralManager(_ c: CBCentralManager, didDisconnectPeripheral p: CBPeripheral, error: Error?) {
        print("已断开")
        CFRunLoopStop(CFRunLoopGetMain())
    }
}

// 加载图标文件
let iconPath = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "firmware/icon_1.bin"
let t = Transfer()
t.iconData = try! Data(contentsOf: URL(fileURLWithPath: iconPath))
print("图标文件: \(iconPath) (\(t.iconData.count)B)")

CFRunLoopRun()
