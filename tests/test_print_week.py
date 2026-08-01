"""Tests for the printable 'week packet'."""

import json

from lib import print_week

WEEK = "2026-W31"


def _recipe(recipes_dir, name, *, cal, protein, coverage=0.95, servings=2):
    (recipes_dir / f"{name}.md").write_text(
        f'---\ntitle: "{name}"\nnutrition_calories: {cal}\n'
        f'nutrition_protein: {protein}\nnutrition_carbs: 30\nnutrition_fat: 12\n'
        f'nutrition_coverage: {coverage}\nservings: {servings}\n---\n\n# {name}\n'
    )


def _setup_markdown_week(vault):
    (vault / "My Macros.md").write_text(
        "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n\n# My Macros\n")
    recipes = vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    _recipe(recipes, "Beef Bowl", cal=650, protein=48)
    _recipe(recipes, "Oatmeal", cal=300, protein=12)
    plans = vault / "Meal Plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / f"{WEEK}.md").write_text(
        "## Monday (Jul 27)\n\n### breakfast\n[[Oatmeal]]\n\n### dinner\n[[Beef Bowl]]\n\n"
        "## Wednesday (Jul 29)\n\n### dinner\n[[Beef Bowl]] x2\n\n"
    )
    return vault, recipes


class TestBuildWeekPacket:
    def test_markdown_week_macros_and_grid(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])

        assert packet["source"] == "links"
        assert packet["targets"]["protein"] == 190
        monday = next(d for d in packet["days"] if d["day"] == "Monday")
        # Oatmeal (12) + Beef Bowl (48) = 60 g protein
        assert monday["macros"]["protein"] == 60
        assert monday["slots"]["breakfast"][0]["name"] == "Oatmeal"
        assert monday["slots"]["dinner"][0]["name"] == "Beef Bowl"
        # A day with no meals has null macros.
        tues = next(d for d in packet["days"] if d["day"] == "Tuesday")
        assert tues["macros"] is None
        # xN multiplier flows through to the slot.
        wed = next(d for d in packet["days"] if d["day"] == "Wednesday")
        assert wed["slots"]["dinner"][0]["servings"] == 2.0

    def test_do_ahead_reads_cached_tasks(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        # Pre-write a tasks sidecar so load_cached_tasks stays LLM-free.
        sidecar = vault / "Meal Plans" / f"{WEEK}.tasks.json"
        sidecar.write_text(json.dumps({"week": WEEK, "tasks": [
            {"id": "a", "recipe": "Beef Bowl", "day": "Monday", "slot": "dinner",
             "step": 1, "text": "Marinate the beef", "type": "prep",
             "time_minutes": 10, "can_do_ahead": True, "depends_on": [], "done": False},
            {"id": "b", "recipe": "Beef Bowl", "day": "Monday", "slot": "dinner",
             "step": 2, "text": "Sear the beef", "type": "active",
             "time_minutes": 8, "can_do_ahead": False, "depends_on": [], "done": False},
        ]}))
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        assert packet["tasks_available"] is True
        assert [t["text"] for t in packet["do_ahead"]] == ["Marinate the beef"]

    def test_missing_plan_raises(self, tmp_vault):
        (tmp_vault / "Recipes").mkdir(parents=True, exist_ok=True)
        try:
            print_week.build_week_packet(WEEK, tmp_vault, tmp_vault / "Recipes", pantry=[])
            assert False, "expected FileNotFoundError"
        except FileNotFoundError:
            pass


class TestRenderPacketHtml:
    def test_renders_grid_shopping_prep_and_links(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        html = print_week.render_packet_html(packet, base_url="https://ko.example")

        assert "week-grid" in html
        assert "The week" in html and "Shopping list" in html and "Get ahead" in html
        # recipe names link to their grid cards
        assert "https://ko.example/recipe-card/Beef%20Bowl" in html
        # macros shown as actual / target
        assert "/190g P" in html
        # targets header
        assert "2300" in html

    def test_no_tasks_shows_hint(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        html = print_week.render_packet_html(packet)
        assert "?tasks=1" in html  # hint when no cached prep tasks exist


def test_week_label_is_human_readable(tmp_vault):
    """REGRESSION: the printed page's <h1> read "2026-W31  (2026-07-27 → 2026-08-02)".

    It goes on the fridge — an ISO week id and ISO dates are the two least
    readable ways to say "this week".
    """
    vault, recipes = _setup_markdown_week(tmp_vault)
    packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])

    assert "2026-W31" not in packet["week_label"]
    assert "Jul 27 - Aug 2, 2026" in packet["week_label"]
    assert packet["week"] == "2026-W31", "the id stays as the key"
