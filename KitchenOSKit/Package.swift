// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "KitchenOSKit",
    platforms: [.macOS(.v13), .iOS(.v16)],
    products: [
        .library(name: "KitchenOSKit", targets: ["KitchenOSKit"]),
    ],
    targets: [
        .target(name: "KitchenOSKit"),
        .testTarget(name: "KitchenOSKitTests", dependencies: ["KitchenOSKit"]),
    ]
)
