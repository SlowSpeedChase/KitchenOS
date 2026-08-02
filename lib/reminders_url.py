"""Read share-sheet URLs out of the macOS Reminders store.

When a web page (recipe, reel, video) is shared to Reminders via the iOS/macOS
Share Sheet, the link is stored as a rich-link *attachment*, not in the
reminder's title, URL field, or notes. EventKit and AppleScript both return
``None`` for that URL — the only place it is reachable is the Reminders Core
Data SQLite store.

This module reads those stores directly (read-only) and returns a mapping of
``calendarItemIdentifier`` → URL, so ``batch_extract`` can recover the link for
reminders whose title is just the page name.

Schema (as of macOS "Tahoe" / Darwin 27):
  * ``ZREMCDREMINDER`` — one row per reminder; ``ZCKIDENTIFIER`` equals
    EventKit's ``calendarItemIdentifier``; ``ZLIST`` → ``ZREMCDBASELIST.Z_PK``.
  * ``ZREMCDBASELIST`` — lists; ``ZNAME`` is the list title.
  * ``ZREMCDOBJECT`` — attachments; a URL attachment has ``ZURL`` set and links
    back to its reminder via one of several ``ZREMINDER*`` FK columns
    (share-sheet links use ``ZREMINDER2``, other URL rows use ``ZREMINDER3``),
    so we match against every ``ZREMINDER*`` column we find.

Core Data column names are private and could change across macOS versions;
every failure mode here degrades to an empty result rather than raising, so
the caller simply falls back to the title as before.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# Default location of the Reminders Core Data stores.
STORES_DIR = (
    Path.home()
    / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
)

_REMINDER_FK_RE = re.compile(r"^ZREMINDER\d*$")


def find_stores(stores_dir: Path = STORES_DIR) -> list[Path]:
    """Return the Reminders ``*.sqlite`` store files (sorted, sidecars excluded)."""
    stores_dir = Path(stores_dir)
    if not stores_dir.is_dir():
        log.warning("Reminders stores directory not readable: %s", stores_dir)
        return []
    stores = sorted(p for p in stores_dir.glob("*.sqlite") if p.is_file())
    if not stores:
        # A TCC denial does not raise: the directory stats fine and its listing
        # comes back empty. That is what a LaunchAgent sees without Full Disk
        # Access, while the same code run from a terminal reads every store —
        # so "it works when I run it by hand" proves nothing about the job.
        #
        # This message previously told the reader to grant the bash shim in
        # ops/agents/. That advice was wrong and cost a real debugging session:
        # macOS accepts a shell script into the Full Disk Access list and then
        # never matches it, because TCC binds to signed executables and the
        # shim's `exec` replaces the process image with the interpreter before
        # any protected read happens. The launcher is now a signed copy of the
        # interpreter living in .venv/bin/, which *is* the process.
        log.warning(
            "No Reminders store files (*.sqlite) under %s — an empty listing "
            "here usually means this process lacks Full Disk Access. Grant it "
            "to '.venv/bin/KitchenOS · Batch Extract' (System Settings → "
            "Privacy & Security → Full Disk Access, ⇧⌘G to paste the path), "
            "then reload the agent. That file is a signed *copy* of the Python "
            "interpreter, not a shim: TCC binds to executables, and a bash "
            "shim's `exec` replaces the process image, so a grant on the shim "
            "never matches anything. Regenerate it with "
            "scripts/make-agent-launchers.sh.",
            stores_dir,
        )
    return stores


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f"PRAGMA table_info({table})")]


def _urls_from_store(db_path: Path, list_name: str | None) -> dict[str, str]:
    """Map ``ZCKIDENTIFIER`` → URL for one store. Empty on any schema mismatch."""
    # Open read-only so we never disturb the live database.
    uri = f"file:{db_path}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as e:
        log.warning("Cannot open Reminders store %s: %s", db_path.name, e)
        return {}
    try:
        obj_cols = _columns(con, "ZREMCDOBJECT")
        rem_cols = _columns(con, "ZREMCDREMINDER")
        missing = [c for c in ("ZURL",) if c not in obj_cols]
        missing += [c for c in ("ZCKIDENTIFIER",) if c not in rem_cols]
        if missing:
            log.warning(
                "Reminders store %s is missing expected column(s) %s — "
                "the Core Data schema may have changed",
                db_path.name,
                ", ".join(missing),
            )
            return {}
        fk_cols = [c for c in obj_cols if _REMINDER_FK_RE.match(c)]
        if not fk_cols:
            log.warning(
                "Reminders store %s has no ZREMINDER* attachment foreign key",
                db_path.name,
            )
            return {}

        fk_match = " OR ".join(f"r.Z_PK = o.{c}" for c in fk_cols)
        url_expr = "COALESCE(o.ZURL, o.ZHOSTURL)" if "ZHOSTURL" in obj_cols else "o.ZURL"
        sql = f"""
            SELECT r.ZCKIDENTIFIER, {url_expr}
            FROM ZREMCDREMINDER r
            JOIN ZREMCDBASELIST l ON r.ZLIST = l.Z_PK
            JOIN ZREMCDOBJECT o ON o.ZURL LIKE 'http%' AND ({fk_match})
            WHERE (:list IS NULL OR l.ZNAME = :list)
        """
        rows = con.execute(sql, {"list": list_name}).fetchall()
    except sqlite3.Error as e:
        # A permission denial arrives here too: TCC turns the read into
        # sqlite3.OperationalError("unable to open database file").
        log.warning("Cannot read Reminders store %s: %s", db_path.name, e)
        return {}
    finally:
        con.close()

    return {ident: url for ident, url in rows if ident and url}


def urls_by_identifier(
    list_name: str | None = None, stores_dir: Path = STORES_DIR
) -> dict[str, str]:
    """Return ``{calendarItemIdentifier: url}`` for share-sheet reminders.

    Args:
        list_name: Restrict to a single Reminders list by name; ``None`` = all.
        stores_dir: Override the Reminders stores directory (tests).

    Never raises — any missing directory, locked/renamed store, or schema
    change yields an empty mapping so the caller can fall back gracefully.
    Every one of those paths logs a warning first: an empty result that says
    nothing is indistinguishable from a list with no share-sheet links, and
    that silence once hid three weeks of unresolved reminders.
    """
    stores = find_stores(stores_dir)
    merged: dict[str, str] = {}
    for store in stores:
        merged.update(_urls_from_store(store, list_name))

    scope = f'list "{list_name}"' if list_name else "all lists"
    if not stores:
        pass  # find_stores already said why
    elif not merged:
        log.warning(
            "Recovered no share-sheet URLs for %s from %d Reminders store(s)",
            scope,
            len(stores),
        )
    else:
        log.info("Recovered %d share-sheet URL(s) for %s", len(merged), scope)
    return merged
