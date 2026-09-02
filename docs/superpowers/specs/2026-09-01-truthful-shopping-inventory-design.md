# Truthful Shopping Inventory Comparison Design

**Status:** Approved / In Progress
**Branch:** `phase-4/truthful-shopping-list`
**Date:** 2026-09-01

## Problem

KitchenOS currently uses the broad head-noun matcher from recipe discovery to
remove shopping demand. On the live 2026-W36 plan this credited bone-in chicken
breast from canned chicken breast, garlic from garlic powder, onion from
caramelized onions, and raw potatoes from diced fried potatoes. A false credit
is worse than a false negative: buying a duplicate is inconvenient, while
omitting a required ingredient can make the planned meal impossible.

The same run exposed two adjacent honesty defects. Inventory `ct` values usually
mean “one package exists,” but the reconciler treats them as an ingredient count.
The shopping normalizer also truncates at every comma, turning “medium red,
orange, or yellow bell pepper” into “red.” Finally, unit conflicts appear under
“Already have” even though no credit occurred.

## Decision

Shopping reconciliation becomes precision-first while broad matching remains
available for discovery and Cook Now.

Every demand line receives one disposition:

- `credited`: the inventory identity is exact after shopping normalization and
  the quantities are convertible.
- `review`: a related inventory row exists, but identity, package quantity, or
  units are uncertain. The full demand remains on the buy list.
- `buy`: no inventory candidate exists. The full or remaining demand is bought.
- `excluded`: a household supply such as water or ice; it is not shoppable.

The broad matcher may nominate a related row, but it may not authorize a credit.
Automatic credit requires exact normalized identity. An inventory `ct` may only
credit a recipe `ct`; against `whole`, `each`, `clove`, weight, or volume it is a
package-presence signal and becomes `review`.

## Output

The weekly note has three honest surfaces:

- `Items`: checkboxes sent to Reminders.
- `Already have`: only quantities actually credited.
- `Check pantry`: plain bullets naming the related inventory row and why it was
  not credited. The item remains in `Items`.

Water and ice are omitted entirely. Generation remains read-only with respect to
inventory.

## Ingredient normalization

Comma stripping remains for ordinary preparation suffixes such as “red onion,
thinly sliced.” When a line contains comma-separated alternatives joined by
“or,” the alternatives are preserved and only a final preparation suffix is
removed. This keeps “red, orange, or yellow bell pepper” intact.

An embedded spelled measurement such as `1 whole one scoop protein powder` is
recovered before scaling as `1 scoop protein powder`, so a 5× cook renders as
`5 scoops protein powder`.

## Scope

### Included

- Precision-first shopping disposition and transparent match metadata.
- Exact-identity and package-count guards.
- Expired rows excluded from comparison.
- Honest note sections.
- Comma-alternative and embedded-scoop repair.
- Water/ice exclusion.
- W36-derived regression tests and live regeneration audit.

### Deferred

- Inventory schema changes for package size, usable amount, and food form.
- Grocery-package rounding (`2 eggs` → `1 dozen`).
- Bulk repair of historical recipe Markdown.
- Interactive per-line confirmation in the native app.

## Acceptance criteria

- Bone-in chicken never receives credit from canned chicken.
- Garlic never receives credit from garlic powder.
- Onion never receives credit from caramelized onion.
- Raw potatoes never receive credit from fried potatoes.
- A `ct` package cannot credit a non-`ct` demand.
- Exact, convertible quantities still receive full or partial credit.
- Expired inventory never receives credit.
- Warning/review lines stay in `Items` and appear only under `Check pantry`.
- `Already have` contains only real credits.
- Bell-pepper alternatives remain a complete ingredient name.
- Embedded scoop measurements scale as scoops.
- Water and ice do not appear in the shopping note.
- W36 regeneration produces zero false automatic credits for the known cases.
- Targeted tests and the full default suite pass.

## ADHD and scope checks

- The failure direction is visible: uncertainty becomes one `Check pantry`
  section instead of silent omission.
- No per-item chore is added to generation; the existing checklist remains the
  primary shopping surface.
- The change is under one focused week and does not require a data migration.
- No external blocker exists.
