"""rename_nutrition_keys must never create a duplicate YAML key.

Renaming 'calories: 3058' in a file that already carries
'nutrition_calories: 169' produces two 'nutrition_calories:' lines. All 13
affected files are legacy-*first*, so the renamed line lands in the earlier
position and PyYAML's last-wins rule happens to keep the canonical 169 — the
value survives, but only by ordering luck. What is left behind is malformed:
yaml.safe_load tolerates the duplicate, a strict parser raises on it, and a
single canonical-first file would silently publish a whole-recipe total as a
per-serving value.

A rename's only safe move on a collision is to decline. Deleting the legacy
key belongs to scripts/normalize_recipes.py.
"""
import yaml

from migrate_recipes import rename_nutrition_keys

LEGACY_FIRST = """---
title: Watermelon Feta Salad
calories: 3058
nutrition_calories: 169
---

# Watermelon Feta Salad
"""

NO_TWIN = """---
title: Old Recipe
calories: 420
---

# Old Recipe
"""


def _fm(content: str) -> dict:
    return yaml.safe_load(content.split("---")[1])


def test_rename_refuses_when_the_canonical_key_already_exists():
    out, changes = rename_nutrition_keys(LEGACY_FIRST)
    assert out == LEGACY_FIRST
    assert changes == []


def test_the_canonical_value_survives_a_migration_attempt():
    """169 kcal/serving must not become the 3058 whole-recipe total.

    This passes even before the fix, because legacy-first ordering plus
    last-wins keeps the canonical value. It is here so that a future change to
    key ordering or to the rename direction cannot quietly flip it.
    """
    out, _ = rename_nutrition_keys(LEGACY_FIRST)
    assert _fm(out)["nutrition_calories"] == 169


def test_a_canonical_first_file_would_otherwise_be_corrupted():
    """Why declining matters: the ordering that saves the corpus is luck.

    With the canonical key first, the renamed whole-recipe total lands last and
    last-wins publishes 3058 kcal as a per-serving value.
    """
    canonical_first = """---
title: Hypothetical
nutrition_calories: 169
calories: 3058
---

# Hypothetical
"""
    out, changes = rename_nutrition_keys(canonical_first)
    assert changes == []
    assert _fm(out)["nutrition_calories"] == 169


def test_no_duplicate_key_is_ever_emitted():
    out, _ = rename_nutrition_keys(LEGACY_FIRST)
    keys = [ln.split(":")[0] for ln in out.split("---")[1].strip().splitlines()]
    assert len(keys) == len(set(keys))


def test_rename_still_works_when_there_is_no_canonical_twin():
    out, changes = rename_nutrition_keys(NO_TWIN)
    assert "nutrition_calories: 420" in out
    assert "calories: 420" not in out.replace("nutrition_calories: 420", "")
    assert changes == ["Renamed 'calories' to 'nutrition_calories'"]


def test_rename_is_idempotent():
    once, _ = rename_nutrition_keys(NO_TWIN)
    twice, changes = rename_nutrition_keys(once)
    assert twice == once
    assert changes == []


def test_a_partial_collision_renames_only_the_safe_key():
    content = """---
title: Mixed
calories: 3058
nutrition_calories: 169
fat: 12
---

# Mixed
"""
    out, changes = rename_nutrition_keys(content)
    assert changes == ["Renamed 'fat' to 'nutrition_fat'"]
    assert _fm(out)["nutrition_calories"] == 169
    assert _fm(out)["nutrition_fat"] == 12
    assert "calories: 3058" in out  # left for the normalizer to delete
