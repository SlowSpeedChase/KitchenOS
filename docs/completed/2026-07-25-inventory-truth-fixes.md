# Completed: Inventory Truth Fixes

**Completed:** 2026-07-25
**Branch:** inventory-truth-fixes
**Duration:** 1 day (started 2026-07-25)

## Summary

Three defects surfaced by a plain question — "what can I actually cook right
now?". `Inventory.md` was rendering an empty table while the database held 219
items, and `Cook Now.md` was ranking almost entirely desserts.

## Key Changes

### 1. Generated views had two sources of truth (`lib/inventory.py`)

`write_inventory()` rendered `Inventory.md` from the caller's list, then called
`cook_now.write_note()`, which re-reads the DB. One function, two sources — a
stale or empty argument produced two notes that disagreed with no error raised.
Observed in production: `Inventory.md` and `Cook Now.md` both written at 17:08
while the DB's mtime stayed at 12:41, so the empty list never reached the
database. The view now renders from the committed rows.

**Root cause not found.** Nothing identified *which* caller passed the empty
list. The fix makes the view self-correcting regardless, but the trigger is
still unexplained.

### 2. Token matching produced false positives (`lib/use_it_up.py`, `lib/recipe_matcher.py`)

`_matches`/`_is_staple` used a bare bidirectional subset test, so any
single-token ingredient matched every longer inventory name containing that
word: "eggs" ↔ *Lo mein egg noodles*, "butter" ↔ *Peanut butter*, "lemon" ↔
*Lemon pepper seasoning*, "avocado" ↔ *Avocado oil*, "ground beef" ↔ *Beef
broth*.

Containment into a **clean** name (inventory row or configured staple) must now
reach that name's head noun — English food phrases are head-final, so the last
content word is what the phrase *is*. Free-text recipe ingredients keep plain
containment, because their trailing words are preparation notes ("butter
(melted)"), not a different food. That asymmetry — clean names are strict, recipe
text is not — is the core of the design.

Two refinements the real library forced out:
- **Cut/form words are skipped when finding a head** (`_PART_WORDS`), so
  "chicken breasts" is still chicken and "coriander powder" is still coriander.
- **Compound foods** (`_ATOMIC_FOODS`: peanut butter, coconut milk, …) match only
  something naming the whole compound — not the bare staple, but still their own
  prep-note variants ("creamy peanut butter jif…").

### 3. Staples were an invisible assumption (`lib/inventory.py`)

`config/pantry_staples.json` credited butter/milk/eggs/garlic/onion as on-hand
without them existing in inventory, so recipes read 100% that couldn't be made.
`seed_pantry_staples()` materializes them as perpetual rows (`source: staple`,
no `expires`) — never pruned, never flagged at-risk, deduped against equivalent
stock so a receipt's "Salted Butter" absorbs the "butter" staple rather than
duplicating it. New `staple` entry in `SOURCES`.

## Verification

1426 tests pass (1404 → 1426, +22 new, each watched fail first).

Measured against the real 219-item DB across all 236 recipes: **60 recipes lost
inflated coverage, 54 distinct false-positive ingredients eliminated, zero true
matches regressed.**

Four false-negative classes were introduced and fixed during the pass — each
found by diffing real data, not by the unit tests:
- prep notes (`butter (melted)`, `unsalted butter, softened`) — fixed by the
  strict/non-strict split;
- form words (`Coriander powder` ↔ `ground coriander`, `Dried dill weed` ↔
  `dill`) — fixed by `_PART_WORDS`;
- atomic over-blocking (`Peanut butter` ↔ `creamy peanut butter jif…`,
  `Canned coconut milk` ↔ `coconut milk (chilled)`) — fixed by requiring the
  atomic core in both phrases rather than rejecting outright.

**Accepted remaining misses** (need modifier-aware matching; forcing them
reopens the false positives): `chipotle powder` vs *Chipotle chili powder*,
`cayenne` vs *Cayenne pepper*, `coarse cornmeal` vs *Yellow cornmeal mix*.

## Design Doc

None — bugfix branch. Scope confirmed with the user before implementation
(staples kept as an assumption but materialized; matcher limited to false
positives, no synonym/substitution layer).

## Lessons Learned

- **Unit tests passed a design that real data disproved.** The first head-noun
  implementation was green on the whole suite and still wrong — recipe ingredient
  text is far noisier than any fixture. The before/after diff over all 236
  recipes is what caught it, and it caught four separate classes. For a matcher
  change, a corpus diff is not optional.
- **Two sources of truth in one function is the whole bug.** The view and Cook
  Now disagreed only because one read an argument and the other read the DB.
  Recorded as a CLAUDE.md invariant: generated views read the DB after the commit.
- **An invisible assumption reads as a data error.** Staples being credited
  without existing made Cook Now look broken rather than optimistic. Making the
  assumption a visible row cost little and removed a whole class of confusion.
