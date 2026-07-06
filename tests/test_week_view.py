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
    """A week the ledger never owned (no rows, no plan file) is left alone —
    no file is created."""
    week_view.write_week_markdown("2026-W20")
    assert not (tmp_vault / "Meal Plans" / "2026-W20.md").exists()


def test_write_week_markdown_writes_empty_skeleton_when_ledger_empties(tmp_db, tmp_vault):
    """When the plan file exists but the ledger just emptied (last cook
    deleted), the file becomes the clean empty skeleton — stale cards and
    [[links]] must not linger (the link-scan grocery fallback would see
    phantom recipes)."""
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(parents=True)
    stale = plans / "2026-W28.md"
    stale.write_text(
        "# Meal Plan - Week 28\n\n## Monday (Jul 6)\n### Dinner\n"
        "[[Chili]] x2\n### Notes\n", encoding="utf-8")
    week_view.write_week_markdown("2026-W28")
    text = stale.read_text(encoding="utf-8")
    assert "[[Chili]]" not in text
    assert "## Monday" in text and "### Dinner" in text


def test_import_legacy_week_creates_cooks_from_links(tmp_db, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True)
    (recipes / "Chili.md").write_text(
        "---\nservings: 4\n---\n\nChili.\n", encoding="utf-8")
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(parents=True)
    (plans / "2026-W28.md").write_text(
        "## Monday (Jul 6)\n### Breakfast\n### Lunch\n### Snack\n"
        "### Dinner\n[[Chili]] x2\n### Notes\n", encoding="utf-8")
    imported = week_view.import_legacy_week("2026-W28")
    assert len(imported) == 1
    cooks = sl.cooks_for_week("2026-W28")
    assert cooks[0]["recipe"] == "Chili"
    assert cooks[0]["scale"] == 2.0
    assert cooks[0]["servings_produced"] == 8.0
    assert cooks[0]["unassigned"] == 0.0


def test_import_legacy_week_skips_leftover_lines(tmp_db, tmp_vault):
    """'(leftover xN)' lines are display text rendered from slot placements —
    they must never become cooks."""
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(parents=True)
    (plans / "2026-W28.md").write_text(
        "## Monday (Jul 6)\n### Breakfast\n### Lunch\n### Snack\n"
        "### Dinner\n[[Chili]] (leftover x1)\n### Notes\n", encoding="utf-8")
    imported = week_view.import_legacy_week("2026-W28")
    assert imported == []
    assert sl.cooks_for_week("2026-W28") == []
