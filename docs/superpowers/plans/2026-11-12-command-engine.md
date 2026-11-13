# Command Engine and Gold-Standard Kitchen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One sentence plus the screen it was said on becomes validated, typed actions that run through the existing ledger and inventory code, with one Undo per command.

**Architecture:** A code-first pipeline in `lib/command/` — split, extract slots, classify, resolve, validate, execute, log. A model is consulted only through `Decider.decide(question, options)` when rules and feasibility leave more than one action possible; when it declines, the same options go back to the user as buttons. Every command is recorded in `command_log` with before/after row snapshots, which is what Undo restores.

**Tech Stack:** Python 3.11, Flask, SQLite (`data/kitchenos.db`), `requests` to local Ollama, pytest. No new dependency.

**Spec:** [Command engine and gold-standard kitchen](../specs/2026-11-12-command-engine-design.md), approved 2026-11-12 with both open questions accepted as proposed.

## Scope of this plan

Covers spec pieces 0 and 1 for **meal plan and leftovers, cooking and freezer, inventory, and navigation**.

**Deferred to a follow-on plan: the three shopping actions** (`shopping_generate`, `shopping_send`, `shopping_add`). Their logic lives inside two Flask route bodies in `api_server.py` and there is no manual-row writer to call; they need those bodies extracted into `lib/` first, which is its own reviewable change. In this plan a shopping phrase returns `failed` with "Shopping-list commands aren't built yet." and the two shopping gold cases assert exactly that, so the gap is tested, not silent.

**Two narrowings of the spec, both deliberate:**

- **Look-alike recipes always go to the user, never to a model.** The spec allowed a decider on name ties; nothing in "put the caldo on Monday" tells a model which caldo, so the planner asks.
- **Warming the model when a command bar opens** belongs to the bar (piece 2). This plan sets `keep_alive` so a model stays loaded between commands.

## Global Constraints

- Run Python as `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python` — the worktree has no `.venv` of its own. Abbreviated below as `$PY`.
- Work only in `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/command-engine` on branch `command-engine`.
- **Ledger only.** No code path may call `PUT /api/meal-plan` or `saveMealPlan`.
- **Recipe name is identity.** Never key on `short_title` / `display_name`; use them only in text shown to the user.
- **`location` is omitted unless the user said it.** `inventory_add` places via `storage_locations.place_item`.
- **No LLM call may bypass `lib/llm_gate.py`.** Ask `llm_gate.allowed()` first; take the timeout from `llm_gate.budget_s()`; a returned `0` means skip.
- **A week id is a key, never a label.** User-facing lines show dates in words ("Wed Nov 18"), never `2026-W47`.
- **Wrong-action count on the gold set must be 0.** A command may end in `ask`; it may never run the wrong thing.
- Tests never read live data: the autouse fixtures in `tests/conftest.py` already isolate the DB, vault and storage table. Do not weaken them.
- Commit footer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Stage explicit paths. Never `git add .`.

## File Structure

| File | Responsibility |
|------|----------------|
| `tests/gold/kitchen.py` | Builds the fixed fake kitchen (recipes, planned week, freezer, inventory) |
| `tests/gold/commands.json` | The gold command set: context, sentence, expected outcome |
| `lib/command/phrases.py` | Sentence → phrases |
| `lib/command/slots.py` | Phrase → dates, meal, numbers, location, item text |
| `lib/command/resolve.py` | `Kitchen` snapshot; words → real recipes, cooks, freezer rows, inventory rows |
| `lib/command/intents.py` | Closed action list, rules, feasibility |
| `lib/command/decider.py` | `Option`, `NoDecider`, `ScriptedDecider`, `OllamaDecider` |
| `lib/command/planner.py` | Runs the pipeline; returns `Plan`, `Question` or `Failure` |
| `lib/command/log.py` | `command_log` rows and cook/inventory snapshots |
| `lib/command/executor.py` | Runs a `Plan`; records snapshots; `undo` |
| `lib/command/context.py` | Validates the request's screen context |
| `api_server.py` | Three routes: command, answer, undo |
| `scripts/score_command_models.py` | On-demand scorecard against real local models |

---

### Task 1: Gold kitchen and gold command set

**Files:**
- Create: `tests/gold/__init__.py` (empty), `tests/gold/kitchen.py`, `tests/gold/commands.json`, `tests/test_gold_kitchen.py`
- Modify: `tests/conftest.py` (append one fixture)

**Interfaces:**
- Produces: `tests.gold.kitchen.TODAY` (`date(2026, 11, 12)`), `tests.gold.kitchen.build() -> dict` (ids of seeded cooks), pytest fixture `gold_kitchen`, `tests/gold/commands.json`.

- [ ] **Step 1: Write the failing test**

`tests/test_gold_kitchen.py`:

```python
"""The gold kitchen is the fixture every command feature is run through."""
import json
from pathlib import Path

GOLD = Path(__file__).parent / "gold" / "commands.json"
STATUSES = {"done", "ask", "confirm", "failed"}


def test_gold_kitchen_builds(gold_kitchen):
    from lib import inventory_db, paths, serving_ledger

    assert (paths.recipes_dir() / "Chicken Caldo A.md").exists()
    assert (paths.recipes_dir() / "Chicken Caldo B.md").exists()
    planned = [c["recipe"] for c in serving_ledger.cooks_for_week("2026-W47")]
    assert planned == ["Black Bean Chili", "Miso Salmon Bowls"]
    frozen = {r["recipe"]: r["count"] for r in serving_ledger.freezer_contents()}
    assert frozen == {"Chicken Caldo A": 3.0, "Black Bean Chili": 2.0}
    names = [r["name"] for r in inventory_db.fetch_inventory_rows()]
    assert names.count("milk") == 2 and "eggs" in names and "bread" in names
    assert set(gold_kitchen) == {"chili", "salmon", "frozen_caldo", "frozen_chili"}


def test_gold_commands_are_well_formed():
    cases = json.loads(GOLD.read_text())
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(ids) >= 19
    for c in cases:
        assert c["say"].strip() and c["context"]["screen"]
        assert c["expect"]["status"] in STATUSES
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/test_gold_kitchen.py -q`
Expected: FAIL — `fixture 'gold_kitchen' not found` and `FileNotFoundError` for `commands.json`.

- [ ] **Step 3: Write the kitchen builder**

`tests/gold/kitchen.py`:

```python
"""The gold-standard kitchen: one fixed fake kitchen every command is run through.

Today is frozen at Thursday 2026-11-12 (ISO week 2026-W46). Next week, 2026-W47,
runs Mon Nov 16 - Sun Nov 22. Change this file and tests/gold/commands.json together.
"""
from datetime import date

TODAY = date(2026, 11, 12)

# name -> (servings, short_title, [(amount, unit, ingredient)])
RECIPES = {
    "Chicken Caldo A": (6, None, [("2", "lb", "chicken thighs"), ("3", "whole", "carrots")]),
    "Chicken Caldo B": (4, None, [("1", "lb", "chicken breast"), ("2", "whole", "potatoes")]),
    "Black Bean Chili": (6, "Bean Chili", [("2", "can", "black beans"), ("1", "whole", "onion")]),
    "Butter Biscuits": (8, None, [("2", "cup", "flour"), ("1", "stick", "butter")]),
    "Miso Salmon Bowls": (2, None, [("2", "whole", "salmon fillets"), ("1", "cup", "rice")]),
    "Mystery Stew": ("null", None, [("1", "lb", "beef")]),
}

# (name, quantity, unit, location)
INVENTORY = [
    ("eggs", 12, "ct", "fridge"),
    ("bread", 1, "loaf", "counter"),
    ("olive oil", 1, "bottle", "pantry"),
    ("milk", 1, "carton", "fridge"),
    ("milk", 1, "carton", "freezer"),
]


def _recipe_md(name, servings, short, rows):
    front = [f'title: "{name}"', f"servings: {servings}"]
    if short:
        front.append(f'short_title: "{short}"')
    table = "\n".join(f"| {a} | {u} | {i} |" for a, u, i in rows)
    return (
        "---\n" + "\n".join(front) + "\n---\n\n## Ingredients\n\n"
        "| Amount | Unit | Ingredient |\n|--------|------|------------|\n"
        + table + "\n\n## Instructions\n\n1. Cook it.\n"
    )


def build() -> dict:
    """Write the kitchen into whatever vault and DB the environment points at.

    Call only under the tmp_vault + tmp_db fixtures. Returns the seeded cook ids.
    """
    from lib import paths, serving_ledger
    from lib.inventory import InventoryItem, add_items

    paths.recipes_dir().mkdir(parents=True, exist_ok=True)
    paths.meal_plans_dir().mkdir(parents=True, exist_ok=True)
    for name, (servings, short, rows) in RECIPES.items():
        (paths.recipes_dir() / f"{name}.md").write_text(
            _recipe_md(name, servings, short, rows), encoding="utf-8")

    chili = serving_ledger.create_cook(
        "Black Bean Chili", "2026-W47", servings_produced=6.0,
        date="2026-11-17", meal="dinner")
    salmon = serving_ledger.create_cook(
        "Miso Salmon Bowls", "2026-W47", servings_produced=2.0,
        date="2026-11-18", meal="dinner")
    frozen_caldo = serving_ledger.create_cook(
        "Chicken Caldo A", "2026-W44", servings_produced=6.0,
        date="2026-10-27", meal="dinner")
    serving_ledger.add_placement(frozen_caldo["id"], "freezer", 3)
    frozen_chili = serving_ledger.create_cook(
        "Black Bean Chili", "2026-W44", servings_produced=6.0,
        date="2026-10-28", meal="dinner")
    serving_ledger.add_placement(frozen_chili["id"], "freezer", 2)

    add_items([
        InventoryItem(name=n, quantity=q, unit=u, category="other",
                      location=loc, location_source="manual")
        for n, q, u, loc in INVENTORY
    ])
    return {"chili": chili["id"], "salmon": salmon["id"],
            "frozen_caldo": frozen_caldo["id"], "frozen_chili": frozen_chili["id"]}
```

Create `tests/gold/__init__.py` as an empty file.

Append to `tests/conftest.py`:

```python
@pytest.fixture
def gold_kitchen(tmp_vault, tmp_db):
    """The fixed fake kitchen, built into this test's temp vault and DB."""
    from tests.gold import kitchen
    return kitchen.build()
```

- [ ] **Step 4: Write the gold command set**

`tests/gold/commands.json` (today is Thu 2026-11-12; `expect.actions` entries are matched as subsets of the response's actions, in order):

```json
[
  {"id": "plan-leftovers-freeze", "context": {"screen": "recipe", "recipe": "Chicken Caldo A"},
   "say": "I want this on the meal plan for this Wednesday and to distribute the leftovers for lunch the next day and freeze the rest",
   "expect": {"status": "done", "actions": [
     {"type": "plan_cook", "recipe": "Chicken Caldo A", "date": "2026-11-18", "meal": "dinner"},
     {"type": "place_leftovers", "date": "2026-11-19", "meal": "lunch"},
     {"type": "freeze_rest"}]}},
  {"id": "plan-simple", "context": {"screen": "recipe", "recipe": "Chicken Caldo A"},
   "say": "put this on friday dinner",
   "expect": {"status": "done", "actions": [
     {"type": "plan_cook", "recipe": "Chicken Caldo A", "date": "2026-11-13", "meal": "dinner"}]}},
  {"id": "plan-double", "context": {"screen": "recipe", "recipe": "Chicken Caldo A"},
   "say": "add this for tomorrow lunch, double batch",
   "expect": {"status": "done", "actions": [
     {"type": "plan_cook", "recipe": "Chicken Caldo A", "date": "2026-11-13", "meal": "lunch", "scale": 2.0}]}},
  {"id": "plan-default-meal", "context": {"screen": "recipe", "recipe": "Chicken Caldo A"},
   "say": "lets do this sunday",
   "expect": {"status": "done", "actions": [
     {"type": "plan_cook", "recipe": "Chicken Caldo A", "date": "2026-11-15", "meal": "dinner"}]}},
  {"id": "plan-named", "context": {"screen": "home"},
   "say": "put butter biscuits on saturday breakfast",
   "expect": {"status": "done", "actions": [
     {"type": "plan_cook", "recipe": "Butter Biscuits", "date": "2026-11-14", "meal": "breakfast"}]}},
  {"id": "which-caldo", "context": {"screen": "home"},
   "say": "put the caldo on monday",
   "expect": {"status": "ask", "options": ["Chicken Caldo A", "Chicken Caldo B"]}},
  {"id": "plan-or-move", "context": {"screen": "recipe", "recipe": "Miso Salmon Bowls"},
   "say": "put this on friday",
   "expect": {"status": "ask", "options": ["plan_cook", "move_cook"]}},
  {"id": "move-cook", "context": {"screen": "planner", "week": "2026-W47"},
   "say": "move the salmon from wednesday to saturday",
   "expect": {"status": "done", "actions": [
     {"type": "move_cook", "recipe": "Miso Salmon Bowls", "date": "2026-11-21"}]}},
  {"id": "remove-cook", "context": {"screen": "planner", "week": "2026-W47"},
   "say": "take the chili off tuesday",
   "expect": {"status": "confirm", "actions": [
     {"type": "remove_cook", "recipe": "Black Bean Chili", "date": "2026-11-17"}]}},
  {"id": "cooked", "context": {"screen": "recipe", "recipe": "Chicken Caldo A"},
   "say": "I cooked this tonight",
   "expect": {"status": "done", "actions": [{"type": "mark_cooked", "recipe": "Chicken Caldo A"}]}},
  {"id": "thaw", "context": {"screen": "home"},
   "say": "pull a caldo out of the freezer for friday dinner",
   "expect": {"status": "done", "actions": [
     {"type": "thaw", "recipe": "Chicken Caldo A", "date": "2026-11-13", "meal": "dinner"}]}},
  {"id": "inv-out", "context": {"screen": "home"},
   "say": "we're out of eggs",
   "expect": {"status": "done", "actions": [{"type": "inventory_remove", "name": "eggs"}]}},
  {"id": "inv-out-many", "context": {"screen": "home"},
   "say": "we're out of milk",
   "expect": {"status": "confirm", "actions": [{"type": "inventory_remove", "name": "milk"}]}},
  {"id": "inv-add-two", "context": {"screen": "home"},
   "say": "add two cans of chickpeas and a bag of rice",
   "expect": {"status": "done", "actions": [
     {"type": "inventory_add", "item": "chickpeas", "quantity": 2.0, "unit": "can"},
     {"type": "inventory_add", "item": "rice", "quantity": 1.0, "unit": "bag"}]}},
  {"id": "inv-move", "context": {"screen": "home"},
   "say": "move the bread to the freezer",
   "expect": {"status": "done", "actions": [
     {"type": "inventory_move", "name": "bread", "location": "freezer"}]}},
  {"id": "open-day", "context": {"screen": "home"},
   "say": "open saturday",
   "expect": {"status": "done", "actions": [{"type": "open_page", "page": "day", "date": "2026-11-14"}]}},
  {"id": "open-recipe", "context": {"screen": "home"},
   "say": "show me the black bean chili",
   "expect": {"status": "done", "actions": [
     {"type": "open_page", "page": "recipe", "recipe": "Black Bean Chili"}]}},
  {"id": "unclear", "context": {"screen": "home"},
   "say": "put that thing on whenever",
   "expect": {"status": "ask", "options": []}},
  {"id": "shop-make-send", "context": {"screen": "home"},
   "say": "make the shopping list for next week and send it to reminders",
   "expect": {"status": "failed"}},
  {"id": "shop-add", "context": {"screen": "home"},
   "say": "add olive oil to the shopping list",
   "expect": {"status": "failed"}}
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_gold_kitchen.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add tests/gold/__init__.py tests/gold/kitchen.py tests/gold/commands.json tests/test_gold_kitchen.py tests/conftest.py
git commit -m "test: gold-standard kitchen and command set"
```

---

### Task 2: Phrases and slots

**Files:**
- Create: `lib/command/__init__.py` (empty), `lib/command/phrases.py`, `lib/command/slots.py`, `tests/test_command_slots.py`

**Interfaces:**
- Produces:
  - `phrases.split_phrases(text: str, protect: Iterable[str] = ()) -> list[str]`
  - `slots.Slots` with fields `dates`, `nav_dates`, `date_options` (lists of `date`), `meal`, `scale`, `count`, `quantity`, `unit`, `location`, `week`
  - `slots.extract(phrase: str, *, today: date, week_start: date | None = None, prev_date: date | None = None) -> Slots`
  - `slots.item_text(phrase: str) -> str`
  - `slots.iso_week(d: date) -> str`, `slots.week_monday(week: str) -> date`
  - constants `slots.DAYS`, `slots.MEALS`, `slots.LOCATIONS`, `slots.NUMBER_WORDS`

- [ ] **Step 1: Write the failing tests**

`tests/test_command_slots.py`:

```python
from datetime import date

from lib.command.phrases import split_phrases
from lib.command.slots import extract, item_text, iso_week, week_monday

THU = date(2026, 11, 12)


def test_split_on_and_then_comma():
    assert split_phrases("put this on friday and then freeze the rest, double batch") == [
        "put this on friday", "freeze the rest", "double batch"]


def test_split_protects_recipe_names_containing_and():
    assert split_phrases("put mac and cheese on friday and freeze the rest",
                         protect=["Mac and Cheese"]) == [
        "put mac and cheese on friday", "freeze the rest"]


def test_weekday_when_planning_is_next_occurrence_from_today():
    s = extract("for this wednesday", today=THU)
    assert s.dates == [date(2026, 11, 18)]


def test_weekday_for_navigation_stays_in_this_iso_week():
    s = extract("open wednesday", today=THU)
    assert s.nav_dates == [date(2026, 11, 11)]


def test_weekday_on_planner_uses_the_week_shown():
    s = extract("from wednesday to saturday", today=THU, week_start=date(2026, 11, 16))
    assert s.dates == [date(2026, 11, 18), date(2026, 11, 21)]


def test_today_is_a_valid_weekday_answer():
    assert extract("thursday", today=THU).dates == [THU]


def test_relative_days():
    assert extract("tomorrow lunch", today=THU).dates == [date(2026, 11, 13)]
    assert extract("for lunch the next day", today=THU,
                   prev_date=date(2026, 11, 18)).dates == [date(2026, 11, 19)]
    assert extract("the next day", today=THU).dates == []


def test_next_weekday_is_a_question_not_a_guess():
    s = extract("next friday", today=THU)
    assert s.dates == [] and s.date_options == [date(2026, 11, 13), date(2026, 11, 20)]


def test_next_week_sets_week():
    assert extract("for next week", today=THU).week == "2026-W47"


def test_meal_scale_count_location():
    assert extract("tonight", today=THU).meal == "dinner"
    assert extract("double batch", today=THU).scale == 2.0
    assert extract("two servings for lunch", today=THU).count == 2.0
    assert extract("to the freezer", today=THU).location == "freezer"


def test_quantity_and_unit():
    s = extract("add two cans of chickpeas", today=THU)
    assert (s.quantity, s.unit) == (2.0, "can")
    s = extract("a bag of rice", today=THU)
    assert (s.quantity, s.unit) == (1.0, "bag")


def test_item_text_strips_verbs_numbers_units_places():
    assert item_text("add two cans of chickpeas") == "chickpeas"
    assert item_text("we’re out of eggs") == "eggs"
    assert item_text("move the bread to the freezer") == "bread"
    assert item_text("a bag of rice") == "rice"


def test_week_helpers():
    assert iso_week(THU) == "2026-W46"
    assert week_monday("2026-W47") == date(2026, 11, 16)
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_slots.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.command'`.

- [ ] **Step 3: Implement**

Create `lib/command/__init__.py` as an empty file.

`lib/command/phrases.py`:

```python
"""Split a spoken command into phrases. No model, no state."""
import re
from typing import Iterable

_SPLIT = re.compile(r"\s*(?:[,;]|\band then\b|\bthen\b|\band\b)\s*", re.I)


def split_phrases(text: str, protect: Iterable[str] = ()) -> list[str]:
    """Split on commas, semicolons, "and", "then".

    ``protect`` is a list of names (recipes) that must survive intact even if
    they contain a splitting word — "Mac and Cheese" is one phrase, not two.
    """
    held: list[str] = []
    for name in sorted(protect, key=len, reverse=True):
        if not _SPLIT.search(name):
            continue
        match = re.search(re.escape(name), text, re.I)
        if match:
            held.append(match.group(0))
            text = text[:match.start()] + f"\x00{len(held) - 1}\x00" + text[match.end():]
    parts = [p.strip() for p in _SPLIT.split(text) if p and p.strip()]
    return [re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], p) for p in parts]
```

`lib/command/slots.py`:

```python
"""Pull dates, meals, numbers and places out of one phrase. No model.

Two date rules live side by side because the two uses disagree on purpose:
planning a meal on "Wednesday" means the next Wednesday from today, while
opening "Wednesday" keeps the Siri web-navigation rule (this ISO week).
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MEALS = ("breakfast", "lunch", "dinner", "snack")
LOCATIONS = ("freezer", "fridge", "pantry", "counter")
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "dozen": 12}
SCALE_WORDS = {"double": 2.0, "triple": 3.0, "half": 0.5}
UNIT_WORDS = {"can": "can", "cans": "can", "bag": "bag", "bags": "bag", "jar": "jar",
              "jars": "jar", "bottle": "bottle", "bottles": "bottle", "box": "box",
              "boxes": "box", "carton": "carton", "cartons": "carton", "loaf": "loaf",
              "loaves": "loaf", "bunch": "bunch", "bunches": "bunch", "lb": "lb",
              "lbs": "lb", "pound": "lb", "pounds": "lb", "oz": "oz", "ounce": "oz",
              "ounces": "oz"}

_ITEM_STOP = {
    "add", "got", "bought", "picked", "grabbed", "up", "have", "we", "we're", "were",
    "are", "i", "i'm", "im", "am", "out", "of", "ran", "run", "used", "no", "more",
    "finished", "move", "put", "stick", "the", "to", "some", "my", "our", "please",
    "another", "in", "into", "on", "and", "is", "there",
} | set(NUMBER_WORDS) | set(UNIT_WORDS) | set(LOCATIONS)

_DATE = re.compile(
    r"\b(today|tonight|tomorrow|the next day|the day after|next week|this week"
    r"|(next )?(" + "|".join(DAYS) + r"))\b")
_SERVINGS = re.compile(
    r"\b(\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")\s+servings?\b")


def iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def week_monday(week: str) -> date:
    year, number = week.split("-W")
    return date.fromisocalendar(int(year), int(number), 1)


def _number(token: str) -> Optional[float]:
    if token in NUMBER_WORDS:
        return float(NUMBER_WORDS[token])
    try:
        return float(token)
    except ValueError:
        return None


@dataclass
class Slots:
    dates: list = field(default_factory=list)         # planning rule
    nav_dates: list = field(default_factory=list)     # this-ISO-week rule
    date_options: list = field(default_factory=list)  # "next friday": must be asked
    meal: Optional[str] = None
    scale: Optional[float] = None
    count: Optional[float] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    location: Optional[str] = None
    week: Optional[str] = None


def _clean(phrase: str) -> str:
    return phrase.lower().replace("’", "'")


def extract(phrase: str, *, today: date, week_start: Optional[date] = None,
            prev_date: Optional[date] = None) -> Slots:
    low = _clean(phrase)
    s = Slots()
    for m in _DATE.finditer(low):
        word = m.group(1)
        if word in ("today", "tonight"):
            plan = nav = today
        elif word == "tomorrow":
            plan = nav = today + timedelta(days=1)
        elif word in ("the next day", "the day after"):
            if prev_date is None:
                continue
            plan = nav = prev_date + timedelta(days=1)
        elif word == "next week":
            s.week = iso_week(today + timedelta(days=7))
            continue
        elif word == "this week":
            s.week = iso_week(today)
            continue
        else:
            idx = DAYS.index(m.group(3))
            coming = today + timedelta(days=(idx - today.weekday()) % 7)
            if m.group(2):
                s.date_options = [coming, coming + timedelta(days=7)]
                continue
            if week_start is not None:
                plan = nav = week_start + timedelta(days=idx)
            else:
                plan = coming
                nav = today - timedelta(days=today.weekday()) + timedelta(days=idx)
        s.dates.append(plan)
        s.nav_dates.append(nav)

    s.meal = next((m for m in MEALS if re.search(rf"\b{m}\b", low)), None)
    if s.meal is None and "tonight" in low:
        s.meal = "dinner"
    s.location = next((p for p in LOCATIONS if re.search(rf"\b{p}\b", low)), None)
    s.scale = next((v for w, v in SCALE_WORDS.items() if re.search(rf"\b{w}\b", low)), None)

    servings = _SERVINGS.search(low)
    if servings:
        s.count = _number(servings.group(1))

    tokens = re.findall(r"[a-z0-9.']+", low)
    for i, token in enumerate(tokens):
        value = _number(token)
        followed_by_servings = i + 1 < len(tokens) and tokens[i + 1].startswith("serving")
        if value is not None and not followed_by_servings:
            s.quantity = value
            break
    s.unit = next((UNIT_WORDS[t] for t in tokens if t in UNIT_WORDS), None)
    return s


def item_text(phrase: str) -> str:
    """The food being talked about, with verbs, numbers, units and places removed."""
    tokens = re.findall(r"[a-z']+", _clean(phrase))
    return " ".join(t for t in tokens if t not in _ITEM_STOP)
```

- [ ] **Step 4: Run to verify pass**

Run: `$PY -m pytest tests/test_command_slots.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add lib/command/__init__.py lib/command/phrases.py lib/command/slots.py tests/test_command_slots.py
git commit -m "feat(command): deterministic phrase splitting and slot extraction"
```

---

### Task 3: Kitchen snapshot and name resolution

**Files:**
- Create: `lib/command/resolve.py`, `tests/test_command_resolve.py`

**Interfaces:**
- Consumes: `slots.iso_week`, `slots.DAYS`, `slots.MEALS`; `serving_ledger.cooks_for_week(week) -> list[dict]`, `serving_ledger.freezer_contents() -> list[dict]` (keys `placement_id`, `count`, `cook_id`, `recipe`, `cook_week`), `inventory_db.fetch_inventory_rows() -> list[dict]`, `paths.recipes_dir()`.
- Produces:
  - `resolve.Match(name: str | None, options: list[str], how: str | None)` — `how` is `"exact"`, `"pointer"`, `"fuzzy"` or `None`
  - `resolve.Kitchen` with fields `today`, `recipes`, `cooks`, `freezer`, `inventory`
  - `Kitchen.load(today: date, extra_weeks: Iterable[str] = ()) -> Kitchen`
  - `Kitchen.find_recipe(phrase, screen_recipe=None, pool=None) -> Match`
  - `Kitchen.planned(recipe, on: date | None = None) -> list[dict]`, `Kitchen.planned_names() -> list[str]`
  - `Kitchen.frozen(recipe) -> list[dict]`, `Kitchen.frozen_names() -> list[str]`
  - `Kitchen.inventory_rows(item: str) -> list[dict]`
  - `Kitchen.display(recipe: str) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_command_resolve.py`:

```python
from datetime import date

from lib.command.resolve import Kitchen
from tests.gold.kitchen import TODAY


def _kitchen():
    return Kitchen.load(TODAY)


def test_load_sees_recipes_plan_freezer_inventory(gold_kitchen):
    k = _kitchen()
    assert "Chicken Caldo A" in k.recipes and len(k.recipes) == 6
    assert k.planned_names() == ["Black Bean Chili", "Miso Salmon Bowls"]
    assert k.frozen_names() == ["Black Bean Chili", "Chicken Caldo A"]
    assert len(k.inventory) == 5


def test_exact_name_wins(gold_kitchen):
    m = _kitchen().find_recipe("show me the black bean chili")
    assert (m.name, m.how) == ("Black Bean Chili", "exact")


def test_pointer_uses_the_screen_recipe_before_fuzzy(gold_kitchen):
    m = _kitchen().find_recipe("put this on the bean plan", screen_recipe="Chicken Caldo A")
    assert (m.name, m.how) == ("Chicken Caldo A", "pointer")


def test_fuzzy_single_hit(gold_kitchen):
    m = _kitchen().find_recipe("move the salmon to saturday")
    assert (m.name, m.how) == ("Miso Salmon Bowls", "fuzzy")


def test_lookalikes_are_options_not_a_guess(gold_kitchen):
    m = _kitchen().find_recipe("put the caldo on monday")
    assert m.name is None and m.options == ["Chicken Caldo A", "Chicken Caldo B"]


def test_pool_narrows_lookalikes(gold_kitchen):
    k = _kitchen()
    assert k.find_recipe("pull a caldo out", pool=k.frozen_names()).name == "Chicken Caldo A"


def test_pointer_ignored_when_screen_recipe_not_in_pool(gold_kitchen):
    k = _kitchen()
    m = k.find_recipe("move this", screen_recipe="Chicken Caldo A", pool=k.planned_names())
    assert m.name is None and m.options == []


def test_planned_filters_by_date(gold_kitchen):
    k = _kitchen()
    assert len(k.planned("Black Bean Chili")) == 1
    assert k.planned("Black Bean Chili", on=date(2026, 11, 18)) == []


def test_inventory_rows_match_whole_words(gold_kitchen):
    k = _kitchen()
    assert [r["name"] for r in k.inventory_rows("eggs")] == ["eggs"]
    assert len(k.inventory_rows("milk")) == 2
    assert k.inventory_rows("oil")[0]["name"] == "olive oil"
    assert k.inventory_rows("saffron") == []


def test_display_uses_short_title(gold_kitchen):
    k = _kitchen()
    assert k.display("Black Bean Chili") == "Bean Chili"
    assert k.display("Chicken Caldo A") == "Chicken Caldo A"
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_resolve.py -q`
Expected: FAIL — `No module named 'lib.command.resolve'`.

- [ ] **Step 3: Implement**

`lib/command/resolve.py`:

```python
"""Turn words into real things in this kitchen. Read-only; no model.

A recipe's *name* is its identity. Matching may read `short_title` to render a
line, but every match lands on a canonical name or on a list of options.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

from lib.command.slots import DAYS, LOCATIONS, MEALS, iso_week

_WORD = re.compile(r"[a-z0-9]+")
_POINTER = re.compile(r"\b(this|it|that)\b")
_SKIP = {"a", "b", "the", "of", "and", "with", "in", "for", "to", "on", "my", "me",
         "meal", "plan", "recipe", "leftover", "this", "that", "it"} \
    | set(DAYS) | set(MEALS) | set(LOCATIONS)


def _norm(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text: str) -> set:
    return {_norm(w) for w in _WORD.findall(text.lower())} - {_norm(w) for w in _SKIP}


@dataclass
class Match:
    name: Optional[str] = None
    options: list = field(default_factory=list)
    how: Optional[str] = None


@dataclass
class Kitchen:
    today: date
    recipes: list
    cooks: list
    freezer: list
    inventory: list

    @classmethod
    def load(cls, today: date, extra_weeks: Iterable[str] = ()) -> "Kitchen":
        from lib import inventory_db, paths, serving_ledger

        weeks = {iso_week(today), iso_week(today + timedelta(days=7)), *extra_weeks}
        cooks = [c for w in sorted(weeks) for c in serving_ledger.cooks_for_week(w)]
        recipes_dir = paths.recipes_dir()
        recipes = sorted(p.stem for p in recipes_dir.glob("*.md")) if recipes_dir.exists() else []
        return cls(today=today, recipes=recipes, cooks=cooks,
                   freezer=serving_ledger.freezer_contents(),
                   inventory=inventory_db.fetch_inventory_rows())

    def find_recipe(self, phrase: str, screen_recipe: Optional[str] = None,
                    pool: Optional[Iterable[str]] = None) -> Match:
        names = list(self.recipes if pool is None else pool)
        low = phrase.lower()
        exact = [n for n in names if n.lower() in low]
        if exact:
            return Match(max(exact, key=len), [], "exact")
        if screen_recipe and screen_recipe in names and _POINTER.search(low):
            return Match(screen_recipe, [], "pointer")
        have = _words(phrase)
        scored = [(len(have & _words(n)), n) for n in names]
        best = max((score for score, _ in scored), default=0)
        hits = sorted(n for score, n in scored if score == best and score > 0)
        if len(hits) == 1:
            return Match(hits[0], [], "fuzzy")
        return Match(None, hits, None)

    def planned(self, recipe: str, on: Optional[date] = None) -> list:
        return [c for c in self.cooks
                if c["recipe"] == recipe and c.get("date")
                and (on is None or c["date"] == on.isoformat())]

    def planned_names(self) -> list:
        return sorted({c["recipe"] for c in self.cooks if c.get("date")})

    def frozen(self, recipe: str) -> list:
        return [r for r in self.freezer if r["recipe"] == recipe]

    def frozen_names(self) -> list:
        return sorted({r["recipe"] for r in self.freezer})

    def inventory_rows(self, item: str) -> list:
        want = _words(item)
        return [r for r in self.inventory if want and want <= _words(r["name"])]

    def display(self, recipe: str) -> str:
        """What a line shows. The name is always the fallback."""
        from lib import paths, short_title
        from lib.recipe_parser import parse_recipe_file

        path = paths.recipes_dir() / f"{recipe}.md"
        try:
            front = parse_recipe_file(path.read_text(encoding="utf-8"))["frontmatter"]
            return short_title.display_name(recipe, front.get("short_title"))
        except Exception:
            return recipe
```

- [ ] **Step 4: Run to verify pass**

Run: `$PY -m pytest tests/test_command_resolve.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add lib/command/resolve.py tests/test_command_resolve.py
git commit -m "feat(command): kitchen snapshot and name resolution"
```

---

### Task 4: Intents, rules and feasibility

**Files:**
- Create: `lib/command/intents.py`, `tests/test_command_intents.py`

**Interfaces:**
- Consumes: `slots.Slots`, `resolve.Match`, `resolve.Kitchen`.
- Produces:
  - `intents.Intent(name, label, hint, policy="auto", open=False)`; `intents.INTENTS: dict[str, Intent]`
  - `intents.UNSUPPORTED` (compiled regex for shopping phrases)
  - `intents.rule_for(phrase: str) -> str | None`
  - `intents.Facts(phrase, slots, any, planned, frozen, item, has_prior_cook)` — `any`/`planned`/`frozen` are `Match`
  - `intents.feasible(name: str, facts: Facts) -> bool`
  - `intents.candidates(facts: Facts, screen: str) -> list[str]` — the *open* intents that could run
  - `intents.why_not(name: str, facts: Facts) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_command_intents.py`:

```python
import pytest

from lib.command import intents
from lib.command.intents import Facts
from lib.command.resolve import Match
from lib.command.slots import extract, item_text
from tests.gold.kitchen import TODAY


@pytest.mark.parametrize("phrase,expected", [
    ("open saturday", "open_page"),
    ("show me the black bean chili", "open_page"),
    ("freeze the rest", "freeze_rest"),
    ("to distribute the leftovers for lunch the next day", "place_leftovers"),
    ("pull a caldo out of the freezer for friday dinner", "thaw"),
    ("we're out of eggs", "inventory_remove"),
    ("I cooked this tonight", "mark_cooked"),
    ("take the chili off tuesday", "remove_cook"),
    ("move the bread to the freezer", "inventory_move"),
    ("put the bread in the freezer", "inventory_move"),
    ("move the salmon from wednesday to saturday", "move_cook"),
    ("put this on friday dinner", None),
    ("add two cans of chickpeas", None),
])
def test_rules(phrase, expected):
    assert intents.rule_for(phrase) == expected


def test_shopping_phrases_are_flagged_unsupported():
    assert intents.UNSUPPORTED.search("add olive oil to the shopping list")
    assert intents.UNSUPPORTED.search("send it to reminders")
    assert not intents.UNSUPPORTED.search("add olive oil")


def _facts(phrase, any_=Match(), planned=Match(), frozen=Match(), prior=False):
    return Facts(phrase=phrase, slots=extract(phrase, today=TODAY), any=any_,
                 planned=planned, frozen=frozen, item=item_text(phrase),
                 has_prior_cook=prior)


def test_plan_needs_a_recipe_and_a_day():
    caldo = Match("Chicken Caldo A", [], "pointer")
    assert intents.feasible("plan_cook", _facts("put this on friday", any_=caldo))
    assert not intents.feasible("plan_cook", _facts("put this on the plan", any_=caldo))
    assert not intents.feasible("plan_cook", _facts("put that on friday"))


def test_move_needs_a_planned_cook():
    salmon = Match("Miso Salmon Bowls", [], "pointer")
    assert intents.feasible("move_cook", _facts("put this on friday", planned=salmon))
    assert not intents.feasible("move_cook", _facts("put this on friday"))


def test_open_candidates_tie_only_when_both_could_run():
    salmon = Match("Miso Salmon Bowls", [], "pointer")
    tie = _facts("put this on friday", any_=salmon, planned=salmon)
    assert intents.candidates(tie, "recipe") == ["plan_cook", "move_cook"]
    caldo = Match("Chicken Caldo A", [], "pointer")
    assert intents.candidates(_facts("put this on friday", any_=caldo), "recipe") == ["plan_cook"]


def test_inventory_add_needs_an_add_verb_and_no_day():
    assert intents.candidates(_facts("add two cans of chickpeas"), "home") == ["inventory_add"]
    assert intents.candidates(_facts("put that thing on whenever"), "home") == []


def test_a_fuzzy_recipe_hit_does_not_block_inventory_add():
    fuzzy = Match("Black Bean Chili", [], "fuzzy")
    assert intents.candidates(_facts("add two cans of black beans", any_=fuzzy), "home") == [
        "inventory_add"]


def test_a_named_recipe_blocks_inventory_add():
    exact = Match("Butter Biscuits", [], "exact")
    assert intents.candidates(_facts("add butter biscuits", any_=exact), "home") == []


def test_inventory_screen_hides_plan_actions_unless_a_recipe_is_named():
    fuzzy = Match("Miso Salmon Bowls", [], "fuzzy")
    f = _facts("put salmon on friday", any_=fuzzy)
    assert intents.candidates(f, "home") == ["plan_cook"]
    assert intents.candidates(f, "inventory") == []


def test_why_not_is_a_sentence_a_person_can_act_on():
    assert "day" in intents.why_not("plan_cook", _facts("put this on the plan"))
    assert "freezer" in intents.why_not("thaw", _facts("thaw the caldo for friday"))
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_intents.py -q`
Expected: FAIL — `cannot import name 'intents'`.

- [ ] **Step 3: Implement**

`lib/command/intents.py`:

```python
"""The closed list of things a command can do, and when each one could run.

Three filters shrink a decision before any model sees it: a rule (known
phrasing), feasibility (could this even run on this kitchen?), and the screen.
Only `open` intents can be chosen without a rule firing — everything else needs
its verb, so "I want this Wednesday" can never drift into "mark cooked".
"""
import re
from dataclasses import dataclass

from lib.command.resolve import Match
from lib.command.slots import Slots


@dataclass(frozen=True)
class Intent:
    name: str
    label: str          # button text when the user is the decider
    hint: str           # one line for a model
    policy: str = "auto"
    open: bool = False


INTENTS = {i.name: i for i in [
    Intent("plan_cook", "Add it to the meal plan", "put a recipe on the meal plan for a day", open=True),
    Intent("move_cook", "Move it to that day", "move an already-planned recipe to another day", open=True),
    Intent("inventory_add", "Add it to inventory", "we now have this food", open=True),
    Intent("place_leftovers", "Plan the leftovers", "eat leftovers at another meal"),
    Intent("freeze_rest", "Freeze the rest", "freeze the remaining servings"),
    Intent("remove_cook", "Take it off the plan", "remove a planned recipe", policy="confirm"),
    Intent("mark_cooked", "Mark it cooked", "a recipe has been cooked"),
    Intent("thaw", "Take it out of the freezer", "use a frozen portion for a meal"),
    Intent("inventory_remove", "Remove it from inventory", "we ran out of a food"),
    Intent("inventory_move", "Move it in the kitchen", "move a food to fridge, freezer, pantry or counter"),
    Intent("open_page", "Open it", "open a page, a day or a recipe"),
]}

UNSUPPORTED = re.compile(r"\b(shopping list|grocery list|reminders)\b", re.I)

# First match wins, so order is part of the rule.
_RULES = [(re.compile(pattern), name) for pattern, name in [
    (r"\b(open|show|go to|pull up|take me to)\b", "open_page"),
    (r"\bfreeze (the )?(rest|remainder|leftovers?|what'?s left)\b", "freeze_rest"),
    (r"\bleftovers?\b", "place_leftovers"),
    (r"\b(out of the freezer|from the freezer|thaw|defrost)\b", "thaw"),
    (r"\b(out of|ran out|run out|used up|no more)\b", "inventory_remove"),
    (r"\b(cooked|made)\b", "mark_cooked"),
    (r"\b(take|remove|cancel|delete|drop)\b", "remove_cook"),
    (r"\b(move|put|stick)\b.*\b(freezer|fridge|pantry|counter)\b", "inventory_move"),
    (r"\b(move|reschedule|push|bump|shift)\b", "move_cook"),
]]

_ADD_VERB = re.compile(r"\b(add|got|bought|picked up|grabbed|have)\b")
_PAGE_WORD = re.compile(r"\b(planner|meal plan|inventory|home)\b")
_SCREEN_HIDES = {"inventory": {"plan_cook", "move_cook"}}


def rule_for(phrase: str):
    low = phrase.lower().replace("’", "'")
    for pattern, name in _RULES:
        if pattern.search(low):
            return name
    return None


@dataclass
class Facts:
    phrase: str
    slots: Slots
    any: Match        # against every recipe
    planned: Match    # against recipes on the plan
    frozen: Match     # against recipes in the freezer
    item: str
    has_prior_cook: bool


def _found(match: Match) -> bool:
    return bool(match.name or match.options)


def feasible(name: str, f: Facts) -> bool:
    s, low = f.slots, f.phrase.lower()
    if name == "plan_cook":
        return _found(f.any) and bool(s.dates)
    if name == "move_cook":
        return _found(f.planned) and bool(s.dates)
    if name == "inventory_add":
        named = f.any.how in ("exact", "pointer")
        return bool(f.item) and bool(_ADD_VERB.search(low)) and not s.dates and not named
    if name == "place_leftovers":
        return bool(s.dates) and (f.has_prior_cook or _found(f.planned))
    if name == "freeze_rest":
        return f.has_prior_cook or _found(f.planned)
    if name == "remove_cook":
        return _found(f.planned)
    if name == "mark_cooked":
        return _found(f.any)
    if name == "thaw":
        return _found(f.frozen) and bool(s.dates)
    if name == "inventory_remove":
        return bool(f.item)
    if name == "inventory_move":
        return bool(f.item) and s.location is not None
    if name == "open_page":
        return _found(f.any) or bool(s.nav_dates) or bool(_PAGE_WORD.search(low))
    return False


def candidates(f: Facts, screen: str) -> list:
    """Open intents that could run for this phrase on this screen."""
    hidden = _SCREEN_HIDES.get(screen, set()) if f.any.how != "exact" else set()
    return [i.name for i in INTENTS.values()
            if i.open and i.name not in hidden and feasible(i.name, f)]


def why_not(name: str, f: Facts) -> str:
    s = f.slots
    if name in ("plan_cook", "place_leftovers") and not s.dates:
        return "Which day? Say a day, like Wednesday or tomorrow."
    if name == "plan_cook":
        return "Which recipe? Say its name, or open the recipe first."
    if name in ("move_cook", "remove_cook"):
        if not _found(f.planned):
            return "That isn't on the meal plan."
        return "Which day should it move to?"
    if name in ("place_leftovers", "freeze_rest"):
        return "Leftovers of what? Plan the recipe in the same sentence, or name it."
    if name == "mark_cooked":
        return "Which recipe did you cook?"
    if name == "thaw":
        if not _found(f.frozen):
            return "Nothing like that is in the freezer."
        return "Which day is it for?"
    if name == "inventory_move":
        return "Move what, and where — fridge, freezer, pantry or counter?"
    if name == "inventory_remove":
        return "Out of what?"
    return "Open what? Name a day or a recipe."
```

- [ ] **Step 4: Run to verify pass**

Run: `$PY -m pytest tests/test_command_intents.py -q`
Expected: `22 passed`.

- [ ] **Step 5: Commit**

```bash
git add lib/command/intents.py tests/test_command_intents.py
git commit -m "feat(command): closed intent list, rules and feasibility"
```

---

### Task 5: Decider

**Files:**
- Create: `lib/command/decider.py`, `tests/test_command_decider.py`

**Interfaces:**
- Consumes: `lib.llm_gate.allowed() -> bool`, `lib.llm_gate.budget_s(default: float) -> float`.
- Produces:
  - `decider.Option(id: str, label: str, hint: str = "")`
  - `decider.NoDecider().decide(question, options, context) -> None`
  - `decider.ScriptedDecider(answers: dict[str, str])` — returns the first option whose id is a value in `answers`, else `None`; records calls in `.calls`
  - `decider.OllamaDecider(model: str = DEFAULT_MODEL)`; `decider.DEFAULT_MODEL = "qwen2.5:3b"`
  - `decider.default() -> OllamaDecider`
  - Every decider: `decide(question: str, options: list[Option], context: str) -> str | None` (an option id, or `None` to hand the question to the user)

- [ ] **Step 1: Write the failing tests**

`tests/test_command_decider.py`:

```python
from lib.command import decider
from lib.command.decider import NoDecider, OllamaDecider, Option, ScriptedDecider

OPTIONS = [Option("plan_cook", "Add it to the meal plan"), Option("move_cook", "Move it")]


def test_no_decider_always_defers():
    assert NoDecider().decide("q", OPTIONS, "ctx") is None


def test_scripted_decider_picks_and_records():
    d = ScriptedDecider({"anything": "move_cook"})
    assert d.decide("q", OPTIONS, "ctx") == "move_cook"
    assert d.calls == [("q", ["plan_cook", "move_cook"])]


def test_ollama_decider_refuses_when_llm_disabled(monkeypatch):
    monkeypatch.setenv("KITCHENOS_NO_LLM", "1")
    monkeypatch.setattr(decider.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dialled")))
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None


class _Reply:
    status_code = 200

    def __init__(self, content):
        self._content = content

    def json(self):
        return {"message": {"content": self._content}}


def test_ollama_decider_returns_a_listed_choice(monkeypatch):
    monkeypatch.delenv("KITCHENOS_NO_LLM", raising=False)
    sent = {}

    def post(url, json, timeout):
        sent.update(json=json, timeout=timeout)
        return _Reply('{"choice": "move_cook"}')

    monkeypatch.setattr(decider.requests, "post", post)
    assert OllamaDecider().decide("q", OPTIONS, "ctx") == "move_cook"
    assert sent["json"]["format"]["properties"]["choice"]["enum"] == ["plan_cook", "move_cook"]
    assert sent["json"]["keep_alive"] == "30m"


def test_ollama_decider_rejects_an_unlisted_or_broken_answer(monkeypatch):
    monkeypatch.delenv("KITCHENOS_NO_LLM", raising=False)
    monkeypatch.setattr(decider.requests, "post", lambda *a, **k: _Reply('{"choice": "explode"}'))
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None
    monkeypatch.setattr(decider.requests, "post", lambda *a, **k: _Reply("not json"))
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None


def test_ollama_decider_survives_a_timeout(monkeypatch):
    monkeypatch.delenv("KITCHENOS_NO_LLM", raising=False)

    def boom(*a, **k):
        raise decider.requests.Timeout()

    monkeypatch.setattr(decider.requests, "post", boom)
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_decider.py -q`
Expected: FAIL — `cannot import name 'decider'`.

- [ ] **Step 3: Implement**

`lib/command/decider.py`:

```python
"""The only place a model is consulted, and only for one typed choice.

`decide` returns an option id or None. None is not an error: it means "ask the
user", and the same options are shown as buttons. A decider must never raise.
"""
import json
from dataclasses import dataclass

import requests

from lib import llm_gate

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
#: The smallest local model that passes the gold scorecard. Change it only
#: after running scripts/score_command_models.py.
DEFAULT_MODEL = "qwen2.5:3b"
_DEFAULT_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    hint: str = ""


class NoDecider:
    def decide(self, question, options, context):
        return None


class ScriptedDecider:
    """Test double: answers with the first option whose id it was told to pick."""

    def __init__(self, answers: dict):
        self._wanted = set(answers.values())
        self.calls = []

    def decide(self, question, options, context):
        self.calls.append((question, [o.id for o in options]))
        return next((o.id for o in options if o.id in self._wanted), None)


class OllamaDecider:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def decide(self, question, options, context):
        if not llm_gate.allowed():
            return None
        timeout = llm_gate.budget_s(_DEFAULT_TIMEOUT_S)
        if timeout <= 0:
            return None
        ids = [o.id for o in options]
        menu = "\n".join(f"- {o.id}: {o.hint or o.label}" for o in options)
        body = {
            "model": self.model, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0},
            "format": {"type": "object", "required": ["choice"],
                       "properties": {"choice": {"type": "string", "enum": ids}}},
            "messages": [
                {"role": "system", "content": f"Pick the one label that fits.\n{menu}"},
                {"role": "user", "content": f"{context}\n{question}"},
            ],
        }
        try:
            reply = requests.post(OLLAMA_CHAT_URL, json=body, timeout=timeout)
            if reply.status_code != 200:
                return None
            choice = json.loads(reply.json()["message"]["content"]).get("choice")
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
            return None
        return choice if choice in ids else None


def default():
    return OllamaDecider()
```

- [ ] **Step 4: Run to verify pass**

Run: `$PY -m pytest tests/test_command_decider.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add lib/command/decider.py tests/test_command_decider.py
git commit -m "feat(command): typed-choice decider with user fallback"
```

---

### Task 6: Planner

**Files:**
- Create: `lib/command/planner.py`, `tests/test_command_planner.py`

**Interfaces:**
- Consumes: everything produced by Tasks 2–5.
- Produces:
  - `planner.Action(type: str, args: dict)` with `to_json() -> dict` (`{"type": ..., **args}`)
  - `planner.Plan(actions: list[Action], confirm: list[str])`
  - `planner.Question(key: str, text: str, options: list[Option])`
  - `planner.Failure(reason: str)`
  - `planner.plan(text: str, context: dict, kitchen: Kitchen, decider, answers: dict | None = None) -> Plan | Question | Failure`
  - `planner.describe(action: Action, kitchen: Kitchen) -> str`
  - `planner.weeks_touched(plan: Plan) -> set[str]`
  - `planner.day_text(iso: str) -> str` ("Wed Nov 18")
- Action args by type (all JSON-serialisable):
  - `plan_cook`: `recipe, date, meal, scale`
  - `place_leftovers`: `cook` (`{"new": <action index>}` or `{"id": <cook id>}`), `date, meal, count`
  - `freeze_rest`: `cook`
  - `move_cook`: `cook_id, recipe, date, meal, cook_week, bundle_id`
  - `remove_cook`: `cook_id, recipe, date, cook_week, bundle_id`
  - `mark_cooked`: `recipe, batches`
  - `thaw`: `placement_id, cook_id, recipe, date, meal, count, cook_week`
  - `inventory_add`: `item, quantity, unit`
  - `inventory_remove`: `name, rows`
  - `inventory_move`: `name, location`
  - `open_page`: `page` plus `recipe` or `date`+`week`
- Answer keys: `intent:<i>`, `recipe:<i>`, `date:<i>`, `meal:<i>` where `<i>` is the phrase index. A `Question` with key `"rephrase"` has no options.

- [ ] **Step 1: Write the failing tests**

`tests/test_command_planner.py`:

```python
import json
from pathlib import Path

import pytest

from lib.command import planner
from lib.command.decider import NoDecider, ScriptedDecider
from lib.command.planner import Failure, Plan, Question
from lib.command.resolve import Kitchen
from tests.gold.kitchen import TODAY

CASES = json.loads((Path(__file__).parent / "gold" / "commands.json").read_text())


def _plan(say, context, decider=None, answers=None):
    return planner.plan(say, context, Kitchen.load(TODAY, [context["week"]] if context.get("week") else []),
                        decider or NoDecider(), answers)


def _status(outcome):
    if isinstance(outcome, Failure):
        return "failed"
    if isinstance(outcome, Question):
        return "ask"
    return "confirm" if outcome.confirm else "done"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_gold_command_plans_as_expected(gold_kitchen, case):
    outcome = _plan(case["say"], case["context"])
    expect = case["expect"]
    assert _status(outcome) == expect["status"]
    if isinstance(outcome, Plan):
        got = [a.to_json() for a in outcome.actions]
        assert len(got) == len(expect["actions"])
        for want, have in zip(expect["actions"], got):
            assert want.items() <= have.items(), (want, have)
    if isinstance(outcome, Question):
        assert [o.id for o in outcome.options] == expect["options"]


def test_no_model_is_called_when_rules_and_feasibility_decide(gold_kitchen):
    d = ScriptedDecider({"x": "plan_cook"})
    _plan("put this on friday dinner", {"screen": "recipe", "recipe": "Chicken Caldo A"}, d)
    _plan("we're out of eggs", {"screen": "home"}, d)
    assert d.calls == []


def test_decider_breaks_a_plan_or_move_tie(gold_kitchen):
    d = ScriptedDecider({"x": "move_cook"})
    outcome = _plan("put this on friday", {"screen": "recipe", "recipe": "Miso Salmon Bowls"}, d)
    assert [a.type for a in outcome.actions] == ["move_cook"]
    assert d.calls[0][1] == ["plan_cook", "move_cook"]


def test_an_answer_resolves_the_question_it_was_asked(gold_kitchen):
    context = {"screen": "recipe", "recipe": "Miso Salmon Bowls"}
    first = _plan("put this on friday", context)
    assert first.key == "intent:0"
    second = _plan("put this on friday", context, answers={"intent:0": "plan_cook"})
    assert [a.type for a in second.actions] == ["plan_cook"]


def test_recipe_answer_must_be_one_of_the_options(gold_kitchen):
    context = {"screen": "home"}
    ok = _plan("put the caldo on monday", context, answers={"recipe:0": "Chicken Caldo B"})
    assert ok.actions[0].args["recipe"] == "Chicken Caldo B"
    bad = _plan("put the caldo on monday", context, answers={"recipe:0": "Butter Biscuits"})
    assert isinstance(bad, Question) and bad.key == "recipe:0"


def test_next_friday_asks_which_friday(gold_kitchen):
    context = {"screen": "recipe", "recipe": "Chicken Caldo A"}
    q = _plan("put this on next friday", context)
    assert q.key == "date:0" and [o.id for o in q.options] == ["2026-11-13", "2026-11-20"]
    done = _plan("put this on next friday", context, answers={"date:0": "2026-11-20"})
    assert done.actions[0].args["date"] == "2026-11-20"


def test_leftovers_without_a_meal_asks_which_meal(gold_kitchen):
    context = {"screen": "recipe", "recipe": "Chicken Caldo A"}
    q = _plan("put this on friday and the leftovers on saturday", context)
    assert q.key == "meal:1" and [o.id for o in q.options] == ["breakfast", "lunch", "dinner"]


def test_leftovers_refer_to_the_cook_planned_in_the_same_sentence(gold_kitchen):
    outcome = _plan(CASES[0]["say"], CASES[0]["context"])
    assert outcome.actions[1].args["cook"] == {"new": 0}
    assert outcome.actions[2].args["cook"] == {"new": 0}


def test_rule_that_cannot_run_explains_why(gold_kitchen):
    outcome = _plan("thaw the biscuits for friday", {"screen": "home"})
    assert isinstance(outcome, Failure) and "freezer" in outcome.reason


def test_out_of_something_we_do_not_have(gold_kitchen):
    outcome = _plan("we're out of saffron", {"screen": "home"})
    assert isinstance(outcome, Failure) and "saffron" in outcome.reason


def test_describe_uses_words_not_ids(gold_kitchen):
    k = Kitchen.load(TODAY, ["2026-W47"])
    outcome = planner.plan("take the chili off tuesday",
                           {"screen": "planner", "week": "2026-W47"}, k, NoDecider())
    assert outcome.confirm == ["Remove Bean Chili from Tue Nov 17"]


def test_weeks_touched(gold_kitchen):
    outcome = _plan(CASES[0]["say"], CASES[0]["context"])
    assert planner.weeks_touched(outcome) == {"2026-W47"}
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_planner.py -q`
Expected: FAIL — `cannot import name 'planner'`.

- [ ] **Step 3: Implement**

`lib/command/planner.py`:

```python
"""Sentence + screen context -> a Plan, a Question, or a Failure. Changes nothing.

Order of authority for "which action is this phrase?":
rule -> the user's earlier answer -> only one feasible -> decider -> ask the user.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from lib.command import intents
from lib.command.decider import Option
from lib.command.intents import INTENTS, Facts
from lib.command.phrases import split_phrases
from lib.command.resolve import Kitchen
from lib.command.slots import MEALS, NUMBER_WORDS, extract, iso_week, item_text, week_monday

REPHRASE = "rephrase"
_RECIPE_POOL = {"plan_cook": "any", "mark_cooked": "any", "open_page": "any",
                "move_cook": "planned", "remove_cook": "planned", "thaw": "frozen"}
_MODIFIER_WORDS = {"double", "triple", "half", "batch", "batches", "make", "it", "the",
                   "for", "please", "of", "serving", "servings"} | set(MEALS) | set(NUMBER_WORDS)


@dataclass
class Action:
    type: str
    args: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"type": self.type, **self.args}


@dataclass
class Plan:
    actions: list
    confirm: list = field(default_factory=list)


@dataclass
class Question:
    key: str
    text: str
    options: list = field(default_factory=list)


@dataclass
class Failure:
    reason: str


def day_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%a %b')} {d.day}"


def _modifier_only(phrase: str, s) -> bool:
    tokens = re.findall(r"[a-z]+", phrase.lower())
    return bool(tokens) and all(t in _MODIFIER_WORDS for t in tokens) \
        and bool(s.scale or s.meal or s.count)


def _apply_modifier(action: Action, s) -> None:
    if s.scale and action.type == "plan_cook":
        action.args["scale"] = s.scale
    if s.scale and action.type == "mark_cooked":
        action.args["batches"] = s.scale
    if s.meal and "meal" in action.args:
        action.args["meal"] = s.meal
    if s.count and "count" in action.args:
        action.args["count"] = s.count


def plan(text, context, kitchen: Kitchen, decider, answers=None):
    answers = answers or {}
    screen = context.get("screen", "other")
    screen_recipe = context.get("recipe")
    week_start = week_monday(context["week"]) if screen == "planner" and context.get("week") else None

    actions: list = []
    last_cook = None      # {"new": index} or {"id": cook_id} of the cook leftovers refer to
    prev_date = None

    for i, phrase in enumerate(split_phrases(text, protect=kitchen.recipes)):
        if intents.UNSUPPORTED.search(phrase):
            return Failure("Shopping-list commands aren't built yet.")

        s = extract(phrase, today=kitchen.today, week_start=week_start, prev_date=prev_date)
        if s.date_options:
            valid = [d.isoformat() for d in s.date_options]
            picked = answers.get(f"date:{i}")
            if picked not in valid:
                return Question(f"date:{i}", "Which day did you mean?",
                                [Option(v, day_text(v)) for v in valid])
            s.dates = s.nav_dates = [date.fromisoformat(picked)]

        facts = Facts(
            phrase=phrase, slots=s,
            any=kitchen.find_recipe(phrase, screen_recipe),
            planned=kitchen.find_recipe(phrase, screen_recipe, pool=kitchen.planned_names()),
            frozen=kitchen.find_recipe(phrase, screen_recipe, pool=kitchen.frozen_names()),
            item=item_text(phrase), has_prior_cook=last_cook is not None)

        rule = intents.rule_for(phrase)
        if rule is None and actions and _modifier_only(phrase, s):
            _apply_modifier(actions[-1], s)
            continue

        continues_add = (rule is None and actions and actions[-1].type == "inventory_add"
                         and facts.item and not s.dates
                         and facts.any.how not in ("exact", "pointer"))
        if continues_add:
            name = "inventory_add"
        elif rule is not None:
            if not intents.feasible(rule, facts):
                return Failure(intents.why_not(rule, facts))
            name = rule
        else:
            options = intents.candidates(facts, screen)
            answered = answers.get(f"intent:{i}")
            if answered in options:
                name = answered
            elif len(options) == 1:
                name = options[0]
            elif not options:
                return Question(REPHRASE, f"I couldn't tell what to do with “{phrase}”. "
                                          "Try naming a recipe and a day.")
            else:
                choices = [Option(o, INTENTS[o].label, INTENTS[o].hint) for o in options]
                name = decider.decide(f"Part of the command: {phrase}", choices,
                                      f"Whole command: {text}")
                if name not in options:
                    return Question(f"intent:{i}", f"What should I do with “{phrase}”?", choices)

        built = _build(name, i, facts, kitchen, answers, last_cook)
        if not isinstance(built, Action):
            return built
        actions.append(built)
        if name == "plan_cook":
            last_cook = {"new": len(actions) - 1}
        if s.dates:
            prev_date = s.dates[-1]

    if not actions:
        return Question(REPHRASE, "I didn't catch a command. Try again?")
    confirm = [describe(a, kitchen) for a in actions if _needs_confirm(a)]
    return Plan(actions, confirm)


def _needs_confirm(action: Action) -> bool:
    if INTENTS[action.type].policy == "confirm":
        return True
    return action.type == "inventory_remove" and action.args["rows"] > 1


def _recipe(name, i, facts, answers):
    """The recipe this intent acts on, or a Question / Failure."""
    match = getattr(facts, _RECIPE_POOL[name])
    if match.name:
        return match.name
    if match.options:
        picked = answers.get(f"recipe:{i}")
        if picked in match.options:
            return picked
        return Question(f"recipe:{i}", "Which one?", [Option(o, o) for o in match.options])
    return Failure(intents.why_not(name, facts))


def _build(name, i, facts, kitchen, answers, last_cook):
    s = facts.slots
    recipe = None
    if name in _RECIPE_POOL and not (name == "open_page" and not (facts.any.name or facts.any.options)):
        recipe = _recipe(name, i, facts, answers)
        if not isinstance(recipe, str):
            return recipe

    if name == "plan_cook":
        return Action(name, {"recipe": recipe, "date": s.dates[-1].isoformat(),
                             "meal": s.meal or "dinner", "scale": s.scale or 1.0})

    if name in ("place_leftovers", "freeze_rest"):
        cook = last_cook
        if cook is None:
            planned = kitchen.planned(facts.planned.name) if facts.planned.name else []
            if len(planned) != 1:
                return Failure(intents.why_not(name, facts))
            cook = {"id": planned[0]["id"]}
        if name == "freeze_rest":
            return Action(name, {"cook": cook})
        meal = s.meal or answers.get(f"meal:{i}")
        if meal not in MEALS:
            return Question(f"meal:{i}", "Which meal are the leftovers for?",
                            [Option(m, m.capitalize()) for m in ("breakfast", "lunch", "dinner")])
        return Action(name, {"cook": cook, "date": s.dates[-1].isoformat(),
                             "meal": meal, "count": s.count or 1.0})

    if name in ("move_cook", "remove_cook"):
        source = s.dates[0] if (name == "remove_cook" and s.dates) or len(s.dates) > 1 else None
        planned = kitchen.planned(recipe, on=source)
        if len(planned) != 1:
            return Failure(f"{kitchen.display(recipe)} is on the plan "
                           f"{len(planned)} times for that — say which day.")
        cook = planned[0]
        args = {"cook_id": cook["id"], "recipe": recipe, "cook_week": cook["week"],
                "bundle_id": cook.get("bundle_id")}
        if name == "remove_cook":
            return Action(name, {**args, "date": cook["date"]})
        return Action(name, {**args, "date": s.dates[-1].isoformat(),
                             "meal": s.meal or cook["meal"]})

    if name == "mark_cooked":
        return Action(name, {"recipe": recipe, "batches": s.scale or 1.0})

    if name == "thaw":
        count = s.count or 1.0
        row = next((r for r in kitchen.frozen(recipe) if r["count"] >= count), None)
        if row is None:
            return Failure(f"There aren't {count:g} servings of {kitchen.display(recipe)} in the freezer.")
        return Action(name, {"placement_id": row["placement_id"], "cook_id": row["cook_id"],
                             "recipe": recipe, "date": s.dates[-1].isoformat(),
                             "meal": s.meal or "dinner", "count": count,
                             "cook_week": row["cook_week"]})

    if name == "inventory_add":
        return Action(name, {"item": facts.item, "quantity": s.quantity or 1.0,
                             "unit": s.unit or "ct"})

    if name in ("inventory_remove", "inventory_move"):
        rows = kitchen.inventory_rows(facts.item)
        if not rows:
            return Failure(f"There's no {facts.item} in the inventory.")
        names = sorted({r["name"] for r in rows})
        if len(names) > 1:
            return Failure(f"“{facts.item}” matches {', '.join(names)} — say which.")
        if name == "inventory_remove":
            return Action(name, {"name": names[0], "rows": len(rows)})
        return Action(name, {"name": names[0], "location": s.location})

    # open_page
    if recipe:
        return Action(name, {"page": "recipe", "recipe": recipe})
    if s.nav_dates:
        day = s.nav_dates[-1]
        return Action(name, {"page": "day", "date": day.isoformat(), "week": iso_week(day)})
    low = facts.phrase.lower()
    page = "inventory" if "inventory" in low else "planner" if "plan" in low else "home"
    return Action(name, {"page": page})


def describe(action: Action, kitchen: Kitchen) -> str:
    a = action.args
    name = kitchen.display(a["recipe"]) if a.get("recipe") else ""
    if action.type == "plan_cook":
        extra = f" (×{a['scale']:g})" if a["scale"] != 1.0 else ""
        return f"{day_text(a['date'])} {a['meal']} — {name}{extra}"
    if action.type == "place_leftovers":
        return f"{day_text(a['date'])} {a['meal']} — {a['count']:g} leftover serving(s)"
    if action.type == "freeze_rest":
        return "Freeze the rest"
    if action.type == "move_cook":
        return f"Move {name} to {day_text(a['date'])} {a['meal']}"
    if action.type == "remove_cook":
        return f"Remove {name} from {day_text(a['date'])}"
    if action.type == "mark_cooked":
        return f"Cooked {name}"
    if action.type == "thaw":
        return f"{day_text(a['date'])} {a['meal']} — {a['count']:g} {name} from the freezer"
    if action.type == "inventory_add":
        return f"Added {a['quantity']:g} {a['unit']} {a['item']}"
    if action.type == "inventory_remove":
        rows = f" ({a['rows']} rows)" if a["rows"] > 1 else ""
        return f"Remove {a['name']} from inventory{rows}"
    if action.type == "inventory_move":
        return f"Moved {a['name']} to the {a['location']}"
    if a["page"] == "recipe":
        return f"Opening {name}"
    if a["page"] == "day":
        return f"Opening {day_text(a['date'])}"
    return f"Opening {a['page']}"


def weeks_touched(plan: Plan) -> set:
    weeks = set()
    for action in plan.actions:
        if action.type == "open_page":
            continue
        if action.args.get("date"):
            weeks.add(iso_week(date.fromisoformat(action.args["date"])))
        if action.args.get("cook_week"):
            weeks.add(action.args["cook_week"])
    return weeks
```

- [ ] **Step 4: Run to verify pass**

Run: `$PY -m pytest tests/test_command_planner.py -q`
Expected: `31 passed` (20 gold cases + 11 others).

If a gold case fails, fix the planner or its helpers — do not edit `commands.json` to match the code. The one exception is a genuine error in the expectation; say so in the commit message.

- [ ] **Step 5: Commit**

```bash
git add lib/command/planner.py tests/test_command_planner.py
git commit -m "feat(command): planner turns a sentence into a plan, question or failure"
```

---

### Task 7: Command log and snapshots

**Files:**
- Modify: `lib/inventory_db.py` — add the `command_log` table to `_SCHEMA` (after the `placements` table) and two public helpers after `replace_inventory_rows`
- Create: `lib/command/log.py`, `tests/test_command_log.py`

**Interfaces:**
- Consumes: `inventory_db.connect()`.
- Produces:
  - `inventory_db.inventory_rows_in(conn) -> list[dict]`, `inventory_db.replace_inventory_rows_in(conn, rows) -> None`
  - `log.create(text: str, context: dict) -> int`
  - `log.update(command_id: int, **fields) -> None` — fields among `status, answers, plan, response, undo`; dict/list values are JSON-encoded
  - `log.get(command_id: int) -> dict | None` — JSON columns decoded
  - `log.recent_duplicate(text: str, context: dict, window_s: float) -> dict | None`
  - `log.snap_cook(conn, cook_id: int) -> dict | None`
  - `log.restore_cook(conn, cook_id: int, snapshot: dict | None) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_command_log.py`:

```python
from lib import inventory_db, serving_ledger
from lib.command import log


def test_create_get_update_round_trip(tmp_db):
    cid = log.create("put this on friday", {"screen": "recipe", "recipe": "Chili"})
    row = log.get(cid)
    assert row["status"] == "new" and row["context"]["recipe"] == "Chili" and row["answers"] == {}
    log.update(cid, status="done", response={"status": "done"}, undo={"cooks": {}})
    row = log.get(cid)
    assert row["status"] == "done" and row["response"] == {"status": "done"}
    assert log.get(9999) is None


def test_recent_duplicate_only_matches_done_commands(tmp_db):
    context = {"screen": "home"}
    cid = log.create("we're out of eggs", context)
    assert log.recent_duplicate("we're out of eggs", context, 5.0) is None
    log.update(cid, status="done", response={"status": "done"})
    assert log.recent_duplicate("we're out of eggs", context, 5.0)["id"] == cid
    assert log.recent_duplicate("we're out of eggs", {"screen": "recipe"}, 5.0) is None
    assert log.recent_duplicate("we're out of eggs", context, 0) is None


def test_snapshot_and_restore_a_changed_cook(tmp_db):
    cook = serving_ledger.create_cook("Chili", "2026-W47", servings_produced=6.0,
                                      date="2026-11-17", meal="dinner")
    conn = inventory_db.connect()
    try:
        before = log.snap_cook(conn, cook["id"])
    finally:
        conn.close()
    serving_ledger.add_placement(cook["id"], "freezer", 4)
    serving_ledger.move_cook(cook["id"], "2026-11-19", "lunch")

    conn = inventory_db.connect()
    try:
        with conn:
            log.restore_cook(conn, cook["id"], before)
        assert log.snap_cook(conn, cook["id"]) == before
    finally:
        conn.close()
    assert serving_ledger.get_cook(cook["id"])["date"] == "2026-11-17"


def test_restore_recreates_a_deleted_cook_and_deletes_a_created_one(tmp_db):
    cook = serving_ledger.create_cook("Chili", "2026-W47", servings_produced=6.0,
                                      date="2026-11-17", meal="dinner")
    conn = inventory_db.connect()
    try:
        before = log.snap_cook(conn, cook["id"])
        assert log.snap_cook(conn, 9999) is None
    finally:
        conn.close()
    serving_ledger.delete_cook(cook["id"])

    conn = inventory_db.connect()
    try:
        with conn:
            log.restore_cook(conn, cook["id"], before)
        assert log.snap_cook(conn, cook["id"]) == before
        with conn:
            log.restore_cook(conn, cook["id"], None)
        assert log.snap_cook(conn, cook["id"]) is None
    finally:
        conn.close()


def test_inventory_helpers_round_trip(tmp_db):
    from lib.inventory import InventoryItem, add_items
    add_items([InventoryItem(name="eggs", quantity=12, location="fridge")])
    conn = inventory_db.connect()
    try:
        rows = inventory_db.inventory_rows_in(conn)
        with conn:
            inventory_db.replace_inventory_rows_in(conn, [])
        assert inventory_db.inventory_rows_in(conn) == []
        with conn:
            inventory_db.replace_inventory_rows_in(conn, rows)
        assert inventory_db.inventory_rows_in(conn) == rows
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_log.py -q`
Expected: FAIL — `cannot import name 'log'`.

- [ ] **Step 3: Add the table and helpers to `lib/inventory_db.py`**

In `_SCHEMA`, directly after the closing `);` of the `CREATE TABLE IF NOT EXISTS placements (...)` statement, insert:

```sql
-- One row per spoken/typed command (lib/command). `undo` holds before/after
-- snapshots of every row the command touched; see lib/command/executor.py.
CREATE TABLE IF NOT EXISTS command_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    context TEXT NOT NULL,
    answers TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'new',
    plan TEXT,
    response TEXT,
    undo TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Directly after the existing `replace_inventory_rows` function, add:

```python
def inventory_rows_in(conn: sqlite3.Connection) -> list[dict]:
    """Every inventory row, read on a caller's connection (so, in its transaction)."""
    return _fetch_inventory_rows(conn)


def replace_inventory_rows_in(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Overwrite the inventory table on a caller's connection. Caller commits."""
    _replace_inventory_rows(conn, rows)
```

- [ ] **Step 4: Implement `lib/command/log.py`**

```python
"""The command log: what was said, what was done, and how to undo it."""
import json
from typing import Optional

from lib import inventory_db

_JSON_COLUMNS = ("context", "answers", "plan", "response", "undo")
_UPDATABLE = ("status", "answers", "plan", "response", "undo")


def _encode(value):
    return json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value


def create(text: str, context: dict) -> int:
    conn = inventory_db.connect()
    try:
        with conn:
            cur = conn.execute("INSERT INTO command_log (text, context) VALUES (?, ?)",
                               (text, _encode(context)))
        return cur.lastrowid
    finally:
        conn.close()


def update(command_id: int, **fields) -> None:
    bad = set(fields) - set(_UPDATABLE)
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute(f"UPDATE command_log SET {assignments} WHERE id = ?",
                         (*[_encode(v) for v in fields.values()], command_id))
    finally:
        conn.close()


def _decode(row) -> dict:
    out = dict(row)
    for column in _JSON_COLUMNS:
        if out.get(column) is not None:
            out[column] = json.loads(out[column])
    return out


def get(command_id: int) -> Optional[dict]:
    conn = inventory_db.connect()
    try:
        row = conn.execute("SELECT * FROM command_log WHERE id = ?", (command_id,)).fetchone()
    finally:
        conn.close()
    return _decode(row) if row else None


def recent_duplicate(text: str, context: dict, window_s: float) -> Optional[dict]:
    """The same sentence on the same screen, finished within ``window_s`` seconds."""
    if window_s <= 0:
        return None
    conn = inventory_db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM command_log WHERE text = ? AND context = ? AND status = 'done'"
            " AND created_at >= datetime('now', ?) ORDER BY id DESC LIMIT 1",
            (text, _encode(context), f"-{float(window_s)} seconds")).fetchone()
    finally:
        conn.close()
    return _decode(row) if row else None


def snap_cook(conn, cook_id: int) -> Optional[dict]:
    """A cook with its placements and schedule, exactly as stored. None if absent."""
    cook = conn.execute("SELECT * FROM cooks WHERE id = ?", (cook_id,)).fetchone()
    if cook is None:
        return None
    return {
        "cook": dict(cook),
        "placements": [dict(r) for r in conn.execute(
            "SELECT * FROM placements WHERE cook_id = ? ORDER BY id", (cook_id,))],
        "schedule": [dict(r) for r in conn.execute(
            "SELECT * FROM cook_schedule WHERE cook_id = ?", (cook_id,))],
    }


def _insert(conn, table: str, row: dict) -> None:
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values()))


def restore_cook(conn, cook_id: int, snapshot: Optional[dict]) -> None:
    """Make the cook exactly what ``snapshot`` says. None means "did not exist".

    The caller owns the transaction. Ids are preserved, so anything that pointed
    at the cook before still does.
    """
    conn.execute("DELETE FROM placements WHERE cook_id = ?", (cook_id,))
    conn.execute("DELETE FROM cook_schedule WHERE cook_id = ?", (cook_id,))
    conn.execute("DELETE FROM cooks WHERE id = ?", (cook_id,))
    if snapshot is None:
        return
    _insert(conn, "cooks", snapshot["cook"])
    for row in snapshot["placements"]:
        _insert(conn, "placements", row)
    for row in snapshot["schedule"]:
        _insert(conn, "cook_schedule", row)
```

- [ ] **Step 5: Run to verify pass**

Run: `$PY -m pytest tests/test_command_log.py tests/test_inventory_db.py -q`
Expected: all pass (`5 passed` for the new file; the existing DB tests still pass, proving the new table did not break `connect()`). If `tests/test_inventory_db.py` does not exist, run `$PY -m pytest tests/test_command_log.py tests/test_api_ledger.py -q` instead.

- [ ] **Step 6: Commit**

```bash
git add lib/inventory_db.py lib/command/log.py tests/test_command_log.py
git commit -m "feat(command): command log table and cook snapshots"
```

---

### Task 8: Executor and Undo

**Files:**
- Create: `lib/command/executor.py`, `tests/test_command_executor.py`

**Interfaces:**
- Consumes: `planner.Plan`, `planner.Action`, `planner.describe`; `log.snap_cook`, `log.restore_cook`; `inventory_db.inventory_rows_in`, `inventory_db.replace_inventory_rows_in`; `serving_ledger.create_cook / add_placement / get_cook / get_bundle / move_cook / move_bundle / delete_cook / delete_bundle / move_servings`; `week_view.recipe_base_servings(name) -> float`; `cook.consume_recipe(name, servings=) -> dict`; `inventory.add_items / remove_item / move_item / refresh_inventory_views`; `storage_locations.place_item(name, category)` returning an object with `.location` and `.source`.
- Produces:
  - `executor.Result(ok, lines, warnings, weeks, recipes, navigate, undo, error)`
  - `executor.run(plan: Plan, kitchen: Kitchen) -> Result`
  - `executor.undo(record: dict, force: bool = False) -> tuple[bool, str]`
  - `executor.undoable(record: dict | None) -> bool`
- Undo record shape: `{"cooks": {"<id>": {"before": snap|None, "after": snap|None}}, "inventory": {"before": rows, "after": rows} | None, "weeks": [...], "recipes": [...]}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_command_executor.py`:

```python
import json

from lib import inventory_db, serving_ledger
from lib.command import executor, planner
from lib.command.decider import NoDecider
from lib.command.planner import Action, Plan
from lib.command.resolve import Kitchen
from tests.gold.kitchen import TODAY


def _dump():
    conn = inventory_db.connect()
    try:
        state = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                 for t in ("cooks", "placements")}
    finally:
        conn.close()
    state["inventory"] = inventory_db.fetch_inventory_rows()
    return state


def _run(say, context, answers=None):
    kitchen = Kitchen.load(TODAY, [context["week"]] if context.get("week") else [])
    outcome = planner.plan(say, context, kitchen, NoDecider(), answers)
    assert isinstance(outcome, Plan), outcome
    return executor.run(outcome, kitchen)


def test_plan_leftovers_freeze_writes_the_ledger(gold_kitchen):
    result = _run("put this on wednesday, leftovers for lunch the next day and freeze the rest",
                  {"screen": "recipe", "recipe": "Chicken Caldo A"})
    assert result.ok and result.weeks == {"2026-W47"}
    cook = [c for c in serving_ledger.cooks_for_week("2026-W47")
            if c["recipe"] == "Chicken Caldo A"][0]
    placed = {(p["destination"], p["date"], p["meal"]): p["count"] for p in cook["placements"]}
    assert placed == {("slot", "2026-11-18", "dinner"): 1.0,
                      ("slot", "2026-11-19", "lunch"): 1.0,
                      ("freezer", None, None): 4.0}
    assert result.lines == ["Wed Nov 18 dinner — Chicken Caldo A",
                            "Thu Nov 19 lunch — 1 leftover serving(s)",
                            "Freezer — 4 servings"]


def test_undo_restores_the_database_exactly(gold_kitchen):
    before = _dump()
    result = _run("put this on wednesday and freeze the rest",
                  {"screen": "recipe", "recipe": "Chicken Caldo A"})
    assert _dump() != before
    record = json.loads(json.dumps(result.undo))      # as it comes back from the log
    assert executor.undo(record) == (True, "")
    assert _dump() == before


def test_undo_refuses_when_the_cook_changed_afterwards(gold_kitchen):
    result = _run("put this on friday dinner", {"screen": "recipe", "recipe": "Chicken Caldo A"})
    cook_id = int(next(iter(result.undo["cooks"])))
    serving_ledger.add_placement(cook_id, "freezer", 2)
    ok, reason = executor.undo(json.loads(json.dumps(result.undo)))
    assert not ok and "changed" in reason
    assert serving_ledger.get_cook(cook_id) is not None


def test_move_and_remove_and_thaw_are_undoable(gold_kitchen):
    for say, context in [
        ("move the salmon from wednesday to saturday", {"screen": "planner", "week": "2026-W47"}),
        ("take the chili off tuesday", {"screen": "planner", "week": "2026-W47"}),
        ("pull a caldo out of the freezer for friday dinner", {"screen": "home"}),
    ]:
        before = _dump()
        result = _run(say, context)
        assert result.ok, result.error
        assert _dump() != before
        assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
        assert _dump() == before


def test_a_bundle_moves_and_is_removed_as_one(gold_kitchen):
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("UPDATE cooks SET bundle_id = 'plate1', bundle_name = 'Chili Plate',"
                         " date = '2026-11-17', meal = 'dinner' WHERE id IN (?, ?)",
                         (gold_kitchen["chili"], gold_kitchen["salmon"]))
            conn.execute("UPDATE placements SET date = '2026-11-17' WHERE cook_id = ?",
                         (gold_kitchen["salmon"],))
    finally:
        conn.close()
    before = _dump()
    result = _run("move the chili to thursday", {"screen": "planner", "week": "2026-W47"})
    assert result.ok, result.error
    assert {c["date"] for c in serving_ledger.cooks_for_week("2026-W47")} == {"2026-11-19"}
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
    assert _dump() == before


def test_inventory_actions_and_their_undo(gold_kitchen):
    before = _dump()
    result = _run("add two cans of chickpeas and a bag of rice", {"screen": "home"})
    names = {r["name"]: r for r in inventory_db.fetch_inventory_rows()}
    assert names["chickpeas"]["quantity"] == 2.0 and names["chickpeas"]["unit"] == "can"
    assert names["chickpeas"]["location_source"] != "manual"   # never a fabricated confirmation
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
    assert _dump() == before

    result = _run("we're out of eggs", {"screen": "home"})
    assert "eggs" not in {r["name"] for r in inventory_db.fetch_inventory_rows()}
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
    assert _dump() == before

    result = _run("move the bread to the freezer", {"screen": "home"})
    bread = [r for r in inventory_db.fetch_inventory_rows() if r["name"] == "bread"][0]
    assert bread["location"] == "freezer"
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")


def test_undo_refuses_when_inventory_changed_afterwards(gold_kitchen):
    from lib.inventory import InventoryItem, add_items
    result = _run("we're out of eggs", {"screen": "home"})
    add_items([InventoryItem(name="butter", quantity=1, location="fridge")])
    ok, reason = executor.undo(json.loads(json.dumps(result.undo)))
    assert not ok and "Inventory" in reason


def test_mark_cooked_and_open_page(gold_kitchen):
    result = _run("I cooked this tonight", {"screen": "recipe", "recipe": "Chicken Caldo A"})
    assert result.ok and result.lines == ["Cooked Chicken Caldo A"]
    result = _run("open saturday", {"screen": "home"})
    assert result.ok and result.navigate == {"page": "day", "date": "2026-11-14", "week": "2026-W46"}
    assert not executor.undoable(result.undo)


def test_a_failing_action_rolls_back_the_ones_before_it(gold_kitchen):
    before = _dump()
    kitchen = Kitchen.load(TODAY)
    plan = Plan([
        Action("plan_cook", {"recipe": "Miso Salmon Bowls", "date": "2026-11-13",
                             "meal": "dinner", "scale": 1.0}),
        Action("place_leftovers", {"cook": {"new": 0}, "date": "2026-11-14",
                                   "meal": "lunch", "count": 9.0}),
    ])
    result = executor.run(plan, kitchen)
    assert not result.ok and result.error
    assert _dump() == before
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_executor.py -q`
Expected: FAIL — `cannot import name 'executor'`.

- [ ] **Step 3: Implement**

`lib/command/executor.py`:

```python
"""Run a Plan through the ledger and inventory code, and undo it.

Every handler calls the same functions the web UI's own endpoints call — this
module adds no new way to write a cook or an inventory row. What it adds is the
record: a before/after snapshot of each row a command touched. Undo restores
"before" and refuses if the row no longer matches "after".
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from lib import inventory_db
from lib.command import log
from lib.command.planner import Plan, day_text, describe
from lib.command.resolve import Kitchen
from lib.command.slots import iso_week


@dataclass
class Result:
    ok: bool
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    weeks: set = field(default_factory=set)
    recipes: set = field(default_factory=set)
    navigate: Optional[dict] = None
    undo: Optional[dict] = None
    error: Optional[str] = None


class _Run:
    def __init__(self, kitchen: Kitchen):
        self.kitchen = kitchen
        self.cooks: dict = {}          # str(cook id) -> {"before": snap}
        self.inventory: Optional[dict] = None
        self.new_cooks: dict = {}      # action index -> cook id
        self.result = Result(ok=True)

    def touch_cook(self, cook_id: int) -> None:
        key = str(cook_id)
        if key in self.cooks:
            return
        conn = inventory_db.connect()
        try:
            self.cooks[key] = {"before": log.snap_cook(conn, cook_id)}
        finally:
            conn.close()

    def created_cook(self, cook_id: int) -> None:
        self.cooks[str(cook_id)] = {"before": None}

    def touch_inventory(self) -> None:
        if self.inventory is None:
            self.inventory = {"before": inventory_db.fetch_inventory_rows()}

    def record(self) -> dict:
        conn = inventory_db.connect()
        try:
            for key, entry in self.cooks.items():
                entry["after"] = log.snap_cook(conn, int(key))
        finally:
            conn.close()
        if self.inventory is not None:
            self.inventory["after"] = inventory_db.fetch_inventory_rows()
        return {"cooks": self.cooks, "inventory": self.inventory,
                "weeks": sorted(self.result.weeks), "recipes": sorted(self.result.recipes)}

    def cook_id(self, ref: dict) -> int:
        return self.new_cooks[ref["new"]] if "new" in ref else ref["id"]


def _members(cook_id: int, bundle_id) -> list:
    from lib import serving_ledger
    if not bundle_id:
        return [cook_id]
    bundle = serving_ledger.get_bundle(bundle_id)
    return [c["id"] for c in bundle["cooks"]] if bundle else [cook_id]


def _plan_cook(run, index, action):
    from lib import serving_ledger, week_view
    a = action.args
    week = iso_week(date.fromisoformat(a["date"]))
    servings = week_view.recipe_base_servings(a["recipe"]) * float(a["scale"])
    cook = serving_ledger.create_cook(
        a["recipe"], week, scale=float(a["scale"]), servings_produced=servings,
        date=a["date"], meal=a["meal"], initial_placement_count=1.0)
    run.created_cook(cook["id"])
    run.new_cooks[index] = cook["id"]
    run.result.weeks.add(week)
    run.result.recipes.add(a["recipe"])
    try:
        from lib import dislike_guard
        hits = dislike_guard.warning_for([a["recipe"]])
        if hits:
            run.result.warnings.append(hits)
    except Exception:
        pass
    return describe(action, run.kitchen)


def _place_leftovers(run, index, action):
    from lib import serving_ledger
    a = action.args
    cook_id = run.cook_id(a["cook"])
    run.touch_cook(cook_id)
    serving_ledger.add_placement(cook_id, "slot", float(a["count"]), a["date"], a["meal"])
    run.result.weeks.update({iso_week(date.fromisoformat(a["date"])),
                             serving_ledger.get_cook(cook_id)["week"]})
    return describe(action, run.kitchen)


def _freeze_rest(run, index, action):
    from lib import serving_ledger
    cook_id = run.cook_id(action.args["cook"])
    run.touch_cook(cook_id)
    cook = serving_ledger.get_cook(cook_id)
    left = cook["unassigned"]
    if left <= 0:
        return "Nothing left to freeze"
    serving_ledger.add_placement(cook_id, "freezer", left)
    run.result.weeks.add(cook["week"])
    return f"Freezer — {left:g} servings"


def _move_cook(run, index, action):
    from lib import serving_ledger
    a = action.args
    for member in _members(a["cook_id"], a.get("bundle_id")):
        run.touch_cook(member)
    if a.get("bundle_id"):
        serving_ledger.move_bundle(a["bundle_id"], a["date"], a["meal"])
    else:
        serving_ledger.move_cook(a["cook_id"], a["date"], a["meal"])
    run.result.weeks.update({a["cook_week"], iso_week(date.fromisoformat(a["date"]))})
    return describe(action, run.kitchen)


def _remove_cook(run, index, action):
    from lib import serving_ledger
    a = action.args
    for member in _members(a["cook_id"], a.get("bundle_id")):
        run.touch_cook(member)
    if a.get("bundle_id"):
        removed = serving_ledger.delete_bundle(a["bundle_id"])
        run.result.recipes.update(c["recipe"] for c in removed)
    else:
        serving_ledger.delete_cook(a["cook_id"])
        run.result.recipes.add(a["recipe"])
    run.result.weeks.add(a["cook_week"])
    return f"Removed {run.kitchen.display(a['recipe'])} from {day_text(a['date'])}"


def _thaw(run, index, action):
    from lib import serving_ledger
    a = action.args
    run.touch_cook(a["cook_id"])
    serving_ledger.move_servings(a["placement_id"], float(a["count"]), "slot",
                                 a["date"], a["meal"])
    run.result.weeks.update({a["cook_week"], iso_week(date.fromisoformat(a["date"]))})
    return describe(action, run.kitchen)


def _mark_cooked(run, index, action):
    from lib.cook import consume_recipe
    a = action.args
    run.touch_inventory()
    summary = consume_recipe(a["recipe"], servings=float(a["batches"]))
    if summary.get("error"):
        raise ValueError(summary["error"])
    run.result.recipes.add(a["recipe"])
    return describe(action, run.kitchen)


def _inventory_add(run, index, action):
    from lib.inventory import InventoryItem, add_items
    from lib.storage_locations import place_item
    a = action.args
    run.touch_inventory()
    # The user did not say where it goes, so the storage table decides and the
    # row records that as a guess — never as a confirmed placement.
    placement = place_item(a["item"], "other")
    add_items([InventoryItem(name=a["item"], quantity=float(a["quantity"]), unit=a["unit"],
                             category="other", location=placement.location,
                             location_source=placement.source, source="manual")])
    return describe(action, run.kitchen)


def _inventory_remove(run, index, action):
    from lib.inventory import remove_item
    run.touch_inventory()
    if not remove_item(action.args["name"]):
        raise ValueError(f"There's no {action.args['name']} in the inventory.")
    return f"Removed {action.args['name']} from inventory"


def _inventory_move(run, index, action):
    from lib.inventory import move_item
    run.touch_inventory()
    if move_item(action.args["name"], action.args["location"]) is None:
        raise ValueError(f"There's no {action.args['name']} in the inventory.")
    return describe(action, run.kitchen)


def _open_page(run, index, action):
    run.result.navigate = dict(action.args)
    return describe(action, run.kitchen)


_HANDLERS = {
    "plan_cook": _plan_cook, "place_leftovers": _place_leftovers, "freeze_rest": _freeze_rest,
    "move_cook": _move_cook, "remove_cook": _remove_cook, "thaw": _thaw,
    "mark_cooked": _mark_cooked, "inventory_add": _inventory_add,
    "inventory_remove": _inventory_remove, "inventory_move": _inventory_move,
    "open_page": _open_page,
}


def run(plan: Plan, kitchen: Kitchen) -> Result:
    state = _Run(kitchen)
    try:
        for index, action in enumerate(plan.actions):
            state.result.lines.append(_HANDLERS[action.type](state, index, action))
    except (ValueError, TypeError, sqlite3.Error) as exc:
        # OverplacementError is a ValueError. Put back whatever already ran.
        undo(state.record(), force=True)
        return Result(ok=False, error=str(exc), weeks=state.result.weeks,
                      recipes=state.result.recipes)
    state.result.undo = state.record()
    return state.result


def undoable(record: Optional[dict]) -> bool:
    return bool(record and (record.get("cooks") or record.get("inventory")))


def undo(record: dict, force: bool = False) -> tuple:
    """Restore every "before". Returns (ok, reason). ``force`` skips the changed-since check."""
    from lib.inventory import refresh_inventory_views

    cooks = record.get("cooks") or {}
    inventory = record.get("inventory")
    conn = inventory_db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not force:
            for key, entry in cooks.items():
                if log.snap_cook(conn, int(key)) != entry.get("after"):
                    conn.rollback()
                    return False, "The meal plan has changed since then, so I left it alone."
            if inventory and inventory_db.inventory_rows_in(conn) != inventory.get("after"):
                conn.rollback()
                return False, "Inventory has changed since then, so I left it alone."
        for key in reversed(list(cooks)):
            log.restore_cook(conn, int(key), cooks[key]["before"])
        if inventory:
            inventory_db.replace_inventory_rows_in(conn, inventory["before"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if inventory:
        refresh_inventory_views()
    return True, ""
```

- [ ] **Step 4: Run to verify pass**

Run: `$PY -m pytest tests/test_command_executor.py -q`
Expected: `9 passed`.

Two things to check if a test fails rather than guessing:
- `test_a_bundle_moves_and_is_removed_as_one` depends on `move_bundle` accepting a same-week date. If the ledger raises, read `serving_ledger._move_cook_in_txn` and adjust the *test's* target date, not the executor.
- `test_inventory_actions_and_their_undo` asserts the placed row is not `manual`. If `place_item` returns a different attribute name than `.source`, read `lib/storage_locations.py::place_item` and use the real one in `_inventory_add`.

- [ ] **Step 5: Commit**

```bash
git add lib/command/executor.py tests/test_command_executor.py
git commit -m "feat(command): execute plans through the ledger with snapshot undo"
```

---

### Task 9: Context validation and the three API routes

**Files:**
- Create: `lib/command/context.py`, `tests/test_command_api.py`
- Modify: `api_server.py` — add the routes directly after the `api_freezer` route function (search for `@app.route('/api/freezer', methods=['GET'])` and insert after that function ends)

**Interfaces:**
- Consumes: Tasks 3–8; `api_server._import_legacy_if_first_write(*weeks)`, `_regen_weeks(*weeks)`, `_sync_cook_history(*recipes)`, `require_token`; `lib.safe_paths.parse_iso_week`.
- Produces:
  - `context.validate(raw) -> dict` (raises `ValueError`)
  - `POST /api/command`, `POST /api/command/<int:command_id>/answer`, `POST /api/command/<int:command_id>/undo`
  - `api_server._command_today() -> date` (the one seam tests patch)

- [ ] **Step 1: Write the failing tests**

`tests/test_command_api.py`:

```python
import json
from pathlib import Path

import pytest

import api_server
from api_server import app
from lib import inventory_db
from lib.command import context as command_context
from tests.gold.kitchen import TODAY

CASES = json.loads((Path(__file__).parent / "gold" / "commands.json").read_text())


@pytest.fixture
def client(monkeypatch, gold_kitchen):
    monkeypatch.setattr(api_server, "_command_today", lambda: TODAY)
    monkeypatch.setenv("KITCHENOS_NO_LLM", "1")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _dump():
    conn = inventory_db.connect()
    try:
        state = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                 for t in ("cooks", "placements")}
    finally:
        conn.close()
    state["inventory"] = inventory_db.fetch_inventory_rows()
    return state


def _say(client, say, context):
    return client.post("/api/command", json={"text": say, "context": context}).get_json()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_gold_happy_path(client, case):
    """Every gold command: right outcome, and Undo leaves the database as it was."""
    before = _dump()
    body = _say(client, case["say"], case["context"])
    expect = case["expect"]
    assert body["status"] == expect["status"], body

    if expect["status"] == "ask":
        assert [o["id"] for o in body["options"]] == expect["options"]
        assert _dump() == before
        return
    if expect["status"] == "failed":
        assert body["reason"] and _dump() == before
        return
    if expect["status"] == "confirm":
        assert _dump() == before, "a confirm must not have changed anything yet"
        body = client.post(f"/api/command/{body['command_id']}/answer",
                           json={"confirm": True}).get_json()
        assert body["status"] == "done", body

    assert len(body["actions"]) == len(expect["actions"])
    for want, have in zip(expect["actions"], body["actions"]):
        assert want.items() <= have.items(), (want, have)
    assert body["lines"] and all("2026-W" not in line for line in body["lines"])

    if body["undo"]:
        undone = client.post(f"/api/command/{body['command_id']}/undo").get_json()
        assert undone == {"status": "undone"}
        assert _dump() == before


def test_answering_a_question_finishes_the_command(client):
    body = _say(client, "put the caldo on monday", {"screen": "home"})
    assert body["status"] == "ask" and body["question"] == "Which one?"
    body = client.post(f"/api/command/{body['command_id']}/answer",
                       json={"option": "Chicken Caldo B"}).get_json()
    assert body["status"] == "done"
    assert body["actions"][0]["recipe"] == "Chicken Caldo B"


def test_an_answer_that_was_not_offered_is_rejected(client):
    body = _say(client, "put the caldo on monday", {"screen": "home"})
    resp = client.post(f"/api/command/{body['command_id']}/answer", json={"option": "Butter Biscuits"})
    assert resp.status_code == 400


def test_declining_a_confirm_changes_nothing(client):
    before = _dump()
    body = _say(client, "take the chili off tuesday", {"screen": "planner", "week": "2026-W47"})
    body = client.post(f"/api/command/{body['command_id']}/answer", json={"confirm": False}).get_json()
    assert body == {"status": "failed", "reason": "Cancelled."}
    assert _dump() == before


def test_undo_twice_and_undo_of_unknown(client):
    body = _say(client, "we're out of eggs", {"screen": "home"})
    assert client.post(f"/api/command/{body['command_id']}/undo").status_code == 200
    assert client.post(f"/api/command/{body['command_id']}/undo").status_code == 409
    assert client.post("/api/command/99999/undo").status_code == 404


def test_undo_refused_after_a_later_change(client):
    from lib.inventory import InventoryItem, add_items
    body = _say(client, "we're out of eggs", {"screen": "home"})
    add_items([InventoryItem(name="butter", quantity=1, location="fridge")])
    resp = client.post(f"/api/command/{body['command_id']}/undo")
    assert resp.status_code == 409 and resp.get_json()["status"] == "refused"


def test_a_double_send_runs_once(client):
    context = {"screen": "recipe", "recipe": "Chicken Caldo A"}
    first = _say(client, "put this on friday dinner", context)
    second = _say(client, "put this on friday dinner", context)
    assert second["command_id"] == first["command_id"]
    from lib import serving_ledger
    assert len([c for c in serving_ledger.cooks_for_week("2026-W46")
                if c["recipe"] == "Chicken Caldo A"]) == 1


def test_bad_requests(client):
    assert client.post("/api/command", json={"text": "", "context": {"screen": "home"}}).status_code == 400
    assert client.post("/api/command", json={"text": "x" * 501, "context": {"screen": "home"}}).status_code == 400
    for bad in [{"screen": "nope"}, {"screen": "recipe", "recipe": "../etc/passwd"},
                {"screen": "planner", "week": "2026-W99"}, {"screen": "home", "url": "http://x"},
                {"screen": "home", "date": "2026-02-30"}]:
        assert client.post("/api/command", json={"text": "open saturday", "context": bad}).status_code == 400


def test_context_validate_returns_only_known_keys(gold_kitchen):
    assert command_context.validate({"screen": "recipe", "recipe": "Chicken Caldo A"}) == {
        "screen": "recipe", "recipe": "Chicken Caldo A"}
    assert command_context.validate(None) == {"screen": "other"}
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_command_api.py -q`
Expected: FAIL — `cannot import name 'context'`.

- [ ] **Step 3: Implement `lib/command/context.py`**

```python
"""Validate what a page or the app says is on screen. It is untrusted input.

The context is typed, never a URL or a path: a recipe must be an existing
recipe *name*, a week a real ISO week, a date a real civil date.
"""
from datetime import date

from lib.safe_paths import parse_iso_week

SCREENS = {"home", "recipe", "planner", "inventory", "shopping", "cook-now", "other"}
_KEYS = {"screen", "recipe", "week", "date", "cook_id"}


def validate(raw) -> dict:
    if raw is None:
        return {"screen": "other"}
    if not isinstance(raw, dict):
        raise ValueError("context must be an object")
    unknown = set(raw) - _KEYS
    if unknown:
        raise ValueError(f"unknown context keys: {sorted(unknown)}")
    screen = raw.get("screen", "other")
    if screen not in SCREENS:
        raise ValueError(f"unknown screen: {screen!r}")
    out = {"screen": screen}

    if raw.get("recipe") is not None:
        from lib import paths
        names = {p.stem for p in paths.recipes_dir().glob("*.md")}
        if raw["recipe"] not in names:
            raise ValueError("unknown recipe")
        out["recipe"] = raw["recipe"]
    if raw.get("week") is not None:
        out["week"] = parse_iso_week(raw["week"])
    if raw.get("date") is not None:
        if not isinstance(raw["date"], str):
            raise ValueError("date must be YYYY-MM-DD")
        out["date"] = date.fromisoformat(raw["date"]).isoformat()
    if raw.get("cook_id") is not None:
        from lib import serving_ledger
        if not isinstance(raw["cook_id"], int) or serving_ledger.get_cook(raw["cook_id"]) is None:
            raise ValueError("unknown cook")
        out["cook_id"] = raw["cook_id"]
    return out
```

- [ ] **Step 4: Add the routes to `api_server.py`**

Insert after the end of the `api_freezer` function:

```python
#: Seconds within which the same sentence on the same screen is one command.
COMMAND_DEDUPE_WINDOW_S = 5.0
COMMAND_MAX_CHARS = 500


def _command_today():
    """The kitchen's "today". A function so tests can freeze the clock."""
    from datetime import date as _date
    return _date.today()


def _command_respond(command_id, text, context, answers, confirmed):
    """Plan the command and, if nothing is in the way, run it. Returns the payload."""
    from lib.command import decider, executor, log as command_log, planner
    from lib.command.resolve import Kitchen

    kitchen = Kitchen.load(_command_today(),
                           extra_weeks=[context["week"]] if context.get("week") else [])
    outcome = planner.plan(text, context, kitchen, decider.default(), answers)

    if isinstance(outcome, planner.Failure):
        payload = {"status": "failed", "reason": outcome.reason}
        command_log.update(command_id, status="failed", answers=answers, response=payload)
        return payload

    if isinstance(outcome, planner.Question):
        payload = {"status": "ask", "command_id": command_id, "key": outcome.key,
                   "question": outcome.text,
                   "options": [{"id": o.id, "label": o.label} for o in outcome.options]}
        command_log.update(command_id, status="ask", answers=answers, response=payload)
        return payload

    actions = [a.to_json() for a in outcome.actions]
    if outcome.confirm and not confirmed:
        payload = {"status": "confirm", "command_id": command_id,
                   "lines": outcome.confirm, "actions": actions}
        command_log.update(command_id, status="confirm", answers=answers,
                           plan=actions, response=payload)
        return payload

    # A hand-edited legacy week must be converted before its first ledger row lands.
    _import_legacy_if_first_write(*planner.weeks_touched(outcome))
    result = executor.run(outcome, kitchen)
    if not result.ok:
        payload = {"status": "failed", "reason": result.error}
        command_log.update(command_id, status="failed", answers=answers,
                           plan=actions, response=payload)
        return payload

    _regen_weeks(*result.weeks)
    _sync_cook_history(*result.recipes)
    payload = {"status": "done", "command_id": command_id,
               "undo": executor.undoable(result.undo), "lines": result.lines,
               "warnings": result.warnings, "navigate": result.navigate, "actions": actions}
    command_log.update(command_id, status="done", answers=answers, plan=actions,
                       response=payload, undo=result.undo)
    return payload


@app.route('/api/command', methods=['POST'])
@require_token
def api_command():
    """Run one spoken or typed command. Body: {text, context}. See docs/API.md."""
    from lib.command import context as command_context, log as command_log

    data = request.get_json(force=True, silent=True) or {}
    text = data.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > COMMAND_MAX_CHARS:
        return jsonify({"error": f"'text' is required (1-{COMMAND_MAX_CHARS} characters)"}), 400
    text = text.strip()
    try:
        context = command_context.validate(data.get('context'))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    repeat = command_log.recent_duplicate(text, context, COMMAND_DEDUPE_WINDOW_S)
    if repeat is not None:
        return jsonify(repeat["response"])
    command_id = command_log.create(text, context)
    return jsonify(_command_respond(command_id, text, context, {}, False))


@app.route('/api/command/<int:command_id>/answer', methods=['POST'])
@require_token
def api_command_answer(command_id):
    """Answer a paused command. Body: {option: <id>} for ask, {confirm: bool} for confirm."""
    from lib.command import log as command_log

    command = command_log.get(command_id)
    if command is None:
        return jsonify({"error": "command not found"}), 404
    if command["status"] not in ("ask", "confirm"):
        return jsonify({"error": "this command is not waiting for an answer"}), 409
    data = request.get_json(force=True, silent=True) or {}
    answers = dict(command["answers"])

    if command["status"] == "confirm":
        if data.get("confirm") is not True:
            payload = {"status": "failed", "reason": "Cancelled."}
            command_log.update(command_id, status="failed", response=payload)
            return jsonify(payload)
        return jsonify(_command_respond(command_id, command["text"], command["context"],
                                        answers, True))

    offered = [o["id"] for o in command["response"]["options"]]
    if data.get("option") not in offered:
        return jsonify({"error": "'option' must be one of the offered ids"}), 400
    answers[command["response"]["key"]] = data["option"]
    return jsonify(_command_respond(command_id, command["text"], command["context"],
                                    answers, False))


@app.route('/api/command/<int:command_id>/undo', methods=['POST'])
@require_token
def api_command_undo(command_id):
    """Reverse a finished command. Refused if what it touched has changed since."""
    from lib.command import executor, log as command_log

    command = command_log.get(command_id)
    if command is None:
        return jsonify({"error": "command not found"}), 404
    if command["status"] != "done" or not executor.undoable(command["undo"]):
        return jsonify({"error": "Nothing to undo."}), 409
    ok, reason = executor.undo(command["undo"])
    if not ok:
        return jsonify({"status": "refused", "reason": reason}), 409
    command_log.update(command_id, status="undone")
    _regen_weeks(*command["undo"].get("weeks", []))
    _sync_cook_history(*command["undo"].get("recipes", []))
    return jsonify({"status": "undone"})
```

- [ ] **Step 5: Run to verify pass**

Run: `$PY -m pytest tests/test_command_api.py tests/test_api_auth.py -q`
Expected: all pass — `28 passed` in `test_command_api.py` (20 gold + 8), and `test_api_auth.py` still green, which proves the three routes are gated and correctly absent from `KNOWN_UNGATED`.

- [ ] **Step 6: Run the whole suite**

Run: `$PY -m pytest -q`
Expected: no failures this branch introduced. If anything outside `tests/test_command_*` and `tests/test_gold_kitchen.py` fails, run that test on `origin/main` first to see whether it was already failing; fix only what this branch broke.

- [ ] **Step 7: Commit**

```bash
git add lib/command/context.py api_server.py tests/test_command_api.py
git commit -m "feat(api): /api/command with answer and undo"
```

---

### Task 10: Model scorecard

**Files:**
- Create: `scripts/score_command_models.py`, `tests/test_score_command_models.py`

**Interfaces:**
- Consumes: `tests.gold.kitchen`, `tests/gold/commands.json`, `planner.plan`, `decider.OllamaDecider`, `decider.NoDecider`.
- Produces: `score(cases, decider, kitchen) -> dict` with keys `passed`, `asked`, `wrong`, `total`, `seconds` (list), `failures` (list of `(id, got_status)`); CLI `scripts/score_command_models.py [model ...]`, exit code 1 when any model has `wrong > 0`.

- [ ] **Step 1: Write the failing test**

`tests/test_score_command_models.py`:

```python
import json
from pathlib import Path

from lib.command.decider import NoDecider, ScriptedDecider
from lib.command.resolve import Kitchen
from scripts.score_command_models import score
from tests.gold.kitchen import TODAY

CASES = json.loads((Path(__file__).parent / "gold" / "commands.json").read_text())


def test_no_model_scores_the_gold_set_with_zero_wrong_actions(gold_kitchen):
    result = score(CASES, NoDecider(), lambda extra: Kitchen.load(TODAY, extra))
    assert result["total"] == len(CASES)
    assert result["wrong"] == 0
    assert result["passed"] == len(CASES)


def test_a_wrong_choice_is_counted_as_wrong_not_as_asked(gold_kitchen):
    tie = [c for c in CASES if c["id"] == "plan-or-move"]
    result = score(tie, ScriptedDecider({"x": "move_cook"}), lambda extra: Kitchen.load(TODAY, extra))
    assert (result["passed"], result["asked"], result["wrong"]) == (0, 0, 1)
```

The second test encodes the gate's meaning: the gold answer for `plan-or-move` is "ask", so a model that picks an action there has run something the user did not clearly request.

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest tests/test_score_command_models.py -q`
Expected: FAIL — `No module named 'scripts.score_command_models'`. If the failure is instead `No module named 'scripts'`, check whether `scripts/__init__.py` exists; if it does not, create it empty and add it to this task's commit.

- [ ] **Step 3: Implement**

`scripts/score_command_models.py`:

```python
#!/usr/bin/env python
"""Score local models on the gold command set. Run before changing model or prompt.

    .venv/bin/python scripts/score_command_models.py                 # default model
    .venv/bin/python scripts/score_command_models.py qwen2.5:3b granite4.1:8b

The gate is the WRONG column: it must be 0. A model that ends a command in a
question is safe; one that runs a different action than the gold answer is not.
Run it with nothing else using Ollama, or the timings mean nothing.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _status(outcome):
    from lib.command.planner import Failure, Question
    if isinstance(outcome, Failure):
        return "failed"
    if isinstance(outcome, Question):
        return "ask"
    return "confirm" if outcome.confirm else "done"


def _matches(case, outcome) -> bool:
    from lib.command.planner import Plan, Question
    expect = case["expect"]
    if _status(outcome) != expect["status"]:
        return False
    if isinstance(outcome, Question):
        return [o.id for o in outcome.options] == expect["options"]
    if isinstance(outcome, Plan):
        got = [a.to_json() for a in outcome.actions]
        return len(got) == len(expect["actions"]) and all(
            want.items() <= have.items() for want, have in zip(expect["actions"], got))
    return True


def score(cases, decider, load_kitchen) -> dict:
    from lib.command import planner
    from lib.command.planner import Plan

    out = {"passed": 0, "asked": 0, "wrong": 0, "total": len(cases), "seconds": [], "failures": []}
    for case in cases:
        context = case["context"]
        kitchen = load_kitchen([context["week"]] if context.get("week") else [])
        started = time.time()
        outcome = planner.plan(case["say"], context, kitchen, decider)
        out["seconds"].append(time.time() - started)
        if _matches(case, outcome):
            out["passed"] += 1
        elif isinstance(outcome, Plan):
            out["wrong"] += 1
            out["failures"].append((case["id"], _status(outcome)))
        else:
            out["asked"] += 1
            out["failures"].append((case["id"], _status(outcome)))
    return out


def main(models) -> int:
    from lib.command.decider import DEFAULT_MODEL, OllamaDecider
    from lib.command.resolve import Kitchen
    from tests.gold import kitchen as gold

    cases = json.loads((ROOT / "tests" / "gold" / "commands.json").read_text())
    worst = 0
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["KITCHENOS_VAULT"] = str(Path(tmp) / "vault")
        os.environ["KITCHENOS_DB"] = str(Path(tmp) / "gold.db")
        os.environ["KITCHENOS_STORAGE_TABLE"] = str(Path(tmp) / "storage.json")
        gold.build()
        print(f"{'model':<20} {'pass':>5} {'ask':>4} {'WRONG':>6} {'median s':>9} {'max s':>7}")
        for model in models or [DEFAULT_MODEL]:
            result = score(cases, OllamaDecider(model), lambda extra: Kitchen.load(gold.TODAY, extra))
            times = sorted(result["seconds"])
            print(f"{model:<20} {result['passed']:>5} {result['asked']:>4} {result['wrong']:>6} "
                  f"{times[len(times) // 2]:>9.1f} {times[-1]:>7.1f}")
            for case_id, status in result["failures"]:
                print(f"    {case_id}: got {status}")
            worst = max(worst, result["wrong"])
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run to verify pass**

Run: `$PY -m pytest tests/test_score_command_models.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Run the real scorecard once and record it**

Run (needs Ollama on this Mac; make sure no extraction batch is running):

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python scripts/score_command_models.py qwen2.5:3b granite4.1:8b
```

Expected: a table with a `WRONG` column. Paste the table into the commit message body. If `WRONG` is non-zero for `qwen2.5:3b`, do **not** change `DEFAULT_MODEL` to chase a pass — report the failing case ids; the fix belongs in rules or feasibility (Task 4), where a tie should not have reached a model.

- [ ] **Step 6: Commit**

```bash
git add scripts/score_command_models.py tests/test_score_command_models.py
git commit -m "feat(command): on-demand model scorecard for the gold set"
```

---

### Task 11: Documentation and branch status

**Files:**
- Modify: `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/ROADMAP.md`, `CLAUDE.md`
- Create: `BRANCH-STATUS.md` (copy `templates/BRANCH-STATUS.md`)

- [ ] **Step 1: `docs/API.md`** — in section `## 1. HTTP endpoints`, add these three rows to the endpoint table next to the `/api/cooks` rows:

```markdown
| `/api/command` 🔒 | POST | Run one spoken or typed command. Body `{text, context}` where `context` is `{screen, recipe?, week?, date?, cook_id?}` — typed and validated, never a URL. Returns one of `{status:"done", command_id, undo, lines, warnings, navigate, actions}`, `{status:"ask", command_id, key, question, options:[{id,label}]}` (empty `options` means "say it differently"), `{status:"confirm", command_id, lines, actions}`, or `{status:"failed", reason}`. Code decides everything it can; a local model is asked only to pick one of several feasible actions, and if it declines the options come back as `ask`. Repeating the same text and context within 5 s returns the first result. |
| `/api/command/<id>/answer` 🔒 | POST | Continue a paused command: `{option:<id>}` for `ask`, `{confirm:true}` for `confirm` (anything else cancels). 400 if the option was not offered; 409 if the command is not waiting. |
| `/api/command/<id>/undo` 🔒 | POST | Reverse a `done` command by restoring the before-snapshot of every row it touched. 409 `{status:"refused", reason}` if any of those rows has changed since; 409 if there is nothing to undo. |
```

- [ ] **Step 2: `docs/ARCHITECTURE.md`** — add a subsection to the module map:

```markdown
### Command engine (`lib/command/`)

Sentence + screen context → typed actions → ledger/inventory, with Undo.

| Module | Role |
|--------|------|
| `phrases.py`, `slots.py` | Split the sentence; extract dates, meals, numbers, places. No model. |
| `resolve.py` | `Kitchen` snapshot; words → real recipes, cooks, freezer and inventory rows. |
| `intents.py` | The closed action list, rules, and feasibility. |
| `decider.py` | The only model call: one typed choice. `None` means "ask the user". |
| `planner.py` | Runs the pipeline; returns `Plan`, `Question` or `Failure`. Changes nothing. |
| `executor.py`, `log.py` | Run a plan through existing ledger/inventory functions; snapshot rows; undo. |

The gold kitchen (`tests/gold/`) and `scripts/score_command_models.py` are the standard every
change is run through.
```

- [ ] **Step 3: `docs/OPERATIONS.md`** — add under the maintenance commands:

```markdown
### Score local models on the gold command set

    .venv/bin/python scripts/score_command_models.py qwen2.5:3b granite4.1:8b

Run before changing `lib/command/decider.DEFAULT_MODEL` or any prompt in that file. The
`WRONG` column must be 0. Run it while nothing else is using Ollama.
```

- [ ] **Step 4: `CLAUDE.md`** — add one invariant bullet at the end of the invariants list:

```markdown
- **A command runs the wrong thing never; it asks instead.** `lib/command/` turns a sentence plus the screen it was said on into typed actions. Code does everything it can — splitting, dates, names, feasibility — and a model is reachable only through `decider.decide(question, options)`, which returns an option id or `None`. `None` is not an error: the same options go to the user as buttons, so a slow, absent or disabled model degrades to a tap, not a hang. Measured on the Mac mini, asking a model to write the whole plan got dates wrong on every model tried and never once asked a question; picking one label per phrase took the smallest model from 3/16 to 11/16. Only `open` intents (`plan_cook`, `move_cook`, `inventory_add`) can be chosen without their verb firing a rule — widening that set is how "I want this Wednesday" becomes "mark cooked". The gate is `scripts/score_command_models.py`'s WRONG column, which must stay 0; a new action or phrasing adds a case to `tests/gold/commands.json` in the same commit. Undo restores row snapshots and **refuses** when a touched row has changed since, rather than overwriting later work.
```

- [ ] **Step 5: `docs/ROADMAP.md`** — add at the top of "Done / Shipped":

```markdown
**2026-11 — Command engine and gold-standard kitchen (branch `command-engine`).** `POST /api/command`
turns a sentence plus screen context into ledger and inventory actions with one Undo. Covers meal
plan, leftovers, freezer, cooking, inventory and navigation. **Still open:** the three shopping
actions, the in-page "tell it" bar, Siri and app-shell wiring, the touch pass, and signing
automation — see `docs/superpowers/specs/2026-11-12-command-engine-design.md`.
```

- [ ] **Step 6: `BRANCH-STATUS.md`** — copy `templates/BRANCH-STATUS.md` to the worktree root and set the header to:

```markdown
# Branch Status: command-engine

**Created:** 2026-11-12
**Design Doc:** docs/superpowers/specs/2026-11-12-command-engine-design.md
**Current Stage:** docs
**Last Rebased:** 2026-11-12

## Overview

Sentence + screen context → typed actions → ledger/inventory, with Undo. Gold kitchen and
gold command set as the standing test standard. Shopping actions deferred to a follow-on plan.

## Dependencies

- None
```

Tick the Planning, Dev and Testing boxes that are true. Leave Review and Ready unticked.

- [ ] **Step 7: Verify and commit**

Run: `$PY -m pytest tests/test_command_slots.py tests/test_command_resolve.py tests/test_command_intents.py tests/test_command_decider.py tests/test_command_planner.py tests/test_command_log.py tests/test_command_executor.py tests/test_command_api.py tests/test_score_command_models.py tests/test_gold_kitchen.py tests/test_api_auth.py -q`
Expected: all pass.

```bash
git add docs/API.md docs/ARCHITECTURE.md docs/OPERATIONS.md docs/ROADMAP.md CLAUDE.md BRANCH-STATUS.md
git commit -m "docs: command engine API, architecture, invariant and branch status"
```

---

## After the last task

Not part of any task, and each needs the user's say-so:

- **Deploy:** the live API holds `lib/*` in memory. After merge, restart `com.kitchenos.api` (see `CLAUDE.md`), then try one command against the real kitchen with `curl` on the Mac mini.
- **Follow-on plan:** shopping actions (extract the `/generate-shopping-list` and `/send-to-reminders` route bodies into `lib/`, add a manual-row writer, add the three intents and flip the two gold cases from `failed` to their real expectations).
- **Unsettled from the spec:** a clean scorecard run for a model larger than 3b, and what was competing for Ollama during the first measurements.
