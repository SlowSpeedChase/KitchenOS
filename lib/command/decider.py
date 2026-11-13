"""The only place a model is consulted, and only for one typed choice.

`decide` returns an option id or None. None is not an error: it means "ask the
user", and the same options are shown as buttons. A decider must never raise.
"""
import json
from dataclasses import dataclass

import requests

from lib import llm_gate

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
#: The smallest local model that passes the gold scorecard. Change it only
#: after running scripts/score_command_models.py.
DEFAULT_MODEL = "qwen2.5:3b"
_DEFAULT_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    hint: str = ""


class NoDecider:
    def decide(self, question, options, context):
        return None


class ScriptedDecider:
    """Test double: answers with the first option whose id it was told to pick."""

    def __init__(self, answers: dict):
        self._wanted = set(answers.values())
        self.calls = []

    def decide(self, question, options, context):
        self.calls.append((question, [o.id for o in options]))
        return next((o.id for o in options if o.id in self._wanted), None)


class OllamaDecider:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def decide(self, question, options, context):
        if not llm_gate.allowed():
            return None
        timeout = llm_gate.budget_s(_DEFAULT_TIMEOUT_S)
        if timeout <= 0:
            return None
        ids = [o.id for o in options]
        menu = "\n".join(f"- {o.id}: {o.hint or o.label}" for o in options)
        body = {
            "model": self.model, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0},
            "format": {"type": "object", "required": ["choice"],
                       "properties": {"choice": {"type": "string", "enum": ids}}},
            "messages": [
                {"role": "system", "content": f"Pick the one label that fits.\n{menu}"},
                {"role": "user", "content": f"{context}\n{question}"},
            ],
        }
        try:
            reply = requests.post(OLLAMA_CHAT_URL, json=body, timeout=timeout)
            if reply.status_code != 200:
                return None
            choice = json.loads(reply.json()["message"]["content"]).get("choice")
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
            return None
        return choice if choice in ids else None


def default():
    return OllamaDecider()
