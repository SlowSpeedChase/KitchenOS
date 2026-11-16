"""The week's nutrition as a web page (/nutrition) and the add-recipe page."""

import pytest

from lib import nutrition_week as nw

T = {"calories": 2200, "protein": 190, "carbs": 220, "fat": 70}


def _day(name, macros=None, **extra):
    return {"day": name, "date": "2026-08-03", "slots": {}, "macros": macros,
            "incomplete": False, **extra}


def _packet():
    return {"warnings": [], "days": [
        _day("Monday", {"calories": 2180, "protein": 184, "carbs": 210, "fat": 66}),
        _day("Tuesday", {"calories": 1400, "protein": 90, "carbs": 150, "fat": 95},
             excluded=["Mystery <Stew>"]),
        _day("Wednesday"),
    ]}


class TestMacroState:
    @pytest.mark.parametrize("value,expected", [
        (190, "on"), (172, "on"), (170, "under"), (208, "on"), (210, "over")])
    def test_ten_percent_band(self, value, expected):
        assert nw.macro_state(value, 190) == expected

    def test_no_target_is_never_a_miss(self):
        assert nw.macro_state(50, 0) == "on"


class TestWeekAverage:
    def test_ignores_unplanned_days(self):
        avg = nw.week_average(_packet()["days"])
        assert avg["calories"] == (2180 + 1400) / 2
        assert avg["protein"] == (184 + 90) / 2

    def test_none_when_nothing_is_planned(self):
        assert nw.week_average([_day("Monday")]) is None


class TestRender:
    def _html(self, packet=None):
        return nw.render_nutrition_week_html(
            "2026-W32", packet if packet is not None else _packet(), T,
            "https://ko.example", "2026-W31", "2026-W33")

    def test_each_day_against_target_with_a_word_not_only_a_colour(self):
        html = self._html()
        assert "184g" in html and "/ 190g" in html
        assert "on target" in html and "under" in html and "over" in html

    def test_names_what_was_left_out_and_escapes_it(self):
        html = self._html()
        assert "Not counted: Mystery &lt;Stew&gt;" in html
        assert "<Stew>" not in html

    def test_unplanned_day_is_not_shown_as_zero(self):
        assert "Nothing planned" in self._html()

    def test_week_nav_and_next_steps_keep_the_week(self):
        html = self._html()
        assert "https://ko.example/nutrition?week=2026-W31" in html
        assert "https://ko.example/nutrition?week=2026-W33" in html
        assert "https://ko.example/meal-planner?week=2026-W32" in html

    def test_empty_week_points_at_the_planner(self):
        html = self._html({"days": [_day("Monday")], "warnings": []})
        assert "Nothing is planned" in html
        assert "meal-planner?week=2026-W32" in html

    def test_missing_plan_file_renders_the_empty_state(self):
        html = nw.render_nutrition_week_html(
            "2026-W32", None, T, "", "2026-W31", "2026-W33")
        assert "Nothing is planned" in html


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("KITCHENOS_AUTH_MODE", "open")
    import api_server
    return api_server.app.test_client()


class TestRoutes:
    def test_nutrition_page_renders_for_a_week(self, client, monkeypatch):
        from lib import print_week
        monkeypatch.setattr(print_week, "build_week_packet",
                            lambda *a, **k: {**_packet(), "targets": T})
        response = client.get("/nutrition?week=2026-W32")
        assert response.status_code == 200
        assert "Nutrition this week" in response.text
        assert "184g" in response.text

    def test_nutrition_page_survives_a_week_with_no_plan(self, client, monkeypatch):
        from lib import print_week

        def missing(*_a, **_k):
            raise FileNotFoundError

        monkeypatch.setattr(print_week, "build_week_packet", missing)
        response = client.get("/nutrition?week=2026-W32")
        assert response.status_code == 200
        assert "Nothing is planned" in response.text

    def test_nutrition_page_rejects_a_bad_week(self, client):
        assert client.get("/nutrition?week=nope").status_code == 400

    def test_add_recipe_page_posts_to_extract(self, client):
        response = client.get("/add-recipe")
        assert response.status_code == 200
        assert "fetch('/extract'" in response.text
        assert 'type="url"' in response.text
