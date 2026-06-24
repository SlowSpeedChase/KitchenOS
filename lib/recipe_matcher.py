"""Match purchased items to the meal-plan recipes they were bought for.

A grocery trip is usually shopping for the week(s) ahead. This module builds an
ingredient index from the meal plans in a week window (default: the current ISO
week plus the next), then matches each purchase's canonical name against those
recipes' ingredients. A purchase that matches no planned ingredient is left
unassigned and falls through to general inventory.

Matching is deterministic — normalized, singularized token containment — in
keeping with the project's "LLM only for validated jobs" philosophy. A purchase
matches a recipe ingredient when one side's content tokens are a subset of the
other's (so "chicken" or "chicken breast" both match "boneless skinless chicken
breasts"). A single staple bought for several planned recipes matches all of
them; ``match()`` returns every matching recipe name.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from lib import paths
from lib.meal_plan_parser import flatten_to_recipes, parse_meal_plan
from lib.recipe_parser import parse_recipe_body, parse_recipe_file

# Units and generic descriptors carry no identity — drop them before matching.
_STOPWORDS = {
    # units / measures
    "cup", "cups", "tbsp", "tablespoon", "tablespoons", "tsp", "teaspoon",
    "teaspoons", "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds",
    "g", "gram", "grams", "kg", "ml", "l", "liter", "litre", "quart", "pint",
    "gallon", "clove", "cloves", "can", "cans", "package", "packages", "pkg",
    "bunch", "head", "stick", "sticks", "slice", "slices", "pinch", "dash",
    "piece", "pieces", "sprig", "sprigs", "stalk", "stalks",
    # descriptors
    "fresh", "freshly", "dried", "ground", "chopped", "minced", "sliced",
    "diced", "grated", "shredded", "crushed", "large", "small", "medium",
    "organic", "boneless", "skinless", "whole", "ripe", "raw", "cooked",
    "canned", "extra", "virgin", "fine", "coarse", "kosher", "packed",
    "unsalted", "salted", "granulated", "light", "dark", "lean", "plain",
    "low", "reduced", "all", "purpose", "room", "temperature", "optional",
    # connectives
    "of", "the", "a", "to", "taste", "for", "and", "or", "plus", "more",
    "with", "into", "such", "as", "your", "favorite",
}


def _stem(word: str) -> str:
    """Cheap singularizer so "breasts"/"tomatoes" match "breast"/"tomato"."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _content_tokens(text: str) -> frozenset[str]:
    """Lowercase identity tokens: words minus stopwords, singularized."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    return frozenset(_stem(w) for w in words if w not in _STOPWORDS)


def current_week_window() -> list[str]:
    """The current ISO week and the next, as ``YYYY-Www`` strings."""
    today = date.today()
    weeks = []
    for offset in (0, 7):
        iso = (today + timedelta(days=offset)).isocalendar()
        weeks.append(f"{iso.year}-W{iso.week:02d}")
    return weeks


def _planned_recipe_names(weeks: list[str]) -> list[str]:
    """Recipe names scheduled in the given week's meal plans (meals expanded)."""
    names: list[str] = []
    seen: set[str] = set()
    for week in weeks:
        plan_path = paths.meal_plans_dir() / f"{week}.md"
        if not plan_path.exists():
            continue
        try:
            content = plan_path.read_text(encoding="utf-8")
            year, wk = int(week[:4]), int(week.split("W")[1])
            days = parse_meal_plan(content, year, wk)
        except (OSError, ValueError):
            continue
        for day in days:
            entries = [day.get(slot) for slot in
                       ("breakfast", "lunch", "snack", "dinner")]
            for entry in flatten_to_recipes(entries, meals_dir=paths.meals_dir()):
                if entry.name not in seen:
                    seen.add(entry.name)
                    names.append(entry.name)
    return names


def _recipe_ingredient_tokens(name: str) -> list[frozenset[str]]:
    """Content-token sets for one recipe's ingredients (empty if not found)."""
    recipe_path = paths.recipes_dir() / f"{name}.md"
    if not recipe_path.exists():
        return []
    try:
        parsed = parse_recipe_file(recipe_path.read_text(encoding="utf-8"))
        body = parse_recipe_body(parsed["body"])
    except (OSError, ValueError):
        return []
    token_sets = []
    for ing in body.get("ingredients", []):
        tokens = _content_tokens(ing.get("item", ""))
        if tokens:
            token_sets.append(tokens)
    return token_sets


class PlanIndex:
    """Ingredient → recipe index over a meal-plan week window."""

    def __init__(self, recipes: dict[str, list[frozenset[str]]]):
        # name → list of ingredient content-token sets
        self._recipes = recipes

    @property
    def recipe_names(self) -> list[str]:
        return list(self._recipes)

    def match(self, canonical_name: str) -> list[str]:
        """Recipe names whose ingredients match this purchased item."""
        purchase = _content_tokens(canonical_name)
        if not purchase:
            return []
        hits = []
        for name, ingredient_sets in self._recipes.items():
            for ing in ingredient_sets:
                shared = purchase & ing
                if shared and (purchase <= ing or ing <= purchase):
                    hits.append(name)
                    break
        return hits


def build_plan_index(weeks: Optional[list[str]] = None) -> PlanIndex:
    """Build a ``PlanIndex`` for the given weeks (default: current + next)."""
    if weeks is None:
        weeks = current_week_window()
    recipes = {
        name: _recipe_ingredient_tokens(name)
        for name in _planned_recipe_names(weeks)
    }
    return PlanIndex(recipes)


def assign_recipes(purchases: list[dict],
                   index: Optional[PlanIndex] = None) -> PlanIndex:
    """Set ``for_recipe`` on each purchase from the plan index, in place.

    Skips ``fee`` lines. Returns the index used (built if not supplied) so
    callers can reuse it. ``for_recipe`` is a comma-joined recipe-name string,
    or ``None`` when nothing in the plan matches.
    """
    if index is None:
        index = build_plan_index()
    for p in purchases:
        if p.get("category") == "fee":
            continue
        matches = index.match(p.get("canonical_name", ""))
        p["for_recipe"] = ", ".join(matches) if matches else None
    return index
