# Completed: Cook Now Meal-Type Filter

**Completed:** 2026-07-25
**Branch:** cook-now-meal-type-filter
**Duration:** 1 day (started 2026-07-25)
**Design:** `docs/superpowers/specs/2026-07-25-cook-now-meal-type-filter-design.md`
**Plan:** `docs/superpowers/plans/2026-07-25-cook-now-meal-type-filter.md`

## Summary

Cook Now can now be filtered by meal type, so reviewing "what could I cook right
now?" no longer surfaces 47 desserts among the dinner candidates.

The filter needed a field to filter *on*, and `dish_type` was not trustworthy:
12 recipes carried one-off values (`Dinner`, `Tostada`, `Shakshuka`, `biscuits`,
`mocktail`, `Breakfast Pastry`, `savory pie`, `smoothie mix`, `pasta alternative`,
`Salad dressing`, `dessert or snack`), and the dessert bucket was contaminated
because `normalizer.py` mapped `"biscuit" → "dessert"`. So half this branch is a
data repair and half is the feature.

## Key Changes

### 1. `dish_type` became a closed, self-describing vocabulary (`lib/normalizer.py`)

`VALID_DISH_TYPES` is defined as `set(DISH_TYPE_MAP.values())` — derived rather
than hand-listed, so the vocabulary cannot drift from the normalizer that
produces it. Thirteen values: `main, breakfast, side, salad, soup, sandwich,
bread, snack, appetizer, dip, dessert, drink, sauce`.

`dip` is in the list because it was already canonical in `DISH_TYPE_MAP` and two
recipes use it. Folding it into `appetizer` would have reclassified working data
for no benefit.

### 2. The `biscuit → dessert` rule was deleted, not just worked around

This was the root cause, and it had a rot property: repairing the data without
deleting the rule would have re-corrupted the next extracted biscuit recipe. The
one-off repair would have had a built-in expiry date.

`Butter Biscuits` is the live example — it looked perfectly well-formed as a
`dessert`, which is why a hand-written mapping of the visible strays would not
have caught it, and why the repair was done with an LLM pass over all 239
recipes rather than a lookup table for the 12.

### 3. `scripts/reclassify_dish_type.py` — the one-off repair

One Claude Batches job over every recipe, with `output_config.format` →
`json_schema` whose `dish_type` is an **enum of the 13 values**, so an
out-of-vocabulary answer is structurally impossible and no validation branch
can drift from `normalizer.py`.

Dry-run by default; `--apply` writes frontmatter through
`frontmatter.apply(..., managed_keys=("dish_type",))` after `create_backup()`.
Results are keyed by `custom_id` (the recipe's *index*, since the field forbids
the emoji and apostrophes in names like `Arayes 🥙` and `Hardee's Biscuits`),
never by position — batch results arrive in arbitrary order. Every recipe lands
in exactly one of CHANGE / KEEP / UNRESOLVED, so nothing is silently dropped.

**Run against the real vault:** 63 changed, 176 kept, 0 unresolved, of 239.
63 backups in `Recipes/.history/`. All five biscuit recipes — previously spread
across `dessert`, `biscuits`, `bread`, `side`, `breakfast` — are now `bread`.

### 4. Six chip groups over thirteen values (`lib/cook_now.py`)

`DISH_TYPE_GROUPS` keeps the stored data precise and the interface usable:
Mains (`main, sandwich, soup`), Breakfast, Sides (`side, salad, bread, sauce`),
Snacks (`snack, appetizer, dip`), Desserts, Drinks. `generate()` entries gained
`dish_type` and `group`.

`group_for()` falls back to `Mains` for anything unknown, missing, or
non-string. That last case is not hypothetical: `lib/recipe_parser.py` yields a
list for `dish_type: [dessert]` and an int for `dish_type: 2`, and without the
guard a single malformed line in any one of 239 files would have raised
`AttributeError` inside `generate()` and 500'd the entire endpoint.

`Cook Now.md` is byte-identical — `render_markdown()` reads named keys, verified
by rendering pre- and post-change versions and diffing.

### 5. `/cook-now` and `GET /api/cook-now`

The endpoint never filters; it serves the ranking with a `group` per recipe and
the page filters client-side from one payload, so a chip toggle costs no round
trip. Desserts starts deselected — the point of the feature — with the chip left
visible in its off state and a count of what is hidden.

Registered in `SECTIONS`, so it reached the vault launcher note, the `/` home
page, and Safari bookmarks (9 pages verified after sync).

## Notable Fixes Found in Review

- **`loadSelection()` conflated two states.** Turning off *every* chip persisted
  `[]`, which the falsy-length check treated as "stored names are all stale",
  silently re-enabling five chips on reload. Now distinguished by the parsed
  array's length before filtering, with an `Array.isArray` guard.
- **Nothing tied the page's `GROUPS` array to the Python taxonomy.** Renaming
  `Sides` → `Side` in `lib/cook_now.py` left every test passing while making 48
  recipes permanently unreachable — counted as "hidden" with no chip able to
  reveal them. `TestTemplateGroupsMatchTaxonomy` now parses the template's array
  and compares it; verified by mutation.
- **`?limit=-5` returned the worst-covered recipes** (`or 30` plus a negative
  slice). Now: absent → 30, negative → clamped to 0, `0` → empty list.
- **A tautological test was deleted** rather than kept for the count — it
  asserted `set(DISH_TYPE_MAP.values()) == VALID_DISH_TYPES` against a
  `VALID_DISH_TYPES` defined as exactly that.

## Testing

1476 → 1504 tests, plus 3 new Playwright tests (22 → 25 e2e). The browser tests
pin the behaviour that matters: desserts hidden on first load with no user
action, a toggle that reveals them without refetching, and selection surviving a
reload.

## Follow-ups (not blocking)

- `reclassify --apply` re-runs `classify()`, submitting a second paid batch — so
  what gets written can differ from the dry-run that was approved. Avoided at run
  time by re-fetching the original batch by ID. If it is ever run again, have the
  dry run write a sidecar that `--apply` consumes.
- `classify()`'s poll loop has no timeout or retry cap.
- `/api/use-it-up` has the same `limit=0` / negative-slice bug that was fixed on
  `/api/cook-now`; left alone as out of scope for this branch.
- No JS test harness, so `localStorage` logic is covered only by the e2e tests
  and inspection.
- The "N recipes hidden" count describes the fetched payload (`limit=60`), not
  the whole library.
