"""Parser for user macro targets from My Macros.md file."""

from pathlib import Path
from typing import NamedTuple, Optional

from lib.nutrition import NutritionData
from lib.recipe_parser import parse_recipe_file
from lib.serving_ledger import MEALS

#: How a day's target splits across the four slots when My Macros.md is silent.
DEFAULT_SLOT_SHARES = {
    "breakfast": 0.25,
    "lunch": 0.30,
    "dinner": 0.35,
    "snack": 0.10,
}

#: Tolerance on "the four shares sum to 1.0" before we rescale them.
SHARE_SUM_TOLERANCE = 0.01


def load_macro_targets(vault_path: Path) -> Optional[NutritionData]:
    """Load daily macro targets from My Macros.md file.

    Args:
        vault_path: Path to the Obsidian vault root

    Returns:
        NutritionData with daily targets, or None if file not found
    """
    macros_file = vault_path / "My Macros.md"

    if not macros_file.exists():
        return None

    content = macros_file.read_text(encoding='utf-8')
    parsed = parse_recipe_file(content)
    frontmatter = parsed['frontmatter']

    # Extract macro values from frontmatter
    calories = frontmatter.get('calories', 0)
    protein = frontmatter.get('protein', 0)
    carbs = frontmatter.get('carbs', 0)
    fat = frontmatter.get('fat', 0)

    # Ensure all values are integers
    return NutritionData(
        calories=int(calories) if calories else 0,
        protein=int(protein) if protein else 0,
        carbs=int(carbs) if carbs else 0,
        fat=int(fat) if fat else 0,
    )


class SlotShares(NamedTuple):
    """A day's target split across the four meal slots.

    ``normalized`` is True when the file's own numbers didn't sum to 1.0 and were
    rescaled — surfaced to the UI so it can say so out loud rather than quietly
    reinterpreting what the user wrote.
    """
    shares: dict[str, float]
    normalized: bool


def load_slot_shares(vault_path: Path) -> SlotShares:
    """Load per-slot target shares from My Macros.md.

    Read from four *flat* keys — ``share_breakfast``, ``share_lunch``,
    ``share_dinner``, ``share_snack``. Flat rather than a nested ``slot_shares:``
    block because ``parse_recipe_file`` strips each line before matching
    ``^(\\w+):\\s*(.*)$``, so a nested block's indented children would parse as
    top-level keys.

    Kept separate from :func:`load_macro_targets` on purpose: that function has
    several callers (print_week, nutrition_dashboard, api_server) and none of
    them should have to care about slots.

    Missing file, missing keys and unparseable values all fall back to
    :data:`DEFAULT_SLOT_SHARES` per slot. When the four don't sum to 1.0 within
    :data:`SHARE_SUM_TOLERANCE` they are rescaled proportionally and
    ``normalized`` is True.
    """
    frontmatter: dict = {}
    macros_file = vault_path / "My Macros.md"
    if macros_file.exists():
        try:
            frontmatter = parse_recipe_file(
                macros_file.read_text(encoding="utf-8"))["frontmatter"]
        except Exception:
            frontmatter = {}

    shares: dict[str, float] = {}
    for slot in MEALS:
        raw = frontmatter.get(f"share_{slot}")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = DEFAULT_SLOT_SHARES[slot]
        if value <= 0:
            value = DEFAULT_SLOT_SHARES[slot]
        shares[slot] = value

    total = sum(shares.values())
    if abs(total - 1.0) > SHARE_SUM_TOLERANCE:
        shares = {slot: value / total for slot, value in shares.items()}
        return SlotShares(shares=shares, normalized=True)

    return SlotShares(shares=shares, normalized=False)
