"""Pure three-way field merge. Missing is distinct from an explicit null."""

from dataclasses import dataclass

from .models import validate_fields


@dataclass(frozen=True)
class MergeDecision:
    source_patch: dict
    apple_patch: dict
    conflicts: list[str]


def merge_fields(
    common: dict | None, source: dict, apple: dict | None
) -> MergeDecision:
    validate_fields(source)
    if apple is not None:
        validate_fields(apple)
    if common is None:
        # A marker without a common snapshot is unexplained, even when equal.
        return MergeDecision(
            {},
            dict(source) if apple is None else {},
            [] if apple is None else ["recovery"],
        )
    validate_fields(common)
    if apple is None:
        return MergeDecision({}, {}, ["recovery"])
    source_patch, apple_patch, conflicts = {}, {}, []
    missing = object()
    for key in sorted(common.keys() | source.keys() | apple.keys()):
        base, left, right = (
            common.get(key, missing),
            source.get(key, missing),
            apple.get(key, missing),
        )
        if left == right:
            continue
        if left == base and right is not missing:
            source_patch[key] = right
        elif right == base and left is not missing:
            apple_patch[key] = left
        else:
            # Omitting a previously known field is not authorization to clear it.
            conflicts.append(key)
    return MergeDecision(source_patch, apple_patch, conflicts)
