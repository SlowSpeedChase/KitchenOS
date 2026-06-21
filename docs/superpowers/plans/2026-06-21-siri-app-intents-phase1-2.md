# Siri App Intents — Swift App (Phases 1–2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **NOT an unattended/overnight plan.** Phase 2 requires Xcode, code signing, and on-device Siri testing — interactive steps a human must run on the Mac. Phase 1 (the `KitchenOSKit` Swift package) is `swift test`-able and largely automatable.

**Goal:** Build the iOS/macOS App-Intents front door so the new Siri can search recipes by ingredient, read the meal plan, suggest additions, add a recipe to a day (with spoken confirmation), and report a recipe's calories — all relaying to the existing Flask API over Tailscale/localhost.

**Architecture:** A shared local Swift package `KitchenOSKit` holds the API client, Codable models, the `RecipeEntity`, App Intent enums, the five intents, and the `AppShortcutsProvider`. A macOS app target and an iPadOS app target each embed `KitchenOSKit` and provide only a settings screen (base URL + token). All intelligence stays server-side; Swift relays and speaks.

**Tech Stack:** Swift 5.9+, AppIntents framework, async/await URLSession, Swift Testing or XCTest with a mock `URLProtocol`. Targets the latest iOS/macOS (Apple Intelligence required for the conversational Siri; App Intents core works on iOS 16+/macOS 13+).

## Global Constraints

- All recipe/AI/nutrition logic stays in Python; Swift only relays + formats spoken text (see the spec's "AI placement" section).
- Base URL: Mac → `http://localhost:5001`; iPad → `http://chases-mac-mini.taila69703.ts.net:5001`. Token (optional) → `KITCHENOS_API_TOKEN` sent as `Authorization: Bearer <token>`; localhost is exempt server-side.
- No new backend endpoints. Reuse: `GET /api/recipes?ingredient=`, `GET /api/recipes/<name>`, `GET`/`PUT /api/meal-plan/<week>`, `POST /api/suggest-meal`.
- Endpoint contracts (verified against `api_server.py`):
  - `GET /api/recipes?ingredient=<term>` → `[{name, cuisine?, protein?, image?, ingredient_items:[String]}]`
  - `GET /api/recipes/<name>` → `{title, nutrition_calories?, nutrition_protein?, nutrition_carbs?, nutrition_fat?, servings?, ingredients:[…], …}`
  - `GET /api/meal-plan/<week>` → `{week, days:[{day, date, breakfast, lunch, snack, dinner}]}`; each slot is `null` or `{name, servings, kind}`.
  - `PUT /api/meal-plan/<week>` body `{days:[…]}` — **same day shape as GET** (round-trips); meal value `null` or `{name, servings, kind}`.
  - `POST /api/suggest-meal` body `{week, day, meal, skip_index}` → `{suggestion: {name, score?, shared_ingredients?} | null, message?}`.
- Work on branch `siri-app-intents`. Commit after each task.
- Build/test commands for Phase 1 run from the package dir: `swift test`. Phase 2 build/verify run in Xcode on the Mac.

## File Structure

```
KitchenOSKit/                              # new local Swift package
  Package.swift
  Sources/KitchenOSKit/
    CredentialStore.swift                  # protocol + Keychain + in-memory impls
    KitchenOSConfig.swift                  # base URL + token resolution
    Models.swift                           # Codable DTOs
    WeekDate.swift                         # ISO week id + DayOfWeek mapping
    KitchenOSClient.swift                  # async URLSession client
    RecipeEntity.swift                     # AppEntity + EntityStringQuery
    Enums.swift                            # DayOfWeek, MealSlot AppEnums
    Intents/
      FindRecipesByIngredientIntent.swift
      GetMealPlanIntent.swift
      SuggestForMealPlanIntent.swift
      AddRecipeToMealPlanIntent.swift
      GetRecipeNutritionIntent.swift
    KitchenOSShortcuts.swift               # AppShortcutsProvider
  Tests/KitchenOSKitTests/
    MockURLProtocol.swift
    KitchenOSClientTests.swift
    WeekDateTests.swift
    ModelsTests.swift
KitchenOSSiri.xcodeproj/                   # Phase 2 — new Xcode project (mac + iPad targets)
```

---

## PHASE 1 — Shared `KitchenOSKit` package

### Task 1: Package skeleton + credential store

**Files:**
- Create: `KitchenOSKit/Package.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/CredentialStore.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/KitchenOSConfig.swift`
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/ConfigTests.swift`

**Interfaces:**
- Produces: `protocol CredentialStore { func token() -> String?; func setToken(_:) }`, `InMemoryCredentialStore`, `KeychainCredentialStore`; `struct KitchenOSConfig { var baseURL: URL; var credentials: CredentialStore }`.

- [ ] **Step 1: Write `Package.swift`**

```swift
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
```

- [ ] **Step 2: Write the failing test**

`Tests/KitchenOSKitTests/ConfigTests.swift`:

```swift
import XCTest
@testable import KitchenOSKit

final class ConfigTests: XCTestCase {
    func testInMemoryCredentialStoreRoundTrips() {
        let store = InMemoryCredentialStore()
        XCTAssertNil(store.token())
        store.setToken("secret")
        XCTAssertEqual(store.token(), "secret")
        store.setToken(nil)
        XCTAssertNil(store.token())
    }

    func testConfigHoldsBaseURL() {
        let store = InMemoryCredentialStore()
        let cfg = KitchenOSConfig(baseURL: URL(string: "http://localhost:5001")!, credentials: store)
        XCTAssertEqual(cfg.baseURL.absoluteString, "http://localhost:5001")
    }
}
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd KitchenOSKit && swift test`
Expected: FAIL — `cannot find 'InMemoryCredentialStore' / 'KitchenOSConfig' in scope`.

- [ ] **Step 4: Implement `CredentialStore.swift`**

```swift
import Foundation
import Security

public protocol CredentialStore: AnyObject {
    func token() -> String?
    func setToken(_ token: String?)
}

public final class InMemoryCredentialStore: CredentialStore {
    private var value: String?
    public init(_ initial: String? = nil) { self.value = initial }
    public func token() -> String? { value }
    public func setToken(_ token: String?) { value = token }
}

public final class KeychainCredentialStore: CredentialStore {
    private let account = "kitchenos.api.token"
    private let service = "com.kitchenos.siri"
    public init() {}

    public func token() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let str = String(data: data, encoding: .utf8) else { return nil }
        return str
    }

    public func setToken(_ token: String?) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        guard let token, let data = token.data(using: .utf8) else { return }
        var add = base
        add[kSecValueData as String] = data
        SecItemAdd(add as CFDictionary, nil)
    }
}
```

- [ ] **Step 5: Implement `KitchenOSConfig.swift`**

```swift
import Foundation

public struct KitchenOSConfig {
    public var baseURL: URL
    public var credentials: CredentialStore

    public init(baseURL: URL, credentials: CredentialStore) {
        self.baseURL = baseURL
        self.credentials = credentials
    }

    /// Resolve from UserDefaults (base URL) + Keychain (token). Falls back to localhost.
    public static func resolved(defaults: UserDefaults = .standard,
                                credentials: CredentialStore = KeychainCredentialStore()) -> KitchenOSConfig {
        let raw = defaults.string(forKey: "kitchenos.baseURL") ?? "http://localhost:5001"
        let url = URL(string: raw) ?? URL(string: "http://localhost:5001")!
        return KitchenOSConfig(baseURL: url, credentials: credentials)
    }
}
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd KitchenOSKit && swift test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add KitchenOSKit/Package.swift KitchenOSKit/Sources/KitchenOSKit/CredentialStore.swift KitchenOSKit/Sources/KitchenOSKit/KitchenOSConfig.swift KitchenOSKit/Tests/KitchenOSKitTests/ConfigTests.swift
git commit -m "feat(kit): KitchenOSKit package skeleton + credential store"
```

---

### Task 2: Codable models

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/Models.swift`
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/ModelsTests.swift`

**Interfaces:**
- Produces: `RecipeSummary`, `RecipeDetail`, `MealPlan`, `MealPlanDay`, `MealSlotValue`, `SuggestResponse`, `Suggestion` — all `Codable` matching the contracts in Global Constraints.

- [ ] **Step 1: Write the failing test**

`Tests/KitchenOSKitTests/ModelsTests.swift`:

```swift
import XCTest
@testable import KitchenOSKit

final class ModelsTests: XCTestCase {
    func testDecodeRecipeSummary() throws {
        let json = """
        [{"name":"Butter Chicken","cuisine":"Indian","protein":"chicken",
          "image":"Butter Chicken.jpg","ingredient_items":["chicken thighs","cream"]}]
        """.data(using: .utf8)!
        let recipes = try JSONDecoder().decode([RecipeSummary].self, from: json)
        XCTAssertEqual(recipes.first?.name, "Butter Chicken")
        XCTAssertEqual(recipes.first?.ingredientItems, ["chicken thighs", "cream"])
    }

    func testDecodeMealPlanWithNullSlots() throws {
        let json = """
        {"week":"2026-W26","days":[
          {"day":"Monday","date":"2026-06-22","breakfast":{"name":"Pancakes","servings":1,"kind":"recipe"},
           "lunch":null,"snack":null,"dinner":null}]}
        """.data(using: .utf8)!
        let plan = try JSONDecoder().decode(MealPlan.self, from: json)
        XCTAssertEqual(plan.days.first?.breakfast?.name, "Pancakes")
        XCTAssertNil(plan.days.first?.dinner)
    }

    func testDecodeSuggestResponseNull() throws {
        let json = #"{"suggestion":null,"message":"No suggestions available"}"#.data(using: .utf8)!
        let resp = try JSONDecoder().decode(SuggestResponse.self, from: json)
        XCTAssertNil(resp.suggestion)
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd KitchenOSKit && swift test`
Expected: FAIL — model types not defined.

- [ ] **Step 3: Implement `Models.swift`**

```swift
import Foundation

public struct RecipeSummary: Codable, Sendable, Hashable {
    public let name: String
    public let cuisine: String?
    public let protein: String?
    public let image: String?
    public let ingredientItems: [String]?

    enum CodingKeys: String, CodingKey {
        case name, cuisine, protein, image
        case ingredientItems = "ingredient_items"
    }
}

public struct RecipeDetail: Codable, Sendable {
    public let title: String
    public let servings: Int?
    public let nutritionCalories: Double?
    public let nutritionProtein: Double?
    public let nutritionCarbs: Double?
    public let nutritionFat: Double?

    enum CodingKeys: String, CodingKey {
        case title, servings
        case nutritionCalories = "nutrition_calories"
        case nutritionProtein = "nutrition_protein"
        case nutritionCarbs = "nutrition_carbs"
        case nutritionFat = "nutrition_fat"
    }
}

public struct MealSlotValue: Codable, Sendable, Hashable {
    public var name: String
    public var servings: Int
    public var kind: String

    public init(name: String, servings: Int = 1, kind: String = "recipe") {
        self.name = name; self.servings = servings; self.kind = kind
    }
}

public struct MealPlanDay: Codable, Sendable {
    public var day: String
    public var date: String
    public var breakfast: MealSlotValue?
    public var lunch: MealSlotValue?
    public var snack: MealSlotValue?
    public var dinner: MealSlotValue?
}

public struct MealPlan: Codable, Sendable {
    public let week: String
    public var days: [MealPlanDay]
}

public struct Suggestion: Codable, Sendable {
    public let name: String
    public let score: Double?
    public let sharedIngredients: [String]?

    enum CodingKeys: String, CodingKey {
        case name, score
        case sharedIngredients = "shared_ingredients"
    }
}

public struct SuggestResponse: Codable, Sendable {
    public let suggestion: Suggestion?
    public let message: String?
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd KitchenOSKit && swift test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/Models.swift KitchenOSKit/Tests/KitchenOSKitTests/ModelsTests.swift
git commit -m "feat(kit): Codable models for recipes, meal plan, suggestions"
```

---

### Task 3: Week/date helpers

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/WeekDate.swift`
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/WeekDateTests.swift`

**Interfaces:**
- Produces: `enum WeekDate { static func weekID(for: Date, calendar: Calendar) -> String; static func currentWeekID(...) -> String }` returning `"YYYY-Www"` (e.g. `2026-W26`).

- [ ] **Step 1: Write the failing test**

`Tests/KitchenOSKitTests/WeekDateTests.swift`:

```swift
import XCTest
@testable import KitchenOSKit

final class WeekDateTests: XCTestCase {
    func testWeekIDFormat() {
        var cal = Calendar(identifier: .iso8601)
        cal.timeZone = TimeZone(identifier: "America/Chicago")!
        // 2026-06-22 is a Monday in ISO week 26.
        let comps = DateComponents(year: 2026, month: 6, day: 22)
        let date = cal.date(from: comps)!
        XCTAssertEqual(WeekDate.weekID(for: date, calendar: cal), "2026-W26")
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd KitchenOSKit && swift test`
Expected: FAIL — `WeekDate` not defined.

- [ ] **Step 3: Implement `WeekDate.swift`**

```swift
import Foundation

public enum WeekDate {
    /// ISO-8601 week identifier like "2026-W26".
    public static func weekID(for date: Date, calendar: Calendar = isoCalendar()) -> String {
        let comps = calendar.dateComponents([.weekOfYear, .yearForWeekOfYear], from: date)
        let year = comps.yearForWeekOfYear ?? 0
        let week = comps.weekOfYear ?? 0
        return String(format: "%04d-W%02d", year, week)
    }

    public static func currentWeekID(now: Date = Date(), calendar: Calendar = isoCalendar()) -> String {
        weekID(for: now, calendar: calendar)
    }

    public static func isoCalendar() -> Calendar {
        var cal = Calendar(identifier: .iso8601)
        cal.timeZone = .current
        return cal
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd KitchenOSKit && swift test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/WeekDate.swift KitchenOSKit/Tests/KitchenOSKitTests/WeekDateTests.swift
git commit -m "feat(kit): ISO week-id helper"
```

---

### Task 4: API client (with mock-URLProtocol tests)

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/KitchenOSClient.swift`
- Create: `KitchenOSKit/Tests/KitchenOSKitTests/MockURLProtocol.swift`
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/KitchenOSClientTests.swift`

**Interfaces:**
- Produces: `final class KitchenOSClient` with:
  - `func findRecipes(ingredient: String) async throws -> [RecipeSummary]`
  - `func recipeDetail(name: String) async throws -> RecipeDetail`
  - `func mealPlan(week: String) async throws -> MealPlan`
  - `func putMealPlan(_ plan: MealPlan) async throws`
  - `func suggestMeal(week: String, day: String, meal: String, skipIndex: Int) async throws -> SuggestResponse`
  - `enum KitchenOSError: Error { case unreachable, http(Int), decoding }`

- [ ] **Step 1: Write `MockURLProtocol.swift`**

```swift
import Foundation

final class MockURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let handler = MockURLProtocol.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse)); return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
    override func stopLoading() {}
}

extension KitchenOSClient {
    static func mock(baseURL: String = "http://localhost:5001",
                     token: String? = nil) -> KitchenOSClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let creds = InMemoryCredentialStore(token)
        return KitchenOSClient(
            config: KitchenOSConfig(baseURL: URL(string: baseURL)!, credentials: creds),
            session: session
        )
    }
}
```

- [ ] **Step 2: Write the failing test**

`Tests/KitchenOSKitTests/KitchenOSClientTests.swift`:

```swift
import XCTest
@testable import KitchenOSKit

final class KitchenOSClientTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testFindRecipesParsesAndSendsIngredientQuery() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/recipes")
            XCTAssertEqual(req.url?.query, "ingredient=chicken")
            let body = #"[{"name":"Butter Chicken","ingredient_items":["chicken thighs"]}]"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let recipes = try await client.findRecipes(ingredient: "chicken")
        XCTAssertEqual(recipes.map(\.name), ["Butter Chicken"])
    }

    func testSendsBearerTokenWhenSet() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer secret")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    "[]".data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock(token: "secret")
        _ = try await client.findRecipes(ingredient: "x")
    }

    func testHTTPErrorThrows() async {
        MockURLProtocol.handler = { req in
            (HTTPURLResponse(url: req.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!,
             Data())
        }
        let client = KitchenOSClient.mock(token: "bad")
        do { _ = try await client.findRecipes(ingredient: "x"); XCTFail("expected throw") }
        catch let KitchenOSError.http(code) { XCTAssertEqual(code, 401) }
        catch { XCTFail("wrong error: \(error)") }
    }
}
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd KitchenOSKit && swift test`
Expected: FAIL — `KitchenOSClient` not defined.

- [ ] **Step 4: Implement `KitchenOSClient.swift`**

```swift
import Foundation

public enum KitchenOSError: Error, Equatable {
    case unreachable
    case http(Int)
    case decoding
}

public final class KitchenOSClient: @unchecked Sendable {
    private let config: KitchenOSConfig
    private let session: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    public init(config: KitchenOSConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    public func findRecipes(ingredient: String) async throws -> [RecipeSummary] {
        var comps = URLComponents(url: config.baseURL.appendingPathComponent("/api/recipes"),
                                  resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "ingredient", value: ingredient)]
        return try await get(comps.url!)
    }

    public func recipeDetail(name: String) async throws -> RecipeDetail {
        let url = config.baseURL.appendingPathComponent("/api/recipes/\(name)")
        return try await get(url)
    }

    public func mealPlan(week: String) async throws -> MealPlan {
        let url = config.baseURL.appendingPathComponent("/api/meal-plan/\(week)")
        return try await get(url)
    }

    public func putMealPlan(_ plan: MealPlan) async throws {
        let url = config.baseURL.appendingPathComponent("/api/meal-plan/\(plan.week)")
        var req = request(url, method: "PUT")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(["days": plan.days])
        _ = try await send(req)
    }

    public func suggestMeal(week: String, day: String, meal: String,
                            skipIndex: Int = 0) async throws -> SuggestResponse {
        let url = config.baseURL.appendingPathComponent("/api/suggest-meal")
        var req = request(url, method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: [
            "week": week, "day": day, "meal": meal, "skip_index": skipIndex,
        ])
        let data = try await send(req)
        return try decode(data)
    }

    // MARK: - Plumbing

    private func request(_ url: URL, method: String = "GET") -> URLRequest {
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 12
        if let token = config.credentials.token() {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return req
    }

    private func get<T: Decodable>(_ url: URL) async throws -> T {
        let data = try await send(request(url))
        return try decode(data)
    }

    @discardableResult
    private func send(_ req: URLRequest) async throws -> Data {
        let data: Data, response: URLResponse
        do { (data, response) = try await session.data(for: req) }
        catch { throw KitchenOSError.unreachable }
        guard let http = response as? HTTPURLResponse else { throw KitchenOSError.unreachable }
        guard (200..<300).contains(http.statusCode) else { throw KitchenOSError.http(http.statusCode) }
        return data
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try decoder.decode(T.self, from: data) }
        catch { throw KitchenOSError.decoding }
    }
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd KitchenOSKit && swift test`
Expected: PASS (all client tests).

- [ ] **Step 6: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/KitchenOSClient.swift KitchenOSKit/Tests/KitchenOSKitTests/MockURLProtocol.swift KitchenOSKit/Tests/KitchenOSKitTests/KitchenOSClientTests.swift
git commit -m "feat(kit): async KitchenOSClient with mock-URLProtocol tests"
```

---

### Task 5: App Intent enums + RecipeEntity

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/Enums.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift`

**Interfaces:**
- Produces: `enum DayOfWeek: String, AppEnum` (cases `monday`…`sunday`, `var title: String` → "Monday"…); `enum MealSlot: String, AppEnum` (`breakfast, lunch, snack, dinner`); `struct RecipeEntity: AppEntity` (`id: String` = recipe name) with `RecipeEntityQuery: EntityStringQuery`.
- Consumes: `KitchenOSClient.findRecipes`, `KitchenOSConfig.resolved()`.

> No unit test for this task — `AppEnum`/`AppEntity` conformance is validated by compilation and by the Shortcuts/Siri smoke tests in Phase 2.

- [ ] **Step 1: Implement `Enums.swift`**

```swift
import AppIntents

public enum DayOfWeek: String, AppEnum, CaseIterable {
    case monday, tuesday, wednesday, thursday, friday, saturday, sunday

    public var title: String { rawValue.capitalized }

    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "Day" }
    public static var caseDisplayRepresentations: [DayOfWeek: DisplayRepresentation] {
        Dictionary(uniqueKeysWithValues: allCases.map { ($0, DisplayRepresentation(stringLiteral: $0.title)) })
    }
}

public enum MealSlot: String, AppEnum, CaseIterable {
    case breakfast, lunch, snack, dinner

    public var title: String { rawValue.capitalized }

    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "Meal" }
    public static var caseDisplayRepresentations: [MealSlot: DisplayRepresentation] {
        Dictionary(uniqueKeysWithValues: allCases.map { ($0, DisplayRepresentation(stringLiteral: $0.title)) })
    }
}
```

- [ ] **Step 2: Implement `RecipeEntity.swift`**

```swift
import AppIntents
import Foundation

public struct RecipeEntity: AppEntity, Identifiable {
    public var id: String          // recipe name
    public var cuisine: String?
    public var proteinName: String?

    public init(id: String, cuisine: String? = nil, proteinName: String? = nil) {
        self.id = id; self.cuisine = cuisine; self.proteinName = proteinName
    }

    public init(_ summary: RecipeSummary) {
        self.id = summary.name; self.cuisine = summary.cuisine; self.proteinName = summary.protein
    }

    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "Recipe" }

    public var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(id)", subtitle: cuisine.map { "\($0)" })
    }

    public static var defaultQuery = RecipeEntityQuery()
}

public struct RecipeEntityQuery: EntityStringQuery {
    public init() {}

    private func client() -> KitchenOSClient {
        KitchenOSClient(config: .resolved())
    }

    // Siri resolves a typed/spoken name → matching entities.
    public func entities(matching string: String) async throws -> [RecipeEntity] {
        let matches = try await client().findRecipes(ingredient: string)
        return matches.map(RecipeEntity.init)
    }

    // Required: resolve specific ids back to entities.
    public func entities(for identifiers: [String]) async throws -> [RecipeEntity] {
        identifiers.map { RecipeEntity(id: $0) }
    }

    public func suggestedEntities() async throws -> [RecipeEntity] { [] }
}
```

- [ ] **Step 3: Build the package**

Run: `cd KitchenOSKit && swift build`
Expected: builds clean (AppIntents links on macOS 13+).

- [ ] **Step 4: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/Enums.swift KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift
git commit -m "feat(kit): DayOfWeek/MealSlot enums and RecipeEntity"
```

---

### Task 6: The five App Intents

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/Intents/FindRecipesByIngredientIntent.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/Intents/GetMealPlanIntent.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/Intents/SuggestForMealPlanIntent.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/Intents/AddRecipeToMealPlanIntent.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/Intents/GetRecipeNutritionIntent.swift`

**Interfaces:**
- Consumes: `KitchenOSClient`, `RecipeEntity`, `DayOfWeek`, `MealSlot`, `WeekDate`, `KitchenOSConfig.resolved()`.
- Produces: five `AppIntent` types. `AddRecipeToMealPlanIntent` gates the write behind `requestConfirmation`.

> Build-verified (compilation); behavior verified in Phase 2 via Shortcuts + Siri.

- [ ] **Step 1: `FindRecipesByIngredientIntent.swift`**

```swift
import AppIntents

public struct FindRecipesByIngredientIntent: AppIntent {
    public static var title: LocalizedStringResource = "Find Recipes by Ingredient"
    public static var description = IntentDescription("Find KitchenOS recipes that contain an ingredient.")

    @Parameter(title: "Ingredient")
    public var ingredient: String

    public init() {}
    public init(ingredient: String) { self.ingredient = ingredient }

    public func perform() async throws -> some IntentResult & ReturnsValue<[RecipeEntity]> & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let recipes: [RecipeSummary]
        do { recipes = try await client.findRecipes(ingredient: ingredient) }
        catch KitchenOSError.unreachable { return .result(value: [], dialog: "I can't reach KitchenOS right now.") }

        let entities = recipes.map(RecipeEntity.init)
        if entities.isEmpty {
            return .result(value: [], dialog: "I didn't find any recipes with \(ingredient).")
        }
        let names = entities.prefix(5).map(\.id).joined(separator: ", ")
        let dialog: IntentDialog = entities.count == 1
            ? "I found \(names)."
            : "I found \(entities.count) recipes: \(names)."
        return .result(value: entities, dialog: dialog)
    }
}
```

- [ ] **Step 2: `GetMealPlanIntent.swift`**

```swift
import AppIntents

public struct GetMealPlanIntent: AppIntent {
    public static var title: LocalizedStringResource = "Get Meal Plan"
    public static var description = IntentDescription("Read what's on the KitchenOS meal plan.")

    @Parameter(title: "Day")
    public var day: DayOfWeek?

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let week = WeekDate.currentWeekID()
        let plan: MealPlan
        do { plan = try await client.mealPlan(week: week) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }

        if let day {
            guard let d = plan.days.first(where: { $0.day.lowercased() == day.title.lowercased() }) else {
                return .result(dialog: "I couldn't find \(day.title) on this week's plan.")
            }
            return .result(dialog: IntentDialog(stringLiteral: Self.describe(d)))
        }
        let summary = plan.days.map(Self.describe).joined(separator: "; ")
        return .result(dialog: IntentDialog(stringLiteral: "This week: \(summary)"))
    }

    static func describe(_ d: MealPlanDay) -> String {
        var meals: [String] = []
        if let b = d.breakfast?.name { meals.append("breakfast \(b)") }
        if let l = d.lunch?.name { meals.append("lunch \(l)") }
        if let s = d.snack?.name { meals.append("snack \(s)") }
        if let n = d.dinner?.name { meals.append("dinner \(n)") }
        return meals.isEmpty ? "\(d.day) is empty" : "\(d.day): " + meals.joined(separator: ", ")
    }
}
```

- [ ] **Step 3: `SuggestForMealPlanIntent.swift`**

```swift
import AppIntents

public struct SuggestForMealPlanIntent: AppIntent {
    public static var title: LocalizedStringResource = "Suggest a Meal to Add"
    public static var description = IntentDescription("Suggest a recipe for the next empty slot on the meal plan.")

    @Parameter(title: "Day")
    public var day: DayOfWeek?

    @Parameter(title: "Meal")
    public var meal: MealSlot?

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let week = WeekDate.currentWeekID()
        let plan: MealPlan
        do { plan = try await client.mealPlan(week: week) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }

        guard let (dayName, mealName) = Self.targetSlot(plan: plan, day: day, meal: meal) else {
            return .result(dialog: "The plan looks full — nothing to suggest.")
        }
        let resp = try await client.suggestMeal(week: week, day: dayName, meal: mealName, skipIndex: 0)
        guard let s = resp.suggestion else {
            return .result(dialog: IntentDialog(stringLiteral: resp.message ?? "No suggestions available."))
        }
        return .result(dialog: "For \(mealName) on \(dayName), try \(s.name).")
    }

    /// Pick the requested slot, or the first empty slot in week order.
    static func targetSlot(plan: MealPlan, day: DayOfWeek?, meal: MealSlot?) -> (String, String)? {
        func value(_ d: MealPlanDay, _ m: MealSlot) -> MealSlotValue? {
            switch m { case .breakfast: return d.breakfast; case .lunch: return d.lunch
                       case .snack: return d.snack; case .dinner: return d.dinner }
        }
        let days = day == nil ? plan.days
                              : plan.days.filter { $0.day.lowercased() == day!.title.lowercased() }
        let meals: [MealSlot] = meal.map { [$0] } ?? [.breakfast, .lunch, .snack, .dinner]
        for d in days { for m in meals where value(d, m) == nil { return (d.day, m.rawValue) } }
        return nil
    }
}
```

- [ ] **Step 4: `AddRecipeToMealPlanIntent.swift`**

```swift
import AppIntents

public struct AddRecipeToMealPlanIntent: AppIntent {
    public static var title: LocalizedStringResource = "Add Recipe to Meal Plan"
    public static var description = IntentDescription("Add a recipe to a day on the meal plan.")

    @Parameter(title: "Recipe")
    public var recipe: RecipeEntity

    @Parameter(title: "Day")
    public var day: DayOfWeek

    @Parameter(title: "Meal")
    public var meal: MealSlot

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        try await requestConfirmation(
            result: .result(dialog: "Add \(recipe.id) to \(day.title) \(meal.title)?")
        )

        let client = KitchenOSClient(config: .resolved())
        let week = WeekDate.currentWeekID()
        var plan: MealPlan
        do { plan = try await client.mealPlan(week: week) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }

        guard let idx = plan.days.firstIndex(where: { $0.day.lowercased() == day.title.lowercased() }) else {
            return .result(dialog: "I couldn't find \(day.title) on this week's plan.")
        }
        let slot = MealSlotValue(name: recipe.id)
        switch meal {
        case .breakfast: plan.days[idx].breakfast = slot
        case .lunch:     plan.days[idx].lunch = slot
        case .snack:     plan.days[idx].snack = slot
        case .dinner:    plan.days[idx].dinner = slot
        }
        do { try await client.putMealPlan(plan) }
        catch { return .result(dialog: "I couldn't update the meal plan.") }
        return .result(dialog: "Added \(recipe.id) to \(day.title) \(meal.title).")
    }
}
```

- [ ] **Step 5: `GetRecipeNutritionIntent.swift`**

```swift
import AppIntents

public struct GetRecipeNutritionIntent: AppIntent {
    public static var title: LocalizedStringResource = "Get Recipe Nutrition"
    public static var description = IntentDescription("Report a recipe's calories and macros.")

    @Parameter(title: "Recipe")
    public var recipe: RecipeEntity

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let detail: RecipeDetail
        do { detail = try await client.recipeDetail(name: recipe.id) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }
        catch KitchenOSError.http(404) { return .result(dialog: "I couldn't find \(recipe.id).") }

        guard let cals = detail.nutritionCalories else {
            return .result(dialog: "\(recipe.id) doesn't have nutrition data yet.")
        }
        var parts = ["\(Int(cals)) calories"]
        if let p = detail.nutritionProtein { parts.append("\(Int(p)) grams of protein") }
        return .result(dialog: IntentDialog(stringLiteral: "\(recipe.id) has " + parts.joined(separator: " and ") + " per serving."))
    }
}
```

- [ ] **Step 6: Build the package**

Run: `cd KitchenOSKit && swift build`
Expected: builds clean.

- [ ] **Step 7: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/Intents/
git commit -m "feat(kit): five App Intents (find, get-plan, suggest, add w/ confirm, nutrition)"
```

---

### Task 7: AppShortcutsProvider

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/KitchenOSShortcuts.swift`

**Interfaces:**
- Produces: `KitchenOSShortcuts: AppShortcutsProvider` registering phrases for each intent. `\(.applicationName)` must appear in every phrase.

- [ ] **Step 1: Implement `KitchenOSShortcuts.swift`**

```swift
import AppIntents

public struct KitchenOSShortcuts: AppShortcutsProvider {
    public static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: FindRecipesByIngredientIntent(),
            phrases: [
                "Find \(.applicationName) recipes with \(\.$ingredient)",
                "Which \(.applicationName) recipes use \(\.$ingredient)",
            ],
            shortTitle: "Find by Ingredient",
            systemImageName: "magnifyingglass"
        )
        AppShortcut(
            intent: GetMealPlanIntent(),
            phrases: ["What's on my \(.applicationName) meal plan"],
            shortTitle: "Meal Plan",
            systemImageName: "calendar"
        )
        AppShortcut(
            intent: SuggestForMealPlanIntent(),
            phrases: ["Suggest a \(.applicationName) meal to add"],
            shortTitle: "Suggest a Meal",
            systemImageName: "wand.and.stars"
        )
        AppShortcut(
            intent: AddRecipeToMealPlanIntent(),
            phrases: ["Add a recipe to my \(.applicationName) meal plan"],
            shortTitle: "Add to Plan",
            systemImageName: "plus.circle"
        )
        AppShortcut(
            intent: GetRecipeNutritionIntent(),
            phrases: ["How many calories in a \(.applicationName) recipe"],
            shortTitle: "Recipe Nutrition",
            systemImageName: "flame"
        )
    }
}
```

- [ ] **Step 2: Build**

Run: `cd KitchenOSKit && swift build && swift test`
Expected: builds + all package tests pass.

- [ ] **Step 3: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/KitchenOSShortcuts.swift
git commit -m "feat(kit): AppShortcutsProvider with Siri phrases"
```

---

## PHASE 2 — Xcode app targets (interactive, on the Mac)

> These tasks need Xcode and a signed-in Apple ID. They cannot run unattended. Each ends with a manual verification, not an automated assert.

### Task 8: macOS app target + settings, verify on Mac

**Files:**
- Create: `KitchenOSSiri.xcodeproj` (new Xcode project)
- Create: `KitchenOSSiri/macOS/KitchenOSSiriApp.swift`, `SettingsView.swift`
- Modify: project settings to add `KitchenOSKit` as a local package dependency

- [ ] **Step 1: Create the Xcode project**
  - Xcode → New Project → multiplatform App named `KitchenOSSiri`. Set the **App Category** and a bundle id `com.kitchenos.siri`.
  - File → Add Package Dependencies → Add Local… → select the `KitchenOSKit` folder. Add the `KitchenOSKit` library to the macOS app target.

- [ ] **Step 2: Minimal app + settings UI**

`KitchenOSSiri/macOS/KitchenOSSiriApp.swift`:

```swift
import SwiftUI

@main
struct KitchenOSSiriApp: App {
    var body: some Scene {
        WindowGroup { SettingsView() }
    }
}
```

`KitchenOSSiri/macOS/SettingsView.swift`:

```swift
import SwiftUI
import KitchenOSKit

struct SettingsView: View {
    @AppStorage("kitchenos.baseURL") private var baseURL = "http://localhost:5001"
    @State private var token = ""
    private let creds = KeychainCredentialStore()

    var body: some View {
        Form {
            TextField("Base URL", text: $baseURL)
            SecureField("API token (optional)", text: $token)
            Button("Save token") { creds.setToken(token.isEmpty ? nil : token) }
            Text("Mac uses localhost; iPad uses the Tailscale host.").font(.caption)
        }
        .padding()
        .onAppear { token = creds.token() ?? "" }
    }
}
```

- [ ] **Step 3: Build & run on the Mac**

Run from Xcode (⌘R). Expected: the settings window opens; base URL defaults to localhost.

- [ ] **Step 4: Verify intents in the Shortcuts app**
  - Open Shortcuts → search "KitchenOS" → confirm all five actions appear.
  - Run **Find Recipes by Ingredient** with `chicken` → returns recipe names (API server must be running).
  - Run **Add Recipe to Meal Plan** → confirm it asks "Add … to …?" before writing.

- [ ] **Step 5: Verify by voice on the Mac**
  - "Hey Siri, which KitchenOS recipes use chicken?" → spoken list.
  - "Hey Siri, what's on my KitchenOS meal plan?" → spoken summary.

- [ ] **Step 6: Commit**

```bash
git add KitchenOSSiri.xcodeproj KitchenOSSiri/macOS
git commit -m "feat(app): macOS App-Intents app target + settings, verified on Mac"
```

### Task 9: iPadOS target + Tailscale, verify on iPad

**Files:**
- Modify: `KitchenOSSiri.xcodeproj` (add iOS target)
- Create: `KitchenOSSiri/iOS/` app + settings (reuse `SettingsView`)

- [ ] **Step 1: Add the iOS app target**, embed `KitchenOSKit`, set bundle id `com.kitchenos.siri`, signing team.
- [ ] **Step 2: Set the iPad base URL** to `http://chases-mac-mini.taila69703.ts.net:5001` (default the `kitchenos.baseURL` AppStorage for iOS, or enter it in settings on first launch). Save the API token in settings (matching `KITCHENOS_API_TOKEN` on the server).
- [ ] **Step 3: Build to the iPad** (signed). Ensure the iPad is on the tailnet.
- [ ] **Step 4: Verify in Shortcuts on iPad**, then by voice: "Hey Siri, suggest a KitchenOS meal to add", and a chained "find a chicken recipe… add it to Thursday".
- [ ] **Step 5: Commit**

```bash
git add KitchenOSSiri.xcodeproj KitchenOSSiri/iOS
git commit -m "feat(app): iPadOS App-Intents target over Tailscale, verified on iPad"
```

---

## Self-Review

**Spec coverage:** All five intents from the spec → Task 6; `RecipeEntity` chaining → Task 5/6; confirm-before-write → `AddRecipeToMealPlanIntent` (`requestConfirmation`); graceful spoken errors (unreachable / no-match / write-fail / 404) → each intent; Keychain token + localhost-vs-Tailscale base URL → Task 1 + settings; shared module + two targets → file structure + Phases 1/2; testing via mock `URLProtocol` + Shortcuts/Siri → Tasks 4/8/9. The spec's "AI placement" decision is honored — no on-device model; Swift only relays and templates spoken text.

**Backend:** No new endpoints required — `SuggestForMealPlan` computes the current week + first empty slot client-side and reuses `POST /api/suggest-meal`; `AddRecipeToMealPlan` round-trips GET→mutate→PUT (verified the GET day shape matches `rebuild_meal_plan_markdown`'s expected `{name, servings, kind}`).

**Placeholder scan:** No TBD/TODO; every Swift file is complete. Phase 2 build/sign/device steps are inherently interactive and are labeled as such, with concrete verification phrases rather than code.

**Type consistency:** `RecipeEntity.id` (recipe name) is produced by `FindRecipesByIngredientIntent` and consumed by `Add…`/`GetRecipeNutrition`. `MealSlotValue {name, servings, kind}` matches both the GET response and the PUT body. `WeekDate.currentWeekID()` feeds every week-scoped call. `KitchenOSError` cases are thrown by the client and matched in the intents.

## Execution Handoff

- **Phase 1** (`KitchenOSKit`) is `swift test`-able and suitable for subagent-driven or inline execution on the Mac — NOT this remote/unattended environment (it needs the Swift toolchain).
- **Phase 2** is interactive Xcode work: project creation, signing, and on-device Siri verification.
- Recommended order: Phase 1 end-to-end (green `swift test`), then Phase 2 Task 8 (Mac), then Task 9 (iPad).
