"""Shopping row identities and the single generation/confirmation writer.

Reads never migrate notes. Explicit saves assign identities to legacy/manual
rows and preserve checked progress, duplicates, and inventory-only bullets.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import re
from uuid import uuid4

from lib import paths
from lib.apple_integration.models import RevisionConflict, canonical_json
from lib.ingredient_aggregator import (
    format_ingredient,
    get_unit_family,
    parse_amount_to_float,
)
from lib.ingredient_normalizer import normalize_name
from lib.ingredient_parser import parse_ingredient_best
from lib.note_mutation import content_hash, mutate_note
from lib.safe_paths import shopping_list_path

_MARKER = re.compile(
    r"\s*<!-- kitchenos-item:((?:gen|manual):[A-Za-z0-9_-]{1,64}) -->\s*$"
)
_METADATA = re.compile(r"<!-- kitchenos-shopping-v3:([A-Za-z0-9_=-]+) -->")
_LEGACY = re.compile(r"<!-- kitchenos-generated-items(-v2)?:([A-Za-z0-9_=-]+) -->")
_CHECK = re.compile(r"^- \[([ xX])\] (.*)$")


@dataclass(frozen=True)
class ShoppingRow:
    id: str
    kind: str
    text: str
    completed: bool
    identity: str | None


@dataclass
class ShoppingDocument:
    rows: list[ShoppingRow]
    content_hash: str
    metadata: dict = field(default_factory=dict)
    issues: dict[str, str] = field(default_factory=dict)


def strip_item_marker(text: str) -> str:
    """Keep hidden IDs out of legacy displays and one-way Reminders exports."""
    return _MARKER.sub("", text).strip()


def _decode(payload):
    return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))


def _encode(payload):
    return base64.urlsafe_b64encode(canonical_json(payload).encode("utf-8")).decode(
        "ascii"
    )


def generated_identity(line: dict) -> str:
    """Identity is ingredient plus aggregator bucket, never rendered quantity."""
    needed = line.get("needed") or line.get("to_buy") or {}
    unit = needed.get("unit") or ""
    family = get_unit_family(unit)
    if parse_amount_to_float(needed.get("amount")) is None:
        family = "no_amount"
    elif family == "other":
        family += ":" + unit.lower()
    return canonical_json([normalize_name(line.get("item") or ""), family])


def _text_identity(text):
    parsed = parse_ingredient_best(text)
    return generated_identity({"item": parsed.get("item") or text, "needed": parsed})


def _id(identity):
    return "gen:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def parse_document(content: str) -> ShoppingDocument:
    """Parse rows without assigning IDs. Duplicate/malformed markers fail closed."""
    matches = list(_METADATA.finditer(content))
    metadata = {}
    try:
        if len(matches) > 1 or ("kitchenos-shopping-v3:" in content and not matches):
            raise ValueError()
        if matches:
            metadata = _decode(matches[0][1])
            if not isinstance(metadata, dict) or not isinstance(
                metadata.get("rows"), dict
            ):
                raise ValueError()
    except (ValueError, UnicodeError, TypeError) as exc:
        raise RevisionConflict("Shopping metadata cannot be safely parsed") from exc
    rows, seen, issues = [], set(), {}
    for line in content.splitlines():
        check = _CHECK.fullmatch(line)
        if not check:
            if "kitchenos-item:" in line:
                raise RevisionConflict("Item marker is outside a checkbox")
            continue
        raw, completed = check[2], check[1].lower() == "x"
        marker = _MARKER.search(raw)
        if "kitchenos-item:" in raw and (
            not marker or raw.count("kitchenos-item:") != 1
        ):
            raise RevisionConflict("Malformed item marker")
        text = strip_item_marker(raw)
        if not text:
            continue
        ident = marker[1] if marker else ""
        if ident and ident in seen:
            raise RevisionConflict("Duplicate shopping item ID")
        seen.add(ident)
        snapshot = metadata.get("rows", {}).get(ident, {})
        if not isinstance(snapshot, dict):
            raise RevisionConflict("Invalid row snapshot")
        kind = ident.split(":", 1)[0] if ident else "legacy"
        identity = snapshot.get("identity")
        if ident and not snapshot:
            raise RevisionConflict("Marked row has no identity snapshot")
        if kind == "gen":
            if not isinstance(identity, str) or _id(identity) != ident:
                raise RevisionConflict("Generated ID does not match its identity")
            if _text_identity(text) != snapshot.get("text_identity"):
                issues[ident] = "shopping_identity_changed"
            elif text != snapshot.get("text"):
                issues[ident] = "shopping_amount_changed"
        if "conflict" in snapshot:
            conflict = snapshot["conflict"]
            if (
                kind != "gen"
                or not isinstance(conflict, str)
                or conflict
                not in {"shopping_amount_changed", "shopping_identity_changed"}
            ):
                raise RevisionConflict("Invalid shopping conflict marker")
            issues.setdefault(ident, conflict)
        rows.append(ShoppingRow(ident, kind, text, completed, identity))
    return ShoppingDocument(rows, content_hash(content), metadata, issues)


def read_shopping_note(week: str) -> ShoppingDocument:
    path = shopping_list_path(paths.shopping_lists_dir(), week)
    return parse_document(path.read_bytes().decode("utf-8"))


def _render(week, rows, snapshots, inventory_matches):
    from templates.shopping_list_template import generate_shopping_list_markdown

    return generate_shopping_list_markdown(
        week,
        [],
        inventory_matches=inventory_matches,
        generated_items=[r.text for r in rows if r.kind == "gen"],
        shopping_rows=rows,
        shopping_metadata=_encode({"rows": snapshots}),
    )


def save_shopping_note(
    week: str,
    generated_lines: list[dict],
    inventory_matches: list[dict | str],
    selected_items: list[str] | None = None,
) -> ShoppingDocument:
    """Save generated demand and preserve explicit manual and completed rows.

    Selection is a multiset: identical manual additions are never collapsed.
    A selected title without structured generation evidence is manual.
    """
    from lib.shopping_list_generator import (
        shopping_sections,
        extract_legacy_manual_items,
    )

    path = shopping_list_path(paths.shopping_lists_dir(), week)
    try:
        before = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        before = ""
    if selected_items is not None and (
        not isinstance(selected_items, list)
        or any(
            not isinstance(x, str) or "\n" in x or "<!--" in x for x in selected_items
        )
    ):
        raise ValueError("Selected items must be single-line text")
    inventory_matches = [
        note
        for match in inventory_matches
        for note in (
            shopping_sections([match])["inventory_matches"]
            if isinstance(match, dict)
            else [match]
        )
    ]
    if any(not isinstance(x, str) or "\n" in x for x in inventory_matches):
        raise ValueError("Inventory matches must be single-line text")

    def transform(content):
        old = parse_document(content)
        if any(issue == "shopping_identity_changed" for issue in old.issues.values()):
            raise RevisionConflict(
                "Generated shopping identity changed; preserve and resolve the note"
            )
        old_by_id = {r.id: r for r in old.rows if r.id}
        snapshots = dict(old.metadata.get("rows", {}))
        # A hand-edited checked amount may already match the new demand. Keep
        # its unresolved evidence before replacing the generated text snapshot.
        for row_id, issue in old.issues.items():
            snapshot = dict(snapshots[row_id])
            snapshot["conflict"] = issue
            snapshot.setdefault("previous_text", snapshot["text"])
            snapshots[row_id] = snapshot
        purchase = []
        for line in generated_lines:
            identity = generated_identity(line)
            ident = _id(identity)
            texts = shopping_sections([line])["purchase"]
            if texts:
                if any(r.id == ident for r in purchase):
                    raise RevisionConflict(
                        "Ambiguous duplicate generated ingredient bucket"
                    )
                purchase.append(ShoppingRow(ident, "gen", texts[0], False, identity))
        legacy_match = _LEGACY.search(content)
        previous = None
        if legacy_match:
            try:
                decoded = _decode(legacy_match[2])
                if not isinstance(decoded, list) or any(
                    not isinstance(x, str) for x in decoded
                ):
                    raise ValueError("Expected generated-item list")
                previous = Counter(decoded)
            except (TypeError, ValueError, UnicodeError):
                raise RevisionConflict("Legacy provenance is malformed")
        selected = Counter(selected_items) if selected_items is not None else None
        manual = []
        # Assign provenance once, during explicit save only.
        current_texts = {
            text
            for line in generated_lines
            for text in (
                format_ingredient(
                    {"item": line.get("item", ""), **(line.get("needed") or {})}
                ),
                *shopping_sections([line])["purchase"],
            )
        }
        claimed = set(old_by_id)
        for row in old.rows:
            if row.id:
                if row.kind == "manual":
                    manual.append(row)
                continue
            generated = bool(previous is not None and previous[row.text] > 0)
            if generated:
                previous[row.text] -= 1
            elif previous is None:
                generated = row.text in current_texts
            if not generated and (previous is None or not legacy_match[1]):
                generated = not extract_legacy_manual_items([row.text], generated_lines)
            if generated:
                identity = _text_identity(row.text)
                ident = _id(identity)
                if ident not in claimed:
                    migrated = ShoppingRow(
                        ident, "gen", row.text, row.completed, identity
                    )
                    old_by_id[ident] = migrated
                    claimed.add(ident)
                else:
                    manual.append(
                        ShoppingRow(
                            "manual:" + uuid4().hex,
                            "manual",
                            row.text,
                            row.completed,
                            None,
                        )
                    )
            else:
                manual.append(
                    ShoppingRow(
                        "manual:" + uuid4().hex, "manual", row.text, row.completed, None
                    )
                )
        result = []
        for row in purchase:
            if selected is not None:
                if selected[row.text] <= 0:
                    continue
                selected[row.text] -= 1
            prior = old_by_id.get(row.id)
            was_retired = snapshots.get(row.id, {}).get("retired") is True
            completed = prior.completed if prior and not was_retired else False
            # Preserve hand-edited text while retaining the new generated
            # demand separately for an explicit Keep KitchenOS resolution.
            edited = prior is not None and not was_retired and row.id in old.issues
            text = prior.text if edited else row.text
            result.append(ShoppingRow(row.id, row.kind, text, completed, row.identity))
            snap = dict(snapshots.get(row.id, {}))
            if was_retired:
                snap.pop("conflict", None)
                snap.pop("previous_text", None)
            if prior and completed and prior.text != row.text:
                snap["conflict"] = "shopping_amount_changed"
                snap.setdefault("previous_text", prior.text)
            snap.update(
                identity=row.identity,
                text=row.text,
                text_identity=_text_identity(row.text),
                retired=False,
            )
            snapshots[row.id] = snap
        result_ids = {r.id for r in result}
        # Checked history and unresolved hand edits remain visible even when
        # generated demand disappears; regeneration must not discard evidence.
        for row in old_by_id.values():
            if (
                row.kind == "gen"
                and (row.completed or row.id in old.issues)
                and row.id not in result_ids
            ):
                result.append(row)
                snapshots[row.id] = {
                    **snapshots.get(row.id, {}),
                    "identity": row.identity,
                    "text": row.text,
                    "text_identity": _text_identity(row.text),
                    "retired": True,
                }
        result.extend(manual)
        for row in manual:
            if selected is not None and selected[row.text] > 0:
                selected[row.text] -= 1
        if selected is not None:
            for text in selected_items:
                if selected[text] > 0:
                    result.append(
                        ShoppingRow(
                            "manual:" + uuid4().hex, "manual", text, False, None
                        )
                    )
                    selected[text] -= 1
        for row in result:
            if row.kind == "manual":
                snapshots[row.id] = {"identity": None, "text": row.text}
        snapshots = {r.id: snapshots[r.id] for r in result}
        return _render(week, result, snapshots, inventory_matches)

    mutate_note(path, content_hash(before), transform, str(uuid4()))
    return read_shopping_note(week)


def set_completed(content: str, row_id: str, completed: bool) -> str:
    """Replace only the exact unique ID; never search by visible title."""
    doc = parse_document(content)
    matches = [r for r in doc.rows if r.id == row_id]
    if len(matches) != 1 or row_id in doc.issues:
        raise RevisionConflict("Shopping row missing, ambiguous, or conflicted")
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        marker = _MARKER.search(line.rstrip("\r\n"))
        if marker and marker[1] == row_id:
            lines[index] = line[:3] + ("x" if completed else " ") + line[4:]
    return "".join(lines)
