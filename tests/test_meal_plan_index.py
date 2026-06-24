"""Tests for the Meal Plans Index generator."""

from datetime import date

from lib.meal_plan_index import (
    build_index_markdown,
    regenerate_index,
    INDEX_FILENAME,
)


class TestBuildIndexMarkdown:
    def test_rows_have_week_dates_and_link(self):
        md = build_index_markdown(["2026-W04"], today=date(2026, 1, 1))
        assert "# Meal Plans Index" in md
        assert "| Week 04 | Jan 19 - Jan 25, 2026 | [[2026-W04]] |" in md

    def test_sorted_newest_first(self):
        md = build_index_markdown(
            ["2026-W04", "2026-W26", "2026-W10"], today=date(2026, 1, 1)
        )
        rows = [l for l in md.splitlines() if l.startswith("| Week ")]
        # header row is "| Week | Dates | Plan |"; data rows start "| Week NN"
        data = [r for r in rows if r.startswith("| Week 0") or r.startswith("| Week 1") or r.startswith("| Week 2")]
        assert data[0].startswith("| Week 26")
        assert data[-1].startswith("| Week 04")

    def test_current_week_marked(self):
        # Jan 21 2026 falls inside ISO week 4.
        md = build_index_markdown(["2026-W04", "2026-W26"], today=date(2026, 1, 21))
        wk4 = next(l for l in md.splitlines() if l.startswith("| Week 04"))
        wk26 = next(l for l in md.splitlines() if l.startswith("| Week 26"))
        assert "(this week)" in wk4
        assert "(this week)" not in wk26

    def test_dedupes(self):
        md = build_index_markdown(["2026-W04", "2026-W04"], today=date(2026, 1, 1))
        assert md.count("[[2026-W04]]") == 1


class TestRegenerateIndex:
    def test_writes_index_from_week_files(self, tmp_path):
        (tmp_path / "2026-W04.md").write_text("# plan", encoding="utf-8")
        (tmp_path / "2026-W26.md").write_text("# plan", encoding="utf-8")

        index_path = regenerate_index(tmp_path, today=date(2026, 1, 1))

        assert index_path == tmp_path / INDEX_FILENAME
        content = index_path.read_text(encoding="utf-8")
        assert "[[2026-W04]]" in content
        assert "[[2026-W26]]" in content

    def test_ignores_non_week_files(self, tmp_path):
        (tmp_path / "2026-W04.md").write_text("# plan", encoding="utf-8")
        (tmp_path / "Notes.md").write_text("# notes", encoding="utf-8")
        (tmp_path / "2026-W09.tasks.json").write_text("{}", encoding="utf-8")

        content = regenerate_index(tmp_path, today=date(2026, 1, 1)).read_text(encoding="utf-8")
        assert "[[2026-W04]]" in content
        assert "Notes" not in content
        assert "tasks" not in content

    def test_index_note_excluded_from_itself(self, tmp_path):
        (tmp_path / "2026-W04.md").write_text("# plan", encoding="utf-8")
        # First pass creates the index; a second pass must not list the index note.
        regenerate_index(tmp_path, today=date(2026, 1, 1))
        content = regenerate_index(tmp_path, today=date(2026, 1, 1)).read_text(encoding="utf-8")
        assert "[[Meal Plans Index]]" not in content
        assert content.count("[[2026-W04]]") == 1

    def test_missing_dir_returns_none(self, tmp_path):
        assert regenerate_index(tmp_path / "nope", today=date(2026, 1, 1)) is None

    def test_no_week_files_returns_none(self, tmp_path):
        (tmp_path / "README.md").write_text("hi", encoding="utf-8")
        assert regenerate_index(tmp_path, today=date(2026, 1, 1)) is None
