# Subsystem C — Phase C3: Semantic recipe search via IndexedEntity (Plan)

Spec: `docs/superpowers/specs/2026-06-23-apple-intelligence-subsystem-c-design.md`.
Worktree: `~/Dev/KitchenOS-siri` (branch `siri-app-intents`).

## Scope finding (from SDK introspection)

- **Assistant Schemas don't apply.** iOS 27's `AssistantSchemas` only cover Apple's
  predefined domains; grepping the AppIntents schema set for `food|recipe|meal|cook|grocery`
  returns **zero** matches. There's no recipe domain to conform to — **skip** `@AssistantEntity`.
- **`IndexedEntity` is the applicable mechanism** and the whole of C3: index recipes into
  the system semantic index so Siri/Spotlight/Apple Intelligence match by *meaning* and can
  answer over them.

Verified APIs:
- `protocol IndexedEntity: AppEntity { var attributeSet: CSSearchableItemAttributeSet }`
- `CSSearchableIndex.default().indexAppEntities([some IndexedEntity], priority:) async throws`
  and `deleteAppEntities(ofType:)`.
- `protocol IndexedEntityQuery: EntityQuery where Entity: IndexedEntity` requires
  `reindexEntities(for:indexDescription:)` and `reindexAllEntities(indexDescription:)`.

## Components (reuse existing entity + client; no backend change)

**`RecipeEntity: IndexedEntity`** (modify `RecipeEntity.swift`): add a
`CSSearchableItemAttributeSet` built from the fields we already have — title = name,
`contentDescription`/`keywords` from cuisine + protein. (Ingredient keywords are a future
enhancement — needs an "all recipes with ingredients" endpoint; out of scope for C3 v1.)

**`RecipeEntityQuery: IndexedEntityQuery`** (also keep `EntityStringQuery`): implement
`reindexAllEntities`/`reindexEntities` by delegating to `RecipeIndexer.reindexAll`.

**`RecipeIndexer`** (new, `KitchenOSKit/Sources/KitchenOSKit/RecipeIndexer.swift`):
`static func reindexAll(client:) async throws -> Int` — fetch `client.findRecipes("")`,
map to `[RecipeEntity]`, `CSSearchableIndex.default().indexAppEntities(...)`, return count.
Reuses `findRecipes` + `RecipeEntity(_ summary:)`.

**App wiring:** index on launch (a `.task` on the root `TabView`) and a manual
"Reindex for search" button in Settings (with a result note). CoreSpotlight indexing is
independent of Apple Intelligence, so it runs regardless of model availability.

## Critical files

- Modify: `KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/RecipeIndexer.swift`
- Modify: `KitchenOSSiri/Sources/KitchenOSSiriApp.swift` (launch `.task`), `SettingsView.swift` (reindex button)
- Create test: `KitchenOSKit/Tests/KitchenOSKitTests/RecipeEntityIndexTests.swift`

## Tests (deterministic — `swift test`)

- `RecipeEntity.attributeSet` — title == name; keywords/contentDescription include cuisine + protein.
- Not unit-tested (touches the live system index / non-deterministic): `RecipeIndexer.reindexAll`
  and `reindexAllEntities` — verified on-device.

## Verification

1. `cd KitchenOSKit && swift build && swift test` → green.
2. `xcodegen generate && xcodebuild … -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build` → BUILD SUCCEEDED.
3. On-device: launch app once (auto-index) or tap **Reindex** in Settings; then Spotlight/Siri
   "spicy Indian chicken" or a fuzzy description surfaces matching recipes (semantic match,
   not exact name). `GetRecipeNutrition`/`Summarize`/add-to-plan still resolve the entity.

## Note

C3 is intentionally smaller than first framed (assistant schemas turned out N/A). After C3,
Subsystem C is feature-complete; remaining polish: ingredient keywords (needs a backend
endpoint) and index-refresh cadence.
