"""The e2e harness must be runnable from a worktree, not just the main checkout.

`vault/` and `data/` are git-ignored, so they exist only in the main worktree —
but every branch in this repo is developed in a linked worktree under
`.worktrees/`. The harness resolved both relative to its own checkout, so the
whole browser suite errored out with `FileNotFoundError: .../vault/KitchenOS`
anywhere except `main`.

Real git repos here rather than a mocked `subprocess`: the behaviour under test
*is* git's, specifically that `--git-common-dir` points a linked worktree back at
the repository it was created from.
"""

import subprocess
from pathlib import Path

from tests.e2e._paths import data_root


def _git(*args, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _repo_with_a_commit(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    (root / "README.md").write_text("hi\n")
    _git("add", "README.md", cwd=root)
    _git("commit", "-m", "init", cwd=root)
    return root


def test_the_main_checkout_is_its_own_data_root(tmp_path):
    main = _repo_with_a_commit(tmp_path / "repo")

    assert data_root(main) == main.resolve()


def test_a_linked_worktree_reads_the_main_checkout(tmp_path):
    """The point of the fix: vault/ and data/ live only in the main worktree."""
    main = _repo_with_a_commit(tmp_path / "repo")
    linked = main / ".worktrees" / "feature"
    _git("worktree", "add", "-b", "feature", str(linked), "main", cwd=main)

    assert data_root(linked) == main.resolve()


def test_a_non_repo_falls_back_to_itself(tmp_path):
    """No git, no answer to give — don't raise, just use what we were handed."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    assert data_root(plain) == plain.resolve()
