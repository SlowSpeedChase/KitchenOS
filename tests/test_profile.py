"""Parsing the personal food profile out of `My Meal System.md`.

Design constraint that drives every test here: **the note will keep growing.**
The parser therefore extracts only the few sections something consumes
structurally, and hands the whole prose to LLM callers verbatim. A new section
must reach the model without anyone editing this module.
"""
import pytest

from lib import profile as prof

NOTE = """---
type: personal-profile
health_goals: [lower-ldl, prevent-t2d]
---
# My Meal System

Some intro prose.

## The buffer menu — "eat this first"

Keep at least one per row stocked.

### Sweet
- Chocolate chia pudding (chia + soy milk + cocoa) [heart][steady]
- Apple/pear + nut butter [heart]

### Salty / crunchy
- Roasted chickpeas (batch a jar) [heart][steady]
- Handful of pistachios or almonds [heart]

## Building blocks — stock these, then meals are assembly

- **Protein:** canned beans/lentils, tofu, edamame, eggs
- **Smart carbs:** rolled/steel-cut oats, brown rice/quinoa (batch)
- **Crunch & veg:** baby carrots, cucumber, snap peas

## Some Future Section I Add Later

Whatever I feel like writing.
"""


@pytest.fixture
def vault(tmp_vault):
    (tmp_vault / "My Meal System.md").write_text(NOTE, encoding="utf-8")
    return tmp_vault


def test_returns_none_when_the_note_is_absent(tmp_vault):
    """Everything downstream must degrade, not crash, without a profile."""
    assert prof.load_profile() is None


def test_loads_the_note(vault):
    assert prof.load_profile() is not None


def test_prose_carries_the_entire_note(vault):
    """The growth guarantee: unparsed sections still reach the LLM."""
    p = prof.load_profile()
    assert "Some Future Section I Add Later" in p.prose
    assert "Whatever I feel like writing." in p.prose


def test_prose_excludes_the_frontmatter(vault):
    """Frontmatter is machine plumbing; feeding it to a model is noise."""
    assert "type: personal-profile" not in prof.load_profile().prose


def test_reads_health_goals_from_frontmatter(vault):
    assert prof.load_profile().health_goals == ["lower-ldl", "prevent-t2d"]


# --- buffer menu ----------------------------------------------------------

def test_groups_buffer_foods_by_craving_lane(vault):
    lanes = prof.load_profile().buffer_menu
    assert set(lanes) == {"Sweet", "Salty / crunchy"}
    assert len(lanes["Sweet"]) == 2


def test_buffer_items_keep_their_full_text(vault):
    """The parenthetical is the recipe; stripping it loses the useful part."""
    sweet = prof.load_profile().buffer_menu["Sweet"]
    assert "Chocolate chia pudding (chia + soy milk + cocoa)" in sweet[0]


def test_buffer_items_expose_their_health_tags(vault):
    p = prof.load_profile()
    assert p.buffer_tags("Chocolate chia pudding") == {"heart", "steady"}
    assert p.buffer_tags("Handful of pistachios or almonds") == {"heart"}


def test_buffer_menu_prose_is_not_mistaken_for_an_item(vault):
    """"Keep at least one per row stocked." is instruction, not a food."""
    all_items = [i for items in prof.load_profile().buffer_menu.values() for i in items]
    assert not any("Keep at least one" in i for i in all_items)


# --- building blocks ------------------------------------------------------

def test_splits_building_blocks_into_categories_and_items(vault):
    blocks = prof.load_profile().building_blocks
    assert blocks["Protein"] == ["canned beans/lentils", "tofu", "edamame", "eggs"]
    assert "brown rice/quinoa (batch)" in blocks["Smart carbs"]


def test_building_block_categories_keep_their_ampersands(vault):
    assert "Crunch & veg" in prof.load_profile().building_blocks


# --- resilience -----------------------------------------------------------

def test_missing_sections_yield_empty_structures_not_errors(tmp_vault):
    """A half-written profile must still load — it is a personal note."""
    (tmp_vault / "My Meal System.md").write_text(
        "---\n---\n# My Meal System\n\nJust prose so far.\n", encoding="utf-8")
    p = prof.load_profile()
    assert p.buffer_menu == {} and p.building_blocks == {}
    assert "Just prose so far." in p.prose


def test_heading_matching_survives_rewording(tmp_vault):
    """Headings are prose and get edited; matching must not be exact-string."""
    (tmp_vault / "My Meal System.md").write_text(
        "---\n---\n## My buffer menu, revised\n\n### Sweet\n- Berries\n",
        encoding="utf-8")
    assert prof.load_profile().buffer_menu == {"Sweet": ["Berries"]}


def test_prompt_context_is_bounded(vault):
    """Injected into every suggestion prompt, so it cannot grow without limit."""
    ctx = prof.load_profile().prompt_context(max_chars=200)
    assert len(ctx) <= 200
