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
