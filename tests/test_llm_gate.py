"""The single authority on whether a call may reach an LLM, and for how long.

Both defects this module exists for were live on `main`: a page render that
blocks for up to 120 s on a cold cache, and an e2e harness that promised never
to hit a live LLM while leaving the Ollama tier wide open.
"""

import pytest

from lib import llm_gate


class TestKillSwitch:
    def test_llm_is_allowed_by_default(self, monkeypatch):
        monkeypatch.delenv(llm_gate.DISABLE_ENV, raising=False)
        assert llm_gate.allowed() is True

    def test_the_kill_switch_refuses_the_call(self, monkeypatch):
        monkeypatch.setenv(llm_gate.DISABLE_ENV, "1")
        assert llm_gate.allowed() is False

    def test_an_empty_value_is_not_a_kill_switch(self, monkeypatch):
        """`FOO=` in a shell profile must not silently disable inference."""
        monkeypatch.setenv(llm_gate.DISABLE_ENV, "")
        assert llm_gate.allowed() is True

    def test_falsey_words_are_honoured(self, monkeypatch):
        """A config that sets it to 0/false means enabled, not 'any value = off'."""
        for value in ("0", "false", "no"):
            monkeypatch.setenv(llm_gate.DISABLE_ENV, value)
            assert llm_gate.allowed() is True, value


class TestBudget:
    def test_a_script_keeps_its_own_long_budget(self, monkeypatch):
        """Outside a request nobody is waiting — a nightly job may take minutes."""
        monkeypatch.delenv(llm_gate.DISABLE_ENV, raising=False)
        assert llm_gate.budget_s(120) == 120

    def test_a_page_render_gets_the_short_budget(self, monkeypatch):
        """A reader is waiting behind a 30 s browser timeout; 120 s cannot happen."""
        from flask import Flask

        monkeypatch.delenv(llm_gate.DISABLE_ENV, raising=False)
        app = Flask(__name__)
        with app.test_request_context("/recipe-card/Anything"):
            # approx: the deadline is real wall-clock, so a sliver is already spent
            assert llm_gate.budget_s(120) == pytest.approx(llm_gate.WEB_BUDGET_S, abs=0.5)

    def test_the_web_budget_fits_inside_a_browser_navigation(self):
        """Playwright's default navigation timeout is 30 s; leave room to render."""
        assert llm_gate.WEB_BUDGET_S < 30

    def test_a_caller_asking_for_less_than_the_web_budget_keeps_its_own(self, monkeypatch):
        """The gate is a ceiling, never a floor — it may not slow a fast caller down."""
        from flask import Flask

        monkeypatch.delenv(llm_gate.DISABLE_ENV, raising=False)
        app = Flask(__name__)
        with app.test_request_context("/"):
            assert llm_gate.budget_s(2) == 2

    def test_the_budget_covers_the_whole_request_not_each_call(self, monkeypatch):
        """Both callers try Claude *then* Ollama, so a per-call ceiling doubles.

        8 s each is 16 s of dead page. The budget is a deadline for the request.
        """
        from flask import Flask

        monkeypatch.delenv(llm_gate.DISABLE_ENV, raising=False)
        clock = {"t": 1000.0}
        monkeypatch.setattr(llm_gate.time, "monotonic", lambda: clock["t"])
        app = Flask(__name__)
        with app.test_request_context("/"):
            assert llm_gate.budget_s(120) == llm_gate.WEB_BUDGET_S
            clock["t"] += 6.0  # the first tier spent 6 s
            assert llm_gate.budget_s(120) == llm_gate.WEB_BUDGET_S - 6.0

    def test_an_exhausted_budget_reports_no_time_left(self, monkeypatch):
        """0 means 'don't make the call' — never a negative timeout."""
        from flask import Flask

        monkeypatch.delenv(llm_gate.DISABLE_ENV, raising=False)
        clock = {"t": 1000.0}
        monkeypatch.setattr(llm_gate.time, "monotonic", lambda: clock["t"])
        app = Flask(__name__)
        with app.test_request_context("/"):
            llm_gate.budget_s(120)
            clock["t"] += llm_gate.WEB_BUDGET_S + 5
            assert llm_gate.budget_s(120) == 0

    def test_each_request_starts_with_a_full_budget(self, monkeypatch):
        """The deadline is per request, not process-wide."""
        from flask import Flask

        monkeypatch.delenv(llm_gate.DISABLE_ENV, raising=False)
        clock = {"t": 1000.0}
        monkeypatch.setattr(llm_gate.time, "monotonic", lambda: clock["t"])
        app = Flask(__name__)
        with app.test_request_context("/"):
            llm_gate.budget_s(120)
            clock["t"] += llm_gate.WEB_BUDGET_S + 5
            assert llm_gate.budget_s(120) == 0
        with app.test_request_context("/"):
            assert llm_gate.budget_s(120) == llm_gate.WEB_BUDGET_S


class TestWhereTheCallIsComingFrom:
    """Callers need this to decide whether a fallback is worth persisting."""

    def test_a_script_is_not_a_page_render(self):
        assert llm_gate.on_page_render() is False

    def test_inside_a_request_it_is(self):
        from flask import Flask

        with Flask(__name__).test_request_context("/prep"):
            assert llm_gate.on_page_render() is True
