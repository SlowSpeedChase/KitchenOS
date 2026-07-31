"""Tests for macro targets parser."""

import tempfile
from pathlib import Path

import pytest

from lib.macro_targets import (
    DEFAULT_SLOT_SHARES,
    load_macro_targets,
    load_slot_shares,
)
from lib.nutrition import NutritionData


class TestMacroTargets:
    def test_load_macro_targets(self):
        """Test loading macro targets from My Macros.md file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault_path = Path(tmp_dir)
            macros_file = vault_path / "My Macros.md"
            macros_file.write_text("""---
calories: 2000
protein: 150
carbs: 200
fat: 65
---

# My Daily Macros

| Macro    | Target |
|----------|--------|
| Calories | 2000   |
| Protein  | 150g   |
| Carbs    | 200g   |
| Fat      | 65g    |
""")

            targets = load_macro_targets(vault_path)

            assert targets is not None
            assert targets.calories == 2000
            assert targets.protein == 150
            assert targets.carbs == 200
            assert targets.fat == 65

    def test_load_macro_targets_file_not_found(self):
        """Test returns None when My Macros.md doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault_path = Path(tmp_dir)
            targets = load_macro_targets(vault_path)
            assert targets is None

    def test_load_macro_targets_missing_values(self):
        """Test handling of missing values defaults to 0."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault_path = Path(tmp_dir)
            macros_file = vault_path / "My Macros.md"
            macros_file.write_text("""---
calories: 2000
protein: 150
---

# My Daily Macros
""")

            targets = load_macro_targets(vault_path)

            assert targets is not None
            assert targets.calories == 2000
            assert targets.protein == 150
            assert targets.carbs == 0
            assert targets.fat == 0


class TestSlotShares:
    """load_slot_shares reads the four optional flat share_* keys."""

    def _write(self, vault_path: Path, body: str) -> None:
        (vault_path / "My Macros.md").write_text(
            f"---\ncalories: 2000\nprotein: 150\ncarbs: 200\nfat: 65\n{body}---\n"
        )

    def test_defaults_when_file_missing(self, tmp_path: Path):
        result = load_slot_shares(tmp_path)
        assert result.shares == DEFAULT_SLOT_SHARES
        assert result.normalized is False

    def test_defaults_when_keys_absent(self, tmp_path: Path):
        self._write(tmp_path, "")
        result = load_slot_shares(tmp_path)
        assert result.shares == DEFAULT_SLOT_SHARES
        assert result.normalized is False

    def test_reads_all_four_keys(self, tmp_path: Path):
        self._write(
            tmp_path,
            "share_breakfast: 0.2\nshare_lunch: 0.3\nshare_dinner: 0.4\nshare_snack: 0.1\n",
        )
        result = load_slot_shares(tmp_path)
        assert result.shares == {
            "breakfast": 0.2, "lunch": 0.3, "dinner": 0.4, "snack": 0.1,
        }
        assert result.normalized is False

    def test_partial_keys_fall_back_per_slot(self, tmp_path: Path):
        """A single override keeps the defaults for the other three."""
        self._write(tmp_path, "share_dinner: 0.35\n")
        result = load_slot_shares(tmp_path)
        assert result.shares["dinner"] == 0.35
        assert result.shares["breakfast"] == DEFAULT_SLOT_SHARES["breakfast"]
        assert result.normalized is False

    def test_unparseable_and_non_positive_values_fall_back(self, tmp_path: Path):
        self._write(tmp_path, "share_lunch: lots\nshare_snack: 0\nshare_dinner: -0.5\n")
        result = load_slot_shares(tmp_path)
        assert result.shares == DEFAULT_SLOT_SHARES
        assert result.normalized is False

    def test_shares_that_do_not_sum_to_one_are_normalised_and_flagged(self, tmp_path: Path):
        self._write(
            tmp_path,
            "share_breakfast: 1\nshare_lunch: 1\nshare_dinner: 1\nshare_snack: 1\n",
        )
        result = load_slot_shares(tmp_path)
        assert result.normalized is True
        assert result.shares == {
            "breakfast": 0.25, "lunch": 0.25, "dinner": 0.25, "snack": 0.25,
        }
        assert sum(result.shares.values()) == pytest.approx(1.0)

    def test_percentages_are_normalised_proportionally(self, tmp_path: Path):
        """Someone writing 25/30/35/10 as percentages still gets sane shares."""
        self._write(
            tmp_path,
            "share_breakfast: 25\nshare_lunch: 30\nshare_dinner: 35\nshare_snack: 10\n",
        )
        result = load_slot_shares(tmp_path)
        assert result.normalized is True
        assert result.shares["lunch"] == pytest.approx(0.30)

    def test_within_tolerance_is_left_alone(self, tmp_path: Path):
        self._write(
            tmp_path,
            "share_breakfast: 0.25\nshare_lunch: 0.3\nshare_dinner: 0.35\nshare_snack: 0.105\n",
        )
        result = load_slot_shares(tmp_path)
        assert result.normalized is False
        assert result.shares["snack"] == 0.105
