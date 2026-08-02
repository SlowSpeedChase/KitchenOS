"""Tests for the silent-failure assertions.

These exist because /system-health reported "ok" through ten simultaneous
silent failures — it checked whether things were running, not whether they
were working.
"""

import os
from pathlib import Path

import pytest

from lib import health_assertions as ha


def _run(total, succeeded):
    return {"total": total, "succeeded": succeeded, "failed": total - succeeded}


class TestCaptureQueue:
    def test_draining_queue_is_ok(self):
        c = ha.check_capture_queue([_run(3, 3), _run(2, 2), _run(1, 1)])
        assert c["status"] == ha.OK

    def test_repeated_zero_capture_runs_are_failing(self):
        """719 of 725 runs captured nothing and nothing said so."""
        c = ha.check_capture_queue([_run(7, 0), _run(7, 0), _run(7, 0)])
        assert c["status"] == ha.FAILING
        assert "21" in c["detail"]          # 3 runs x 7 attempts
        assert c["consequence"]
        assert c["fix"]

    def test_an_idle_queue_is_not_a_jam(self):
        """Nothing to process is not the same as failing to process."""
        c = ha.check_capture_queue([_run(0, 0), _run(0, 0), _run(0, 0)])
        assert c["status"] == ha.OK

    def test_one_bad_run_is_not_yet_a_jam(self):
        c = ha.check_capture_queue([_run(1, 0), _run(2, 2), _run(2, 2)])
        assert c["status"] == ha.OK

    def test_no_logs_is_unknown_not_ok(self):
        assert ha.check_capture_queue([])["status"] == ha.UNKNOWN


class TestInstagramCookies:
    def test_configured_is_ok(self, monkeypatch):
        monkeypatch.setenv("INSTAGRAM_COOKIES_FROM_BROWSER", "safari")
        assert ha.check_instagram_cookies([])["status"] == ha.OK

    def test_unconfigured_with_recent_failures_is_failing(self, monkeypatch):
        monkeypatch.delenv("INSTAGRAM_COOKIES_FROM_BROWSER", raising=False)
        monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)
        c = ha.check_instagram_cookies(
            [{"error": "Could not fetch Instagram Reel metadata"}])
        assert c["status"] == ha.FAILING
        assert "instagram" in c["fix"].lower()

    def test_unconfigured_without_attempts_is_only_unknown(self, monkeypatch):
        monkeypatch.delenv("INSTAGRAM_COOKIES_FROM_BROWSER", raising=False)
        monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)
        assert ha.check_instagram_cookies([])["status"] == ha.UNKNOWN


class TestPrepSidecar:
    def test_fresh_sidecar_is_ok(self, tmp_path):
        (tmp_path / "2026-W31.md").write_text("plan", encoding="utf-8")
        sidecar = tmp_path / "2026-W31.tasks.json"
        sidecar.write_text("{}", encoding="utf-8")
        os.utime(sidecar, (10_000_000, 10_000_000))
        os.utime(tmp_path / "2026-W31.md", (9_000_000, 9_000_000))
        assert ha.check_prep_sidecar(tmp_path, "2026-W31")["status"] == ha.OK

    def test_stale_sidecar_is_failing(self, tmp_path):
        plan = tmp_path / "2026-W31.md"
        plan.write_text("plan", encoding="utf-8")
        sidecar = tmp_path / "2026-W31.tasks.json"
        sidecar.write_text("{}", encoding="utf-8")
        os.utime(sidecar, (9_000_000, 9_000_000))
        os.utime(plan, (10_000_000, 10_000_000))
        c = ha.check_prep_sidecar(tmp_path, "2026-W31")
        assert c["status"] == ha.FAILING
        assert "blank tab" in c["consequence"]

    def test_missing_plan_is_unknown(self, tmp_path):
        assert ha.check_prep_sidecar(tmp_path, "2026-W31")["status"] == ha.UNKNOWN


class TestNutritionPlausibility:
    def _recipe(self, d, name, kcal, protein):
        (d / f"{name}.md").write_text(
            f'---\ntitle: "{name}"\nnutrition_calories: {kcal}\n'
            f"nutrition_protein: {protein}\n---\n\n# {name}\n", encoding="utf-8")

    def test_clean_corpus_is_ok(self, tmp_path):
        self._recipe(tmp_path, "Chili", 500, 30)
        assert ha.check_nutrition_plausibility(tmp_path)["status"] == ha.OK

    def test_implausible_recipes_are_counted(self, tmp_path):
        self._recipe(tmp_path, "Chili", 500, 30)
        self._recipe(tmp_path, "Smoothie", 1440, 244)
        c = ha.check_nutrition_plausibility(tmp_path)
        assert c["status"] == ha.FAILING
        assert "1 of 2" in c["detail"]

    def test_empty_corpus_is_unknown(self, tmp_path):
        assert ha.check_nutrition_plausibility(tmp_path)["status"] == ha.UNKNOWN


class TestContract:
    """Every check must be actionable, and none may raise."""

    ALL = [
        lambda: ha.check_capture_queue([_run(7, 0), _run(7, 0), _run(7, 0)]),
        lambda: ha.check_instagram_cookies([{"error": "instagram"}]),
        lambda: ha.check_prep_sidecar(Path("/nonexistent"), "2026-W31"),
        lambda: ha.check_nutrition_plausibility(Path("/nonexistent")),
    ]

    @pytest.mark.parametrize("make", ALL)
    def test_shape_is_complete(self, make):
        c = make()
        assert set(c) == {"id", "label", "status", "detail", "consequence", "fix"}
        assert c["status"] in (ha.OK, ha.FAILING, ha.UNKNOWN)
        assert c["label"] and c["detail"]

    @pytest.mark.parametrize("make", ALL)
    def test_a_failing_check_says_what_breaks(self, make):
        c = make()
        if c["status"] == ha.FAILING:
            assert c["consequence"], f"{c['id']} fails without naming a consequence"
            assert c["fix"], f"{c['id']} fails without naming a fix"

    def test_a_probe_that_raises_becomes_unknown_not_a_500(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ha, "check_inventory_consumption",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        out = ha.run_all(recipes_dir=tmp_path, meal_plans_dir=tmp_path,
                         week="2026-W31", run_logs=[], failure_logs=[])
        assert any(c["status"] == ha.UNKNOWN for c in out["checks"])
        assert out["ok"] + out["failing"] + out["unknown"] == len(out["checks"])


class TestShareSheetCapture:
    """Reads batch-extract's own log, because TCC grants are per-executable.

    Probing the Reminders store from inside the API server answers a question
    about the API server. The job that fails is batch-extract.
    """

    def test_denials_in_recent_runs_are_failing(self, tmp_path):
        log = tmp_path / "batch_extract.log"
        log.write_text(f"starting\n{ha.FDA_DENIAL_MARKER} blah\ndone\n",
                       encoding="utf-8")
        c = ha.check_share_sheet_capture(log)
        assert c["status"] == ha.FAILING
        assert "shim" in c["fix"]

    def test_clean_log_is_ok(self, tmp_path):
        log = tmp_path / "batch_extract.log"
        log.write_text("starting\nRecovered 3 share-sheet URL(s)\ndone\n",
                       encoding="utf-8")
        assert ha.check_share_sheet_capture(log)["status"] == ha.OK

    def test_old_denials_scroll_out_of_the_window(self, tmp_path):
        """A grant that was fixed must stop being reported as broken."""
        log = tmp_path / "batch_extract.log"
        log.write_text(f"{ha.FDA_DENIAL_MARKER}\n" + "ok\n" * 1000,
                       encoding="utf-8")
        assert ha.check_share_sheet_capture(log)["status"] == ha.OK

    def test_missing_log_is_unknown(self, tmp_path):
        assert ha.check_share_sheet_capture(
            tmp_path / "nope.log")["status"] == ha.UNKNOWN
