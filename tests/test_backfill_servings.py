"""Tests for scripts/backfill_servings.py (servings estimation)."""

import importlib

from lib.recipe_parser import parse_recipe_file

backfill_servings = importlib.import_module("scripts.backfill_servings")


def _write(recipes_dir, name, fm_lines):
    (recipes_dir / f"{name}.md").write_text(
        "---\n" + "".join(f"{l}\n" for l in fm_lines) + "---\n\n# " + name + "\n")


class TestEstimateServings:
    def test_anchor_by_dish_type(self):
        est, anchor = backfill_servings.estimate_servings(
            {"dish_type": "main", "nutrition_calories": 2400})
        assert anchor == 600
        assert est == 4  # 2400 / 600

    def test_default_anchor_when_no_dish_type(self):
        est, anchor = backfill_servings.estimate_servings({"nutrition_calories": 1500})
        assert anchor == backfill_servings.DEFAULT_ANCHOR_KCAL
        assert est == 3  # 1500 / 500

    def test_clamps_low_and_high(self):
        assert backfill_servings.estimate_servings(
            {"dish_type": "main", "nutrition_calories": 100})[0] == 1
        assert backfill_servings.estimate_servings(
            {"dish_type": "main", "nutrition_calories": 90000})[0] == 12

    def test_no_calories_returns_zero(self):
        assert backfill_servings.estimate_servings({"dish_type": "main"})[0] == 0


class TestPlanBackfill:
    def test_selects_only_missing_servings(self, tmp_path):
        r = tmp_path / "Recipes"; r.mkdir()
        _write(r, "Has Servings", ['title: "Has Servings"', "servings: 4",
                                    "nutrition_calories: 500"])
        _write(r, "Big Batch", ['title: "Big Batch"', "dish_type: main",
                                 "nutrition_calories: 2400"])
        _write(r, "No Cals", ['title: "No Cals"'])
        rows = backfill_servings.plan_backfill(r)
        by_name = {row["name"]: row for row in rows}
        assert "Has Servings" not in by_name          # already has servings
        assert by_name["Big Batch"]["servings"] == 4
        assert by_name["Big Batch"]["status"] == "estimated"
        assert by_name["No Cals"]["status"] == "needs-nutrition-first"


class TestApplyRow:
    def test_writes_flagged_servings_and_backs_up(self, tmp_path):
        r = tmp_path / "Recipes"; r.mkdir()
        _write(r, "Big Batch", ['title: "Big Batch"', "dish_type: main",
                                 "nutrition_calories: 2400"])
        row = next(x for x in backfill_servings.plan_backfill(r) if x["name"] == "Big Batch")
        backfill_servings.apply_row(row)

        fm = parse_recipe_file((r / "Big Batch.md").read_text())["frontmatter"]
        assert int(fm["servings"]) == 4
        assert str(fm["servings_inferred"]).lower() == "true"
        assert str(fm["servings_needs_review"]).lower() == "true"
        assert fm["title"] == "Big Batch"  # untouched
        assert list((r / ".history").glob("*")) != []  # backup written


class TestMainDryRun:
    def test_dry_run_writes_nothing(self, tmp_path, capsys):
        r = tmp_path / "Recipes"; r.mkdir()
        _write(r, "Big Batch", ['title: "Big Batch"', "dish_type: main",
                                 "nutrition_calories: 2400"])
        rc = backfill_servings.main(["--recipes-dir", str(r)])
        assert rc == 0
        assert "DRY RUN" in capsys.readouterr().out
        fm = parse_recipe_file((r / "Big Batch.md").read_text())["frontmatter"]
        assert fm.get("servings") is None  # nothing written
