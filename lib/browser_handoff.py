"""Bounded, process-local credentials for the Siri browser viewing handoff.

Only SHA-256 keys persist. Raw credentials exist solely in return values, whose
repr deliberately omits them. A restart revokes every outstanding credential.
"""

from dataclasses import dataclass, field
from datetime import date
import hashlib
import re
import secrets
import threading
import time
from urllib.parse import unquote

CODE_TTL = 60
SESSION_TTL = 900
COOKIE_TTL = 86400
CAPACITY = 1024


class CapacityExceeded(Exception):
    """No live entry may be evicted to make room for another credential."""


@dataclass(frozen=True)
class IssuedCode:
    code: str = field(repr=False)
    expires_at: float


@dataclass(frozen=True)
class BrowserGrant:
    session_id: str = field(repr=False)
    redirect_path: str
    expires_at: float


@dataclass(frozen=True)
class _Entry:
    redirect_path: str
    origin: str
    token_fingerprint: str
    expires_at: float


def _key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _valid_destination(path: str) -> bool:
    if not isinstance(path, str):
        return False
    if path.startswith("/recipe/"):
        encoded = path[len("/recipe/") :]
        name = unquote(encoded)
        return bool(
            name
            and name not in (".", "..")
            and not any(c in name for c in "/\\\x00")
            and not any(ord(c) < 32 for c in name)
            and not any(c in encoded for c in "?#")
        )
    match = re.fullmatch(
        r"/meal-planner\?week=(\d{4}-W\d{2})&date=(\d{4}-\d{2}-\d{2})&view=calendar",
        path,
    )
    if not match:
        return False
    try:
        day = date.fromisoformat(match[2])
    except ValueError:
        return False
    iso = day.isocalendar()
    return match[1] == f"{iso.year:04d}-W{iso.week:02d}"


class BrowserHandoffStore:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._codes: dict[str, _Entry] = {}
        self._sessions: dict[str, _Entry] = {}

    def _prune(self, now):
        for entries in (self._codes, self._sessions):
            for key in [
                key for key, entry in entries.items() if entry.expires_at <= now
            ]:
                del entries[key]

    def issue(self, destination, origin, token_fingerprint):
        if not _valid_destination(destination):
            raise ValueError("Invalid viewing destination")
        with self._lock:
            now = self._clock()
            self._prune(now)
            if len(self._codes) >= CAPACITY:
                raise CapacityExceeded()
            code = secrets.token_urlsafe(32)
            expires = now + CODE_TTL
            self._codes[_key(code)] = _Entry(
                destination, origin, token_fingerprint, expires
            )
            return IssuedCode(code, expires)

    def exchange(self, code, origin, token_fingerprint):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
            return None
        with self._lock:
            now = self._clock()
            self._prune(now)
            key = _key(code)
            entry = self._codes.get(key)
            if entry is None or (entry.origin, entry.token_fingerprint) != (
                origin,
                token_fingerprint,
            ):
                return None
            # Check before consuming: the caller may retry while the code lives.
            if len(self._sessions) >= CAPACITY:
                raise CapacityExceeded()
            session_id = secrets.token_urlsafe(32)
            expires = now + SESSION_TTL
            self._sessions[_key(session_id)] = _Entry(
                entry.redirect_path, origin, token_fingerprint, expires
            )
            del self._codes[key]
            return BrowserGrant(session_id, entry.redirect_path, expires)

    def authorize(self, session_id, origin, token_fingerprint):
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", session_id
        ):
            return None
        with self._lock:
            now = self._clock()
            self._prune(now)
            entry = self._sessions.get(_key(session_id))
            if entry is None or (entry.origin, entry.token_fingerprint) != (
                origin,
                token_fingerprint,
            ):
                return None
            return entry
