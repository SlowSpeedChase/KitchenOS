"""The dislike guard: a plain string match, no model anywhere.

The profile note says "Do not infer that all other peppers are disliked", so the
negatives below matter as much as the positives — a matcher that flags red
pepper flakes would quietly drop half the corpus from suggestions.
"""
import pytest

from lib import dislike_guard as dg

DISLIKES = ["bell pepper", "pepperoncini", "peperoncini"]


@pytest.mark.parametrize("item", [
    "bell pepper",
    "red bell pepper, diced",
    "Bell Peppers",
    "bell-pepper strips",
    "green pepper",
    "roasted red peppers (jarred)",
    "capsicum",
    "mini sweet peppers",
    "pepperoncini",
    "sliced peperoncini",
    "pepperoncinis",
    "**pepperoncini peppers**",
])
def test_flags_disliked_ingredients(item):
    assert dg.match_item(item, DISLIKES), item


@pytest.mark.parametrize("item", [
    "red pepper flakes",
    "crushed red pepper",
    "aleppo pepper",
    "urfa biber pepper",
    "jalapeño",
    "jalapeno pepper",
    "black pepper",
    "freshly ground pepper",
    "green peppercorns",
    "salt and pepper",
    "chipotle peppers in adobo",
    "Kashmiri chili",
    "peppermint",
])
def test_other_peppers_are_not_disliked(item):
    assert dg.match_item(item, DISLIKES) is None, item


def test_match_item_names_the_dislike():
    assert dg.match_item("2 red bell peppers", DISLIKES) == "bell pepper"
    assert dg.match_item("capsicum", DISLIKES) == "bell pepper"


def test_synonyms_only_apply_when_their_dislike_is_listed():
    assert dg.match_item("capsicum", ["pepperoncini"]) is None


def test_scan_items_returns_the_matched_rows():
    hits = dg.scan_items(["olive oil", "1 bell pepper", "pepperoncini, sliced"], DISLIKES)
    assert hits == [
        {"item": "1 bell pepper", "dislike": "bell pepper"},
        {"item": "pepperoncini, sliced", "dislike": "pepperoncini"},
    ]


RECIPE = """---
title: "Salad"
---
# Salad

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | can | chickpeas |
| 1 | whole | red bell pepper, diced |

### For the dressing

| Amount | Unit | Ingredient |
|--------|------|------------|
| 4 | whole | pepperoncini, chopped |
| 1 | tsp | red pepper flakes |

## Instructions

1. Mix. Garnish with bell pepper rings.
"""


def test_scan_recipe_reads_the_whole_ingredients_section_only():
    hits = dg.scan_recipe(RECIPE, DISLIKES)
    assert [h["item"] for h in hits] == ["red bell pepper, diced", "pepperoncini, chopped"]


def test_scan_recipe_with_no_dislikes_is_empty():
    assert dg.scan_recipe(RECIPE, []) == []


def test_recipe_hits_reads_the_file(tmp_path):
    (tmp_path / "Salad.md").write_text(RECIPE)
    assert len(dg.recipe_hits("Salad", DISLIKES, recipes_dir=tmp_path)) == 2
    assert dg.recipe_hits("Missing", DISLIKES, recipes_dir=tmp_path) == []


PROFILE_NOTE = """# My Meal System

## Vegetables built into meals

- **Dislike:** Bell pepper, pepperoncini/peperoncini. Do not infer that all other peppers are disliked.
"""


def test_extraction_writes_dislike_hits_frontmatter(tmp_vault):
    import yaml
    import extract_recipe
    (tmp_vault / "My Meal System.md").write_text(PROFILE_NOTE)
    path = tmp_vault / "Salad.md"
    path.write_text(RECIPE)
    extract_recipe._tag_dislikes(path)
    fm = yaml.safe_load(path.read_text().split("---")[1])
    assert fm["dislike_hits"] == ["red bell pepper, diced", "pepperoncini, chopped"]


def test_extraction_removes_a_stale_flag_when_clean(tmp_vault):
    import extract_recipe
    (tmp_vault / "My Meal System.md").write_text(PROFILE_NOTE)
    path = tmp_vault / "Clean.md"
    path.write_text('---\ntitle: "Clean"\ndislike_hits: ["old"]\n---\n'
                    "## Ingredients\n\n| Amount | Unit | Ingredient |\n|---|---|---|\n"
                    "| 1 | tsp | red pepper flakes |\n")
    extract_recipe._tag_dislikes(path)
    assert "dislike_hits" not in path.read_text()


def test_current_dislikes_reads_the_vault_note(tmp_vault):
    (tmp_vault / "My Meal System.md").write_text(PROFILE_NOTE)
    assert dg.current_dislikes() == ["bell pepper", "pepperoncini", "peperoncini"]


def test_current_dislikes_without_a_note_is_empty(tmp_vault):
    assert dg.current_dislikes() == []


def test_swaps_refused_when_llm_disabled(monkeypatch):
    monkeypatch.setenv("KITCHENOS_NO_LLM", "1")
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("dialled"))
    assert dg.suggest_swaps([{"item": "bell pepper", "dislike": "bell pepper"}]) == []


def test_swaps_drop_a_suggestion_that_is_itself_disliked(monkeypatch):
    import json
    import requests
    monkeypatch.delenv("KITCHENOS_NO_LLM", raising=False)

    class Resp:
        status_code = 200
        def json(self):
            return {"response": json.dumps({"swaps": [
                {"item": "1 bell pepper", "role": "crunch", "swap": "yellow bell pepper"},
                {"item": "pepperoncini", "role": "tang", "swap": "dill pickle"},
            ]})}
    calls = []
    monkeypatch.setattr(requests, "post", lambda url, **k: calls.append(url) or Resp())
    hits = [{"item": "1 bell pepper", "dislike": "bell pepper"},
            {"item": "pepperoncini", "dislike": "pepperoncini"}]
    assert dg.suggest_swaps(hits) == [
        {"item": "pepperoncini", "role": "tang", "swap": "dill pickle"}]
    assert calls == [dg.OLLAMA_URL]   # local only, never Claude
