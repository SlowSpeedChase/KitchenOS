"""URL resolution from the Reminders Core Data SQLite store.

iOS/macOS share-sheet reminders store a shared link as a rich-link *attachment*
that EventKit and AppleScript do not expose. The URL is only reachable by
reading the Reminders SQLite store directly. These tests exercise the query
logic against a synthetic DB that mimics the real schema (ZREMCDREMINDER →
ZREMCDBASELIST, ZREMCDOBJECT attachment rows), so they don't depend on a live
Reminders database.
"""

import sqlite3

import pytest

from lib.reminders_url import urls_by_identifier, find_stores


LIST = "Recipies to Process"


def _make_store(path):
    """Build a minimal Reminders-store-shaped SQLite DB.

    Mirrors the real column names we rely on: reminders carry ZCKIDENTIFIER
    (== EventKit calendarItemIdentifier) and ZLIST; attachments carry ZURL and
    link back to a reminder via one of several ZREMINDER* FK columns (share-sheet
    links use ZREMINDER2, other URL rows use ZREMINDER3 — we match any).
    """
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE ZREMCDBASELIST (Z_PK INTEGER PRIMARY KEY, ZNAME TEXT);
        CREATE TABLE ZREMCDREMINDER (
            Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZLIST INTEGER,
            ZCOMPLETED INTEGER, ZCKIDENTIFIER TEXT
        );
        CREATE TABLE ZREMCDOBJECT (
            Z_PK INTEGER PRIMARY KEY, ZURL TEXT, ZHOSTURL TEXT,
            ZREMINDER INTEGER, ZREMINDER1 INTEGER, ZREMINDER2 INTEGER,
            ZREMINDER3 INTEGER
        );
        """
    )
    con.execute("INSERT INTO ZREMCDBASELIST VALUES (1, ?)", (LIST,))
    con.execute("INSERT INTO ZREMCDBASELIST VALUES (2, 'Groceries')")
    # Reminder with a share-sheet link (FK in ZREMINDER2)
    con.execute("INSERT INTO ZREMCDREMINDER VALUES (2254, 'Chopped Italian Sliders', 1, 0, 'ID-SLIDER')")
    # Reminder with a link stored in ZREMINDER3 (other attachment shape)
    con.execute("INSERT INTO ZREMCDREMINDER VALUES (201, 'YouTube', 1, 0, 'ID-YT')")
    # Reminder with no attachment at all
    con.execute("INSERT INTO ZREMCDREMINDER VALUES (300, 'Just text', 1, 0, 'ID-PLAIN')")
    # Reminder in a different list (must be excluded when filtering by list)
    con.execute("INSERT INTO ZREMCDREMINDER VALUES (400, 'Milk', 2, 0, 'ID-MILK')")
    con.execute(
        "INSERT INTO ZREMCDOBJECT (Z_PK, ZURL, ZREMINDER2) VALUES "
        "(816, 'https://simplymadeeats.com/15205/chopped-italian-sliders-on-hawaiian-rolls/', 2254)"
    )
    con.execute(
        "INSERT INTO ZREMCDOBJECT (Z_PK, ZURL, ZREMINDER3) VALUES "
        "(48, 'https://www.youtube.com/watch?v=P4Y17i9DW_M', 201)"
    )
    con.execute(
        "INSERT INTO ZREMCDOBJECT (Z_PK, ZURL, ZREMINDER2) VALUES "
        "(900, 'https://www.heb.com/recipe/x', 400)"
    )
    con.commit()
    con.close()


def test_resolves_share_sheet_url_by_identifier(tmp_path):
    db = tmp_path / "Data-test.sqlite"
    _make_store(db)
    urls = urls_by_identifier(list_name=LIST, stores_dir=tmp_path)
    assert urls["ID-SLIDER"] == "https://simplymadeeats.com/15205/chopped-italian-sliders-on-hawaiian-rolls/"


def test_matches_any_reminder_fk_column(tmp_path):
    db = tmp_path / "Data-test.sqlite"
    _make_store(db)
    urls = urls_by_identifier(list_name=LIST, stores_dir=tmp_path)
    # YouTube attachment links via ZREMINDER3, not ZREMINDER2
    assert urls["ID-YT"] == "https://www.youtube.com/watch?v=P4Y17i9DW_M"


def test_reminder_without_attachment_absent(tmp_path):
    db = tmp_path / "Data-test.sqlite"
    _make_store(db)
    urls = urls_by_identifier(list_name=LIST, stores_dir=tmp_path)
    assert "ID-PLAIN" not in urls


def test_filters_by_list_name(tmp_path):
    db = tmp_path / "Data-test.sqlite"
    _make_store(db)
    urls = urls_by_identifier(list_name=LIST, stores_dir=tmp_path)
    # 'Milk' is in the Groceries list, must be excluded
    assert "ID-MILK" not in urls


def test_merges_across_multiple_stores(tmp_path):
    _make_store(tmp_path / "Data-a.sqlite")
    # A second store with only unrelated tables should be skipped, not crash
    con = sqlite3.connect(str(tmp_path / "Data-b.sqlite"))
    con.execute("CREATE TABLE ZUNRELATED (Z_PK INTEGER)")
    con.commit()
    con.close()
    urls = urls_by_identifier(list_name=LIST, stores_dir=tmp_path)
    assert "ID-SLIDER" in urls


def test_missing_stores_dir_returns_empty(tmp_path):
    assert urls_by_identifier(list_name=LIST, stores_dir=tmp_path / "nope") == {}


def test_find_stores_lists_sqlite_files(tmp_path):
    _make_store(tmp_path / "Data-a.sqlite")
    (tmp_path / "Data-a.sqlite-wal").write_text("")  # non-.sqlite sidecar ignored
    stores = find_stores(tmp_path)
    assert len(stores) == 1
    assert stores[0].name == "Data-a.sqlite"
