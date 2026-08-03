"""`freezes_well` — whether leftovers survive the freezer, as data not guesswork.

Batch cooking only buys variety if the leftovers keep. Some of this library's
best-yielding recipes don't freeze: sirloin reheats tough, a potato-based dish
goes grainy, a leafy salad collapses. Nothing recorded that, so any advice about
what to batch was the assistant guessing from the recipe name.

Tri-state on purpose. `null` is the honest answer for most of the corpus and
must stay distinct from `false` — "nobody has said" is not "it doesn't freeze",
and treating the two alike would quietly rule out half the library.
"""
import pytest

from lib import cook_now, recipe_schema
from lib.recipe_index import get_recipe_index
from templates.recipe_template import format_recipe_markdown


class TestSchema:
    def test_the_key_is_declared(self):
        """A frontmatter key must be declared in the same commit that writes it."""
        assert "freezes_well" in recipe_schema.KNOWN_KEYS

    def test_it_is_optional_not_required(self):
        """403 existing recipes don't carry it and are not thereby malformed."""
        assert "freezes_well" in recipe_schema.OPTIONAL_KEYS
        assert "freezes_well" not in recipe_schema.REQUIRED_KEYS


def _rendered(**over):
    data = {"name": "Test Chili", "ingredients": [], "instructions": []}
    data.update(over)
    return format_recipe_markdown(data, "https://x.test/1", "vid", "chan")


class TestTemplate:
    @pytest.mark.parametrize("value,expected", [
        (True, "freezes_well: true"),
        (False, "freezes_well: false"),
        (None, "freezes_well: null"),
    ])
    def test_all_three_states_render_as_yaml_literals(self, value, expected):
        assert expected in _rendered(freezes_well=value)

    def test_an_absent_value_renders_as_null_not_a_missing_line(self):
        """Absent and unknown are the same thing, and both mean null."""
        assert "freezes_well: null" in _rendered()

    def test_a_junk_value_does_not_produce_unparseable_frontmatter(self):
        """The field arrives from an LLM, so it can be anything."""
        out = _rendered(freezes_well="probably?")
        line = [ln for ln in out.splitlines() if ln.startswith("freezes_well:")]
        assert line == ["freezes_well: null"]


class TestReadPath:
    def _write(self, d, name, line):
        (d / f"{name}.md").write_text(
            f"---\nservings: 4\n{line}\n---\n# {name}\n", encoding="utf-8")

    def test_recipe_index_surfaces_it(self, tmp_path):
        self._write(tmp_path, "Chili", "freezes_well: true")
        assert get_recipe_index(tmp_path)[0]["freezes_well"] is True

    def test_a_recipe_without_it_reads_as_unknown(self, tmp_path):
        self._write(tmp_path, "Chili", "cuisine: null")
        assert get_recipe_index(tmp_path)[0]["freezes_well"] is None

    def test_false_survives_the_read_as_false_not_none(self, tmp_path):
        """The distinction the whole tri-state exists for."""
        self._write(tmp_path, "Steak", "freezes_well: false")
        assert get_recipe_index(tmp_path)[0]["freezes_well"] is False


class TestSuggesterCarriesIt:
    class _Item:
        def __init__(self, name):
            self.name, self.expires, self.quantity, self.unit = name, None, 1.0, "ct"

    def test_the_payload_reports_it(self):
        pantry = [self._Item("chicken"), self._Item("rice")]
        out = cook_now.generate(items=pantry, banked=set(), recipe_index=[{
            "name": "Chili", "dish_type": "main",
            "ingredient_items": ["chicken", "rice"],
            "nutrition_protein": 40, "nutrition_calories": 500,
            "nutrition_coverage": 1.0, "servings": 6, "freezes_well": True,
        }])
        assert out["recipes"][0]["freezes_well"] is True

    def test_it_is_reported_but_not_scored_on(self):
        """Too sparse to rank by — surfaced so a page can label, not reorder."""
        pantry = [self._Item("chicken"), self._Item("rice")]
        def score(value):
            out = cook_now.generate(items=pantry, banked=set(), recipe_index=[{
                "name": "Chili", "dish_type": "main",
                "ingredient_items": ["chicken", "rice"],
                "nutrition_protein": 40, "nutrition_calories": 500,
                "nutrition_coverage": 1.0, "servings": 6, "freezes_well": value,
            }])
            return out["recipes"][0]["score"]
        assert score(True) == score(False) == score(None)
