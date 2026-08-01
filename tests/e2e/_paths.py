"""Where the e2e harness finds the data it copies.

`vault/` and `data/kitchenos.db` are git-ignored, so they exist only in the main
checkout — but all work in this repo happens in linked worktrees under
`.worktrees/`, and the harness used to resolve both relative to itself. Running
the browser suite from a branch therefore died on
``FileNotFoundError: .../.worktrees/<branch>/vault/KitchenOS`` before a single
test ran, which is why e2e was only ever run from `main`.

Only the *data* comes from the main checkout. `api_server.py`, `config/` and the
tests themselves must keep coming from the worktree under test — otherwise the
harness would faithfully exercise a branch's tests against main's code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def data_root(start: Path) -> Path:
    """The main worktree for ``start``'s repository, or ``start`` if there isn't one.

    ``git rev-parse --git-common-dir`` answers with the *shared* git directory —
    a linked worktree's own ``.git`` is a file pointing into
    ``<main>/.git/worktrees/<name>``, but the common dir is ``<main>/.git``. Its
    parent is therefore the main checkout, from either side.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=start, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return start.resolve()

    if not out:
        return start.resolve()

    # Relative (".git") in the main checkout, absolute from a linked worktree.
    common = Path(out)
    if not common.is_absolute():
        common = start / common
    return common.resolve().parent
