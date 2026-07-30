"""Tests for scripts/backfill_servings.py (servings estimation)."""

import importlib

import pytest

from lib.recipe_parser import parse_recipe_file

backfill_servings = importlib.import_module("scripts.backfill_servings")


def _write(recipes_dir, name, fm_lines):
    (recipes_dir / f"{name}.md").write_text(
        "---\n" + "".join(f"{l}\n" for l in fm_lines) + "---\n\n# " + name + "\n")


def _write_with_body(recipes_dir, name, fm_lines, body):
    (recipes_dir / f"{name}.md").write_text(
        "---\n" + "".join(f"{l}\n" for l in fm_lines) + "---\n\n# " + name
        + "\n\n" + body + "\n")


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


class TestStatedYield:
    """A yield the recipe states is a measurement, so it outranks the anchor."""

    @pytest.mark.parametrize("text,expected", [
        ("Serves 4", 4),
        ("serves about 6", 6),
        ("Feeds 8 hungry people", 8),
        ("Makes: 12 biscuits", 12),
        ("Yields 24 cookies", 24),
        ("Makes 4 servings", 4),
        ("Cut into 6 servings", 6),
        ("Divided into 8 servings", 8),
        # Our OWN generated nutrition footer. A bare "N serving(s)" pattern
        # scraped `servings: 1` off this and wrote it unflagged as fact — the
        # exact batch-as-one-serving corruption the tool repairs. 3/3 real
        # vault recipes hit this. Never match machine provenance.
        ("| 814 | 48g | 152g | 5g |\n\n*Serving size: 1 serving • Source: Fdc "
         "• Confidence: 0.84*\n\n## Instructions", None),
        ("*Serving size: 1 serving • Source: Ai*", None),
        ("Nutrition per 1 serving", None),
        # Measures are batch sizes, not yields — these must NOT be read as counts.
        ("This makes 2 cups of sauce", None),
        ("Yield: 12 oz of dough", None),
        ("Makes 500 g of granola", None),
        # Out of plausible bounds, or simply absent.
        ("Serves 0", None),
        ("Makes 900 tiny candies", None),
        ("A quiet recipe that never says how much it makes", None),
        ("", None),
        (None, None),
    ])
    def test_reads_a_stated_yield(self, text, expected):
        assert backfill_servings.servings_from_body(text) == expected

    def test_stated_count_beats_the_kcal_anchor_and_is_not_clamped(self, tmp_path):
        r = tmp_path / "Recipes"; r.mkdir()
        _write_with_body(r, "Cookie Batch",
                         ['title: "Cookie Batch"', "dish_type: dessert",
                          "nutrition_calories: 2400"],
                         "Makes 24 cookies.")
        row = next(x for x in backfill_servings.plan_backfill(r)
                   if x["name"] == "Cookie Batch")
        # The anchor would have estimated 2400/350 ≈ 7, and SERVINGS_MAX would
        # have capped a stated 24 at 12. Neither may happen here.
        assert row["servings"] == 24
        assert row["status"] == "stated"
        assert row["per_serving_kcal"] == 100

    def test_stated_count_is_written_as_fact_with_no_review_flag(self, tmp_path):
        r = tmp_path / "Recipes"; r.mkdir()
        _write_with_body(r, "Family Stew",
                         ['title: "Family Stew"', "dish_type: main",
                          "nutrition_calories: 2400"],
                         "Serves 6 with bread on the side.")
        row = next(x for x in backfill_servings.plan_backfill(r)
                   if x["name"] == "Family Stew")
        backfill_servings.apply_row(row)

        fm = parse_recipe_file((r / "Family Stew.md").read_text())["frontmatter"]
        assert int(fm["servings"]) == 6
        assert "servings_inferred" not in fm
        assert "servings_needs_review" not in fm

    def test_stated_count_clears_a_stale_inference_flag(self, tmp_path):
        """An earlier estimate's flags must not outlive the estimate."""
        r = tmp_path / "Recipes"; r.mkdir()
        _write_with_body(r, "Reclaimed Soup",
                         ['title: "Reclaimed Soup"', "dish_type: soup",
                          "nutrition_calories: 1200",
                          "servings_inferred: true",
                          "servings_needs_review: true"],
                         "Serves 5.")
        row = next(x for x in backfill_servings.plan_backfill(r)
                   if x["name"] == "Reclaimed Soup")
        assert row["status"] == "stated"
        backfill_servings.apply_row(row)

        fm = parse_recipe_file((r / "Reclaimed Soup.md").read_text())["frontmatter"]
        assert int(fm["servings"]) == 5
        assert "servings_inferred" not in fm
        assert "servings_needs_review" not in fm

    def test_estimated_rows_still_get_flagged(self, tmp_path):
        """The graft must not weaken the honesty of an actual estimate."""
        r = tmp_path / "Recipes"; r.mkdir()
        _write_with_body(r, "Mystery Bake",
                         ['title: "Mystery Bake"', "dish_type: main",
                          "nutrition_calories: 2400"],
                         "No stated yield anywhere in here.")
        row = next(x for x in backfill_servings.plan_backfill(r)
                   if x["name"] == "Mystery Bake")
        assert row["status"] == "estimated"
        backfill_servings.apply_row(row)

        fm = parse_recipe_file((r / "Mystery Bake.md").read_text())["frontmatter"]
        assert int(fm["servings"]) == 4
        assert str(fm["servings_needs_review"]).lower() == "true"


class TestPerServingKcal:
    def test_none_when_calories_are_unusable(self):
        assert backfill_servings._per_serving_kcal("not a number", 4) is None
        assert backfill_servings._per_serving_kcal(None, 4) is None

    def test_none_when_servings_is_zero(self):
        assert backfill_servings._per_serving_kcal(2400, 0) is None


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
