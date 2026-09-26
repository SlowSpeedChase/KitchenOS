"""Version-one weekly packet snapshots and sparse edits in the shared DB.

Generated rows have globally unique ``item_id`` values. Only direct fields in
``EDITABLE_FIELDS`` can be patched; source identities and nested paths cannot.
An edit value of JSON null deletes that override, including orphaned overrides.
Reads return the generated document with edits applied plus repository metadata,
``edits``, ``store_snapshot``, and recoverable orphan changes in ``needs_review``.
This module never writes inventory, cook schedules, or recipes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
import re

from lib import inventory_db

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_GENERATED_ITEMS = 2000
MAX_STRING_LENGTH = 10000
EDITABLE_FIELDS = frozenset({
    "text", "notes", "amount", "quantity", "unit", "date", "start", "time",
    "duration_minutes", "phase", "done",
})
_PHASES = {"prep_or_flavor_base", "cook", "finish_and_taste", "freeze_and_store", "reheat", "instructions"}
_RESERVED = {"revision", "edits", "store_snapshot", "generated_at", "store_refreshed_at", "reviewed_at", "updated_at"}


class RevisionConflict(ValueError):
    """The caller's revision no longer matches the saved packet."""


def _validate_week(week: str) -> None:
    if not isinstance(week, str) or not re.fullmatch(r"[0-9]{4}-W[0-9]{2}", week):
        raise ValueError("week must be an ISO week key (YYYY-Www)")
    try:
        date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    except ValueError as exc:
        raise ValueError("invalid ISO week") from exc


def _json(value) -> str:
    """Validate JSON and every key/value string before serializing."""
    def visit(node):
        if isinstance(node, str):
            if len(node) > MAX_STRING_LENGTH:
                raise ValueError("string exceeds 10,000 characters")
        elif node is None or type(node) in (bool, int):
            pass
        elif type(node) is float:
            if not math.isfinite(node):
                raise ValueError("JSON numbers must be finite")
        elif isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                visit(key)
                visit(child)
        else:
            raise ValueError("document must contain only JSON values")

    try:
        visit(value)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError("serialized packet exceeds 2 MiB")
        return encoded
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid JSON document") from exc


def _validate_document(document: dict) -> None:
    if not isinstance(document, dict) or type(document.get("version")) is not int or document["version"] != 1:
        raise ValueError("document version must be 1")
    _json(document)


def _items(document: dict) -> dict[str, dict]:
    result = {}
    count = 0

    def walk(node, in_list=False):
        nonlocal count
        if isinstance(node, dict):
            if in_list or "item_id" in node:
                count += 1
                if count > MAX_GENERATED_ITEMS:
                    raise ValueError("generated document exceeds 2,000 items")
            if "item_id" in node:
                item_id = node["item_id"]
                if not isinstance(item_id, str) or not item_id:
                    raise ValueError("item_id must be a nonempty string")
                if item_id in result:
                    raise ValueError("generated item_id values must be globally unique")
                result[item_id] = node
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child, in_list=True)

    walk(document)
    return result


def _validate_generated(week: str, generated: dict) -> None:
    _validate_document(generated)
    if generated.get("week", week) != week:
        raise ValueError("generated week does not match the packet key")
    if _RESERVED.intersection(generated):
        raise ValueError("generated document contains repository-owned fields")
    if "status" in generated:
        _validate_status(generated["status"])
    if "needs_review" in generated and not isinstance(generated["needs_review"], list):
        raise ValueError("needs_review must be a list")
    _items(generated)


def _validate_status(status: str) -> None:
    if status not in ("draft", "reviewed"):
        raise ValueError("status must be draft or reviewed")


def _validate_revision(revision: int) -> None:
    if type(revision) is not int or revision < 1:
        raise ValueError("expected_revision must be a positive integer")


def _decode(row) -> dict:
    packet = dict(row)
    for column, key in (("generated_json", "generated"), ("edits_json", "edits"),
                        ("store_snapshot_json", "store_snapshot"), ("request_ids_json", "request_ids")):
        packet[key] = json.loads(packet.pop(column))
    return packet


def _read(conn, week: str, expected_revision: int | None = None) -> dict | None:
    row = conn.execute("SELECT * FROM cooking_packets WHERE week = ?", (week,)).fetchone()
    if row is None:
        if expected_revision is not None:
            raise KeyError(week)
        return None
    packet = _decode(row)
    if expected_revision is not None and packet["revision"] != expected_revision:
        raise RevisionConflict(f"expected revision {expected_revision}; current revision is {packet['revision']}")
    return packet


def _merged(packet: dict) -> dict:
    document = deepcopy(packet["generated"])
    items = _items(document)
    needs_review = document.setdefault("needs_review", [])
    for edit in packet["edits"]:
        item = items.get(edit["item_id"])
        if item is None:
            needs_review.append({**deepcopy(edit), "reason": "Source item no longer exists"})
        else:
            item[edit["field"]] = deepcopy(edit["value"])
    document.update({key: deepcopy(value) for key, value in packet.items() if key not in {"generated", "request_ids"}})
    return document


def _save(conn, packet: dict) -> None:
    # Bound the total stored JSON, not just each independently bounded component.
    _json({key: packet[key] for key in ("generated", "edits", "store_snapshot", "request_ids")})
    _json(_merged(packet))
    conn.execute(
        "INSERT INTO cooking_packets (week, generated_json, edits_json, store_snapshot_json, request_ids_json,"
        " status, generated_at, store_refreshed_at, reviewed_at, updated_at, revision)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(week) DO UPDATE SET generated_json=excluded.generated_json, edits_json=excluded.edits_json,"
        " store_snapshot_json=excluded.store_snapshot_json, request_ids_json=excluded.request_ids_json,"
        " status=excluded.status, generated_at=excluded.generated_at, store_refreshed_at=excluded.store_refreshed_at,"
        " reviewed_at=excluded.reviewed_at, updated_at=excluded.updated_at, revision=excluded.revision",
        (packet["week"], _json(packet["generated"]), _json(packet["edits"]), _json(packet["store_snapshot"]),
         _json(packet["request_ids"]), packet["status"], packet["generated_at"], packet["store_refreshed_at"],
         packet["reviewed_at"], packet["updated_at"], packet["revision"]),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_packet(week: str) -> dict | None:
    """Read the committed packet, applying active edits and exposing orphans."""
    _validate_week(week)
    conn = inventory_db.connect()
    try:
        packet = _read(conn, week)
        return _merged(packet) if packet else None
    finally:
        conn.close()


def replace_generated(week: str, generated: dict, request_id: str | None = None) -> dict:
    """Replace sources while preserving edits; a committed request ID is a no-op."""
    _validate_week(week)
    _validate_generated(week, generated)
    if request_id is not None:
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be a nonempty string")
        _json(request_id)
    with inventory_db.write_transaction() as conn:
        packet = _read(conn, week)
        if packet is None:
            now = _now()
            packet = {"week": week, "generated": {}, "edits": [], "store_snapshot": {"version": 1},
                      "request_ids": [], "status": "draft", "generated_at": now, "store_refreshed_at": None,
                      "reviewed_at": None, "updated_at": now, "revision": 0}
        repeated = request_id is not None and request_id in packet["request_ids"]
        changed = packet["generated"] != generated or packet["status"] != "draft" or request_id is not None
        if not repeated and changed:
            packet["generated"] = deepcopy(generated)
            packet.update(status="draft", reviewed_at=None, generated_at=_now(), updated_at=_now(), revision=packet["revision"] + 1)
            if request_id is not None:
                packet["request_ids"].append(request_id)
            _save(conn, packet)
    return get_packet(week)


def _validate_changes(changes: list[dict], items: dict[str, dict], overrides: set[tuple[str, str]]) -> None:
    if not isinstance(changes, list):
        raise ValueError("changes must be a list")
    _json(changes)
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"item_id", "field", "value"}:
            raise ValueError("each change must contain exactly item_id, field, value")
        item_id, field, value = change["item_id"], change["field"], change["value"]
        if not isinstance(field, str) or field not in EDITABLE_FIELDS:
            raise ValueError("field is not editable")
        if not isinstance(item_id, str) or (
            item_id not in items and (value is not None or (item_id, field) not in overrides)
        ):
            raise ValueError("change item_id is not in the generated document or a saved override")
        if value is None:
            continue
        if field == "done" and type(value) is not bool:
            raise ValueError("done must be a boolean")
        if field in {"text", "notes", "unit", "date", "start", "time"} and not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        if field == "date":
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError as exc:
                raise ValueError("date must be YYYY-MM-DD") from exc
        if field == "duration_minutes" and (type(value) is not int or not 1 <= value <= 1440):
            raise ValueError("duration_minutes must be an integer from 1 to 1440")
        if field in {"amount", "quantity"} and (type(value) not in (int, float, str) or (type(value) in (int, float) and value < 0)):
            raise ValueError(f"{field} must be a nonnegative number or quantity string")
        if field == "phase" and (not isinstance(value, str) or value not in _PHASES):
            raise ValueError("phase must be a canonical phase")


def patch_packet(week: str, expected_revision: int, changes: list[dict], status: str | None = None) -> dict:
    """Commit field overrides or null deletions against one saved revision."""
    _validate_week(week)
    _validate_revision(expected_revision)
    if status is not None:
        _validate_status(status)
    with inventory_db.write_transaction() as conn:
        packet = _read(conn, week, expected_revision)
        edits = {(edit["item_id"], edit["field"]): edit for edit in packet["edits"]}
        _validate_changes(changes, _items(packet["generated"]), set(edits))
        for change in changes:
            key = (change["item_id"], change["field"])
            if change["value"] is None:
                edits.pop(key, None)
            else:
                edits[key] = deepcopy(change)
        packet["edits"] = list(edits.values())
        packet["status"] = status or "draft"
        packet["reviewed_at"] = _now() if packet["status"] == "reviewed" else None
        packet["revision"] += 1
        packet["updated_at"] = _now()
        _save(conn, packet)
    return get_packet(week)


def replace_store_snapshot(week: str, expected_revision: int, snapshot: dict) -> dict:
    """Replace retailer evidence without changing sources or sparse edits."""
    _validate_week(week)
    _validate_revision(expected_revision)
    _validate_document(snapshot)
    with inventory_db.write_transaction() as conn:
        packet = _read(conn, week, expected_revision)
        if packet["store_snapshot"] != snapshot or packet["status"] != "draft":
            packet["store_snapshot"] = deepcopy(snapshot)
            packet.update(status="draft", reviewed_at=None, store_refreshed_at=_now(), updated_at=_now(), revision=packet["revision"] + 1)
            _save(conn, packet)
    return get_packet(week)


def retailer_preferences() -> dict[str, dict]:
    """Return approved store locations and named recommendation policies."""
    conn = inventory_db.connect()
    try:
        result = {}
        for row in conn.execute("SELECT * FROM retailer_preferences ORDER BY preference_rank, retailer"):
            preference = dict(row)
            preference["policy"] = json.loads(preference.pop("policy_json"))
            result[preference.pop("retailer")] = preference
        return result
    finally:
        conn.close()
