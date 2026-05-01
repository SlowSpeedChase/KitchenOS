"""Meal definitions — bundles of sub-recipes stored as .meal.md files.

A meal lives at `vault/Meals/<Name>.meal.md` with frontmatter:

    ---
    type: meal
    name: Salmon Dinner
    description: Weeknight pan-seared salmon with sides
    tags: [weeknight, fish]
    sub_recipes:
      - recipe: "Pan-Seared Salmon"
        servings: 1
      - recipe: "Lemon Asparagus"
      - recipe: "Wild Rice Pilaf"
        servings: 2
    ---

Body is free-form notes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from lib import paths


@dataclass
class SubRecipe:
    recipe: str
    servings: int = 1


@dataclass
class Meal:
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    sub_recipes: list[SubRecipe] = field(default_factory=list)
    body: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "sub_recipes": [asdict(s) for s in self.sub_recipes],
        }


def _parse_inline_list(value: str) -> list[str]:
    inner = value.strip()[1:-1].strip()
    if not inner:
        return []
    return [item.strip().strip('"').strip("'") for item in inner.split(",")]


def _parse_meal_frontmatter(yaml_text: str) -> dict:
    """Parse the small subset of YAML used in meal frontmatter."""
    result: dict = {"sub_recipes": []}
    lines = yaml_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Block list under `sub_recipes:`
        if stripped == "sub_recipes:" or stripped.startswith("sub_recipes:"):
            i += 1
            current: Optional[dict] = None
            while i < len(lines):
                ln = lines[i]
                if not ln.strip():
                    i += 1
                    continue
                # Indent must be > 0 to belong to the list
                if not ln.startswith((" ", "\t")):
                    break
                item_match = re.match(r"^\s*-\s*(.*)$", ln)
                if item_match:
                    if current is not None:
                        result["sub_recipes"].append(current)
                    current = {}
                    rest = item_match.group(1).strip()
                    if rest:
                        kv = re.match(r"^(\w+):\s*(.*)$", rest)
                        if kv:
                            current[kv.group(1)] = _coerce_scalar(kv.group(2))
                else:
                    kv = re.match(r"^\s+(\w+):\s*(.*)$", ln)
                    if kv and current is not None:
                        current[kv.group(1)] = _coerce_scalar(kv.group(2))
                i += 1
            if current is not None:
                result["sub_recipes"].append(current)
            continue

        kv = re.match(r"^(\w+):\s*(.*)$", stripped)
        if kv:
            key = kv.group(1)
            value = kv.group(2).strip()
            if value.startswith("[") and value.endswith("]"):
                result[key] = _parse_inline_list(value)
            else:
                result[key] = _coerce_scalar(value)
        i += 1
    return result


def _coerce_scalar(value: str):
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value == "null" or value == "":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def parse_meal_file(content: str) -> dict:
    """Parse a .meal.md file into {frontmatter, body}."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if not match:
        return {"frontmatter": {}, "body": content}
    fm = _parse_meal_frontmatter(match.group(1))
    return {"frontmatter": fm, "body": match.group(2)}


def _meal_path(name: str, meals_dir: Optional[Path] = None) -> Path:
    base = meals_dir if meals_dir is not None else paths.meals_dir()
    return base / f"{name}.meal.md"


def _from_frontmatter(fm: dict, name_fallback: str, body: str = "") -> Meal:
    sub_recipes_raw = fm.get("sub_recipes") or []
    sub_recipes = []
    for entry in sub_recipes_raw:
        if not isinstance(entry, dict):
            continue
        recipe = entry.get("recipe")
        if not recipe:
            continue
        servings = entry.get("servings", 1)
        try:
            servings = int(servings) if servings is not None else 1
        except (TypeError, ValueError):
            servings = 1
        sub_recipes.append(SubRecipe(recipe=str(recipe), servings=servings))
    return Meal(
        name=str(fm.get("name") or name_fallback),
        description=str(fm.get("description") or ""),
        tags=list(fm.get("tags") or []),
        sub_recipes=sub_recipes,
        body=body,
    )


def load_meal(name: str, meals_dir: Optional[Path] = None) -> Optional[Meal]:
    """Load a single meal by name. Returns None if the file is missing."""
    path = _meal_path(name, meals_dir)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    parsed = parse_meal_file(content)
    return _from_frontmatter(parsed["frontmatter"], name_fallback=name, body=parsed["body"])


def list_meals(meals_dir: Optional[Path] = None) -> list[Meal]:
    """List all meals in the meals directory, sorted by name."""
    base = meals_dir if meals_dir is not None else paths.meals_dir()
    if not base.exists():
        return []
    meals: list[Meal] = []
    for filepath in base.iterdir():
        if not filepath.is_file() or not filepath.name.endswith(".meal.md"):
            continue
        name = filepath.name[: -len(".meal.md")]
        try:
            content = filepath.read_text(encoding="utf-8")
            parsed = parse_meal_file(content)
            meals.append(_from_frontmatter(parsed["frontmatter"], name_fallback=name, body=parsed["body"]))
        except Exception:
            continue
    meals.sort(key=lambda m: m.name.lower())
    return meals


def save_meal(meal: Meal, meals_dir: Optional[Path] = None) -> Path:
    """Write a meal to <meals_dir>/<name>.meal.md, returning the path."""
    base = meals_dir if meals_dir is not None else paths.meals_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = _meal_path(meal.name, base)
    path.write_text(_render_meal(meal), encoding="utf-8")
    return path


def delete_meal(name: str, meals_dir: Optional[Path] = None) -> bool:
    """Delete a meal file. Returns True if it existed."""
    path = _meal_path(name, meals_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def _yaml_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_meal(meal: Meal) -> str:
    lines = ["---", "type: meal", f"name: {_yaml_quote(meal.name)}"]
    if meal.description:
        lines.append(f"description: {_yaml_quote(meal.description)}")
    if meal.tags:
        tag_str = ", ".join(_yaml_quote(t) for t in meal.tags)
        lines.append(f"tags: [{tag_str}]")
    if meal.sub_recipes:
        lines.append("sub_recipes:")
        for sub in meal.sub_recipes:
            lines.append(f"  - recipe: {_yaml_quote(sub.recipe)}")
            if sub.servings != 1:
                lines.append(f"    servings: {sub.servings}")
    lines.append("---")
    body = meal.body or ""
    if body and not body.startswith("\n"):
        lines.append("")
    lines.append(body.rstrip("\n"))
    return "\n".join(lines).rstrip("\n") + "\n"
