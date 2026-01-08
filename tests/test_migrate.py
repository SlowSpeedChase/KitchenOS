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
