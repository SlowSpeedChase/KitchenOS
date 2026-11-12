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

from tests.e2e._paths import data_root

#: The checkout under test — its api_server.py and config/ are what we exercise.
REPO = Path(__file__).resolve().parents[2]
#: Where the git-ignored vault/ and data/ actually live: always the main
#: worktree, so the suite runs from a branch worktree too.
DATA_ROOT = data_root(REPO)
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
        DATA_ROOT / "vault" / "KitchenOS",
        vault,
        ignore=shutil.ignore_patterns("Images", ".obsidian", ".history"),
    )
    db = root / "kitchenos.db"
    shutil.copy2(DATA_ROOT / "data" / "kitchenos.db", db)
    # A move teaches the storage table, so the server *writes* this file. Copied
    # rather than pointed at the real one: otherwise the browser tests rewrite
    # the developer's config/storage_locations.json — observed, they injected
    # their fixture item names and reordered by_category. Copied rather than
    # left empty because plenty of routing depends on its real contents.
    storage_table = root / "storage_locations.json"
    shutil.copy2(REPO / "config" / "storage_locations.json", storage_table)

    port = _free_port()
    log = root / "server.log"
    env = {
        **os.environ,
        "KITCHENOS_VAULT": str(vault),
        "KITCHENOS_DB": str(db),
        "KITCHENOS_STORAGE_TABLE": str(storage_table),
        "PORT": str(port),
        # Never let a test hit the paid APIs or a live LLM. Blank keys alone did
        # not achieve this: Ollama needs no key, so /prep and /recipe-card kept
        # reaching the local tier and the browser's 30 s navigation timeout raced
        # a model. lib/llm_gate refuses every tier, keyed or not.
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "KITCHENOS_NO_LLM": "1",
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


@pytest.fixture(scope="module")
def siri_server(tmp_path_factory) -> LiveServer:
    """Synthetic domain data behind real remote bearer/viewing-session checks."""
    root = tmp_path_factory.mktemp("kitchenos-siri-e2e")
    vault = root / "KitchenOS"
    for folder in ("Recipes", "Meal Plans", "Meals"):
        (vault / folder).mkdir(parents=True)
    (vault / "Recipes" / "Rice & Beans 100%.md").write_text(
        "---\ntitle: Rice & Beans 100%\nservings: 4\ndish_type: main\n"
        "nutrition_calories: 400\nnutrition_protein: 20\n"
        "nutrition_carbs: 60\nnutrition_fat: 10\n---\n# Rice & Beans 100%\n\n"
        "## Ingredients\n\n| Amount | Unit | Ingredient |\n|---|---|---|\n"
        "| 1 | cup | rice |\n\n## Instructions\n\n1. Simmer the fixture rice until tender.\n"
    )
    storage = root / "storage_locations.json"
    shutil.copy2(REPO / "config" / "storage_locations.json", storage)
    port = _free_port()
    log = root / "server.log"
    db = root / "kitchenos.db"
    env = {**os.environ, "KITCHENOS_VAULT": str(vault), "KITCHENOS_DB": str(db),
           "KITCHENOS_STORAGE_TABLE": str(storage), "KITCHENOS_API_TOKEN": "siri-fixture-token",
           "KITCHENOS_NO_LLM": "1", "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}
    (root / "clock.txt").write_text(str(time.time()))
    # The remote address middleware is test-only; production auth is unchanged.
    runner = '''
from lib import inventory_db
with inventory_db.connect() as conn:
    c = conn.execute("INSERT INTO cooks(recipe,week,date,meal,scale,servings_produced) VALUES ('Rice & Beans 100%','2026-W42','2026-10-16','dinner',1,4)")
    conn.execute("INSERT INTO placements(cook_id,destination,date,meal,count) VALUES (?,'slot','2026-10-16','dinner',1)", (c.lastrowid,))
    conn.commit()
import api_server
from lib.browser_handoff import BrowserHandoffStore
from pathlib import Path
import os
clock_file = Path(os.environ['KITCHENOS_DB']).parent / 'clock.txt'
api_server.browser_handoff_store = BrowserHandoffStore(clock=lambda: float(clock_file.read_text()))
original = api_server.app.wsgi_app
def remote(environ, start_response):
    environ['REMOTE_ADDR'] = '198.51.100.9'
    return original(environ, start_response)
api_server.app.wsgi_app = remote
api_server.app.run(host='0.0.0.0', port=PORT, debug=False)
'''.replace("port=PORT", f"port={port}")
    with log.open("w") as logfile:
        proc = subprocess.Popen([sys.executable, "-c", runner], env=env, cwd=REPO,
                                stdout=logfile, stderr=subprocess.STDOUT)
    base_url = f"http://127.0.0.1:{port}"
    try:
        _await_health(proc, base_url, log)
        yield LiveServer(base_url, vault, db, log)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
