"""Tests for the printable 'week packet'."""

import json

import pytest

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

    def test_markdown_week_prints_every_recipe_in_a_slot(self, tmp_vault):
        """Two breakfasts in one slot both reach the paper, not just the first."""
        vault, recipes = _setup_markdown_week(tmp_vault)
        (vault / "Meal Plans" / f"{WEEK}.md").write_text(
            "## Monday (Jul 27)\n\n### breakfast\n[[Oatmeal]]\n[[Beef Bowl]] x0.5\n\n")
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        monday = next(d for d in packet["days"] if d["day"] == "Monday")
        assert [s["name"] for s in monday["slots"]["breakfast"]] == ["Oatmeal", "Beef Bowl"]
        assert monday["slots"]["breakfast"][1]["servings"] == 0.5

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
    @pytest.mark.parametrize("base", ["https://ko.example", "https://chases-mac-mini.taila69703.ts.net"])
    def test_renders_grid_shopping_prep_and_links(self, tmp_vault, base):
        vault, recipes = _setup_markdown_week(tmp_vault)
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        html = print_week.render_packet_html(packet, base_url=base)

        assert "week-grid" in html
        assert "The week" in html and "Shopping list" in html and "Get ahead" in html
        # recipe names link to their grid cards
        assert f"{base}/recipe-card/Beef%20Bowl" in html
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


class TestLedgerWeekPacket:
    """The ledger path had no test at all — every case here used `source: links`."""

    def test_a_ledger_week_names_what_it_excluded(self, tmp_db, tmp_vault):
        """An excluded recipe must reach the packet, not just set a ⚠.

        The printed packet is read away from the screen, so "⚠" with nothing
        naming the cause is the one place a reader cannot go and check.
        """
        from lib import serving_ledger as sl

        vault = tmp_vault
        (vault / "My Macros.md").write_text(
            "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n")
        recipes = vault / "Recipes"
        recipes.mkdir(parents=True, exist_ok=True)
        _recipe(recipes, "Beef Bowl", cal=650, protein=48)
        _recipe(recipes, "Mystery Soup", cal=400, protein=20, coverage=0.4)

        sl.create_cook(recipe="Beef Bowl", week=WEEK, scale=1.0,
                       servings_produced=2.0, date="2026-07-27", meal="dinner")
        sl.create_cook(recipe="Mystery Soup", week=WEEK, scale=1.0,
                       servings_produced=2.0, date="2026-07-27", meal="lunch")

        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        assert packet["source"] == "ledger"
        monday = next(d for d in packet["days"] if d["date"] == "2026-07-27")
        assert monday["incomplete"] is True
        assert monday["excluded"] == ["Mystery Soup"]
        # The sound recipe still counts; only the untrusted one is left out.
        assert monday["macros"]["calories"] == 650

    def test_a_sound_ledger_week_excludes_nothing(self, tmp_db, tmp_vault):
        from lib import serving_ledger as sl

        vault = tmp_vault
        (vault / "My Macros.md").write_text(
            "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n")
        recipes = vault / "Recipes"
        recipes.mkdir(parents=True, exist_ok=True)
        _recipe(recipes, "Beef Bowl", cal=650, protein=48)
        sl.create_cook(recipe="Beef Bowl", week=WEEK, scale=1.0,
                       servings_produced=2.0, date="2026-07-27", meal="dinner")

        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        monday = next(d for d in packet["days"] if d["date"] == "2026-07-27")
        assert monday["excluded"] == []
        assert monday["incomplete"] is False

    def test_the_rendered_packet_names_the_exclusion(self, tmp_db, tmp_vault):
        """On paper a ⚠ cannot be hovered — the name has to be in the ink."""
        from lib import serving_ledger as sl

        vault = tmp_vault
        (vault / "My Macros.md").write_text(
            "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n")
        recipes = vault / "Recipes"
        recipes.mkdir(parents=True, exist_ok=True)
        _recipe(recipes, "Mystery Soup", cal=400, protein=20, coverage=0.4)
        sl.create_cook(recipe="Mystery Soup", week=WEEK, scale=1.0,
                       servings_produced=2.0, date="2026-07-27", meal="dinner")

        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
        html = print_week.render_packet_html(packet)
        assert "excludes Mystery Soup" in html


class TestRecipePages:
    """Optional full recipes at the end of the print packet (?recipes=1)."""

    def _full_recipe(self, recipes_dir, name):
        (recipes_dir / f"{name}.md").write_text(
            f'---\ntitle: "{name}"\nservings: 4\ntotal_time: "30 minutes"\n---\n\n'
            f"# {name}\n\n## Ingredients\n\n| Amount | Unit | Ingredient |\n"
            "|--------|------|------------|\n| 1 | lb | ground beef |\n| 2 | cup | rice |\n\n"
            "## Instructions\n\n1. Brown the beef.\n2. Serve over rice.\n")

    def test_can_be_turned_off(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[],
                                              include_recipes=False)
        assert packet["recipes"] == []
        assert "class='recipe-page" not in print_week.render_packet_html(packet)

    def test_each_recipe_once_in_week_order(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        self._full_recipe(recipes, "Beef Bowl")
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[],
                                              include_recipes=True)
        # Oatmeal (Mon breakfast) before Beef Bowl (Mon dinner); Beef Bowl's
        # second appearance on Wednesday does not print it twice.
        assert [r["name"] for r in packet["recipes"]] == ["Oatmeal", "Beef Bowl"]
        beef = packet["recipes"][1]
        assert [i["item"] for i in beef["ingredients"]] == ["ground beef", "rice"]
        assert [s["text"] for s in beef["instructions"]] == ["Brown the beef.", "Serve over rice."]

        html = print_week.render_packet_html(packet)
        assert html.count("class='recipe-page") == 2
        assert "Brown the beef." in html and "ground beef" in html

    def test_missing_recipe_file_is_skipped(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        (recipes / "Oatmeal.md").unlink()
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[],
                                              include_recipes=True)
        assert [r["name"] for r in packet["recipes"]] == ["Beef Bowl"]

    def test_recipe_text_is_escaped(self, tmp_vault):
        vault, recipes = _setup_markdown_week(tmp_vault)
        packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[],
                                              include_recipes=True)
        packet["recipes"][0]["instructions"] = [{"step": 1, "text": "<script>x</script>"}]
        assert "<script>x" not in print_week.render_packet_html(packet)


# ---- shopping list by location (printed, every ingredient) -----------------

from lib.inventory import InventoryItem


def _line(item, status, *, matched=None, to_buy=None, needed="1 cup"):
    amount, _, unit = needed.partition(" ")
    return {"item": item, "status": status, "matched_inventory": matched,
            "to_buy": to_buy, "needed": {"amount": amount, "unit": unit},
            "needed_display": f"{needed} {item}", "display": f"{needed} {item}"}


class TestShoppingByLocation:
    def _groups(self, lines, recipes, inventory, place=lambda n: "pantry", head=lambda n: ""):
        return print_week.shopping_by_location(lines, recipes, inventory, place=place, head=head)

    def test_groups_by_where_it_lives_in_kitchen_order(self):
        lines = [
            _line("rolled oats", "on_hand", matched={"item": "Rolled oats", "amount": "1", "unit": "ct"}),
            _line("greek yogurt", "credited", matched={"item": "Greek yogurt", "amount": "2", "unit": "cup"}),
            _line("blueberries", "buy", to_buy={"amount": "0.5", "unit": "cup"}),
        ]
        recipes = {"Oats": [{"item": "rolled oats"}, {"item": "Greek yogurt"}, {"item": "blueberries"}]}
        inv = [InventoryItem("Rolled oats", 1, location="pantry"),
               InventoryItem("Greek yogurt", 2, unit="cup", location="fridge")]
        groups = self._groups(lines, recipes, inv, place=lambda n: "freezer")
        assert [g["location"] for g in groups] == ["fridge", "freezer", "pantry"]
        fridge, freezer, pantry = groups
        assert fridge["items"][0]["have"] is True and fridge["label"] == "Fridge"
        assert freezer["items"][0]["have"] is False   # not owned → predicted spot
        assert pantry["items"][0]["recipes"] == ["Oats"]

    def test_every_ingredient_appears_including_owned_ones(self):
        lines = [_line("baking soda", "on_hand", matched={"item": "Baking soda", "amount": "1", "unit": "ct"}),
                 _line("oat flour", "buy", to_buy={"amount": "0.75", "unit": "cup"})]
        groups = self._groups(lines, {}, [InventoryItem("Baking soda", 1)])
        names = [i["text"] for g in groups for i in g["items"]]
        assert any("baking soda" in n for n in names) and any("oat flour" in n for n in names)

    def test_partial_credit_is_unchecked_and_says_how_much_more(self):
        lines = [_line("eggs", "credited", needed="6 whole",
                       matched={"item": "Eggs", "amount": "2", "unit": "whole"},
                       to_buy={"amount": "4", "unit": "whole"})]
        [g] = self._groups(lines, {}, [InventoryItem("Eggs", 2, unit="whole", location="fridge")])
        item = g["items"][0]
        assert item["have"] is False
        assert "4" in item["note"] and "more" in item["note"]

    def test_related_item_is_not_ticked_but_names_what_you_have(self):
        """Oat flour vs all-purpose flour: a wrong tick means you don't buy it."""
        lines = [_line("oat flour", "review", matched={"item": "All-purpose flour", "amount": "1", "unit": "ct"})]
        [g] = self._groups(lines, {}, [InventoryItem("All-purpose flour", 1)])
        item = g["items"][0]
        assert item["have"] is False and item["verify"] is True
        assert "All-purpose flour" in item["note"]

    def test_to_buy_goes_where_you_keep_that_food(self):
        lines = [_line("greek-style yogurt", "buy", to_buy={"amount": "1", "unit": "cup"})]
        inv = [InventoryItem("whole milk yogurt", 1, location="fridge")]
        [g] = self._groups(lines, {}, inv, place=lambda n: "pantry",
                           head=lambda n: "yogurt" if "yogurt" in n else "")
        assert g["location"] == "fridge"

    def test_unknown_spot_is_not_sure_rather_than_a_wrong_shelf(self):
        lines = [_line("mozzarella", "buy", to_buy={"amount": "8", "unit": "oz"})]
        [g] = self._groups(lines, {}, [], place=lambda n: None)
        assert g["location"] == "other" and g["label"] == "Not sure where it goes"

    def test_shared_ingredient_names_every_recipe_once(self):
        lines = [_line("garlic", "buy", to_buy={"amount": "3", "unit": "clove"})]
        recipes = {"B": [{"item": "Garlic"}], "A": [{"item": "garlic"}, {"item": "garlic"}]}
        [g] = self._groups(lines, recipes, [])
        assert g["items"][0]["recipes"] == ["A", "B"]

    def test_excluded_lines_are_left_out(self):
        assert self._groups([_line("water", "excluded")], {}, []) == []

    def test_render_shows_checked_boxes_and_no_markdown_checkboxes(self):
        packet_groups = [{"location": "fridge", "label": "Fridge", "items": [
            {"text": "1 cup greek yogurt", "have": True, "verify": False,
             "note": "have Greek yogurt (2 cup)", "recipes": ["Oats"]},
            {"text": "8 oz mozzarella", "have": False, "verify": False,
             "note": "", "recipes": ["Mini Pizzas"]}]}]
        html = print_week.render_shopping_html(packet_groups)
        assert "Fridge" in html and "☑" in html and "☐" in html
        assert "Mini Pizzas" in html and "have Greek yogurt" in html
        assert "- [ ]" not in html


def test_full_recipes_are_included_by_default(tmp_vault):
    vault, recipes = _setup_markdown_week(tmp_vault)
    packet = print_week.build_week_packet(WEEK, vault, recipes, pantry=[])
    assert packet["recipes"], "recipe pages (with steps) should print unless turned off"
    assert "shopping_by_location" in packet


@pytest.mark.parametrize("wanted,owned,same", [
    ("blueberries", "frozen blueberries", True),
    ("1/2 teaspoon fine sea salt", "Celtic sea salt", True),
    ("extra-virgin olive oil", "extra virgin olive oil", True),
    ("yogurt", "whole milk yogurt", True),
    ("oat flour", "All-purpose flour", False),
    ("pumpkin seeds", "pumpkin", False),
    ("lemon", "lemon juice", False),
    ("unsweetened nondairy milk", "whole milk", False),
])
def test_same_food(wanted, owned, same):
    assert print_week.same_food(wanted, owned) is same


def test_same_food_review_match_is_ticked():
    lines = [_line("blueberries", "review", matched={"item": "frozen blueberries", "amount": "1", "unit": "ct"})]
    [g] = print_week.shopping_by_location(lines, {}, [InventoryItem("frozen blueberries", 1, location="freezer")])
    assert g["items"][0]["have"] is True and g["location"] == "freezer"
