#!/usr/bin/env python3
"""Mirror the browsable KitchenOS pages into Safari's "KitchenOS" bookmarks folder.

The page list comes from ``SECTIONS`` in ``lib/web_dashboard.py`` — the same
registry that renders ``Dashboards/KitchenOS Web.md`` — so one edit there
propagates to both the vault launcher note and the phone's bookmarks bar.
``desired_bookmarks()`` also prepends ``HOME``, the registry root that lives
outside ``SECTIONS`` (see that function's docstring).

Additive and idempotent: entries are matched on ``URLString``, nothing is ever
deleted or reordered, and the folder is never created a second time. Hand-made
bookmarks living in the folder are left alone.

    scripts/sync_safari_bookmarks.py            # --check: report drift, touch nothing
    scripts/sync_safari_bookmarks.py --apply    # quit Safari, add the missing ones, relaunch

Safari caches ``Bookmarks.plist`` in memory and rewrites it on quit, so a write
made while it is running is silently discarded — hence the quit/relaunch dance in
``--apply``. Safari's session restore brings the tabs back. iCloud bookmark sync
assigns each new leaf a ``Sync`` dict on its next upload; we deliberately write
none, which is exactly the shape of a bookmark created by hand in the UI.
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import paths  # noqa: E402,F401  (import triggers load_dotenv)
from lib import web_dashboard  # noqa: E402

BOOKMARKS_PLIST = Path.home() / "Library" / "Safari" / "Bookmarks.plist"

# The folder the user created by hand on 2026-07-25, first item in the Bookmarks
# Bar. Matched by UUID first so a rename doesn't strand us, by title second so a
# rebuilt folder still works.
FOLDER_UUID = "114F69DD-AF8F-4A63-B429-1F574E27A51C"
FOLDER_TITLE = "KitchenOS"

BACKUP_DIR = Path.home() / "Library" / "Safari" / "KitchenOS-bookmark-backups"

QUIT_TIMEOUT_S = 15
VERIFY_SETTLE_S = 10


class SyncError(RuntimeError):
    """Something is wrong enough that we must not write to the plist."""


# ---------------------------------------------------------------- desired state


def desired_bookmarks(base: str | None = None) -> list[tuple[str, str]]:
    """[(title, url)] for the home page, then every page in the registry."""
    base = (base if base is not None else web_dashboard.base_url()).rstrip("/")
    home_title, home_path = web_dashboard.HOME[1], web_dashboard.HOME[2]
    return [(home_title, f"{base}{home_path}")] + [
        (title, f"{base}{path}")
        for _section, items in web_dashboard.SECTIONS
        for _emoji, title, path, _desc in items
    ]


def _check_base(base: str) -> None:
    """A loopback bookmark is useless on the phone — refuse to write one."""
    if "localhost" in base or "127.0.0.1" in base or "://[::1]" in base:
        raise SyncError(
            f"base URL is loopback ({base}) — these bookmarks would only work on "
            "this Mac. Set KITCHENOS_API_BASE to the tailnet host and re-run."
        )


# ------------------------------------------------------------------- plist I/O


def load_plist() -> dict:
    with open(BOOKMARKS_PLIST, "rb") as fh:
        return plistlib.load(fh)


def find_folder(root: dict) -> dict:
    """Depth-first hunt for the KitchenOS folder. Raises if it isn't there."""
    by_title = None

    def walk(node):
        nonlocal by_title
        if node.get("WebBookmarkType") != "WebBookmarkTypeList":
            return None
        if node.get("WebBookmarkUUID") == FOLDER_UUID:
            return node
        if by_title is None and node.get("Title") == FOLDER_TITLE:
            by_title = node
        for child in node.get("Children", []):
            hit = walk(child)
            if hit is not None:
                return hit
        return None

    found = walk(root) or by_title
    if found is None:
        raise SyncError(
            f'no "{FOLDER_TITLE}" bookmarks folder found in {BOOKMARKS_PLIST}. '
            "Create it once by hand in Safari (Bookmarks > Add Bookmark Folder), "
            "then re-run."
        )
    found.setdefault("Children", [])
    return found


def make_leaf(title: str, url: str) -> dict:
    """A bookmark leaf shaped exactly like one Safari makes by hand."""
    return {
        "WebBookmarkType": "WebBookmarkTypeLeaf",
        "WebBookmarkUUID": str(uuid.uuid4()).upper(),
        "URLString": url,
        "URIDictionary": {"title": title},
        "dateAdded": datetime.now(timezone.utc).replace(tzinfo=None),
    }


def missing_entries(folder: dict, wanted: list[tuple[str, str]]) -> list[tuple[str, str]]:
    have = {
        child.get("URLString")
        for child in folder.get("Children", [])
        if child.get("WebBookmarkType") == "WebBookmarkTypeLeaf"
    }
    return [(title, url) for title, url in wanted if url not in have]


def write_plist(data: dict) -> None:
    """Atomic replace — tmp file in the same dir, then os.replace."""
    tmp = BOOKMARKS_PLIST.with_suffix(".plist.kitchenos-tmp")
    with open(tmp, "wb") as fh:
        plistlib.dump(data, fh, fmt=plistlib.FMT_BINARY)
    os.replace(tmp, BOOKMARKS_PLIST)


def back_up() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"Bookmarks-{stamp}.plist"
    shutil.copy2(BOOKMARKS_PLIST, dest)
    return dest


# ---------------------------------------------------------------------- Safari


def safari_running() -> bool:
    return subprocess.run(
        ["pgrep", "-x", "Safari"], capture_output=True
    ).returncode == 0


def quit_safari() -> None:
    """Ask Safari to quit, then wait for the process to actually be gone."""
    subprocess.run(
        ["osascript", "-e", 'tell application "Safari" to quit'],
        capture_output=True,
    )
    deadline = time.monotonic() + QUIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if not safari_running():
            return
        time.sleep(0.5)
    raise SyncError(
        f"Safari was still running {QUIT_TIMEOUT_S}s after being asked to quit "
        "(unsaved form, a modal dialog?). Nothing was written. Quit it by hand "
        "and re-run."
    )


def launch_safari() -> None:
    subprocess.run(["open", "-a", "Safari"], capture_output=True)


# ------------------------------------------------------------------------ main


def preflight() -> None:
    if platform.system() != "Darwin":
        raise SystemExit("Not macOS — no Safari bookmarks to sync. Skipping.")
    if not BOOKMARKS_PLIST.exists():
        raise SystemExit(f"No {BOOKMARKS_PLIST} — Safari not set up here. Skipping.")


def run_check(wanted: list[tuple[str, str]]) -> int:
    folder = find_folder(load_plist())
    missing = missing_entries(folder, wanted)
    have = len(wanted) - len(missing)
    if not missing:
        print(f"Safari 'KitchenOS' folder is in sync — all {len(wanted)} pages bookmarked.")
        return 0
    print(f"{len(missing)} of {len(wanted)} pages not bookmarked ({have} already there):")
    for title, url in missing:
        print(f"  + {title}  ->  {url}")
    print("\nRun with --apply to add them (quits and relaunches Safari).")
    return 1


def run_apply(wanted: list[tuple[str, str]]) -> int:
    if not missing_entries(find_folder(load_plist()), wanted):
        print(f"Safari 'KitchenOS' folder is in sync — all {len(wanted)} pages bookmarked.")
        return 0

    backup = back_up()
    print(f"Backed up bookmarks to {backup}")

    was_running = safari_running()
    if was_running:
        print("Quitting Safari (it caches the bookmarks file and would overwrite the edit)...")
        quit_safari()

    # Re-read *after* the quit: Safari flushes its in-memory copy on the way out,
    # so the pre-quit read is stale by definition.
    data = load_plist()
    folder = find_folder(data)
    missing = missing_entries(folder, wanted)
    for title, url in missing:
        folder["Children"].append(make_leaf(title, url))
        print(f"  + {title}  ->  {url}")
    write_plist(data)
    print(f"Added {len(missing)} bookmark(s).")

    if was_running:
        launch_safari()
        print(f"Relaunched Safari; waiting {VERIFY_SETTLE_S}s to confirm the write survived...")
        time.sleep(VERIFY_SETTLE_S)

    still_missing = missing_entries(find_folder(load_plist()), wanted)
    if still_missing:
        print(
            f"\nFAILED: {len(still_missing)} bookmark(s) vanished after Safari "
            f"relaunched — it or iCloud sync overwrote the file.\n"
            f"Restore with:  cp {backup} {BOOKMARKS_PLIST}",
            file=sys.stderr,
        )
        return 1
    print(f"Verified — all {len(wanted)} pages present in the 'KitchenOS' folder.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply",
        action="store_true",
        help="add the missing bookmarks (quits and relaunches Safari)",
    )
    args = ap.parse_args()

    preflight()
    base = web_dashboard.base_url()
    try:
        _check_base(base)
        wanted = desired_bookmarks(base)
        print(f"Base URL: {base}")
        return run_apply(wanted) if args.apply else run_check(wanted)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
