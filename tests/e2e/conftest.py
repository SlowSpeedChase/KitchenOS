"""Fixtures for end-to-end browser tests.

These drive a *real* KitchenOS server, because the failures worth catching here
are the ones unit tests structurally cannot see: a route that returns 200 while
rendering an empty week, a dashboard link pointing at a note nothing ever
generated, a JS exception that silently kills a click handler.

Isolation: the server under test runs on its own port against **copies** of the
vault and the SQLite DB, so a test may click destructive buttons without
touching real inventory or meal plans. `lib/paths.py` reads `KITCHENOS_VAULT`
with `override=False`, and `lib/inventory_db.py` reads `KITCHENOS_DB`, so
passing both in the subprocess env is enough to redirect all writes.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[2]
BOOT_TIMEOUT_S = 30


@dataclass
class LiveServer:
    base_url: str
    vault: Path
    db: Path
    log: Path

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"


def _free_port() -> int:
    """Ask the OS for an unused port, then release it for the child to bind."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory) -> LiveServer:
    """A KitchenOS API server backed by throwaway copies of the vault and DB."""
    root = tmp_path_factory.mktemp("kitchenos-e2e")
    vault = root / "KitchenOS"
    # Skip Images/ (7.5 MB of blobs the tested flows never render), the Obsidian
    # config (machine state, not content), and .history/ (thousands of timestamped
    # backups left by the backfill scripts — pure copy cost, never read).
    shutil.copytree(
        REPO / "vault" / "KitchenOS",
        vault,
        ignore=shutil.ignore_patterns("Images", ".obsidian", ".history"),
    )
    db = root / "kitchenos.db"
    shutil.copy2(REPO / "data" / "kitchenos.db", db)

    port = _free_port()
    log = root / "server.log"
    env = {
        **os.environ,
        "KITCHENOS_VAULT": str(vault),
        "KITCHENOS_DB": str(db),
        "PORT": str(port),
        # Never let a test hit the paid APIs or a live LLM.
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
    }
    with open(log, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "api_server.py")],
            env=env, cwd=REPO, stdout=logfile, stderr=subprocess.STDOUT,
        )

    base_url = f"http://127.0.0.1:{port}"
    try:
        _await_health(proc, base_url, log)
        yield LiveServer(base_url=base_url, vault=vault, db=db, log=log)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _await_health(proc: subprocess.Popen, base_url: str, log: Path) -> None:
    """Block until /health answers, failing loudly with the server log if not."""
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"server exited with code {proc.returncode} before serving:\n"
                f"{log.read_text()[-3000:]}"
            )
        try:
            if requests.get(f"{base_url}/health", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            time.sleep(0.25)
    raise RuntimeError(
        f"server did not answer /health within {BOOT_TIMEOUT_S}s:\n"
        f"{log.read_text()[-3000:]}"
    )


@pytest.fixture
def page_errors(page):
    """Collect console errors and uncaught exceptions raised by the page.

    A silently-broken handler is the most common way one of these screens
    'works' in a smoke test and fails a human, so every test gets this.
    """
    errors: list[str] = []
    page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    return errors
