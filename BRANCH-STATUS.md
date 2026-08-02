# Branch Status: phase-1/honest-system

**Created:** 2026-08-02
**Design Doc:** docs/plans/2026-08-02-daily-driver-audit.md
**Current Stage:** testing
**Last Rebased:** 2026-08-02

## Overview

Phase 1 of the daily-driver plan: **stop the system lying about itself.**

The audit found ten defects that all fail *silently* — no error, no log line, no changed
pixel. This branch does not try to make the numbers right (that is Phase 3). It makes the
system honest about which numbers it cannot stand behind, and revives three controls that
have been dead long enough that nobody remembers pressing them.

Scope is deliberately "no backfill required" — every change here is evaluated at read time
against frontmatter that already exists, so nothing waits on re-deriving the corpus.

## Dependencies

- None. Phase 0 (Full Disk Access grant, Instagram cookies) is a user action that runs in
  parallel and blocks nothing here.
- Phase 2 (`max_retries=0`, suggest on board weeks, consume-on-cook) is a separate branch.

## Acceptance criteria

- [x] A recipe claiming 244 g protein/serving can no longer be returned as a macro-gap suggestion
- [x] The plausibility bounds flag 45/252 on the live corpus, matching the audit measurement
- [x] Zero previously-trusted implausible recipes remain eligible
- [x] A day whose totals depend on an implausible recipe says so instead of stating a number
- [x] An unplanned week no longer reads as a starvation week
- [x] `/nutrition-review` ranks worst-first by violation magnitude, not ascending coverage
- [x] `/reprocess`, `analyze_failures.sh`, and `/refresh` either work or are gated off
- [x] `/system-health` asserts the silent failures rather than reporting "ok"

---

## Stages

### Planning
- [x] Design doc exists and approved (decisions recorded 2026-08-02)
- [x] Conflict check completed — only `move-cook-by-drag` is active, no file overlap
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (docs/plans/2026-08-02-daily-driver-audit.md §4)

### Dev
- [x] Tests written first (superpowers:test-driven-development)
- [x] Core implementation complete
- [x] All tests passing (3702 passed, 1 skipped)
- [x] No linting/type errors (ruff: no new findings vs main)
- [x] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed (required ON MERGE — com.kitchenos.api holds lib/* in memory)

### Testing
- [x] Unit tests pass — 3702 passed, 1 skipped
- [x] Integration tests pass — e2e 124 passed, 1 skipped, 1 xfailed, 3 xpassed, **1 failed
      (pre-existing, see below)**
- [x] Manual testing completed — assertions run against production data report 5 real
      failures with correct figures; suggester before/after verified on the live corpus
- [x] Edge cases verified — bound inclusivity, garbage frontmatter, null-vs-zero calories,
      probes that raise
- [x] Verified with superpowers:verification-before-completion

**Pre-existing e2e failure, NOT introduced here.**
`test_weekly_loop.py::test_marking_a_plan_card_cooked_creates_a_ledger_row` fails
identically on `main` and on this branch when run in isolation (same assertion, line 281).
Left for Phase 2, because it pins a real defect rather than a flaky test: the legacy grid
card's 🍳 button calls `POST /api/cook`, which decrements inventory and contains **zero**
references to the `cooks` ledger, so the test's "marking a plan card cooked creates a
ledger row" is asserting behaviour that was never wired. The MCP `cook_recipe` tool forks
the same way. Fixing it is the Phase 2 item "unify `/api/cook` with the ledger".

Note also that this test is order-dependent: in a full-suite run it fails *earlier* (line
272, "authored plan rendered no legacy cards") because a preceding test leaves a cook row
on week 2099-W07, which turns that week into a board week so legacy cards stop rendering.
Worth isolating when Phase 2 touches it.

### Docs
- [ ] Doc obligations met per CLAUDE.md table (ARCHITECTURE / API / OPERATIONS / invariants)
- [ ] README updated (if interface changed)
- [ ] ROADMAP usage-feedback entries updated / struck through

### Review
- [ ] Code reviewed
- [ ] Feedback addressed

### Ready
- [ ] Rebased on main
- [ ] Final tests pass
- [ ] All checks complete

---

## Notes

**Why absolute bounds and not an Atwater consistency check.** The obvious validator — does
`4P + 4C + 9F` agree with stated calories — flags exactly **1** recipe out of 248. Calories
and macros derive from the same per-100 g record and the same gram weights, so a wrong gram
weight makes them wrong *proportionally*. The 244 g-protein smoothie agrees with itself to
within 1.4%. Only absolute bounds can see resolution error.

**Measured effect of the gate** (live corpus, real targets of 190 g protein / 2300 kcal,
empty day). Before: Chipotle Burrito (178 g), Tofu Scramble (229 g), PB Smoothie (244 g),
Earl Grey Pie (153 g). After: Chilaquiles (68 g), High Protein Pizza (68 g), Osso Buco
(64 g), Chicken Gyro Bowls (61 g).
