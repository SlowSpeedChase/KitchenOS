// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "KitchenOSKit",
    platforms: [.macOS("27.0"), .iOS("27.0")],
    products: [
        .library(name: "KitchenOSKit", targets: ["KitchenOSKit"]),
    ],
    targets: [
        .target(name: "KitchenOSKit"),
        .testTarget(name: "KitchenOSKitTests", dependencies: ["KitchenOSKit"]),
    ],
    swiftLanguageModes: [.v5]
)
