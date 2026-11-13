from lib.command import decider
from lib.command.decider import NoDecider, OllamaDecider, Option, ScriptedDecider

OPTIONS = [Option("plan_cook", "Add it to the meal plan"), Option("move_cook", "Move it")]


def test_no_decider_always_defers():
    assert NoDecider().decide("q", OPTIONS, "ctx") is None


def test_scripted_decider_picks_and_records():
    d = ScriptedDecider({"anything": "move_cook"})
    assert d.decide("q", OPTIONS, "ctx") == "move_cook"
    assert d.calls == [("q", ["plan_cook", "move_cook"])]


def test_ollama_decider_refuses_when_llm_disabled(monkeypatch):
    monkeypatch.setenv("KITCHENOS_NO_LLM", "1")
    monkeypatch.setattr(decider.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dialled")))
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None


class _Reply:
    status_code = 200

    def __init__(self, content):
        self._content = content

    def json(self):
        return {"message": {"content": self._content}}


def test_ollama_decider_returns_a_listed_choice(monkeypatch):
    monkeypatch.delenv("KITCHENOS_NO_LLM", raising=False)
    sent = {}

    def post(url, json, timeout):
        sent.update(json=json, timeout=timeout)
        return _Reply('{"choice": "move_cook"}')

    monkeypatch.setattr(decider.requests, "post", post)
    assert OllamaDecider().decide("q", OPTIONS, "ctx") == "move_cook"
    assert sent["json"]["format"]["properties"]["choice"]["enum"] == ["plan_cook", "move_cook"]
    assert sent["json"]["keep_alive"] == "30m"


def test_ollama_decider_rejects_an_unlisted_or_broken_answer(monkeypatch):
    monkeypatch.delenv("KITCHENOS_NO_LLM", raising=False)
    monkeypatch.setattr(decider.requests, "post", lambda *a, **k: _Reply('{"choice": "explode"}'))
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None
    monkeypatch.setattr(decider.requests, "post", lambda *a, **k: _Reply("not json"))
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None


def test_ollama_decider_survives_a_timeout(monkeypatch):
    monkeypatch.delenv("KITCHENOS_NO_LLM", raising=False)

    def boom(*a, **k):
        raise decider.requests.Timeout()

    monkeypatch.setattr(decider.requests, "post", boom)
    assert OllamaDecider().decide("q", OPTIONS, "ctx") is None
