"""Ranking/resolution tests for lib/fdc_local.resolve_local against a seeded store."""

import sqlite3
from datetime import datetime, timezone

from lib import fdc_local


def _store(rows):
    """rows: list of (fdc_id, data_type, description, kcal, pro, carb, fat, src)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    fdc_local.ensure_schema(conn)
    now = datetime.now(timezone.utc).isoformat()
    for fid, dt, desc, kcal, pro, carb, fat, src in rows:
        conn.execute(
            "INSERT INTO fdc_foods (fdc_id,data_type,description,name_norm,kcal_100g,"
            "kcal_source,protein_100g,carb_100g,fat_100g,brand_owner,dataset_rank,loaded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, dt, desc, fdc_local.normalize_food_name(desc), kcal, src,
             pro, carb, fat, None, fdc_local.DATASET_RANK[dt], now))
    conn.execute("INSERT INTO fdc_foods_fts(fdc_foods_fts) VALUES('rebuild')")
    conn.commit()
    return conn


def test_apple_resolves_to_raw_apple_not_strudel():
    conn = _store([
        (1, "survey_fndds_food", "Strudel, apple", 274, 3, 40, 12, "1008"),
        (2, "sr_legacy_food", "Apples, raw, with skin", 52, 0.3, 14, 0.2, "1008"),
    ])
    r = fdc_local.resolve_local(conn, "apple")
    assert r["description"] == "Apples, raw, with skin"


def test_olive_oil_prefers_caloric_over_zero_kcal_foundation():
    conn = _store([
        (1, "foundation_food", "Oil, olive, extra virgin", None, None, None, None, "none"),
        (2, "sr_legacy_food", "Oil, olive, salad or cooking", 884, 0, 0, 100, "1008"),
    ])
    r = fdc_local.resolve_local(conn, "olive oil")
    assert r["per_100g"]["calories"] == 884


def test_size_modifier_ignored_in_food_name():
    conn = _store([
        (1, "sr_legacy_food", "Apples, raw", 52, 0.3, 14, 0.2, "1008"),
        (2, "survey_fndds_food", "Rose-apples, raw", 25, 0.5, 5, 0.3, "1008"),
    ])
    r = fdc_local.resolve_local(conn, "medium apple")
    assert r["description"] == "Apples, raw"


def test_returns_none_when_no_match():
    conn = _store([(1, "sr_legacy_food", "Soy sauce", 53, 8, 5, 0, "1008")])
    assert fdc_local.resolve_local(conn, "mirin") is None
