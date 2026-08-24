from pathlib import Path

import pytest

from lib.safe_paths import contained_markdown, parse_iso_week, shopping_list_path


def test_contained_markdown_accepts_nested_markdown(tmp_path):
    assert contained_markdown(tmp_path, "Dinner/Stew.md") == (tmp_path / "Dinner/Stew.md").resolve()


@pytest.mark.parametrize("value", ["../outside.md", "/tmp/outside.md", "x.txt", "bad\x00.md"])
def test_contained_markdown_rejects_escape_and_wrong_types(tmp_path, value):
    with pytest.raises(ValueError):
        contained_markdown(tmp_path, value)


def test_contained_markdown_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        contained_markdown(tmp_path, "link/escape.md")


@pytest.mark.parametrize("value", ["2026-W00", "2026-W54", "2026-W1", "../outside", "x2026-W01"])
def test_parse_iso_week_rejects_noncanonical_or_impossible_weeks(value):
    with pytest.raises(ValueError):
        parse_iso_week(value)


def test_parse_iso_week_returns_canonical_week():
    assert parse_iso_week("2026-W35") == "2026-W35"


def test_shopping_list_path_is_constructed_from_validated_week(tmp_path):
    assert shopping_list_path(tmp_path, "2026-W35") == (tmp_path / "2026-W35.md").resolve()
