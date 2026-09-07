"""Explicit, validated part/measure alignment shared by compare and evidence."""

from collections import Counter

from .score_document import ScoreError


def location_key(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"partId", "printedMeasure"}
        or not all(isinstance(v, str) and v for v in value.values())
    ):
        raise ScoreError(
            "invalid-mapping",
            "Locations require exact partId and printedMeasure strings.",
        )
    return value["partId"], value["printedMeasure"]


def location(key):
    return dict(partId=key[0], printedMeasure=key[1])


def mapping_rows(before_keys, after_keys, mapping=None):
    left, right = set(before_keys), set(after_keys)
    if len(left) != len(before_keys) or len(right) != len(after_keys):
        raise ScoreError(
            "ambiguous-mapping", "Repeated part/measure labels cannot be aligned."
        )
    if mapping is not None and (
        not isinstance(mapping, dict) or not set(mapping) <= {"parts", "measures"}
    ):
        raise ScoreError("invalid-mapping", "Expected parts and/or measures mapping.")
    if mapping is not None and "measures" in mapping:
        rows = mapping["measures"]
        if not isinstance(rows, list):
            raise ScoreError("invalid-mapping", "Measures mapping must be an array.")
    else:
        parts = {} if mapping is None else mapping.get("parts", {})
        if (
            not isinstance(parts, dict)
            or not all(
                isinstance(k, str) and k and (v is None or isinstance(v, str) and v)
                for k, v in parts.items()
            )
            or not set(parts) <= {p for p, _ in left}
        ):
            raise ScoreError(
                "invalid-mapping", "Part map keys must name existing parts."
            )
        target_parts = [parts.get(p, p) for p in sorted({p for p, _ in left})]
        if len([p for p in target_parts if p is not None]) != len(
            {p for p in target_parts if p is not None}
        ):
            raise ScoreError(
                "ambiguous-mapping", "Part mapping has a destination collision."
            )
        rows = []
        used = set()
        for key in before_keys:
            candidate = (parts.get(key[0], key[0]), key[1])
            destination = candidate if candidate in right else None
            used.add(destination)
            rows.append(
                dict(
                    before=location(key),
                    after=None if destination is None else location(destination),
                )
            )
        rows.extend(
            dict(before=None, after=location(key))
            for key in after_keys
            if key not in used
        )
    seen_before: Counter = Counter()
    seen_after: Counter = Counter()
    destinations: dict = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not {"before", "after"} <= set(row)
            or not set(row) <= {"before", "after", "relation"}
            or row.get("relation") not in {None, "merged"}
            or (row["before"] is None and row["after"] is None)
        ):
            raise ScoreError(
                "invalid-mapping",
                "Each row must declare before and after locations or null.",
            )
        a = None if row["before"] is None else location_key(row["before"])
        b = None if row["after"] is None else location_key(row["after"])
        if a is not None:
            seen_before[a] += 1
        if b is not None:
            seen_after[b] += 1
            destinations.setdefault(b, []).append(row)
        if a is not None and a not in left or b is not None and b not in right:
            raise ScoreError(
                "mapping-target-missing",
                "Mapping endpoint does not exist in its input version.",
            )
    if (
        set(seen_before) != left
        or set(seen_after) != right
        or any(n != 1 for n in seen_before.values())
    ):
        raise ScoreError(
            "incomplete-mapping",
            "Explicit measure rows must account for every source and destination exactly once (except declared merges).",
        )
    for key, count in seen_after.items():
        if count > 1 and (
            not any(r.get("relation") == "merged" for r in destinations[key])
            or any(r["before"] is None for r in destinations[key])
        ):
            raise ScoreError(
                "ambiguous-mapping",
                "Destination collision requires an explicit merged relation.",
            )
    return rows
