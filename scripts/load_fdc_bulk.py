#!/usr/bin/env python3
"""Load a USDA FDC bulk dataset (unzipped CSV dir) into the local fdc_* tables.

Component B of nutrition-batch-ledger: materialize FDC into SQLite so food
resolution needs no runtime API. Streams the big CSVs (never reads them whole),
pre-computes per-100g macros via the same energy cascade as the live path
(food_db._energy_kcal: 1008 → 2047 → 2048 → Atwater), and replaces a dataset's
rows transactionally (delete-by-data_type + bulk insert) so reloads are idempotent.

Usage:
    .venv/bin/python scripts/load_fdc_bulk.py --csv-dir <unzipped_dataset_dir>
    # optionally restrict which food data_types to ingest:
    .venv/bin/python scripts/load_fdc_bulk.py --csv-dir <dir> --types foundation_food

FNDDS ships far smaller as JSON (64M vs 1.6G CSV) — see load_fndds_json (TODO).
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from lib import inventory_db
from lib.food_db import _energy_kcal, NUTRIENT_PROTEIN, NUTRIENT_CARBS, NUTRIENT_FAT
from lib import fdc_local

# The only nutrient IDs we materialize. Energy IDs are all KCAL; 1062 (kJ) is
# deliberately excluded (the kJ twin).
ENERGY_IDS = {1008, 2047, 2048}
MACRO_IDS = {NUTRIENT_PROTEIN, NUTRIENT_CARBS, NUTRIENT_FAT}
WANTED_NUTRIENTS = ENERGY_IDS | MACRO_IDS

REAL_FOOD_TYPES = {"foundation_food", "sr_legacy_food", "survey_fndds_food", "branded_food"}

csv.field_size_limit(10 * 1024 * 1024)


def _open(path):
    return open(path, encoding="utf-8", errors="replace", newline="")


def _load_measure_units(csv_dir):
    units = {}
    p = os.path.join(csv_dir, "measure_unit.csv")
    if not os.path.exists(p):
        return units
    with _open(p) as f:
        for row in csv.DictReader(f):
            units[row["id"]] = row["name"]
    return units


def _target_foods(csv_dir, types):
    """{fdc_id(str): (data_type, description)} for the wanted food data_types."""
    foods = {}
    with _open(os.path.join(csv_dir, "food.csv")) as f:
        for row in csv.DictReader(f):
            dt = row["data_type"]
            if dt in types:
                foods[row["fdc_id"]] = (dt, row["description"])
    return foods


def _accumulate_nutrients(csv_dir, target_ids):
    """{fdc_id(str): {nutrient_id(int): amount(float)}} over wanted nutrients only."""
    nutr = {}
    with _open(os.path.join(csv_dir, "food_nutrient.csv")) as f:
        for row in csv.DictReader(f):
            fid = row["fdc_id"]
            if fid not in target_ids:
                continue
            try:
                nid = int(row["nutrient_id"])
            except (ValueError, TypeError):
                continue
            if nid not in WANTED_NUTRIENTS:
                continue
            try:
                amt = float(row["amount"])
            except (ValueError, TypeError):
                continue
            nutr.setdefault(fid, {})[nid] = amt  # last value wins (deterministic)
    return nutr


def _kcal_source(nutrients):
    for nid in (1008, 2047, 2048):
        if nutrients.get(nid, 0):
            return str(nid)
    if any(nutrients.get(m, 0) for m in MACRO_IDS):
        return "atwater"
    return "none"


def _portions(csv_dir, target_ids, units):
    """[(fdc_id, portion_label, unit_norm, gram_weight, amount)] for target foods."""
    out = []
    p = os.path.join(csv_dir, "food_portion.csv")
    if not os.path.exists(p):
        return out
    with _open(p) as f:
        for row in csv.DictReader(f):
            fid = row["fdc_id"]
            if fid not in target_ids:
                continue
            try:
                gw = float(row["gram_weight"])
            except (ValueError, TypeError):
                continue
            if gw <= 0 or gw > 2000:  # band-check bad data
                continue
            uname = units.get(row.get("measure_unit_id", ""), "")
            modifier = row.get("modifier") or row.get("portion_description") or ""
            label = " ".join(x for x in (uname if uname != "undetermined" else "",
                                         modifier) if x).strip() or (uname or "portion")
            unit_norm = fdc_local.unit_from_portion(uname, modifier)
            try:
                amt = float(row.get("amount") or 1) or 1.0
            except (ValueError, TypeError):
                amt = 1.0
            out.append((int(fid), label, unit_norm, gw, amt))
    return out


def load_dataset(csv_dir, types, conn):
    now = datetime.now(timezone.utc).isoformat()
    units = _load_measure_units(csv_dir)
    foods = _target_foods(csv_dir, types)
    if not foods:
        return 0, 0
    nutrients = _accumulate_nutrients(csv_dir, set(foods))
    portions = _portions(csv_dir, set(foods), units)

    food_rows = []
    for fid, (dt, desc) in foods.items():
        nut = nutrients.get(fid, {})
        food_rows.append((
            int(fid), dt, desc, fdc_local.normalize_food_name(desc),
            _energy_kcal(nut) or None, _kcal_source(nut),
            nut.get(NUTRIENT_PROTEIN), nut.get(NUTRIENT_CARBS), nut.get(NUTRIENT_FAT),
            None, fdc_local.DATASET_RANK.get(dt, 9), now,
        ))

    present_types = {dt for dt, _ in foods.values()}
    cur = conn.cursor()
    cur.execute("BEGIN")
    for dt in present_types:
        cur.execute("DELETE FROM fdc_foods WHERE data_type = ?", (dt,))
        cur.execute(
            "DELETE FROM fdc_portions WHERE fdc_id IN "
            "(SELECT fdc_id FROM fdc_foods WHERE data_type = ?)", (dt,))
    cur.executemany(
        "INSERT OR REPLACE INTO fdc_foods (fdc_id,data_type,description,name_norm,"
        "kcal_100g,kcal_source,protein_100g,carb_100g,fat_100g,brand_owner,"
        "dataset_rank,loaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", food_rows)
    cur.executemany(
        "INSERT INTO fdc_portions (fdc_id,portion_label,unit_norm,gram_weight,amount) "
        "VALUES (?,?,?,?,?)", portions)
    for dt in present_types:
        cur.execute(
            "INSERT OR REPLACE INTO fdc_meta (dataset,release_date,loaded_at,row_count) "
            "VALUES (?,?,?,?)",
            (dt, os.path.basename(csv_dir), now,
             sum(1 for _, (d, _) in foods.items() if d == dt)))
    conn.commit()
    # Rebuild FTS from the content table.
    conn.execute("INSERT INTO fdc_foods_fts(fdc_foods_fts) VALUES('rebuild')")
    conn.commit()
    return len(food_rows), len(portions)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", required=True, help="unzipped FDC dataset dir")
    ap.add_argument("--types", default=None,
                    help="comma list of data_types (default: all real food types)")
    args = ap.parse_args()
    types = set(args.types.split(",")) if args.types else REAL_FOOD_TYPES

    conn = inventory_db.connect()
    fdc_local.ensure_schema(conn)
    nf, npn = load_dataset(args.csv_dir, types, conn)
    print(f"loaded {nf} foods, {npn} portions from {os.path.basename(args.csv_dir)}")


if __name__ == "__main__":
    main()
