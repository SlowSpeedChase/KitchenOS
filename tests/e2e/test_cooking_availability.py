import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_planner_shows_calendar_statuses_and_unknown(page, live_server):
    statuses = ["good", "possible", "busy", "unknown", "good", "possible", "busy"]
    page.route(
        "**/api/cooking-availability/*",
        lambda route: route.fulfill(
            json={
                "days": {
                    f"2026-09-{day:02d}": status
                    for day, status in zip(range(7, 14), statuses)
                },
                "fresh": True,
            }
        ),
    )
    page.goto(live_server.url("/meal-planner?week=2026-W37"))
    labels = page.locator(".cooking-opportunity")
    expect(labels).to_have_count(7)
    expect(labels.nth(0)).to_have_text("Good cooking day")
    expect(labels.nth(1)).to_have_text("Possible · flexible blocks")
    expect(labels.nth(2)).to_have_text("Busy · keep food easy")
    expect(labels.nth(3)).to_have_text("Availability unknown")
    page.unroute("**/api/cooking-availability/*")
    page.route(
        "**/api/cooking-availability/*",
        lambda route: route.fulfill(status=503, json={}),
    )
    page.evaluate("loadCookingAvailability(currentWeek, boardLoadGen)")
    expect(labels.nth(0)).to_have_text("Availability unknown")
