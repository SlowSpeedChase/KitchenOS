# Branch Status: ios27-new-siri

**Created:** 2026-08-12
**Design Doc:** docs/superpowers/specs/2026-08-12-ios27-new-siri-design.md
**Current Stage:** testing (on-device verification outstanding)
**Last Rebased:** 2026-08-12 (created from main @ 6701d0c)

## Overview

iOS 27 new-Siri feature in two slices: (1) floor raise to 27 + App Intents upgrade —
`IndexedEntityQuery` system reindex, ingredient keywords in the Spotlight donation,
AskKitchenOS multi-turn session store + `LongRunningIntent` progress; (2) on-phone
SwiftData store (`KitchenStore` + `KitchenDataSource` + `SyncEngine` + op-log write queue)
so Siri answers offline and the Mac becomes a sync peer. Security rider: set
`KITCHENOS_API_TOKEN` for real; gate inventory mutation routes.

Approved implementation plan: `~/.claude/plans/proud-baking-koala.md` (2026-08-12).
SDK introspection findings are pinned in the design spec (no public multi-turn/streaming
API — session store + progress are the design, not fallbacks).

## Dependencies

- None on other branches. Active worktrees (close-loops, move-cook-by-drag,
  plates-ledger-native) touch the web planner/ledger, not KitchenOSKit/KitchenOSSiri.
- On-device verification requires the iPhone on the iOS 27 beta (available).

---

## Stages

### Planning
- [x] Design doc exists and approved
- [x] Conflict check completed (no overlapping work)
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (superpowers:writing-plans) — docs/superpowers/plans/2026-08-12-ios27-new-siri-slice1.md

### Dev
- [x] Tests written first (superpowers:test-driven-development) — RED/GREEN evidence per task report
- [x] Core implementation complete (Tasks 1-7 + final-review fixes, commit 1934732)
- [x] All tests passing — Swift 80/80, pytest 21/21 on touched files
- [x] No linting/type errors — swift build clean, metadata gate 9 actions
- [x] Code follows project patterns
- [ ] LaunchAgent restart — needed at MERGE time (api_server.py changed); prod serves main until then

### Testing
- [x] Unit tests pass (80 Swift, 21 Python on touched files)
- [x] Integration: App Intents metadata gate — 9 actions extracted after every intent-touching task
- [ ] Manual testing — deployed to iPad Air 2026-08-12 (devicectl; relaunch + screenshot verified; launch-time `GET /api/recipes?include_ingredients=1` → 200 confirmed in server.log from tailnet node ipaid-air-m4-blue). VOICE CHECKLIST OUTSTANDING (plan Task 8 Step 3: multi-turn, decline flow, long-session probe, Spotlight ingredient search). Note: prod server still runs main, so ingredient keywords in the donation activate at merge + LaunchAgent restart.
- [x] **First end-to-end intent execution on device — 2026-08-13 09:57 CDT:** AskKitchenOSIntent run from the Shortcuts app (tap) answered "what's on the meal plan" from real data — `GET /api/meal-plan/2026-W33` → 200 in server.log at the spoken moment. Shortcuts ARE registered/ingested (visible in the Shortcuts app).
- [x] **DEFINITIVE — Siri phrase routing is broken at the OS level on this beta (2026-08-13 ~10:31 CDT):** Type-to-Siri with the byte-exact registered phrase (pasted via devicectl pasteboard, ASR fully out of the loop) still produced the generic "I can't search within the KitchenOS app right now" fallback; zero server requests, intent never ran. Conversational (Apple Intelligence) Siri on this iOS 27 beta does not consult App Shortcut phrase templates. Not fixable app-side; the broadened phrases remain correct for Shortcuts/Spotlight surfaces and for when a future beta restores routing. Working voice-adjacent entry today: run the shortcut from the Shortcuts app (or Home Screen/widget). Retest phrase routing on each iOS 27 beta bump.
  **Corroborated 2026-08-13 (web research):** third-party App Intent integration with the new Siri is deliberately OFF in the iOS 27 betas — Apple blocks shipping Siri-AI app integrations until the September launch (WVFRM/Cassinelli), beta reports describe the Siri/Shortcuts rework "breaking the underlying logic" of voice-triggered shortcuts, and beta 5's notes list "fewer errors when Siri reaches into third-party app data" as an active fix area. Expect routing to arrive at/after GA, not from anything we ship. Device IS enrolled in the new-Siri beta (user-confirmed 2026-08-13), so the refusals come from Siri AI proper — enrollment is not the missing piece.
- [x] **Phrase-token observation (Task 8 item 10) — answered 2026-08-12 ~21:59 CDT:** a natural meal-plan question *without* "KitchenOS" got Siri's generic fallback ("I can't search within KitchenOS directly…"); no server request, intent never ran. New Siri does NOT route app-less phrasing — with no assistant schema (C3), literal phrase match is the only route in. Mitigation 2026-08-13: broadened KitchenOSShortcuts.swift with natural-leaning variants (meal plan ×3, smart find ×2, AskKitchenOS ×2, all keeping the app-name token); redeploy + voice checklist to verify.
- [x] Edge cases verified in unit tests (idle-store boundary/touch/reset; consuming take(); param encoding)
- [ ] Verified with superpowers:verification-before-completion — after on-device pass

### Docs
- [ ] Doc obligations met per CLAUDE.md table (ARCHITECTURE / API / OPERATIONS / invariants)
- [ ] README updated (if interface changed)
- [ ] docs/plans/INDEX.md updated
- [ ] Code comments where needed

### Review
- [ ] Requested review (superpowers:requesting-code-review)
- [ ] Review feedback addressed
- [ ] Changes approved

### Ready
- [ ] Rebased on latest main
- [ ] Final test pass after rebase
- [ ] BRANCH-STATUS.md fully checked
- [ ] Ready for merge

---

## Notes

- Baseline at branch creation: `swift build` clean, 72/72 KitchenOSKit tests pass.
- SDK re-verify on every Xcode 27 beta bump (introspection date pinned in the spec).
- Decision D (daily-driver audit) recorded as "keep investing" in S1.6.

---

## Blocked Items

(none)
