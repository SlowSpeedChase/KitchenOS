# Completed: ingredient-text-fidelity

**Completed:** 2026-08-02
**Branch:** `ingredient-text-fidelity` (merged `aaaac97`)
**Duration:** same day

## Summary

The 145 EPUB cookbook recipes imported earlier the same day carried **no nutrition at
all** — 0 of 145 had calories — so every one was invisible to day totals, the macro
suggester and the new Cook Now ranking. Backfilling them surfaced why the numbers
would have been untrustworthy anyway: **821 ingredient lines could not be converted to
grams.**

The importer turned out to be innocent. Every fix here is in a *reader*, and every one
recovers information the recipe already stated rather than estimating harder.

## Key changes

**1. Group headings are no longer read as food** (`lib/recipe_parser.py`).
`epub_parser` writes ingredient groups as bolded, quantity-less rows because the
template renders one flat table — a group can only *be* a row — and tags them with
`SUBHEAD_MARKER`. That marker dies at the file boundary, so 123 rows reached the
nutrition engine as ingredients named `**for serving**`. Most resolved to nothing;
seven resolved to *real food* — `**coconut-ginger-lime crisp**` scored 15 g / 12 kcal
— so a section heading was counted as a successfully-resolved ingredient. Fixed in
`parse_ingredient_table`, which fixes all seven consumers at once. The markdown file
keeps the row, so Obsidian still renders the group.

**2. Deleted the third copy of the ingredients-section regex**
(`backfill_nutrition.py`). CLAUDE.md names `extract_ingredients_section()` the only
extractor and records that two near-copies both dropped ingredients. This was a third,
matching one *contiguous* run of table rows, so a recipe grouped under `###` headings
lost everything after the first blank line. Chocolate Peanut Butter Bars had been
reported as "skipped — no ingredients" while holding six real ones.

**3. Corroborated dual-unit package weights** (`lib/gram_equivalent.py`, 58 rows / 49
recipes). The module explicitly refused `(15-ounce/425 g)` as "mixing two systems".
That was right for the corpus it was written against and wrong for this one: it is one
quantity glossed in both, and 15 oz *is* 425 g. Now recovered **only when the halves
agree within 5%** — a stronger guarantee than the lone-figure case the module already
trusted, since two independent statements corroborate rather than one being taken on
faith.

**4. Split amount ranges recover their stranded unit** (`lib/ingredient_text.py`, 132
rows / 76 recipes). `"1 1/2 to 2 teaspoons dijon mustard"` parses as amount `1.5`, unit
`whole` (the parser's default for an unreadable unit) and item
`"to 2 teaspoons dijon mustard"` — the real unit stranded in the name, so `to_grams`
had nothing to convert and the leading number derailed the food match. Gated three
ways: unit must be exactly the fabricated `whole`, the stranded word must be a known
unit (so `"to 2 chipotle peppers"` is left alone), and both ends must parse. Midpoint,
matching `units.parse_amount_to_float`.

## Measured

Full corpus, branch vs main, identical vault and DB:

| | main | branch |
|---|---|---|
| Gram-resolution failures | 821 | **599** |
| Stated weights recovered | 414 | **472** |
| Mean coverage | 0.830 | **0.859** |
| Clearing the 0.8 trust bar | 256 | **280** |

92 recipes improved, 2 lower (both heading-as-food corrections). Live corpus after the
`--force` re-derive:

| | session start | after |
|---|---|---|
| Recipes with calories | 254 / 403 | **400 / 403** |
| Trustworthy (`macro_eligible`) | 184 | **235** |
| Cookbook imports with calories | 0 / 145 | **145 / 145** |
| Cookbook imports trustworthy | 0 | **46** |

3874 unit tests pass; ruff unchanged vs main. LaunchAgent restarted and verified
functionally, not just on `/health`: the API returns 11 ingredients for *A Really Good
Pot Of Saucy Beans* with zero `**For Soaking**` rows, while the file still carries them.

## Lessons learned

**The audit column said `grams_method`, not food resolution.** Mid-branch this
invalidated a stated finding of "~297 genuine resolver misses" — the foods almost
always resolve. Re-reading `_print_audit` changed which subsystem the work belonged in.

**Which surfaced something coverage structurally cannot see:** `coriander seeds`
resolves confidently to *Seeds, pumpkin seeds (pepitas)*. A wrong match still counts as
covered, so the metric rises. Same pathology Phase 1 found in `macro_eligible`. Left
untouched — it is Phase 3 item 17 (`resolution_guard.vet` on the fdc-local path).

**Two pre-existing tests had to be deliberately reversed.** `gram_equivalent`'s refusal
of `(15-ounce/440g)` was a documented decision, not an oversight. Moving those cases was
a conscious reversal with the reasoning recorded in the test file, not a test bent to fit
new code — the distinction matters for whoever reads it next.

**A worktree resolves the vault through the parent `.env` only from a script entry
point.** A `python -` heredoc has no `__file__` and falls through to the dead fallback
default in `lib/paths.py`. Both real runs were pinned with explicit `KITCHENOS_VAULT`
and `KITCHENOS_DB` before writing 400 files.

## Still open

1. **~120 low-coverage recipes**, dominated by seasoning with no meaningful amount
   (`kosher salt` 20x, `coriander seeds` 13x). The food resolves; there is nothing to
   convert. These arguably belong in the `to taste` negligible bucket rather than
   counting against coverage — a scoring decision, not a parser fix.
2. **Alternatives** (`"potato starch or arrowroot powder"`, 62 rows) — changes *which*
   food is chosen, so it wants its own before/after.
3. **3 recipes still have no nutrition**: their `## Ingredients` table has a header row
   and no data rows. Extraction produced an empty recipe; they need re-extraction.
