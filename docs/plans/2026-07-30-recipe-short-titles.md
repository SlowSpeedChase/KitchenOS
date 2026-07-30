# Recipe Short Titles Design

**Status:** Done
**Created:** 2026-07-30
**Updated:** 2026-07-30
**Branch:** `recipe-short-titles`

---

## Problem

Recipe names come from the extractor, whose prompt asked for a `recipe_name` without
ever saying it should be a *dish* name. The models reasonably answered with the video
title. Measured across the live vault:

| Name length | Recipes |
|---|---|
| ≤ 24 | 117 |
| 25–32 | 65 |
| 33–40 | 36 |
| 41–55 | 26 |
| > 55 | 8 |

**70 of 252 are over 32 characters.** A planner grid card is about 104 px wide.

Real entries:

- `[감자치즈빵] 화덕에 구운 것 같은 감자치즈빵! (후라이팬으로 맛있는 빵 만들기, Pot`
- `Maple Sweet Potato Salad - With Whipped Tahini And Crispy Chickpeas`
- `Deconstructed Strawberry Cheesecake 20G Protein 🍓 - Youtube`
- `How To Make The Best Chilaquiles Chilaquiles Rojos Recipe`

This is also what made the tap-target work in the sibling doc fragile: `.grid-card-name`
measured 31 px on a 13" iPad and over 44 on an 11" purely because a long name wrapped to
a different number of lines.

## Solution

Two halves, because the corpus and the pipeline need different fixes.

**Going forward** — the extraction prompt now states the rule: `recipe_name` is the name
of the dish, not the title of the video; strip channel names, "Recipe", emoji,
"- YouTube" and clickbait; name non-English dishes in English; keep a qualifier only when
it distinguishes this version from the plain dish. Shared by both extraction prompts via
one `NAMING_RULE` constant so they cannot drift apart.

**The 252 already captured** — an optional `short_title` frontmatter field, LLM-proposed
and validator-checked, surfaced as `display_name`.

### Why not just rename the files

The name is the join key across the whole system: `cooks.recipe` is a name string, meal
plan markdown references names, freezer rows carry names, and `task_extractor` hashes
`recipe|day|slot|step`. Renaming a recipe would **orphan its planned cooks and silently
reset its task checkboxes** — a data loss, in exchange for a cosmetic win. So the filename
stays the identity and only rendering changes.

`display_name` is set on every index entry — including ones whose parse failed — so
consumers can render it unconditionally without knowing whether an override exists.

---

## Design

### The validator is the load-bearing part

An LLM asked to shorten a name, and then told its answer was rejected, starts reaching
into the ingredient list for words. Every rule below was added in response to something a
model actually produced against this repo's recipes.

| Rule | Caught |
|---|---|
| ≤ 32 chars, shorter than the original, ≥ 3 chars | the common near-miss |
| No invented content words | `High-Fiber Shakshuka **Marinara**`, `...**erythritol**, **oats**` |
| Must be a **subsequence** — no reordering | `19 Calorie Fudgy Brownies (Crouton)` → `Fudgy (Crouton) Brownies` |
| Single characters count as words | `Chicken Fricassee **W/** Crouton` slipped through while they didn't |
| No splitting a compound food | `Cottage Cheese Cookie Dough` → `**Cottage** Cookie Dough` |
| No collision with any name or existing short title | `...Dip (Crouton)` → `...Dip`, which already exists |

Subsequence is the key one: shortening is *deleting words*, and deletion preserves both
membership and order. Membership alone stops "Beef Birria" becoming "Chicken Tacos";
order additionally stops the reshuffles that pass a set check and still read wrong.

**Non-Latin names are exempt from subsequence**, because they must be *translated* to be
readable, which legitimately introduces words the original never had — and those are
exactly the names that need this most. `is_latin()` decides, and treats accented Latin
(`Fricassée`, `Çılbır`) as Latin so it doesn't hand them a free pass.

### Retry with the reason fed back

The single largest rejection cause was a title a few characters over the limit — fixable
when the model is told, impossible when it is not asked again. Feeding the validator's own
reason back into the next attempt moved Ollama from 5/16 to 8/16 accepted. It also makes
the model reach for invented words under pressure, which is precisely what the validator
is there to catch.

### Provider

`--provider ollama|claude`, matching `build_portion_ledger.py`. Measured on the same 16
recipes: **Ollama 8/16, Claude 13/16**, same validator. Default stays `ollama` (local-first),
but the backfill was run with Claude.

---

## Results

Run against all 252 with `--provider claude`:

- **69 short titles written**, 1 rejected after 6 attempts
- **2 written by hand** afterwards, through the same validator — `Chocolate Peanut Butter
  Protein Pancake Bowl` came back as `Chocolate Peanut Butter Protein`, which passes every
  rule and names no dish (the head noun is not reliably last, so this is not a rule the
  validator can carry), and `Ham Cheddar + Chive Protein Biscuits` never got under 33
- **Zero display-name collisions** across all 252
- **Every rendered title now ≤ 32 chars** (max 32, verified in the browser)
- All 71 carry `short_title_inferred: true` — same honesty rule as `servings_inferred`

**A data bug surfaced:** `Roasted Chicken & Mediterranean Avocado Sala` is truncated *at
the source* — the recipe's own name is missing the "d" in "Salad". Its short title
faithfully preserves the typo. Not fixed here; noted because it means some names were
already being cut off before this work.

---

## Implementation Notes

| File | Change |
|---|---|
| `lib/short_title.py` | **New.** Pure validation + `display_name`. Deliberately dependency-free — `recipe_index` imports it and is itself imported by seven modules, so a network client here would sit on the whole app's import path |
| `lib/recipe_index.py` | `short_title` + `display_name` on every entry |
| `lib/food_resolver.py` | `json_call(prompt, provider)` — one public LLM entry point, so the next constrained job doesn't grow a second client that drifts |
| `prompts/recipe_extraction.py` | Shared `NAMING_RULE`; new `SHORT_TITLE_PROMPT` |
| `scripts/backfill_short_titles.py` | **New.** Dry-run by default, `--provider`, `--attempts`, `--redo` |
| `templates/meal_planner.html` | Shelf cards, grid cards, unscheduled rows, freezer chips render `display_name` with the full name on `title=`. The action sheet keeps the full name — it has room, and the short title exists for cards, not to hide what a recipe is called |
| `CLAUDE.md` | New invariant: the name is the identity, `short_title` is not |

**Tests:** 37 in `tests/test_short_title.py` (every rejection case is a real model output),
3 in `tests/test_recipe_index.py`, and the e2e tap-to-assign test now pins display-vs-identity
— the card renders the short title while the cook is created under the real name.

3036 unit / 90 e2e pass. Zero new ruff errors.

---

## Links

- Sibling: [planner-shelf-and-tap-to-assign](2026-07-30-planner-shelf-and-tap-to-assign.md)
- Still open: relocating Today's Prep, and the Use It Up rework
