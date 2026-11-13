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

#: Ties only the user may break. "Put this on Friday" for a recipe already on
#: the plan reads equally well as a second cook or a move, and nothing in the
#: sentence tells a model which — both local models tried simply picked one.
_USER_ONLY_TIES = [{"plan_cook", "move_cook"}]


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


def user_decides(options) -> bool:
    """True when this set of candidates must go to the user, never to a model."""
    return any(tie <= set(options) for tie in _USER_ONLY_TIES)


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
