"""The freezer's read path and the one-tap way to fill it.

`POST /api/placements` has always accepted `destination: "freezer"`, so servings
could be banked — and then nothing could read them back. These cover the other
half: seeing the bank, and putting a cook's leftovers into it without hand-typing
a placement count.
"""
import pytest

from api_server import app
from lib import serving_ledger as sl


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def recipes(tmp_vault):
    """A recipes dir inside the isolated vault, with one priced recipe."""
    d = tmp_vault / "Recipes"
    d.mkdir(parents=True, exist_ok=True)
    (d / "Chili.md").write_text(
        "---\nservings: 6\nnutrition_calories: 500\nnutrition_protein: 40\n"
        "nutrition_carbs: 30\nnutrition_fat: 15\nnutrition_coverage: 1.0\n---\n",
        encoding="utf-8")
    return d


def _cook(**over):
    kw = dict(recipe="Chili", week="2026-W28", scale=1.0,
              servings_produced=6.0, date="2026-07-07", meal="dinner")
    kw.update(over)
    return sl.create_cook(**kw)


class TestReadingTheFreezer:
    def test_an_empty_freezer_returns_an_empty_tray(self, client, tmp_db, recipes):
        body = client.get("/api/freezer").get_json()
        assert body["freezer"] == []
        assert body["totals"]["servings"] == 0

    def test_banked_servings_show_up_priced(self, client, tmp_db, recipes):
        sl.add_placement(_cook()["id"], "freezer", 4.0)
        body = client.get("/api/freezer").get_json()
        row = body["freezer"][0]
        assert row["recipe"] == "Chili"
        assert row["servings"] == 4.0
        assert row["protein"] == 40

    def test_totals_answer_do_i_need_to_cook(self, client, tmp_db, recipes):
        sl.add_placement(_cook()["id"], "freezer", 4.0)
        totals = client.get("/api/freezer").get_json()["totals"]
        assert totals["servings"] == 4.0
        assert totals["protein"] == 160.0
        assert totals["calories"] == 2000.0

    def test_unpriced_servings_still_count_as_servings(self, client, tmp_db, recipes):
        """A recipe with no macros is still food you can eat tonight."""
        sl.add_placement(_cook(recipe="Mystery")["id"], "freezer", 2.0)
        totals = client.get("/api/freezer").get_json()["totals"]
        assert totals["servings"] == 2.0
        assert totals["protein"] == 0.0


class TestFreezeTheRest:
    def test_it_banks_whatever_was_left_unassigned(self, client, tmp_db, recipes):
        """6 produced, 1 auto-placed on the plan, 5 left over."""
        cook = _cook()
        assert cook["unassigned"] == 5.0
        resp = client.post(f"/api/cooks/{cook['id']}/freeze-rest")
        assert resp.status_code == 200
        assert resp.get_json()["unassigned"] == 0.0
        assert sl.freezer_summary(recipes)[0]["servings"] == 5.0

    def test_pressing_it_twice_is_not_an_error(self, client, tmp_db, recipes):
        """A double-tap on a phone must not 400 or double-bank."""
        cook = _cook()
        client.post(f"/api/cooks/{cook['id']}/freeze-rest")
        resp = client.post(f"/api/cooks/{cook['id']}/freeze-rest")
        assert resp.status_code == 200
        assert sl.freezer_summary(recipes)[0]["servings"] == 5.0

    def test_a_fully_placed_cook_is_a_no_op(self, client, tmp_db, recipes):
        cook = _cook(servings_produced=1.0)
        assert cook["unassigned"] == 0.0
        resp = client.post(f"/api/cooks/{cook['id']}/freeze-rest")
        assert resp.status_code == 200
        assert sl.freezer_summary(recipes) == []

    def test_an_unknown_cook_is_a_404(self, client, tmp_db, recipes):
        assert client.post("/api/cooks/9999/freeze-rest").status_code == 404

    def test_it_never_overplaces(self, client, tmp_db, recipes):
        """The ledger invariant holds however the button is pressed."""
        cook = _cook()
        client.post(f"/api/cooks/{cook['id']}/freeze-rest")
        placed = sum(p["count"] for p in sl.get_cook(cook["id"])["placements"])
        assert placed <= cook["servings_produced"]
