// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "KitchenOSKit",
    platforms: [.macOS("26.0"), .iOS("26.0")],
    products: [
        .library(name: "KitchenOSKit", targets: ["KitchenOSKit"]),
    ],
    targets: [
        .target(name: "KitchenOSKit"),
        .testTarget(name: "KitchenOSKitTests", dependencies: ["KitchenOSKit"]),
    ],
    swiftLanguageModes: [.v5]
)
