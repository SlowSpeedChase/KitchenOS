"""Audits of the *real* vault's current state — not tests of code behaviour.

These deliberately read `vault/KitchenOS` directly rather than the isolated
copy used by `test_weekly_loop.py`. The distinction matters: the loop tests
prove the machinery works, while these record whether the machinery has
actually been *run* lately. Both can be true at once — that gap is precisely
why the system is "a little bit broken" despite a green unit suite.

Known-broken state is `xfail`, so it stays visible in test output and flips to
a pass the day it is fixed rather than being silently deleted.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]
VAULT = REPO / "vault" / "KitchenOS"


def current_week() -> str:
    iso = date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _planned_meals(plan_body: str) -> list[str]:
    """Recipe links sitting in a day/meal slot.

    Excludes the trailing "In season for July" suggestion block, whose entries
    are list items (`- [[Name]]`) rather than bare slot links — counting those
    would report an empty plan as full.
    """
    meals, in_suggestions = [], False
    for line in plan_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("*In season"):
            in_suggestions = True
        if in_suggestions or not stripped.startswith("[["):
            continue
        meals.append(stripped)
    return meals


@pytest.mark.xfail(
    reason="generate_meal_plan.py writes an empty template and nothing fills "
           "the slots, so each week *arrives* blank and only gets meals if they "
           "are added by hand. Non-strict because it legitimately oscillates: "
           "XPASS means the week has been planned (good), xfail means it is "
           "still the bare scaffold. Either way the signal is visible rather "
           "than silent.",
    strict=False,
)
def test_current_week_plan_has_at_least_one_meal():
    week = current_week()
    plan = VAULT / "Meal Plans" / f"{week}.md"
    assert plan.exists(), f"no plan file for {week}"
    meals = _planned_meals(plan.read_text(encoding="utf-8"))
    assert meals, f"{week} plan has no meals in any slot (only the template scaffold)"


@pytest.mark.xfail(
    reason="Known: no shopping list has been generated since 2026-W27, so "
           "/current/shopping-list redirects into Obsidian to a note that "
           "does not exist.",
    strict=False,
)
def test_current_week_has_a_shopping_list():
    week = current_week()
    present = sorted(p.stem for p in (VAULT / "Shopping Lists").glob("*.md"))
    assert week in present, f"no shopping list for {week}; present: {present}"


def test_recipe_library_is_readable():
    """Sanity floor: the library the whole system draws on is present."""
    recipes = list((VAULT / "Recipes").glob("*.md"))
    assert len(recipes) > 100, f"only {len(recipes)} recipes found"
