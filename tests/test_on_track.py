"""The "am I on track" view — built from what happened, not what was intended.

The honesty constraint drives these tests. This note exists to answer a
genuinely emotional question, and a dashboard that flatters by counting
*planned* meals rather than *cooked* ones would be worse than no dashboard: it
would report progress that did not occur.

So: every number here comes from the serving ledger, un-judged cooks are never
counted as good or bad, and an empty history says so plainly instead of
rendering encouraging zeros.
"""
import pytest

from lib import on_track, serving_ledger as sl


@pytest.fixture
def recipes(tmp_vault):
    d = tmp_vault / "Recipes"
    d.mkdir(parents=True)
    return d


def _recipe(recipes, name, **fit):
    lines = [f"{k}: {v}" for k, v in fit.items()]
    body = "\n".join(["---", f"title: {name}", *lines, "---", "", f"# {name}", ""])
    (recipes / f"{name}.md").write_text(body, encoding="utf-8")


def _cook(recipe, week="2026-W28", date="2026-07-07", produced=2):
    return sl.create_cook(recipe=recipe, week=week, servings_produced=produced,
                          date=date, meal="dinner")


# --- summarising ----------------------------------------------------------

def test_empty_history_is_reported_as_empty(tmp_db, tmp_vault, recipes):
    assert on_track.summarize(since="2026-01-01")["cooks"] == 0


def test_counts_only_cooks_that_happened(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Chili")
    _cook("Chili")
    assert on_track.summarize(since="2026-01-01")["cooks"] == 1


def test_ignores_cooks_before_the_window(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Chili")
    _cook("Chili", date="2025-01-01", week="2025-W01")
    assert on_track.summarize(since="2026-01-01")["cooks"] == 0


def test_counts_heart_and_steady_leaning_from_the_recipe_tags(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Lentils", fit_heart="true", fit_steady="true")
    _recipe(recipes, "Brownies", fit_heart="false", fit_steady="false")
    _cook("Lentils")
    _cook("Brownies")
    s = on_track.summarize(since="2026-01-01")
    assert s["heart_cooks"] == 1
    assert s["steady_cooks"] == 1


def test_untagged_recipes_are_not_counted_as_unhealthy(tmp_db, tmp_vault, recipes):
    """Absence of a tag is missing data, not a failing grade."""
    _recipe(recipes, "Mystery")  # no fit_* fields at all
    _cook("Mystery")
    s = on_track.summarize(since="2026-01-01")
    assert s["heart_cooks"] == 0
    assert s["untagged_cooks"] == 1


def test_unjudged_cooks_are_excluded_from_the_verdict_tally(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Chili")
    a, b = _cook("Chili"), _cook("Chili")
    sl.update_cook(a["id"], make_again=True)
    # b deliberately unjudged
    s = on_track.summarize(since="2026-01-01")
    assert s["verdicts"] == 1
    assert s["make_again"] == 1


def test_surfaces_the_craving_lanes_actually_cooked(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Brownies", fit_craving_lane="sweet")
    _recipe(recipes, "Chips", fit_craving_lane="salty")
    _cook("Brownies")
    _cook("Brownies")
    _cook("Chips")
    lanes = on_track.summarize(since="2026-01-01")["lanes"]
    assert lanes["sweet"] == 2 and lanes["salty"] == 1


def test_collects_cook_notes_as_the_useful_residue(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Chili")
    cook = _cook("Chili")
    sl.update_cook(cook["id"], cook_note="too much cleanup")
    notes = on_track.summarize(since="2026-01-01")["notes"]
    assert ("Chili", "too much cleanup") in [(n["recipe"], n["note"]) for n in notes]


# --- library gaps ---------------------------------------------------------

def test_reports_thin_buffer_coverage(tmp_db, tmp_vault, recipes):
    """The note calls the afternoon snack the keystone — a thin shelf matters."""
    _recipe(recipes, "Chili", fit_buffer_candidate="false")
    gaps = on_track.library_gaps()
    assert gaps["buffer_candidates"] == 0


def test_counts_buffer_candidates(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Chia Pudding", fit_buffer_candidate="true")
    assert on_track.library_gaps()["buffer_candidates"] == 1


# --- rendering ------------------------------------------------------------

def test_note_carries_the_do_not_edit_banner(tmp_db, tmp_vault, recipes):
    md = on_track.render_markdown(on_track.summarize(since="2026-01-01"),
                                  on_track.library_gaps())
    assert "Generated" in md and "overwritten" in md


def test_empty_history_renders_honestly(tmp_db, tmp_vault, recipes):
    """No cooks must not render as an encouraging wall of zeros."""
    md = on_track.render_markdown(on_track.summarize(since="2026-01-01"),
                                  on_track.library_gaps())
    assert "nothing logged" in md.lower()


def test_write_note_lands_in_dashboards(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Chili")
    _cook("Chili")
    path = on_track.write_note()
    assert path.exists()
    assert path.parent.name == "Dashboards"


def test_singular_counts_read_naturally(tmp_db, tmp_vault, recipes):
    """This note is read by a person; "1 cooks" undermines its credibility."""
    _recipe(recipes, "Chili")
    _cook("Chili", produced=1)
    md = on_track.render_markdown(on_track.summarize(since="2026-01-01"),
                                  on_track.library_gaps())
    summary_line = next(l for l in md.splitlines() if "across" in l)
    assert "**1 cook**" in summary_line
    assert "1 recipe " in summary_line and "1 recipes" not in summary_line


def test_plural_counts_still_pluralize(tmp_db, tmp_vault, recipes):
    _recipe(recipes, "Chili")
    _cook("Chili")
    _cook("Chili", date="2026-07-08")
    md = on_track.render_markdown(on_track.summarize(since="2026-01-01"),
                                  on_track.library_gaps())
    assert "2 cooks" in md
