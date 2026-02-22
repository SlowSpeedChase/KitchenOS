"""Tests for cuisine data cleanup migration."""
import tempfile
from pathlib import Path

from migrate_cuisine import (
    apply_cuisine_corrections,
    CUISINE_CORRECTIONS,
    RECIPE_OVERRIDES,
)


class TestApplyCuisineCorrections:
    """Test deterministic cuisine correction logic."""

    def test_recipe_override_takes_priority(self):
        """Per-recipe override wins over general corrections."""
        result = apply_cuisine_corrections("Seneyet Jaj O Batata", "Ethiopian")
        assert result == "Middle Eastern"

    def test_variant_consolidated(self):
        """Variant cuisine names get consolidated to base."""
        result = apply_cuisine_corrections("Any Recipe", "Korean-inspired")
        assert result == "Korean"

    def test_correct_cuisine_unchanged(self):
        """Already-correct cuisines pass through unchanged."""
        result = apply_cuisine_corrections("Any Recipe", "Italian")
        assert result == "Italian"

    def test_null_cuisine_filled_by_override(self):
        """Null cuisine gets filled if recipe is in RECIPE_OVERRIDES."""
        result = apply_cuisine_corrections("Pasta Aglio E Olio Inspired By Chef", None)
        assert result == "Italian"

    def test_null_cuisine_without_override_stays_null(self):
        """Null cuisine without override remains None."""
        result = apply_cuisine_corrections("Unknown Recipe", None)
        assert result is None

    def test_dietary_label_cleared(self):
        """Dietary labels (Vegan, Vegetarian) get cleared when not in overrides."""
        result = apply_cuisine_corrections("Unknown Vegan Recipe", "Vegan")
        assert result is None

    def test_corrupt_data_cleared(self):
        """Corrupt values like 'protein:' get cleared."""
        result = apply_cuisine_corrections("Some Recipe", "protein:")
        assert result is None


from migrate_cuisine import update_frontmatter_field


class TestUpdateFrontmatterField:
    """Test updating a single frontmatter field in recipe content."""

    def test_updates_string_value(self):
        """Replaces existing cuisine string value."""
        content = '---\ntitle: "Test"\ncuisine: "Ethiopian"\n---\n\n# Test'
        result = update_frontmatter_field(content, "cuisine", "Middle Eastern")
        assert 'cuisine: "Middle Eastern"' in result
        assert "Ethiopian" not in result

    def test_updates_null_to_string(self):
        """Replaces null with string value."""
        content = '---\ntitle: "Test"\ncuisine: null\n---\n\n# Test'
        result = update_frontmatter_field(content, "cuisine", "Italian")
        assert 'cuisine: "Italian"' in result

    def test_preserves_other_fields(self):
        """Other frontmatter fields are unchanged."""
        content = '---\ntitle: "Test"\ncuisine: "Ethiopian"\nprotein: "chicken"\n---\n\n# Test'
        result = update_frontmatter_field(content, "cuisine", "Middle Eastern")
        assert 'protein: "chicken"' in result
        assert 'title: "Test"' in result

    def test_preserves_body(self):
        """Body content after frontmatter is unchanged."""
        content = '---\ntitle: "Test"\ncuisine: null\n---\n\n# Test\n\nSome body content.'
        result = update_frontmatter_field(content, "cuisine", "American")
        assert "# Test\n\nSome body content." in result

    def test_updates_list_field(self):
        """Can update a list field like seasonal_ingredients."""
        content = '---\ntitle: "Test"\nseasonal_ingredients: []\n---\n\n# Test'
        result = update_frontmatter_field(content, "seasonal_ingredients", ["tomato", "basil"])
        assert 'seasonal_ingredients: ["tomato", "basil"]' in result

    def test_updates_int_list_field(self):
        """Can update an int list field like peak_months."""
        content = '---\ntitle: "Test"\npeak_months: []\n---\n\n# Test'
        result = update_frontmatter_field(content, "peak_months", [4, 5, 6])
        assert "peak_months: [4, 5, 6]" in result


from migrate_cuisine import run_cuisine_migration


class TestRunCuisineMigration:
    """Test full cuisine migration on recipe files."""

    def test_fixes_misclassified_cuisine(self):
        """Overwrites wrong cuisine for known recipes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Seneyet Jaj O Batata.md"
            recipe.write_text(
                '---\ntitle: "Seneyet Jaj O Batata"\ncuisine: "Ethiopian"\n---\n\n# Test'
            )
            results = run_cuisine_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'cuisine: "Middle Eastern"' in new_content
            assert len(results["updated"]) == 1

    def test_consolidates_variant(self):
        """Consolidates Korean-inspired to Korean."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Some Korean Dish.md"
            recipe.write_text(
                '---\ntitle: "Some Korean Dish"\ncuisine: "Korean-inspired"\n---\n\n# Test'
            )
            results = run_cuisine_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'cuisine: "Korean"' in new_content

    def test_skips_correct_cuisine(self):
        """Recipes with correct cuisines are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Good Recipe.md"
            recipe.write_text(
                '---\ntitle: "Good Recipe"\ncuisine: "Italian"\n---\n\n# Test'
            )
            results = run_cuisine_migration(recipes_dir, dry_run=False)
            assert len(results["skipped"]) == 1

    def test_dry_run_no_changes(self):
        """Dry run reports changes but doesn't modify files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Seneyet Jaj O Batata.md"
            original = '---\ntitle: "Seneyet Jaj O Batata"\ncuisine: "Ethiopian"\n---\n\n# Test'
            recipe.write_text(original)
            results = run_cuisine_migration(recipes_dir, dry_run=True)
            assert recipe.read_text() == original
            assert len(results["updated"]) == 1

    def test_creates_backup_before_modifying(self):
        """Should create backup in .history before writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Seneyet Jaj O Batata.md"
            recipe.write_text(
                '---\ntitle: "Seneyet Jaj O Batata"\ncuisine: "Ethiopian"\n---\n\n# Test'
            )
            run_cuisine_migration(recipes_dir, dry_run=False)
            history_dir = recipes_dir / ".history"
            assert history_dir.exists()
            assert len(list(history_dir.glob("*.md"))) == 1
