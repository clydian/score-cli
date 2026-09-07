"""Paired notation operations resolve both ends before changing either."""

from .score_document import (
    ScoreError,
    child,
    children,
    content,
    insert_note,
    make,
    pitch_value,
)


def edit_note_pair(start, end, operation):
    family = operation["type"]
    number = operation.get("number")
    if (
        not isinstance(number, str)
        or not number.isdigit()
        or not 1 <= int(number) <= 16
        or type(operation.get("expected")) is not bool
        or type(operation.get("value")) is not bool
    ):
        raise ScoreError(
            "invalid-pair",
            "Pair needs number 1-16 and explicit boolean expected/value.",
        )
    if (
        start.element is end.element
        or start.location["partId"] != end.location["partId"]
        or start.location["voice"] != end.location["voice"]
        or (start.measure_ordinal, start.offset, start.location["eventIndex"])
        >= (end.measure_ordinal, end.offset, end.location["eventIndex"])
    ):
        raise ScoreError(
            "invalid-pair",
            "Endpoints must be ordered distinct notes in the same part and voice.",
        )
    if family == "tie":
        a, b = pitch_value(start.element), pitch_value(end.element)
        if (
            a is None
            or b is None
            or any(a[k] != b[k] for k in ("step", "alter", "octave"))
        ):
            raise ScoreError(
                "invalid-tie-pitch", "Tie endpoints need the same written pitch."
            )
    tag = "tied" if family == "tie" else "slur"
    endpoints = []
    for event, kind in [(start, "start"), (end, "stop")]:
        note = event.element
        found = [
            e
            for n in children(note, "notations")
            for e in children(n, tag)
            if e.get("type") == kind and e.get("number", "1") == number
        ]
        playback = (
            [e for e in children(note, "tie") if e.get("type") == kind]
            if family == "tie"
            else []
        )
        if len(found) > 1 or len(playback) > 1:
            raise ScoreError(
                "ambiguous-pair", "Duplicate endpoints cannot be edited unambiguously."
            )
        present = bool(found)
        if present != operation["expected"] or (
            family == "tie" and bool(playback) != present
        ):
            raise ScoreError(
                "old-value-mismatch",
                "Both notation and playback endpoints must match expected state.",
            )
        endpoints.append((note, kind, found, playback))
    if operation["expected"] == operation["value"]:
        raise ScoreError("no-op-pair", "Pair operation must change its state.")
    for note, kind, found, playback in endpoints:
        if not operation["value"]:
            for e in found + playback:
                parent = e.getparent()
                assert parent is not None
                parent.remove(e)
        else:
            notations = child(note, "notations")
            if notations is None:
                notations = make(note, "notations")
                insert_note(note, notations)
            notations.append(make(notations, tag, type=kind, number=number))
            if family == "tie":
                insert_note(note, make(note, "tie", type=kind))
