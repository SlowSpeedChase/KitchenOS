"""Tests for recipe migration"""
import tempfile
from pathlib import Path
from migrate_recipes import migrate_recipe_file, run_migration, has_tools_callout, add_tools_callout


def test_migrate_recipe_adds_missing_fields():
    """Should add missing frontmatter fields with null value"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"
        recipe.write_text('''---
title: "Test"
source_url: "https://youtube.com/watch?v=abc123"
---

# Test
''')
        changes = migrate_recipe_file(recipe)
        new_content = recipe.read_text()
        assert 'cuisine:' in new_content
        assert 'difficulty:' in new_content
        assert len(changes) > 0


def test_migrate_recipe_preserves_existing_values():
    """Should not overwrite existing field values"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"
        recipe.write_text('''---
title: "Pasta"
cuisine: "Italian"
---

# Pasta
''')
        migrate_recipe_file(recipe)
        new_content = recipe.read_text()
        assert 'cuisine: "Italian"' in new_content or "cuisine: Italian" in new_content


def test_migrate_recipe_preserves_my_notes():
    """Should preserve My Notes section during migration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"
        recipe.write_text('''---
title: "Test"
---

# Test

## My Notes

My important personal notes here!
''')
        migrate_recipe_file(recipe)
        new_content = recipe.read_text()
        assert 'My important personal notes here!' in new_content


def test_run_migration_creates_backups():
    """Should create backups before modifying files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"
        recipe.write_text('''---
title: "Test"
source_url: "https://youtube.com/watch?v=abc123"
---

# Test
''')
        run_migration(recipes_dir, dry_run=False)
        history_dir = recipes_dir / ".history"
        assert history_dir.exists()
        assert len(list(history_dir.glob("*.md"))) == 1


def test_run_migration_dry_run_no_changes():
    """Dry run should not modify files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"
        original_content = '''---
title: "Test"
source_url: "https://youtube.com/watch?v=abc123"
---

# Test
'''
        recipe.write_text(original_content)
        run_migration(recipes_dir, dry_run=True)
        assert recipe.read_text() == original_content
        history_dir = recipes_dir / ".history"
        assert not history_dir.exists()


# ============================================================================
# Tests for 3-column ingredient table format
# ============================================================================

import pytest
from templates.recipe_template import format_recipe_markdown


class TestIngredientTableFormat:
    """Tests for 3-column ingredient table"""

    def test_three_column_header(self):
        """Output has Amount | Unit | Ingredient header"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {"amount": "2", "unit": "cup", "item": "flour"},
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        assert "| Amount | Unit | Ingredient |" in result

    def test_three_column_rows(self):
        """Ingredient rows have 3 columns"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {"amount": "0.5", "unit": "cup", "item": "sugar"},
                {"amount": "1", "unit": "a pinch", "item": "salt"},
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        assert "| 0.5 | cup | sugar |" in result
        assert "| 1 | a pinch | salt |" in result

    def test_backwards_compat_old_format(self):
        """Handles old 'quantity' format gracefully"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {"quantity": "2 cups", "item": "flour"},
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        assert "| Amount | Unit | Ingredient |" in result
        # Should parse old format into new columns
        assert "| 2 | cup |" in result

    def test_inferred_ingredient_marked(self):
        """Inferred ingredients show *(inferred)* marker"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {"amount": "1", "unit": "tsp", "item": "salt", "inferred": True},
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        assert "*(inferred)*" in result

    def test_empty_ingredient_defaults(self):
        """Missing fields default sensibly"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {},  # Empty ingredient dict
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        # Should still produce valid table row
        assert "| Amount | Unit | Ingredient |" in result


class TestInstructionSpacing:
    """Tests for instruction step spacing"""

    def test_blank_line_between_steps(self):
        """Instructions have blank line between steps"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [],
            "instructions": [
                {"step": 1, "text": "First step"},
                {"step": 2, "text": "Second step"},
            ],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        # Should have triple newline (blank line) between steps
        assert "1. First step\n\n\n2. Second step" in result

    def test_single_instruction_no_extra_spacing(self):
        """Single instruction doesn't have trailing blank lines"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [],
            "instructions": [
                {"step": 1, "text": "Only step"},
            ],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        assert "1. Only step" in result


# ============================================================================
# Tests for ingredient table migration
# ============================================================================


class TestIngredientTableParsing:
    """Tests for parsing ingredient tables from recipe markdown"""

    def test_parses_old_2column_table(self):
        """Parses old 2-column ingredient table"""
        from lib.recipe_parser import parse_ingredient_table

        table = '''| Amount | Ingredient |
|--------|------------|
| 500 g | Chicken Breasts |
| a sprinkle | Salt |
|  | Lavash bread |'''

        result = parse_ingredient_table(table)

        assert len(result) == 3
        assert result[0]["amount"] == "500"
        assert result[0]["unit"] == "g"
        assert result[0]["item"] == "chicken breasts"

    def test_parses_new_3column_table(self):
        """Parses new 3-column ingredient table unchanged"""
        from lib.recipe_parser import parse_ingredient_table

        table = '''| Amount | Unit | Ingredient |
|--------|------|------------|
| 500 | g | chicken breasts |
| 1 | a sprinkle | salt |'''

        result = parse_ingredient_table(table)

        assert len(result) == 2
        assert result[0]["amount"] == "500"
        assert result[0]["unit"] == "g"
        assert result[0]["item"] == "chicken breasts"
        assert result[1]["unit"] == "a sprinkle"

    def test_handles_empty_amount(self):
        """Handles empty amount field by defaulting to 1"""
        from lib.recipe_parser import parse_ingredient_table

        table = '''| Amount | Ingredient |
|--------|------------|
|  | Lavash bread |'''

        result = parse_ingredient_table(table)

        assert len(result) == 1
        assert result[0]["amount"] == "1"
        assert result[0]["unit"] == "whole"
        assert result[0]["item"] == "lavash bread"


class TestIngredientTableMigration:
    """Tests for migrating ingredient tables"""

    def test_converts_to_3column_format(self):
        """Migration rewrites table to 3 columns"""
        from migrate_recipes import migrate_ingredient_table

        old_table = '''| Amount | Ingredient |
|--------|------------|
| 500 g | Chicken |'''

        new_table = migrate_ingredient_table(old_table)

        assert "| Amount | Unit | Ingredient |" in new_table
        assert "| 500 | g | chicken |" in new_table

    def test_preserves_informal_units(self):
        """Migration preserves informal units like 'a pinch'"""
        from migrate_recipes import migrate_ingredient_table

        old_table = '''| Amount | Ingredient |
|--------|------------|
| a pinch | Salt |'''

        new_table = migrate_ingredient_table(old_table)

        assert "| 1 | a pinch | salt |" in new_table

    def test_migrate_recipe_content_detects_old_table(self):
        """migrate_recipe_content identifies and replaces 2-column table"""
        from migrate_recipes import migrate_recipe_content

        content = '''---
title: "Test Recipe"
---

## Ingredients

| Amount | Ingredient |
|--------|------------|
| 2 cups | Flour |
| 1 tsp | Salt |

## Instructions

1. Mix ingredients.
'''

        new_content, changes = migrate_recipe_content(content)

        assert "| Amount | Unit | Ingredient |" in new_content
        assert "| 2 | cup | flour |" in new_content
        assert "Converted ingredient table" in changes[0]

    def test_migrate_recipe_content_skips_3column(self):
        """migrate_recipe_content does not modify 3-column tables"""
        from migrate_recipes import migrate_recipe_content

        content = '''---
title: "Test Recipe"
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | cup | flour |

## Instructions

1. Mix ingredients.
'''

        new_content, changes = migrate_recipe_content(content)

        assert new_content == content
        assert len(changes) == 0

    def test_run_migration_converts_ingredient_table(self):
        """run_migration triggers ingredient table conversion"""
        from migrate_recipes import run_migration
        from templates.recipe_template import RECIPE_SCHEMA

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "test.md"

            # Create recipe with all required frontmatter but old table format
            frontmatter_lines = ['---', 'title: "Test"', 'source_url: "https://youtube.com/watch?v=abc123"']
            for field in RECIPE_SCHEMA.keys():
                if field not in ['title', 'source_url']:
                    frontmatter_lines.append(f"{field}: null")
            frontmatter_lines.append('---')

            content = '\n'.join(frontmatter_lines) + '''

## Ingredients

| Amount | Ingredient |
|--------|------------|
| 2 cups | Flour |

## Instructions

1. Mix ingredients.
'''
            recipe.write_text(content)

            results = run_migration(recipes_dir, dry_run=False)

            # Should have updated the file
            assert len(results['updated']) == 1
            assert 'Converted ingredient table' in str(results['updated'][0])

            # Check file was actually converted
            new_content = recipe.read_text()
            assert '| Amount | Unit | Ingredient |' in new_content
            assert '| 2 | cup | flour |' in new_content


# ============================================================================
# Tests for Tools callout migration
# ============================================================================


class TestToolsCalloutMigration:
    """Tests for migrating Tools callout to existing recipes"""

    def test_has_tools_callout_detects_existing(self):
        """Should detect when tools callout already exists"""
        content = '''---
title: Test
---

> [!tools]- Tools
> ```button
> name Re-extract

# Test
'''
        assert has_tools_callout(content) is True

    def test_has_tools_callout_detects_missing(self):
        """Should detect when tools callout is missing"""
        content = '''---
title: Test
---

# Test
'''
        assert has_tools_callout(content) is False

    def test_add_tools_callout_inserts_after_frontmatter(self):
        """Should insert tools callout between frontmatter and title"""
        content = '''---
title: Test
source_url: "https://youtube.com/watch?v=abc"
---

# Test

Content here.
'''
        result = add_tools_callout(content, "Test.md")

        assert "> [!tools]- Tools" in result
        assert "reprocess?file=Test.md" in result
        # Callout should be before title
        callout_pos = result.find("> [!tools]-")
        title_pos = result.find("# Test")
        assert callout_pos < title_pos

    def test_add_tools_callout_url_encodes_filename(self):
        """Should URL-encode filename with spaces"""
        content = '''---
title: Test
---

# Test
'''
        result = add_tools_callout(content, "Pasta Aglio E Olio.md")

        assert "Pasta%20Aglio%20E%20Olio.md" in result
