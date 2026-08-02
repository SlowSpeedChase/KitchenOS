"""The real corpus satisfies the declared schema.

An audit of the user's data, not of code behaviour — which is why it lives
beside test_live_state.py rather than in the hermetic unit suite. The schema
checker itself is tested over synthetic frontmatter in
tests/test_recipe_schema.py; this asks whether the vault currently conforms.

Failing here means a producer started writing a key nobody declared, or drift
came back. The fix is either to add the key to lib/recipe_schema.OPTIONAL_KEYS
(if it is legitimate) or to run scripts/normalize_recipes.py --apply.

It lives under tests/e2e/ because it shares `_paths.data_root` with the browser
harness — the vault is git-ignored and so exists only in the main checkout — but
it is marked ``corpus``, **not** ``e2e``, and therefore runs in the default
suite. It needs no server and no browser, and a drift guard that only runs when
someone remembers to pass `-m e2e` is documentation rather than enforcement.
It skips, visibly, on a machine with no vault.
"""
from __future__ import annotations

import collections
from pathlib import Path

import pytest

from lib.recipe_parser import parse_recipe_file
from lib.recipe_schema import check_frontmatter
from tests.e2e._paths import data_root

pytestmark = pytest.mark.corpus

REPO = Path(__file__).resolve().parents[2]
# The real vault is git-ignored, so it lives in the main worktree even when this
# branch is being tested from .worktrees/. Same reason conftest.py needs this.
RECIPES = data_root(REPO) / "vault" / "KitchenOS" / "Recipes"

needs_vault = pytest.mark.skipif(
    not RECIPES.is_dir() or not any(RECIPES.glob("*.md")),
    reason="vault not present on this machine",
)


def _violations():
    """Every schema violation in the corpus, duplicates included.

    Duplicate keys are checked from the raw text because ``check_frontmatter``
    takes a parsed dict, and a mapping has already collapsed a duplicate —
    which is precisely the artifact ``migrate_recipes.rename_nutrition_keys``
    used to emit, and would otherwise pass this guard unnoticed.
    """
    from lib import frontmatter
    from lib.recipe_schema import Violation, duplicate_keys

    out = []
    for p in sorted(RECIPES.glob("*.md")):
        if p.name.startswith("."):
            continue
        content = p.read_text(encoding="utf-8")
        out.extend(check_frontmatter(p.stem, parse_recipe_file(content)["frontmatter"]))
        fm_text, _ = frontmatter.split_frontmatter(content)
        for key in duplicate_keys(fm_text or ""):
            out.append(Violation(p.stem, key, "duplicate_key",
                                 f"{key!r} appears more than once"))
    return out


@needs_vault
def test_the_corpus_has_no_schema_violations():
    violations = _violations()
    if violations:
        by_code = collections.Counter(v.code for v in violations)
        detail = "\n".join(f"  {v.recipe}: {v.code} ({v.key})" for v in violations[:20])
        more = "" if len(violations) <= 20 else f"\n  ... and {len(violations) - 20} more"
        pytest.fail(
            f"{len(violations)} schema violation(s) across the corpus: {dict(by_code)}\n"
            f"{detail}{more}\n"
            f"Fix: .venv/bin/python scripts/normalize_recipes.py --check"
        )


@needs_vault
def test_no_recipe_declares_a_non_numeric_servings():
    """Called out separately: three subsystems each read a range differently.

    nutrition_engine takes a range's midpoint, week_view's bare float() throws
    into an `except: return 4.0`, and macro_eligible only checks for None — so
    a string here means two subsystems disagree while the third certifies the
    recipe as trustworthy.
    """
    bad = [v for v in _violations() if v.code == "servings_not_numeric"]
    assert bad == [], (
        f"{len(bad)} recipe(s) with a non-numeric servings: {[v.recipe for v in bad]}"
    )


@needs_vault
def test_no_recipe_carries_a_duplicate_key():
    """The artifact migrate_recipes used to emit, guarded at the file itself.

    A dict-based check cannot see this: PyYAML keeps only the last occurrence,
    so two `nutrition_calories:` lines parse as one and every schema check
    passes while the file is malformed and one value has been discarded.
    """
    bad = [v for v in _violations() if v.code == "duplicate_key"]
    assert bad == [], f"duplicate keys: {[(v.recipe, v.key) for v in bad]}"
