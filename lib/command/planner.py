"""Sentence + screen context -> a Plan, a Question, or a Failure. Changes nothing.

Order of authority for "which action is this phrase?":
rule -> the user's earlier answer -> only one feasible -> decider -> ask the user.
A plan-or-move tie skips the decider: only the user may break it.
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
                name = None
                if not intents.user_decides(options):
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
