"""The one authority on whether a call may reach an LLM, and for how long.

Two defects, one root cause — a synchronous page render blocking on inference:

**The hang.** ``/recipe-card/<name>`` and ``/prep`` each try Claude, then Ollama,
then fall back to a non-LLM answer they only reach *after* the wait. Both Ollama
calls were hardcoded ``timeout=120`` and the Anthropic SDK carries a multi-minute
default, so a cold cache meant a page that hung well past the browser's own
timeout. Only 5 of 252 recipes have a ``.grid.json`` sidecar, so nearly every
recipe card is a cold render.

**The kill switch.** ``tests/e2e/conftest.py`` promised "never let a test hit the
paid APIs or a live LLM" and enforced it by blanking ``ANTHROPIC_API_KEY`` and
``OPENAI_API_KEY``. Ollama needs no key, so the local tier was reached anyway and
the browser tests raced a model. Blanking keys cannot express "no inference";
:data:`DISABLE_ENV` can, for every tier at once.

The budget is keyed on Flask's request context rather than passed in as a
parameter, deliberately: a *new* AI-on-render path is then bounded without its
author having to know this rule exists. Outside a request — scripts, the nightly
enricher, MCP — the caller's own timeout stands, because nobody is waiting.

It is a **ceiling, never a floor**: a caller that already asks for less than the
web budget keeps its own shorter timeout.
"""

from __future__ import annotations

import os
import time

#: Set to a truthy value to refuse every LLM tier, keyed or not.
DISABLE_ENV = "KITCHENOS_NO_LLM"

#: Seconds of inference one HTTP request may spend in total. Playwright's default
#: navigation timeout is 30 s and a human gives up sooner; this leaves room for
#: the page to actually render after the model has had its turn.
WEB_BUDGET_S = 8.0

_FALSEY = {"", "0", "false", "no", "off"}

_DEADLINE_ATTR = "_kitchenos_llm_deadline"


def allowed() -> bool:
    """May this process talk to an LLM at all?

    False only when :data:`DISABLE_ENV` is set to something meaningful — an
    empty or explicitly false value must not silently disable inference, since
    a blank ``KITCHENOS_NO_LLM=`` in a shell profile is not a decision.
    """
    return os.getenv(DISABLE_ENV, "").strip().lower() in _FALSEY


def budget_s(default: float) -> float:
    """Seconds this call may wait, given where it is being made from.

    Outside a request context the caller's ``default`` stands. Inside one, the
    whole request shares a single :data:`WEB_BUDGET_S` deadline — both callers
    try two tiers in sequence, so a per-call ceiling would silently double.
    Returns ``0`` when the budget is spent, which callers must read as "skip
    this tier" rather than passing on as a timeout.
    """
    if not on_page_render():
        return default

    from flask import g

    deadline = getattr(g, _DEADLINE_ATTR, None)
    if deadline is None:
        deadline = time.monotonic() + WEB_BUDGET_S
        setattr(g, _DEADLINE_ATTR, deadline)

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return 0
    return min(default, remaining)


def on_page_render() -> bool:
    """True when a reader is waiting on this call — i.e. inside a Flask request.

    Callers use it to decide whether a fallback is worth *persisting*: an answer
    the clock forced is not the same as the answer the machine can give, and
    mtime-keyed sidecars have no way to tell the two apart later.
    """
    try:
        from flask import has_request_context
    except ImportError:
        return False
    return has_request_context()
