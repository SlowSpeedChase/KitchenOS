# KitchenOS Convergence Plan — merge `siri-app-intents` + `ingredient-cleaning` → `main`

**Execute:** when the other agent is **paused** and both branches are **committed + pushed**.
**Where:** run everything in `~/Dev/KitchenOS` (it has `.venv` + is the deploy checkout).
**Shared base of the two work branches:** `9f24dc1` (my C1 completion). `main` base: `6c4c977`.

## What you're converging

| | `siri-app-intents` (Siri/AI app + my backend bits) | `ingredient-cleaning` (their Mac app + nutrition engine) |
|---|---|---|
| App | iOS TabView: Assistant / Plan / Cook / Search / Settings; App Intents; Foundation Models; Spotlight `IndexedEntity` | macOS-oriented: `AppShell` sidebar, `Extraction/` module, their `Recipes/` views, iOS+macOS `Info.plist` split, macOS entitlements |
| Backend | nutrition fields in recipe index; `/api/recipes/by-ingredients`; Plan A (ingredient filter, auth) | nutrition engine, ingredient cleaning, food DB, units (all new `lib/` files) |

**Backend conflicts are small; the app has genuinely forked.** Decide the app direction *before* Step 3 (see "App decision").

---

## Step 0 — Pre-flight (5 min)
```bash
cd ~/Dev/KitchenOS
git fetch origin
git status --short                 # MUST be clean (other agent committed). If dirty, stop & commit/stash their work first.
git switch ingredient-cleaning && git pull
git switch siri-app-intents && git pull   # this updates the branch ref; the iOS worktree is at ~/Dev/KitchenOS-siri
git switch ingredient-cleaning            # base the merge on the bigger branch (their app + nutrition)
git switch -c converge-to-main
```

## Step 1 — Run the merge (surfaces conflicts)
```bash
git merge siri-app-intents --no-edit
git diff --name-only --diff-filter=U     # expected conflicts: KitchenOSSiriApp.swift, SmartSearchView.swift
```
Auto-merged but **must be verified** (auto-merge ≠ correct): `api_server.py`, `KitchenOSKit/.../Models.swift`,
`KitchenOSKit/.../KitchenOSClient+Search.swift`, `KitchenOSSiri/.../SettingsView.swift`.

## Step 2 — Resolve & verify the BACKEND (low risk, do first)
```bash
# recipe index must keep the nutrition fields (from siri)
grep -n NUTRITION_FIELDS lib/recipe_index.py            # expect a hit

# api_server must have BOTH sides' routes
grep -n "by-ingredients" api_server.py                  # mine (must be present)
grep -nE "@app.route" api_server.py | wc -l             # sanity: route count looks right, no dupes

# requirements.txt: if conflicted, union both (keep setproctitle + any nutrition deps)
python3 -c "import api_server; print('api_server imports OK')"   # use .venv: .venv/bin/python -c ...
.venv/bin/python -m pytest -q                            # BOTH test suites should pass
```
If `api_server.py` looks garbled at a merge seam, hand-fix so **both** my endpoints (`by-ingredients`,
ingredient filter, auth) and their endpoints (nutrition/import-text changes) are intact.

## App decision (make before Step 3)
**Recommended:** one **multiplatform** app = *their* scaffolding (the `AppShell` sidebar for macOS,
`Info-iOS/Info-macOS` split, macOS target, `Extraction/` module) **+ my iOS feature views** (the
Assistant/Plan/Cook/Search/Settings tabs and `RecipeDetailView`), gated with `#if os(iOS)` / `#if os(macOS)`.
If that's too much for one sitting, pick **one canonical app** (iOS Siri/AI = mine) and set their Mac
extraction app aside on its branch — you can fold it in later.

## Step 3 — Resolve the APP conflicts + duplicate types
1. **`KitchenOSSiriApp.swift`** (conflict): pick the entry. For the combined app:
   ```swift
   WindowGroup {
   #if os(macOS)
       AppShell()                       // their sidebar (Mac)
   #else
       TabView { Assistant / Plan / Cook / Search / Settings }   // my iOS tabs + .task reindex + .sheet router + onContinueUserActivity
   #endif
   }
   ```
   (My full iOS body is in the `<<<<<<< HEAD` side of the conflict — keep it for the `#else`.)
2. **Duplicate `RecipeDetailView`**: mine `KitchenOSSiri/Sources/RecipeDetailView.swift` vs theirs
   `KitchenOSSiri/Sources/Recipes/RecipeDetailView.swift`. **Keep one** (mine has nutrition + on-device
   summary + Open-in-Obsidian). `git rm` the other, or rename theirs. Check `Recipes/RecipeListView.swift`
   for any other duplicate symbols.
3. **`SmartSearchView.swift`** (conflict): **keep my side (`HEAD`)** — it has the Summarize button,
   Open-in-Obsidian link, and nutrition display that their side stripped.
4. **`project.yml`**: take **their** multiplatform spec (macOS target + Info split + entitlements) but make
   sure the **sources globs include all my files** (AssistantView, MealPlanView, CookView, RecipeDetailView,
   SmartSearchView, the App, plus KitchenOSKit). After editing: `xcodegen generate`.
5. **`Info-iOS.plist`**: confirm it has my iOS networking keys — `NSAppTransportSecurity →
   NSAllowsArbitraryLoads = true` (NO `NSAllowsLocalNetworking`) and `NSLocalNetworkUsageDescription`.

## Step 4 — Build & verify everything
```bash
cd KitchenOSKit && swift test && cd ..                  # KitchenOSKit unit tests green
xcodegen generate
xcodebuild -project KitchenOSSiri.xcodeproj -scheme KitchenOSSiri \
  -destination 'generic/platform=iOS' -derivedDataPath .build-xcode CODE_SIGNING_ALLOWED=NO build   # iOS BUILD SUCCEEDED
# (optional) build the macOS target too
# Fix any duplicate-symbol / missing-type errors that surface (most likely the RecipeDetailView dedupe).
.venv/bin/python -m pytest -q                           # backend still green
```
Confirm App Intents metadata still extracts (8 intents incl. OpenRecipeIntent):
```bash
python3 -c "import json;d=json.load(open('.build-xcode/Build/Products/Debug-iphoneos/KitchenOS.app/Metadata.appintents/extract.actionsdata'));print(sorted(d['actions']))"
```

## Step 5 — Land it & deploy
```bash
git add -A && git commit --no-edit                      # complete the merge commit
git push -u origin converge-to-main
gh pr create --base main --head converge-to-main --title "Converge Siri app + nutrition/ingredient work" --body "Merges siri-app-intents and ingredient-cleaning."
# review the PR, then merge to main on GitHub.

# Deploy the server from main:
git switch main && git pull
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist && launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
sleep 3 && curl -s 'http://localhost:5001/health'       # {"status":"ok"}
curl -s -X POST 'http://localhost:5001/api/recipes/by-ingredients' -H 'Content-Type: application/json' -d '{"ingredients":["chicken","rice"]}'
```
Build the iOS app from `main` going forward (the `~/Dev/KitchenOS-siri` worktree can be retired once main is canonical).

## Rollback (safe at any point)
- Mid-merge mess: `git merge --abort` (branches untouched).
- After merge but before push: `git switch ingredient-cleaning` and delete `converge-to-main`.
- Server: it only changes when you switch the checkout's branch + reload the LaunchAgent.

## If you only have 15 minutes
Do just the **minimal backend deploy** (no merge): on `ingredient-cleaning`,
`git checkout siri-app-intents -- lib/recipe_index.py`, paste the `by-ingredients` route into
`api_server.py` (in `docs/superpowers/plans/` chat history / the prior message), restart the LaunchAgent.
That lights up nutrition search + Cook live without the full convergence.
