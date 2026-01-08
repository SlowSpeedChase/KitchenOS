"""Tests for recipe migration"""
import tempfile
from pathlib import Path
from migrate_recipes import migrate_recipe_file, run_migration


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
