"""Tests for backfill_nutrition.py"""
from pathlib import Path
from unittest.mock import patch

from lib.nutrition import NutritionData
from lib.nutrition_engine import RecipeNutritionResult


def make_result(cal, pro, carb, fat, source="usda", servings_used=2,
                needs_review=False, confidence=0.8, coverage=1.0, unmatched=None):
    """Build an engine-style result for mocking calculate_recipe_nutrition."""
    nd = NutritionData(cal, pro, carb, fat)
    return RecipeNutritionResult(
        per_serving=nd, total=nd, source=source, servings_used=servings_used,
        servings_inferred=False, needs_review=needs_review,
        confidence=confidence, line_items=[],
        coverage=coverage, unmatched=unmatched or [],
    )


def make_recipe_file(path: Path, name: str, nutrition_calories=None, servings=2, ingredients=None):
    """Helper — writes a minimal recipe file."""
    cal_val = nutrition_calories if nutrition_calories is not None else "null"
    ing_table = ""
    if ingredients:
        rows = "\n".join(f"| {i['amount']} | {i['unit']} | {i['item']} |" for i in ingredients)
        ing_table = f"## Ingredients\n\n| Amount | Unit | Ingredient |\n|--------|------|------------|\n{rows}\n"

    content = f"""---
title: "{name}"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: {cal_val}
nutrition_protein: null
nutrition_carbs: null
nutrition_fat: null
nutrition_source: null
servings: {servings}
serving_size: null
---

# {name}

{ing_table}## Instructions

1. Cook it.
"""
    (path / f"{name}.md").write_text(content)


class TestBackfillNutrition:
    def test_skips_recipes_with_existing_nutrition(self, tmp_path):
        from backfill_nutrition import collect_recipes_needing_backfill
        make_recipe_file(tmp_path, "Already Done", nutrition_calories=450)
        make_recipe_file(tmp_path, "Needs Work", nutrition_calories=None)
        recipes = collect_recipes_needing_backfill(tmp_path)
        names = [r.stem for r in recipes]
        assert "Needs Work" in names
        assert "Already Done" not in names

    def test_writes_correct_keys_after_lookup(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Test Recipe", ingredients=[
            {"amount": "1", "unit": "cup", "item": "flour"},
        ])
        recipe_path = tmp_path / "Test Recipe.md"

        result = make_result(150, 4, 30, 0, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            updated = backfill_recipe(recipe_path, dry_run=False)

        assert updated is True
        content = recipe_path.read_text()
        assert "nutrition_calories: 150" in content
        assert "nutrition_protein: 4" in content
        assert "nutrition_carbs: 30" in content
        assert "nutrition_fat: 0" in content
        assert 'nutrition_source: "usda"' in content
        assert "nutrition_confidence: 0.8" in content

    def test_appending_new_key_keeps_frontmatter_parseable(self, tmp_path):
        # Regression: appending a brand-new key (nutrition_confidence) must not
        # glue the closing '---' onto it and corrupt the frontmatter.
        from backfill_nutrition import backfill_recipe
        from lib.recipe_parser import parse_recipe_file

        make_recipe_file(tmp_path, "Append Key", ingredients=[
            {"amount": "1", "unit": "cup", "item": "flour"},
        ])
        recipe_path = tmp_path / "Append Key.md"
        result = make_result(200, 5, 40, 2, "usda", confidence=0.4)
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=False)

        content = recipe_path.read_text()
        assert "0.4---" not in content            # delimiter not glued
        assert "\nnutrition_confidence: 0.4\n" in content
        # Body still recoverable after the write.
        body = parse_recipe_file(content)["body"]
        assert "## Ingredients" in body
        assert "## Instructions" in body

    def test_propagates_needs_review(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Review Me", ingredients=[
            {"amount": "1", "unit": "whole", "item": "mystery"},
        ])
        recipe_path = tmp_path / "Review Me.md"

        result = make_result(100, 1, 2, 3, needs_review=True)
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=False)

        content = recipe_path.read_text()
        assert "needs_review: true" in content
        assert "nutrition_needs_review: true" in content

    def test_needs_review_clears_when_no_longer_flagged(self, tmp_path):
        # Regression: nutrition's own verdict (nutrition_needs_review) must
        # flip to false once the recipe is no longer flagged — but the shared
        # needs_review flag is NOT nutrition's to clear (it may have been set
        # by extraction/normalizer/crouton_parser for an unrelated reason), so
        # a pre-existing needs_review: true must survive untouched.
        from backfill_nutrition import write_nutrition_to_file

        content = '''---
title: "Fixed Recipe"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: null
needs_review: true
servings: 2
serving_size: null
---

# Fixed Recipe

## Instructions

1. Cook it.
'''
        recipe_path = tmp_path / "Fixed Recipe.md"
        recipe_path.write_text(content)

        result = make_result(300, 10, 40, 8, needs_review=False)
        write_nutrition_to_file(recipe_path, result)

        out = recipe_path.read_text()
        assert "nutrition_needs_review: false" in out
        lines = out.splitlines()
        assert lines.count("needs_review: true") == 1
        assert not any(l.startswith("needs_review: false") for l in lines)

    def test_needs_review_not_added_when_absent_and_unflagged(self, tmp_path):
        # An unflagged nutrition result must not introduce a needs_review key
        # where none existed — only nutrition_needs_review is nutrition's to write.
        from backfill_nutrition import write_nutrition_to_file

        content = '''---
title: "Clean Recipe"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: null
servings: 2
serving_size: null
---

# Clean Recipe

## Instructions

1. Cook it.
'''
        recipe_path = tmp_path / "Clean Recipe.md"
        recipe_path.write_text(content)

        result = make_result(300, 10, 40, 8, needs_review=False)
        write_nutrition_to_file(recipe_path, result)

        out = recipe_path.read_text()
        assert "nutrition_needs_review: false" in out
        lines = out.splitlines()
        assert not any(l.startswith("needs_review:") for l in lines)

    def test_flagged_result_writes_both_keys_once(self, tmp_path):
        # A flagged result writes both the scoped and shared keys, each exactly once.
        from backfill_nutrition import write_nutrition_to_file

        content = '''---
title: "New Flag Recipe"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: null
servings: 2
serving_size: null
---

# New Flag Recipe

## Instructions

1. Cook it.
'''
        recipe_path = tmp_path / "New Flag Recipe.md"
        recipe_path.write_text(content)

        result = make_result(300, 10, 40, 8, needs_review=True)
        write_nutrition_to_file(recipe_path, result)

        out = recipe_path.read_text()
        lines = out.splitlines()
        assert lines.count("needs_review: true") == 1
        assert lines.count("nutrition_needs_review: true") == 1

    def test_defaults_null_servings_to_one(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "No Servings", servings="null", ingredients=[
            {"amount": "2", "unit": "cups", "item": "rice"},
        ])
        recipe_path = tmp_path / "No Servings.md"

        result = make_result(400, 8, 80, 1, "off", servings_used=1)
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=False)

        assert "nutrition_calories: 400" in recipe_path.read_text()

    def test_dry_run_does_not_write_file(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Dry Recipe", ingredients=[
            {"amount": "1", "unit": "cup", "item": "oats"},
        ])
        recipe_path = tmp_path / "Dry Recipe.md"
        original = recipe_path.read_text()

        result = make_result(300, 10, 50, 5, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=True)

        assert recipe_path.read_text() == original

    def test_skips_recipe_with_no_ingredients(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Empty Recipe", ingredients=None)
        recipe_path = tmp_path / "Empty Recipe.md"

        with patch("backfill_nutrition.calculate_recipe_nutrition") as mock_lookup:
            result = backfill_recipe(recipe_path, dry_run=False)
            mock_lookup.assert_not_called()
        assert result is False

    def test_overwrites_existing_numeric_values(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Force Recipe", nutrition_calories=450, ingredients=[
            {"amount": "1", "unit": "cup", "item": "butter"},
        ])
        recipe_path = tmp_path / "Force Recipe.md"

        result = make_result(900, 1, 0, 100, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            updated = backfill_recipe(recipe_path, dry_run=False)

        assert updated is True
        content = recipe_path.read_text()
        assert "nutrition_calories: 900" in content
        assert "nutrition_fat: 100" in content

    def test_rewrite_is_idempotent_no_duplicate_keys(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        content = '''---
title: "Already Backfilled"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: 300
nutrition_protein: 10
nutrition_carbs: 40
nutrition_fat: 8
nutrition_source: "usda"
servings: 2
serving_size: "1 serving"
---

# Already Backfilled

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | cup | oats |

## Instructions

1. Cook it.
'''
        recipe_path = tmp_path / "Already Backfilled.md"
        recipe_path.write_text(content)

        result = make_result(250, 9, 35, 6, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=False)
            # Run a second time — must not introduce duplicate keys.
            backfill_recipe(recipe_path, dry_run=False)

        out = recipe_path.read_text()
        assert out.count('"1 serving"') == 1
        assert out.count("nutrition_calories:") == 1
        assert out.count("nutrition_confidence:") == 1
        assert "nutrition_calories: 250" in out

    def test_fix_duplicates_collapses_repeated_keys(self, tmp_path):
        from backfill_nutrition import fix_duplicates_in_file

        # Mirrors the real corruption: nutrition_calories appears twice.
        content = '''---
title: "Dupe Salad"
source_url: "https://feelgoodfoodie.net/x"
nutrition_calories: 144
nutrition_protein: 3
nutrition_carbs: 15
nutrition_fat: 11
nutrition_source: "ai"
servings: 8
nutrition_calories: 144
nutrition_carbs: 15
nutrition_fat: 11
---

# Dupe Salad

## Instructions

1. Toss.
'''
        recipe_path = tmp_path / "Dupe Salad.md"
        recipe_path.write_text(content)

        changed = fix_duplicates_in_file(recipe_path)
        out = recipe_path.read_text()
        assert changed is True
        assert out.count("nutrition_calories:") == 1
        assert out.count("nutrition_carbs:") == 1
        assert out.count("nutrition_fat:") == 1
        # Value preserved.
        assert "nutrition_calories: 144" in out

    def test_collect_skips_unreadable_files(self, tmp_path):
        from backfill_nutrition import collect_recipes_needing_backfill

        make_recipe_file(tmp_path, "Good Recipe", nutrition_calories=None)
        bad_file = tmp_path / "Bad Recipe.md"
        bad_file.write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")

        recipes = collect_recipes_needing_backfill(tmp_path)
        names = [r.stem for r in recipes]
        assert "Good Recipe" in names
        assert "Bad Recipe" not in names

    def test_nutrition_coverage_always_written(self, tmp_path):
        from backfill_nutrition import write_nutrition_to_file

        make_recipe_file(tmp_path, "Coverage Recipe", ingredients=[
            {"amount": "1", "unit": "cup", "item": "flour"},
        ])
        recipe_path = tmp_path / "Coverage Recipe.md"

        result = make_result(150, 4, 30, 0, coverage=0.75)
        write_nutrition_to_file(recipe_path, result)

        assert "nutrition_coverage: 0.75" in recipe_path.read_text()

    def test_nutrition_unmatched_written_when_present(self, tmp_path):
        from backfill_nutrition import write_nutrition_to_file

        make_recipe_file(tmp_path, "Unmatched Recipe", ingredients=[
            {"amount": "1", "unit": "cup", "item": "flour"},
        ])
        recipe_path = tmp_path / "Unmatched Recipe.md"

        result = make_result(150, 4, 30, 0, unmatched=["a", "b"])
        write_nutrition_to_file(recipe_path, result)

        assert 'nutrition_unmatched: "a; b"' in recipe_path.read_text()

    def test_stale_nutrition_unmatched_removed_when_resolved(self, tmp_path):
        # Regression: a recipe previously written with unmatched ingredients
        # must have the stale nutrition_unmatched line removed once a later
        # run resolves everything — and the frontmatter must stay well-formed
        # (trailing newline before the closing '---', delimiter intact).
        from backfill_nutrition import write_nutrition_to_file

        content = '''---
title: "Resolved Recipe"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: null
nutrition_unmatched: "unicorn dust"
servings: 2
serving_size: null
---

# Resolved Recipe

## Instructions

1. Cook it.
'''
        recipe_path = tmp_path / "Resolved Recipe.md"
        recipe_path.write_text(content)

        result = make_result(150, 4, 30, 0, unmatched=[])
        write_nutrition_to_file(recipe_path, result)

        out = recipe_path.read_text()
        assert "nutrition_unmatched" not in out
        # Frontmatter well-formed: exactly two '---' delimiters, the
        # frontmatter text ends in a newline (so the closing '---' sits on
        # its own line, not glued onto the last key), and the body still
        # parses correctly afterward.
        parts = out.split("---", 2)
        assert len(parts) == 3
        fm = parts[1]
        assert fm.endswith("\n")
        from lib.recipe_parser import parse_recipe_file
        body = parse_recipe_file(out)["body"]
        assert "## Instructions" in body
