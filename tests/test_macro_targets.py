"""Tests for macro targets parser."""

import tempfile
from pathlib import Path

from lib.macro_targets import load_macro_targets
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
