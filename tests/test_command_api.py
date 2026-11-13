import json
from pathlib import Path

import pytest

import api_server
from api_server import app
from lib import inventory_db
from lib.command import context as command_context
from tests.gold.kitchen import TODAY

CASES = json.loads((Path(__file__).parent / "gold" / "commands.json").read_text())


@pytest.fixture
def client(monkeypatch, gold_kitchen):
    monkeypatch.setattr(api_server, "_command_today", lambda: TODAY)
    monkeypatch.setenv("KITCHENOS_NO_LLM", "1")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _dump():
    conn = inventory_db.connect()
    try:
        state = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                 for t in ("cooks", "placements")}
    finally:
        conn.close()
    state["inventory"] = inventory_db.fetch_inventory_rows()
    return state


def _say(client, say, context):
    return client.post("/api/command", json={"text": say, "context": context}).get_json()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_gold_happy_path(client, case):
    """Every gold command: right outcome, and Undo leaves the database as it was."""
    before = _dump()
    body = _say(client, case["say"], case["context"])
    expect = case["expect"]
    assert body["status"] == expect["status"], body

    if expect["status"] == "ask":
        assert [o["id"] for o in body["options"]] == expect["options"]
        assert _dump() == before
        return
    if expect["status"] == "failed":
        assert body["reason"] and _dump() == before
        return
    if expect["status"] == "confirm":
        assert _dump() == before, "a confirm must not have changed anything yet"
        body = client.post(f"/api/command/{body['command_id']}/answer",
                           json={"confirm": True}).get_json()
        assert body["status"] == "done", body

    assert len(body["actions"]) == len(expect["actions"])
    for want, have in zip(expect["actions"], body["actions"]):
        assert want.items() <= have.items(), (want, have)
    assert body["lines"] and all("2026-W" not in line for line in body["lines"])

    if body["undo"]:
        undone = client.post(f"/api/command/{body['command_id']}/undo").get_json()
        assert undone == {"status": "undone"}
        assert _dump() == before


def test_answering_a_question_finishes_the_command(client):
    body = _say(client, "put the caldo on monday", {"screen": "home"})
    assert body["status"] == "ask" and body["question"] == "Which one?"
    body = client.post(f"/api/command/{body['command_id']}/answer",
                       json={"option": "Chicken Caldo B"}).get_json()
    assert body["status"] == "done"
    assert body["actions"][0]["recipe"] == "Chicken Caldo B"


def test_an_answer_that_was_not_offered_is_rejected(client):
    body = _say(client, "put the caldo on monday", {"screen": "home"})
    resp = client.post(f"/api/command/{body['command_id']}/answer", json={"option": "Butter Biscuits"})
    assert resp.status_code == 400


def test_declining_a_confirm_changes_nothing(client):
    before = _dump()
    body = _say(client, "take the chili off tuesday", {"screen": "planner", "week": "2026-W47"})
    body = client.post(f"/api/command/{body['command_id']}/answer", json={"confirm": False}).get_json()
    assert body == {"status": "failed", "reason": "Cancelled."}
    assert _dump() == before


def test_undo_twice_and_undo_of_unknown(client):
    body = _say(client, "we're out of eggs", {"screen": "home"})
    assert client.post(f"/api/command/{body['command_id']}/undo").status_code == 200
    assert client.post(f"/api/command/{body['command_id']}/undo").status_code == 409
    assert client.post("/api/command/99999/undo").status_code == 404


def test_undo_refused_after_a_later_change(client):
    from lib.inventory import InventoryItem, add_items
    body = _say(client, "we're out of eggs", {"screen": "home"})
    add_items([InventoryItem(name="butter", quantity=1, location="fridge")])
    resp = client.post(f"/api/command/{body['command_id']}/undo")
    assert resp.status_code == 409 and resp.get_json()["status"] == "refused"


def test_a_double_send_runs_once(client):
    context = {"screen": "recipe", "recipe": "Chicken Caldo A"}
    first = _say(client, "put this on friday dinner", context)
    second = _say(client, "put this on friday dinner", context)
    assert second["command_id"] == first["command_id"]
    from lib import serving_ledger
    assert len([c for c in serving_ledger.cooks_for_week("2026-W46")
                if c["recipe"] == "Chicken Caldo A"]) == 1


def test_bad_requests(client):
    assert client.post("/api/command", json={"text": "", "context": {"screen": "home"}}).status_code == 400
    assert client.post("/api/command", json={"text": "x" * 501, "context": {"screen": "home"}}).status_code == 400
    for bad in [{"screen": "nope"}, {"screen": "recipe", "recipe": "../etc/passwd"},
                {"screen": "planner", "week": "2026-W99"}, {"screen": "home", "url": "http://x"},
                {"screen": "home", "date": "2026-02-30"}]:
        assert client.post("/api/command", json={"text": "open saturday", "context": bad}).status_code == 400


def test_context_validate_returns_only_known_keys(gold_kitchen):
    assert command_context.validate({"screen": "recipe", "recipe": "Chicken Caldo A"}) == {
        "screen": "recipe", "recipe": "Chicken Caldo A"}
    assert command_context.validate(None) == {"screen": "other"}
