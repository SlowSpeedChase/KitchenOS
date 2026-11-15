"""A typed destination becomes a same-origin path here, and nowhere else."""
import pytest

from lib import paths
from lib.command.destinations import href_for


@pytest.fixture
def recipes(tmp_path, monkeypatch):
    (tmp_path / "Chicken Caldo A.md").write_text("---\n---\n")
    (tmp_path / "Mac & Cheese.md").write_text("---\n---\n")
    monkeypatch.setattr(paths, "recipes_dir", lambda: tmp_path)
    return tmp_path


def test_recipe_is_quoted(recipes):
    assert href_for({"page": "recipe", "recipe": "Chicken Caldo A"}) == "/recipe/Chicken%20Caldo%20A"
    assert href_for({"page": "recipe", "recipe": "Mac & Cheese"}) == "/recipe/Mac%20%26%20Cheese"


def test_unknown_or_hostile_recipe_is_none(recipes):
    assert href_for({"page": "recipe", "recipe": "Nope"}) is None
    assert href_for({"page": "recipe", "recipe": "../secrets"}) is None
    assert href_for({"page": "recipe", "recipe": ""}) is None
    assert href_for({"page": "recipe"}) is None


def test_day_recomputes_the_week_from_the_date():
    # The passed week is ignored: the date alone decides it.
    assert href_for({"page": "day", "date": "2026-11-18", "week": "1999-W01"}) == \
        "/meal-planner?week=2026-W47&date=2026-11-18&view=calendar"


def test_bad_day_is_none():
    assert href_for({"page": "day", "date": "2026-13-40"}) is None
    assert href_for({"page": "day"}) is None


def test_fixed_pages():
    assert href_for({"page": "planner"}) == "/meal-planner"
    assert href_for({"page": "home"}) == "/"
    assert href_for({"page": "inventory"}) == "/review"


def test_no_web_page_is_none():
    assert href_for({"page": "https://evil.example"}) is None
    assert href_for(None) is None
    assert href_for("recipe") is None
