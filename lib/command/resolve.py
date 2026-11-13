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
