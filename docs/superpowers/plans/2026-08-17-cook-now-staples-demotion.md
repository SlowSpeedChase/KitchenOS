# Cook Now All-Staples Demotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recipes made entirely of pantry staples (homemade pasta, doughs, spice blends) sink to the bottom of Cook Now instead of squatting at the top forever.

**Architecture:** `recipe_coverage` (the single coverage authority in `lib/use_it_up.py`) additionally reports how many ingredients matched as staples, in its existing single pass. `lib/cook_now.py` gains a seventh multiplicative score factor `_ALL_STAPLES_WEIGHT = 0.25`, applied only when `staple_count == total`, plus an `all_staples` payload field. Every surface (`/cook-now`, `/api/cook-now`, `Cook Now.md`, Kitchen Today) renders from `cook_now.generate`, so all inherit the reordering with no UI change.

**Tech Stack:** Python 3.11 (always `.venv/bin/python`), pytest, Flask (no route changes).

**Spec:** `docs/superpowers/specs/2026-08-17-cook-now-staples-demotion-design.md`

## Global Constraints

- Repo: `/Users/chaseeasterling/Dev/KitchenOS`. Work happens in a worktree branch `cook-now-staples-demotion` under `.worktrees/` (GitOps).
- Run everything via `.venv/bin/python`; test suite is `.venv/bin/python -m pytest` from the worktree root (e2e is excluded by `pytest.ini` `addopts = -m "not e2e"`; corpus tests auto-resolve the vault through the main checkout — no special handling).
- `recipe_coverage`'s existing fields (`have`, `total`, `missing`, `uses_at_risk`) must be **unchanged** for identical inputs — the demotion may not fork coverage semantics.
- Failure direction: an unparseable ingredient counts as a non-staple, so a data gap makes a recipe *less* likely to be demoted, never buried.
- Coverage stays a single pass — `_ingredient_phrase` is the expensive part and the page has a 135 ms budget. No second classification loop.
- Commit format (repo CLAUDE.md): `type: short description` body trailer lines:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01BCSAXpoc7E7mUTKxPwDdnM`
- Post-merge only: the `com.kitchenos.api` LaunchAgent holds `lib/*` in memory — editing `lib/` requires a LaunchAgent restart or the server serves stale code (Task 3 final step).

---

### Task 1: `recipe_coverage` reports the staple count (5-tuple)

**Files:**
- Modify: `lib/use_it_up.py:248-281` (`recipe_coverage`), `lib/use_it_up.py:334` (`suggest`'s unpacking)
- Modify: `lib/cook_now.py:297` (unpacking only — the new value is consumed in Task 2)
- Test: `tests/test_use_it_up.py` (new `TestRecipeCoverage` class)

**Interfaces:**
- Consumes: existing `use_it_up._is_staple(phrase, staple_phrases) -> bool`, `_staple_phrases(staples: Optional[set]) -> list[Phrase]`, `_phrase(name) -> Phrase`, `_ingredient_phrase(text) -> Phrase`.
- Produces: `recipe_coverage(ingredients, inv_phrases, staple_sets, at_risk_sets=None) -> tuple[int, int, list[str], bool, int]` — the fifth element `staple_count` is the number of ingredients matched by `_is_staple`, whether or not they also matched inventory (staples are real inventory rows now; the count means "credited by the staple rule", not "absent from stock"). Task 2 relies on this exact position and meaning.

- [ ] **Step 0: Create the worktree and branch (GitOps)**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git worktree add -b cook-now-staples-demotion .worktrees/cook-now-staples-demotion main
cd .worktrees/cook-now-staples-demotion
cp templates/BRANCH-STATUS.md ./BRANCH-STATUS.md
```

Fill BRANCH-STATUS.md's header (branch name, date, link to the spec) and check off its planning items. All later steps run from this worktree directory.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_use_it_up.py` (the file already has `from lib import use_it_up` and `from lib.use_it_up import _covers, _ingredient_phrase, _phrase` at the top — no new imports needed):

```python
class TestRecipeCoverage:
    """Direct contract tests for the shared coverage authority.

    The 5-tuple's fifth element, ``staple_count``, is what lets ``cook_now``
    demote recipes made entirely of staples. The first four elements are the
    pre-existing contract and must not move for the same inputs.
    """

    STAPLES = {"salt", "olive oil", "flour"}

    def _coverage(self, ingredients, on_hand):
        inv = [_phrase(name) for name in on_hand]
        staples = use_it_up._staple_phrases(self.STAPLES)
        return use_it_up.recipe_coverage(ingredients, inv, staples)

    def test_mixed_list_counts_only_the_staples(self):
        have, total, missing, at_risk, staples = self._coverage(
            ["chicken", "salt", "olive oil"], on_hand=["Chicken"])
        assert (have, total) == (3, 3)
        assert missing == []
        assert staples == 2

    def test_no_staples_counts_zero(self):
        *_, staples = self._coverage(
            ["chicken", "broccoli"], on_hand=["Chicken"])
        assert staples == 0

    def test_all_staples_equals_total_even_with_empty_inventory(self):
        have, total, missing, at_risk, staples = self._coverage(
            ["flour", "salt", "olive oil"], on_hand=[])
        assert staples == total == 3
        assert have == 3 and missing == []

    def test_a_staple_also_in_inventory_still_counts_as_a_staple(self):
        # The count means "credited by the staple rule", not "absent from
        # stock" — staples are real inventory rows now, so most are both.
        *_, staples = self._coverage(["salt"], on_hand=["Salt"])
        assert staples == 1

    def test_existing_fields_unchanged(self):
        have, total, missing, at_risk, _ = self._coverage(
            ["chicken", "broccoli", "salt"], on_hand=["Chicken"])
        assert (have, total) == (2, 3)
        assert missing == ["broccoli"]
        assert at_risk is False
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_use_it_up.py::TestRecipeCoverage -v`
Expected: all 5 FAIL with `ValueError: not enough values to unpack (expected 5, got 4)`.

- [ ] **Step 3: Implement the 5-tuple**

In `lib/use_it_up.py`, `recipe_coverage` — change the signature's return annotation, the docstring's return line, and the loop body. The full function after the edit:

```python
def recipe_coverage(ingredients: list[str], inv_phrases: list[Phrase],
                    staple_sets: list[Phrase],
                    at_risk_sets: Optional[list[Phrase]] = None
                    ) -> tuple[int, int, list[str], bool, int]:
    """How much of a recipe you already have.

    Returns ``(have, total, missing, uses_at_risk, staple_count)``. Staples
    count as always-on-hand: they raise coverage and never appear in
    ``missing``. ``staple_count`` is how many ingredients the staple rule
    credited — whether or not they also matched an inventory row (staples are
    real inventory rows now, so most do both). ``cook_now`` demotes a recipe
    whose entire list is staples; ``suggest`` discards the count. Matching is
    presence-only, not quantity-aware. ``uses_at_risk`` is False whenever
    ``at_risk_sets`` is omitted.

    The single authority for this calculation. ``cook_now.generate`` ranks the
    whole library by it and ``suggest`` ranks each at-risk item's recipes by it —
    and this repo has already been bitten by two modules hand-writing the same
    rule (``unit_compatibility``, where the shopping list credited limes the cook
    then refused to spend). It lives here rather than in ``cook_now`` because
    ``cook_now`` already imports this module's matching machinery, so the
    dependency only points one way.

    One pass on purpose: it runs over the whole library (252 recipes x ~10
    ingredients) on a page with a 135 ms budget, and ``_ingredient_phrase`` is
    the expensive part — so at-risk and the staple count are detected here
    rather than in a second loop that would parse every ingredient twice.
    """
    missing: list[str] = []
    staple_count = 0
    uses_at_risk = False
    for ing in ingredients:
        phrase = _ingredient_phrase(ing)
        is_staple = _is_staple(phrase, staple_sets)
        if is_staple:
            staple_count += 1
        if not (is_staple or _matches(phrase, inv_phrases)):
            missing.append(ing)
        if at_risk_sets and not uses_at_risk and _matches(phrase, at_risk_sets):
            uses_at_risk = True
    total = len(ingredients)
    return total - len(missing), total, missing, uses_at_risk, staple_count
```

Then update both unpacking call sites in the same commit:

`lib/use_it_up.py:334` (inside `suggest` — it discards the count; an all-staples recipe can never appear here, since `at_risk_items` skips staples so no staple is ever the at-risk item a candidate must use):

```python
        have, total, missing, _, _ = recipe_coverage(ingredients, inv_phrases, staple_sets)
```

`lib/cook_now.py:297` (capture now, consume in Task 2):

```python
        have, total, missing, at_risk, staple_count = recipe_coverage(
            ingredients, inv_phrases, staple_sets, at_risk_sets)
```

- [ ] **Step 4: Run the tests to verify they pass — and that nothing else moved**

Run: `.venv/bin/python -m pytest tests/test_use_it_up.py tests/test_cook_now.py -v`
Expected: all PASS (the new 5, plus every pre-existing test untouched).

- [ ] **Step 5: Commit**

```bash
git add tests/test_use_it_up.py lib/use_it_up.py lib/cook_now.py BRANCH-STATUS.md
git commit -m "feat: recipe_coverage reports staple_count (5-tuple)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BCSAXpoc7E7mUTKxPwDdnM"
```

---

### Task 2: The demotion factor and `all_staples` payload field

**Files:**
- Modify: `lib/cook_now.py` (module docstring, new constant near `_BANKED_WEIGHT` at line ~168, `generate`'s docstring/loop/payload at lines ~241-337)
- Test: `tests/test_cook_now.py` (new `TestAllStaplesDemotion` class)

**Interfaces:**
- Consumes: `recipe_coverage(...) -> (have, total, missing, uses_at_risk, staple_count)` from Task 1 — `staple_count` already captured at `lib/cook_now.py:297`.
- Produces: `cook_now._ALL_STAPLES_WEIGHT = 0.25` (module constant); each `generate` payload entry gains `"all_staples": bool` and its `"score"` includes the factor. `tests/test_cook_now.py` fixture facts this task leans on: `Plain Rice` = `["rice", "salt", "olive oil"]` — all three are in `config/pantry_staples.json`, so it is already an all-staples fixture; `Chicken Dinner` = `["boneless skinless chicken breasts", "rice", "broccoli"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cook_now.py`, and add `import pytest` to its imports (currently `re`, `datetime`, `pathlib`, `InventoryItem`, `cook_now` — pytest is not yet imported):

```python
class TestAllStaplesDemotion:
    """A recipe made entirely of staples must sink, not squat.

    Plain Rice (rice + salt + olive oil, all pantry staples) is perpetually
    at 100% coverage because staples never age out — before this factor it
    outranked every partially-covered real dinner, forever.
    """

    def test_all_staples_flag_reported(self):
        result = cook_now.generate([_item("Rice")], RECIPES, today=TODAY)
        rice = next(r for r in result["recipes"] if r["recipe"] == "Plain Rice")
        chicken = next(r for r in result["recipes"] if r["recipe"] == "Chicken Dinner")
        assert rice["all_staples"] is True
        assert chicken["all_staples"] is False

    def test_every_entry_carries_the_flag(self):
        result = cook_now.generate([_item("Chicken")], RECIPES, today=TODAY)
        assert result["recipes"], "fixture produced no entries"
        assert all(isinstance(r["all_staples"], bool) for r in result["recipes"])

    def test_sinks_below_a_partially_covered_real_main(self):
        # Only chicken on hand: Chicken Dinner is 2/3 covered (rice is a
        # staple, broccoli missing) — a real dinner you're one item short of.
        # Plain Rice is 100% covered but every bit of it is the staple
        # assumption. The near-miss dinner must outrank the squatter.
        items = [_item("Chicken")]
        result = cook_now.generate(items, RECIPES, today=TODAY)
        names = [r["recipe"] for r in result["recipes"]]
        assert names.index("Chicken Dinner") < names.index("Plain Rice")

    def test_one_real_ingredient_escapes_demotion(self):
        # Same coverage (100%), same default tier/nutrition/speed/yield —
        # the only differing factor is the demotion, so the score ratio IS
        # the weight. Pins that a single real ingredient escapes entirely.
        recipes = RECIPES + [
            {"name": "Garlic Butter Chicken",
             "ingredient_items": ["chicken", "butter", "salt"]},
        ]
        items = [_item("Chicken"), _item("Rice")]
        result = cook_now.generate(items, recipes, today=TODAY)
        gbc = next(r for r in result["recipes"]
                   if r["recipe"] == "Garlic Butter Chicken")
        rice = next(r for r in result["recipes"] if r["recipe"] == "Plain Rice")
        assert gbc["all_staples"] is False
        assert rice["all_staples"] is True
        assert gbc["score"] > rice["score"]
        assert rice["score"] == pytest.approx(
            gbc["score"] * cook_now._ALL_STAPLES_WEIGHT, abs=1e-3)

    def test_demoted_harder_than_banked(self):
        # A banked demotion expires (the freezer empties); all-staples never
        # does. Pinned so future tuning keeps that ordering argument.
        assert cook_now._ALL_STAPLES_WEIGHT < cook_now._BANKED_WEIGHT
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cook_now.py::TestAllStaplesDemotion -v`
Expected: all 5 FAIL — the first four with `KeyError: 'all_staples'`, the last with `AttributeError: module 'lib.cook_now' has no attribute '_ALL_STAPLES_WEIGHT'`.

- [ ] **Step 3: Implement the factor**

Four edits in `lib/cook_now.py`.

**(a)** Module docstring — the staples paragraph (currently lines 13-14) becomes:

```
Staples are assumed always on hand: never "missing", never penalizing
coverage. A recipe made *entirely* of staples is demoted hard rather than
hidden — see ``_ALL_STAPLES_WEIGHT``. Matching is presence-only, not
quantity-aware.
```

**(b)** New constant directly below the `_BANKED_WEIGHT = 0.5` block (line ~168):

```python
# A recipe made entirely of staples — pasta dough, spice blends, plain
# pancakes — is perpetually "ready": staples never age out, so its coverage
# never moves and it squats at the top of a list being asked "what should I
# make". Demoted rather than hidden, same philosophy as _BANKED_WEIGHT
# (fresh-pasta night is real, so it stays findable by scrolling), but harder:
# a banked demotion expires when the freezer empties, an all-staples recipe
# never stops being all-staples. One real ingredient is enough to escape —
# then the recipe only ranks high when that ingredient is actually on hand,
# which is a legitimate claim on the top of the list. An unparseable
# ingredient counts as a non-staple, so a data gap escapes the demotion
# rather than triggering it.
_ALL_STAPLES_WEIGHT = 0.25
```

**(c)** `generate`'s docstring: first line of the factor sentence changes from "Six factors, multiplied:" to:

```
    Seven factors, multiplied: **coverage** (can you make it) × **meal tier**
    (is it a meal) × **nutrition** (will it feed you) × **speed** (how long
    until it's on the table) × **yield** (how many meals one session buys) ×
    **banked** (is it already cooked and in the freezer) × **all-staples**
    (is its readiness anything more than the staple assumption). Coverage
    alone answered a different question than the one the page is asked — on a
    pantry of dry goods it returned muffins, brownies, cookies and frosting,
    all correctly and none of them dinner.
```

and the return-shape line gains the two fields the current docstring is missing (`freezes_well` was already in the payload but undocumented — fix in passing):

```
    Returns ``{"recipes": [...]}``, each entry ``{recipe, image, dish_type,
    group, have, total, coverage, missing, at_risk, meal_tier, protein,
    minutes, servings, banked, freezes_well, all_staples, score}``, sorted by
    ``score`` descending and capped at ``limit``. Every non-coverage factor is
    reported alongside it so a surface can explain the order rather than
    presenting it as given.
```

**(d)** In the loop (line ~305), beside `is_banked`:

```python
        is_banked = recipe["name"] in banked
        # total >= 1 is guaranteed: empty ingredient lists are skipped above.
        all_staples = staple_count == total
```

and in the payload dict, after `"banked": is_banked,`:

```python
            "banked": is_banked,
            "all_staples": all_staples,
```

and the score expression gains the factor beside the banked term:

```python
            "score": round(
                coverage
                * _TIER_WEIGHT[tier]
                * _nutrition_factor(protein, protein_target)
                * _speed_factor(minutes)
                * _yield_factor(servings)
                * (_BANKED_WEIGHT if is_banked else 1.0)
                * (_ALL_STAPLES_WEIGHT if all_staples else 1.0),
                4,
            ),
```

- [ ] **Step 4: Run the module's tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cook_now.py tests/test_use_it_up.py -v`
Expected: all PASS. Pre-existing tests must survive unchanged — they assert coverage/missing/groups, which this factor does not touch (`test_ranks_by_coverage` still has Chicken Dinner first: fully covered and now definitively above the demoted Plain Rice instead of tied with it).

- [ ] **Step 5: Run the API-level and downstream tests**

Run: `.venv/bin/python -m pytest tests/test_api_cook_now.py tests/test_kitchen_today.py tests/test_cook_now_ranks_meals.py tests/test_cook_now_batch_aware.py -v`
Expected: all PASS (these exercise `generate` through the API and Kitchen Today card; the new key is additive).

- [ ] **Step 6: Commit**

```bash
git add tests/test_cook_now.py lib/cook_now.py
git commit -m "feat: demote all-staples recipes in Cook Now

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BCSAXpoc7E7mUTKxPwDdnM"
```

---

### Task 3: Documentation, full suite, and finish

**Files:**
- Modify: `docs/API.md:82` (the `/api/cook-now` row)
- Modify: `BRANCH-STATUS.md` (check off dev/testing/docs stages)

**Interfaces:**
- Consumes: the final payload shape from Task 2: `{recipe, image, dish_type, group, have, total, coverage, missing, at_risk, meal_tier, protein, minutes, servings, banked, freezes_well, all_staples, score}`.
- Produces: nothing downstream — this is the closing task.

- [ ] **Step 1: Update the API contract doc**

In `docs/API.md` line 82, the `/api/cook-now` row's payload list is stale (it predates the ranking factors: `meal_tier`…`score` are missing) — replace the row's field list and append one sentence, so the full row reads:

```
| `/api/cook-now` | GET | Recipes ranked by ingredient coverage against current inventory. `?limit=` (default 30). Returns `{"recipes": [{recipe, image, dish_type, group, have, total, coverage, missing, at_risk, meal_tier, protein, minutes, servings, banked, freezes_well, all_staples, score}]}`. `group` is the meal-type chip the recipe belongs to — one of `Mains`, `Breakfast`, `Sides`, `Snacks`, `Desserts`, `Drinks`. Filtering happens client-side on the `/cook-now` page; this endpoint never filters. `all_staples` marks a recipe whose every ingredient is a pantry staple; its score is demoted hard (never hidden) so perpetually-"ready" doughs and spice blends stop squatting at the top. |
```

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS across the board (e2e excluded by default; corpus tests resolve the vault via the main checkout and may skip if it's unavailable — a skip is fine, a failure is not).

- [ ] **Step 3: Update BRANCH-STATUS.md and commit**

Check off the dev/testing/docs checklist items in `BRANCH-STATUS.md`, then:

```bash
git add docs/API.md BRANCH-STATUS.md
git commit -m "docs: document all_staples in the /api/cook-now contract

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BCSAXpoc7E7mUTKxPwDdnM"
```

- [ ] **Step 4: Finish the branch**

Invoke the repo's `finish-feature` skill (KitchenOS "Completing Work" checklist), then `superpowers:finishing-a-development-branch` for the merge decision. Merge lands on **local main only — a KitchenOS merge is not a deploy**, but note main is already 23 commits ahead of origin; pushing remains a separate, deliberate act.

- [ ] **Step 5: Post-merge smoke (from the main checkout, not the worktree)**

The API LaunchAgent holds `lib/*` in memory — restart it, then verify end-to-end:

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
sleep 2
curl -s "http://localhost:5001/api/cook-now?limit=5" | .venv/bin/python -m json.tool | grep -E '"recipe"|"all_staples"|"score"'
.venv/bin/python -c "from lib import cook_now; print(cook_now.write_note())"
```

Expected: the top 5 carry `"all_staples": false` (or the list visibly no longer leads with doughs/blends), and `Cook Now.md` regenerates without error. `Cook Now.md` is a generated read-only view — regenerating it is the normal path, no backup needed.

---

## Verification against the spec's acceptance criteria

| Criterion | Where verified |
|---|---|
| All-staples recipe (100%) ranks below a real main at ≥50% coverage | Task 2 `test_sinks_below_a_partially_covered_real_main` (Chicken Dinner at 2/3) + post-merge smoke |
| One non-staple ingredient → score unchanged | Task 2 `test_one_real_ingredient_escapes_demotion` (score ratio exactly equals the weight, so the non-demoted score is the six-factor product) |
| Every `/api/cook-now` entry carries `all_staples` | Task 2 `test_every_entry_carries_the_flag` + Step 5 API-level tests |
| `Cook Now.md` regenerates and reorders | Existing `TestRender` tests (structure) + Task 3 Step 5 (live regeneration) |
| Full suite green | Task 3 Step 2 |
