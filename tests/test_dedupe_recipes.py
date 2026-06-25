"""Tests for scripts/dedupe_recipes.py duplicate detection + keeper selection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dedupe_recipes import dedupe, find_duplicate_groups  # noqa: E402

HOSTNAME = "http://chases-mac-mini.taila69703.ts.net:5001"
RAW_IP = "http://100.111.6.10:5001"


def _write(d: Path, name: str, *, url="", host=HOSTNAME, calories=None):
    fm = [f'source_url: "{url}"'] if url else []
    if calories is not None:
        fm.append(f"nutrition_calories: {calories}")
    body = f"---\n" + "\n".join(fm) + "\n---\n\n> action {h}/reprocess?file=x.md\n".replace("{h}", host)
    (d / name).write_text(body, encoding="utf-8")
    return d / name


def test_groups_by_source_url(tmp_path):
    _write(tmp_path, "A.md", url="https://x.com/r")
    _write(tmp_path, "A 2.md", url="https://x.com/r")
    _write(tmp_path, "B.md", url="https://x.com/other")
    groups = find_duplicate_groups(tmp_path)
    assert len(groups) == 1
    assert {p.name for p in groups[0]} == {"A.md", "A 2.md"}


def test_conflict_copy_without_url_is_grouped(tmp_path):
    _write(tmp_path, "Soup.md")
    _write(tmp_path, "Soup 2.md")
    groups = find_duplicate_groups(tmp_path)
    assert len(groups) == 1


def test_keeper_prefers_hostname_over_raw_ip(tmp_path):
    _write(tmp_path, "A.md", url="u", host=HOSTNAME)
    _write(tmp_path, "A 2.md", url="u", host=RAW_IP)
    moves = dedupe(tmp_path, tmp_path / "_Archive", apply=True)
    assert len(moves) == 1
    loser, keeper = moves[0]
    assert loser.name == "A 2.md" and keeper.name == "A.md"
    # loser moved out of the recipes dir, keeper stays
    assert not (tmp_path / "A 2.md").exists()
    assert (tmp_path / "A.md").exists()
    assert (tmp_path / "_Archive" / "custom-format-dupes" / "A 2.md").exists()


def test_keeper_prefers_more_complete_nutrition(tmp_path):
    # both hostname, but the conflict copy has nutrition and canonical does not
    _write(tmp_path, "A.md", url="u", calories=None)
    _write(tmp_path, "A 2.md", url="u", calories=350)
    moves = dedupe(tmp_path, tmp_path / "_Archive", apply=False)
    loser, keeper = moves[0]
    assert keeper.name == "A 2.md"  # nutrition completeness outranks name


def test_dry_run_moves_nothing(tmp_path):
    _write(tmp_path, "A.md", url="u")
    _write(tmp_path, "A 2.md", url="u")
    dedupe(tmp_path, tmp_path / "_Archive", apply=False)
    assert (tmp_path / "A.md").exists() and (tmp_path / "A 2.md").exists()
    assert not (tmp_path / "_Archive").exists()
