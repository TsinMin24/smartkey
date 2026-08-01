// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SmartKeyApp",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "SmartKeyApp",
            path: "Sources/SmartKeyApp"
        )
    ]
)
