"""Split a spoken command into phrases. No model, no state."""
import re
from typing import Iterable

_SPLIT = re.compile(r"\s*(?:[,;]|\band then\b|\bthen\b|\band\b)\s*", re.I)


def split_phrases(text: str, protect: Iterable[str] = ()) -> list[str]:
    """Split on commas, semicolons, "and", "then".

    ``protect`` is a list of names (recipes) that must survive intact even if
    they contain a splitting word — "Mac and Cheese" is one phrase, not two.
    """
    held: list[str] = []
    for name in sorted(protect, key=len, reverse=True):
        if not _SPLIT.search(name):
            continue
        match = re.search(re.escape(name), text, re.I)
        if match:
            held.append(match.group(0))
            text = text[:match.start()] + f"\x00{len(held) - 1}\x00" + text[match.end():]
    parts = [p.strip() for p in _SPLIT.split(text) if p and p.strip()]
    return [re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], p) for p in parts]
