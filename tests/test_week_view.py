from lib import serving_ledger as sl
from lib import week_view
from lib.meal_plan_parser import parse_meal_plan, fmt_mult


def test_fmt_mult():
    assert fmt_mult(2.0) == "2"
    assert fmt_mult(1.5) == "1.5"
    assert fmt_mult(1.0) == "1"


def test_parser_accepts_fractional_multiplier():
    section = "## Monday (Jul 6)\n### Dinner\n[[Chili]] x1.5\n### Notes\n"
    days = parse_meal_plan(section, 2026, 28)
    assert days[0]["dinner"].servings == 1.5


def test_render_week_markdown_anchor_and_leftover(tmp_db, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True)
    cook = sl.create_cook(recipe="Chili", week="2026-W28", scale=1.5,
                          servings_produced=6.0,
                          date="2026-07-07", meal="dinner")
    sl.add_placement(cook["id"], "slot", 1.0, date="2026-07-08", meal="lunch")
    sl.add_placement(cook["id"], "freezer", 2.0)
    md = week_view.render_week_markdown("2026-W28", recipes)
    assert "[[Chili]] x1.5" in md                      # anchor, Tuesday dinner
    assert "[[Chili]] (leftover x1)" in md             # Wednesday lunch
    assert "Freezer: 2" in md
    # Round-trips through the legacy parser (calendar sync depends on this)
    days = parse_meal_plan(md, 2026, 28)
    assert days[1]["dinner"].name == "Chili"           # Tue = index 1


def test_write_week_markdown_skips_ledgerless_weeks(tmp_db, tmp_vault):
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(parents=True)
    legacy = plans / "2026-W20.md"
    legacy.write_text("# hand-made\n", encoding="utf-8")
    week_view.write_week_markdown("2026-W20")
    assert legacy.read_text(encoding="utf-8") == "# hand-made\n"
