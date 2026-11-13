# Calendar opportunities implementation plan

**Goal:** Show cooking opportunities using iCloud commitments and flexible Time Blocking after noon, as approved in this conversation.

**Architecture:** The server Mac’s native app requests EventKit full access and lets the user select two distinct calendars by stable identifier. A pure Swift classifier checks overlapping events from noon to local midnight. It sends only date/status summaries to an authenticated API backed by kitchenos.db. The browser reads cached status, never Calendar or an LLM during rendering.

**Constraints:** Morning-only events do not block cooking. Firm commitments win over flexible blocks. Free/cancelled/declined events are ignored; all-day busy events count. Missing calendars or denied access produce unknown, never free. Refresh every five minutes while the app is open; expire after six hours. No event titles or notes are uploaded. Calendar writes are never performed. Existing cook mutations remain unchanged.

- [x] Add failing Swift interval-classification tests for morning/noon, flexible/firm precedence, all-day and DST boundaries; implement classifier and upload client.
- [x] Add failing Python API tests for empty/stale/invalid snapshots, authentication and roundtrip; implement bounded snapshot storage and routes.
- [x] Add native permission flow, distinct calendar selectors, refresh/disconnect controls, periodic sync, and usage descriptions.
- [x] Render plain-text daily labels in the web planner with stale-request guards; labels remain suggestions that can be ignored when placing meals.
- [x] Run focused Python and Swift tests, build macOS app, inspect planner behavior, document connection and freshness limits, restart API after edits.

Verification: 124 focused Python tests, 76 Swift package tests, one isolated browser test, and macOS build passed before final review. Worktree creation was sandbox-blocked; changes remain uncommitted in the original checkout. No real Calendar events were read during automated checks.

Review resolution: Calendar reading is restricted to macOS with a localhost server connection. Other devices only read summaries, preventing competing device uploads.
