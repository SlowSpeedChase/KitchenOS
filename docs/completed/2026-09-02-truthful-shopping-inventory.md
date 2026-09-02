# Completed: Truthful shopping inventory comparison

**Completed:** 2026-09-02
**Branches:** `phase-4/truthful-shopping-list`, `phase-4/shopping-list-inventory-split`
**Pull requests:** [#78](https://github.com/SlowSpeedChase/KitchenOS/pull/78), [#79](https://github.com/SlowSpeedChase/KitchenOS/pull/79)
**Duration:** 2 days (started 2026-09-01)

## Summary

KitchenOS now compares weekly recipe demand against inventory without silently
claiming that related foods or unknown package quantities satisfy a recipe. The
weekly note separates unmatched purchases from every inventory match, and only
purchase checkboxes reach Apple Reminders.

## Key changes

- Added precision-first inventory dispositions: buy, credited, review, and excluded.
- Required exact normalized identity and compatible measurable quantities before
  an automatic credit; broad matches remain visible for human verification.
- Rendered **Need to purchase** checkboxes separately from plain-bullet
  **Inventory matches — verify** evidence.
- Made the purchase-only contract consistent across the one-shot API, CLI, print
  packet, and planner preview/confirm flow.
- Preserved manual quantity variants during legacy-note migration.
- Made alias confirmation spend the concrete matched inventory row.
- Excluded expired stock and household water/ice demand; repaired bell-pepper
  alternatives and embedded scoop measurements.

## Verification

- Final default suite: 4,207 passed, 1 skipped, 133 deselected.
- Independent review: no remaining Critical, Important, or Minor findings.
- Live W36: 69 demand lines produced 29 purchase checkboxes, 39 inventory-match
  bullets, and 1 excluded household item.
- Pistachios appear only as an inventory match, not a purchase.
- Saved note sections exactly matched the preview; the inventory-table hash was
  unchanged before and after generation; Reminders was not invoked.

## Design documents

- [Design](../superpowers/specs/2026-09-01-truthful-shopping-inventory-design.md)
- [Implementation plan](../superpowers/plans/2026-09-01-truthful-shopping-inventory.md)

## Lessons learned

- One canonical purchase field is safer than parallel fields with different
  meanings; consumer drift had allowed review matches back into older flows.
- Legacy provenance must fail conservatively: an extra checkbox is safer than
  silently deleting a plausible manual purchase.
- Confirmation decisions must target the matched inventory row, not the recipe
  alias that led to it.
- A live fixture and an inventory hash exposed truthfulness better than unit
  counts alone: the note, parser, preview, and database all had to agree.
