"""Transactional MusicXML editing through a single public interface."""

from __future__ import annotations

import json
from collections import Counter
from fractions import Fraction
import os
import tempfile
from importlib.metadata import version
from pathlib import Path

from .score_document import (
    ScoreDocument,
    ScoreError,
    child,
    children,
    content,
    insert_note,
    make,
    pitch_value,
    replace_note_children,
    sha256,
    placed_offsets,
)

from .validation import validate_document, notation_duration
from .compare import compare_documents
from .symbol_edits import edit_note_pair
from .direction_edits import resolve_direction, edit_dynamics, edit_wedge

EditError = ScoreError


def publish_files(files: dict[Path, bytes]) -> None:
    """No-clobber publication. Roll back our links if any publication fails."""
    staged: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for destination, data in files.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                staged.append((temporary, destination))
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for temporary, destination in staged:
            os.link(temporary, destination)
            published.append(destination)
    except BaseException:
        for destination in published:
            destination.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def edit_score(
    *,
    input_path: str | Path,
    changeset: dict,
    output_path: str | Path,
    dry_run: bool = False,
) -> dict:
    source, destination = Path(input_path), Path(output_path)
    report_path = Path(str(destination) + ".edit.json")
    if (
        destination.resolve() == source.resolve()
        or destination.exists()
        or report_path.exists()
    ):
        raise EditError("output-conflict", "Output score and report must be new files.")
    if destination.suffix.lower() not in {".xml", ".musicxml"}:
        raise EditError(
            "unsupported-output", "Output must be uncompressed .xml or .musicxml."
        )
    input_data = source.read_bytes()
    input_hash = sha256(input_data)
    if not isinstance(changeset, dict) or set(changeset) != {
        "schemaVersion",
        "inputSha256",
        "operations",
    }:
        raise EditError(
            "invalid-changeset",
            "Expected schemaVersion, inputSha256 and operations only.",
        )
    if changeset.get("schemaVersion") != "1":
        raise EditError("unsupported-contract", "Expected changeset schemaVersion 1.")
    if changeset.get("inputSha256") != input_hash:
        raise EditError(
            "stale-input", "Changeset SHA-256 does not match the input snapshot."
        )
    operations = changeset.get("operations")
    if not isinstance(operations, list) or not operations:
        raise EditError(
            "invalid-changeset", "Expected a nonempty ordered operations array."
        )
    document = ScoreDocument.read(source, data=input_data)
    placement_before = placed_offsets(document)
    before = ScoreDocument(document.serialize())
    diagnostics_before = validate_document(before)["diagnostics"]
    resolved: list = []
    direction_cache: dict = {}
    ids = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise EditError("invalid-operation", "Each operation must be an object.")
        op_id = operation.get("id")
        try:
            if not isinstance(op_id, str) or not op_id or op_id in ids:
                raise EditError(
                    "invalid-operation-id", "Operation IDs must be nonempty and unique."
                )
            ids.add(op_id)
            if "expected" not in operation or "value" not in operation:
                raise EditError(
                    "invalid-operation", "Explicit expected and value are required."
                )
            if operation.get("type") not in {
                "pitch",
                "lyric",
                "duration",
                "voice",
                "staff",
                "kind",
                "tie",
                "slur",
                "dynamics",
                "wedge",
            }:
                raise EditError("unsupported-operation", "Unsupported operation type.")
            if operation["type"] == "dynamics":
                resolved.append(
                    (
                        operation,
                        resolve_direction(
                            document, operation["target"], direction_cache
                        ),
                    )
                )
            elif operation["type"] == "wedge":
                resolved.append(
                    (
                        operation,
                        (
                            resolve_direction(
                                document, operation["start"], direction_cache
                            ),
                            resolve_direction(
                                document, operation["end"], direction_cache
                            ),
                        ),
                    )
                )
            elif operation["type"] in {"tie", "slur"}:
                resolved.append(
                    (
                        operation,
                        (
                            document.locate(operation["start"]),
                            document.locate(operation["end"]),
                        ),
                    )
                )
            else:
                resolved.append((operation, document.locate(operation["target"])))
        except ScoreError as exc:
            exc.diagnostic["operationId"] = op_id
            raise
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise EditError("invalid-operation", str(exc), operation_id=op_id) from exc
    for operation, event in resolved:
        try:
            if operation["type"] == "dynamics":
                edit_dynamics(event, operation)
                continue
            if operation["type"] == "wedge":
                edit_wedge(event[0], event[1], operation)
                continue
            if operation["type"] in {"tie", "slur"}:
                edit_note_pair(event[0], event[1], operation)
                continue
            note = event.element
            if operation["type"] in {"voice", "staff", "kind"}:
                _edit_note_identity(event, operation)
                continue
            if operation["type"] == "duration":
                _edit_duration(event, operation)
                continue
            if operation["type"] == "lyric":
                _edit_lyric(note, operation)
                continue
            if pitch_value(note) != operation.get("expected"):
                raise EditError(
                    "old-value-mismatch",
                    "Expected value differs from the state before this operation.",
                    event.location,
                )
            if child(note, "tie") is not None or note.findall(".//{*}tied"):
                raise EditError(
                    "unsupported-tied-pitch",
                    "Remove or repair the entire tie pair before changing pitch.",
                    event.location,
                )
            value = operation["value"]
            if (
                set(value) != {"step", "alter", "octave", "accidental"}
                or value["step"] not in list("ABCDEFG")
                or type(value["octave"]) is not int
                or not 0 <= value["octave"] <= 9
            ):
                raise EditError(
                    "invalid-pitch",
                    "Expected step A-G, alter, octave 0-9 and explicit accidental.",
                )
            from fractions import Fraction

            alter = Fraction(value["alter"])
            if alter.denominator != 1:
                raise EditError(
                    "unsupported-pitch", "Microtonal pitch editing is unsupported."
                )
            pitch = child(note, "pitch")
            if pitch is None:
                raise EditError(
                    "target-kind", "Pitch operation requires an existing pitched note."
                )
            for tag in ("step", "alter", "octave"):
                existing = child(pitch, tag)
                text = str(alter) if tag == "alter" else str(value[tag])
                if existing is not None:
                    existing.text = text
                else:
                    element = make(pitch, tag, text)
                    pitch.insert(1 if tag == "alter" else len(pitch), element)
            accidental = value["accidental"]
            if accidental not in {
                None,
                "sharp",
                "flat",
                "natural",
                "double-sharp",
                "flat-flat",
            }:
                raise EditError(
                    "unsupported-accidental", "Unsupported explicit display accidental."
                )
            if (
                accidental is not None
                and {
                    "sharp": 1,
                    "flat": -1,
                    "natural": 0,
                    "double-sharp": 2,
                    "flat-flat": -2,
                }[accidental]
                != alter
            ):
                raise EditError(
                    "accidental-pitch-mismatch",
                    "Explicit accidental must agree with pitch alter.",
                )
            replace_note_children(
                note,
                "accidental",
                [] if accidental is None else [make(note, "accidental", accidental)],
            )
        except ScoreError as exc:
            exc.diagnostic["operationId"] = operation["id"]
            raise
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise EditError(
                "invalid-operation", str(exc), operation_id=operation["id"]
            ) from exc
    diagnostics_after = validate_document(document)["diagnostics"]
    signature = lambda d: json.dumps(
        {k: d[k] for k in ("code", "severity", "location", "reason")}, sort_keys=True
    )
    remaining = Counter(signature(d) for d in diagnostics_before)
    for diagnostic in diagnostics_after:
        key = signature(diagnostic)
        diagnostic["origin"] = "existing" if remaining[key] else "new-or-unmatched"
        if remaining[key]:
            remaining[key] -= 1
        elif diagnostic["severity"] in {"error", "warning"}:
            raise EditError(
                "introduced-diagnostic",
                "Edit introduces or cannot safely match a diagnostic: "
                + diagnostic["code"]
                + " "
                + diagnostic["reason"],
                diagnostic["location"],
                ",".join(op["id"] for op in operations),
            )
    for element, offset in placed_offsets(document).items():
        if element in placement_before and placement_before[element] != offset:
            raise EditError(
                "unrelated-direction-moved",
                "Duration edit would move an existing direction/harmony; use a timeline-preserving operation sequence.",
            )
    data = document.serialize()
    report: dict = dict(
        schemaVersion="1",
        toolVersion=version("score-cli"),
        inputPath=str(source.resolve()),
        outputPath=str(destination.resolve()),
        reportPath=str(report_path.resolve()),
        status="dry-run" if dry_run else "applied",
        inputSha256=input_hash,
        outputSha256=sha256(data),
        changeset=changeset,
        diagnosticsBefore=diagnostics_before,
        diagnosticsAfter=diagnostics_after,
        diagnosticMatching="exact-code-severity-location-reason-multiset",
        comparison=compare_documents(before, document),
    )
    if not dry_run:
        publish_files({report_path: json_bytes(report), destination: data})
    return report


def _edit_lyric(note, operation):
    selector = operation.get("selector", {})
    if (
        not selector
        or not set(selector) <= {"number", "name"}
        or not all(isinstance(v, str) and v for v in selector.values())
    ):
        raise EditError(
            "invalid-lyric-selector", "Specify a nonempty lyric number and/or name."
        )
    matches = [
        e
        for e in children(note, "lyric")
        if all(e.get(k) == v for k, v in selector.items())
    ]
    if len(matches) > 1:
        raise EditError(
            "ambiguous-lyric", "Lyric selector matches more than one lyric."
        )
    lyric = matches[0] if matches else None
    if lyric is not None and (
        len(children(lyric, "text")) != 1
        or any(
            child(lyric, tag) is not None
            for tag in ("elision", "extend", "humming", "laughing")
        )
    ):
        raise EditError(
            "unsupported-lyric",
            "Complex lyrics require a lossless lyric operation not supported by version 1.",
        )
    old = (
        None
        if lyric is None
        else dict(
            text=content(lyric, "text"), syllabic=content(lyric, "syllabic") or None
        )
    )
    if old != operation.get("expected"):
        raise EditError(
            "old-value-mismatch", "Lyric expected value differs from current state."
        )
    value = operation.get("value")
    if value is None:
        if lyric is None:
            raise EditError("target-missing", "Cannot delete a missing lyric.")
        note.remove(lyric)
        return
    if (
        not isinstance(value, dict)
        or set(value) != {"text", "syllabic"}
        or not isinstance(value["text"], str)
        or value["syllabic"] not in {None, "single", "begin", "middle", "end"}
    ):
        raise EditError("invalid-lyric", "Expected text and explicit syllabic value.")
    if lyric is None:
        lyric = make(note, "lyric", **selector)
        insert_note(note, lyric)
    for tag in ("text", "syllabic"):
        item = child(lyric, tag)
        text = value[tag]
        if text is None:
            if item is not None:
                lyric.remove(item)
        elif item is not None:
            item.text = text
        else:
            anchor = child(lyric, "text") if tag == "syllabic" else None
            lyric.insert(
                lyric.index(anchor) if anchor is not None else len(lyric),
                make(lyric, tag, text),
            )


def _duration_value(event):
    note = event.element
    modification = child(note, "time-modification")
    ratio = (
        None
        if modification is None
        else dict(
            actualNotes=int(content(modification, "actual-notes")),
            normalNotes=int(content(modification, "normal-notes")),
        )
    )
    return dict(
        duration=str(Fraction(content(note, "duration", "0")) / event.divisions),
        type=content(note, "type") or None,
        dots=len(children(note, "dot")),
        timeModification=ratio,
    )


def _edit_duration(event, operation):
    note = event.element
    if operation.get("timeline") != "shift-following":
        raise EditError(
            "unsupported-timeline-policy",
            "Duration requires explicit timeline=shift-following.",
        )
    if child(note, "grace") is not None:
        raise EditError(
            "unsupported-grace-duration", "Grace notes have no timeline duration."
        )
    if _duration_value(event) != operation.get("expected"):
        raise EditError(
            "old-value-mismatch",
            "Duration expected value differs from current state.",
            event.location,
        )
    value = operation.get("value")
    if (
        not isinstance(value, dict)
        or set(value) != {"duration", "type", "dots", "timeModification"}
        or type(value["dots"]) is not int
        or not 0 <= value["dots"] <= 4
    ):
        raise EditError(
            "invalid-duration-value",
            "Provide duration in quarters, type, dots (0-4), and timeModification.",
        )
    raw = Fraction(value["duration"]) * event.divisions
    if raw <= 0 or raw.denominator != 1:
        raise EditError(
            "unrepresentable-duration",
            "Duration must be positive and integral at effective divisions.",
        )
    modification = value["timeModification"]
    if modification is not None and (
        set(modification) != {"actualNotes", "normalNotes"}
        or any(type(v) is not int or v <= 0 for v in modification.values())
    ):
        raise EditError(
            "invalid-tuplet", "Expected positive integral actualNotes and normalNotes."
        )
    old_modification = child(note, "time-modification")
    if old_modification is not None and any(
        child(old_modification, k) is not None for k in ("normal-type", "normal-dot")
    ):
        raise EditError(
            "unsupported-tuplet",
            "Explicit normal-type/normal-dot editing is unsupported.",
        )
    for tag, elements in [
        ("duration", [make(note, "duration", str(raw))]),
        ("type", [make(note, "type", value["type"])]),
        ("dot", [make(note, "dot") for _ in range(value["dots"])]),
    ]:
        replace_note_children(note, tag, elements)
    ratios = []
    if modification is not None:
        ratio = make(note, "time-modification")
        ratio.extend(
            [
                make(ratio, "actual-notes", str(modification["actualNotes"])),
                make(ratio, "normal-notes", str(modification["normalNotes"])),
            ]
        )
        ratios.append(ratio)
    replace_note_children(note, "time-modification", ratios)
    if notation_duration(note) != Fraction(value["duration"]):
        raise EditError(
            "duration-notation-mismatch",
            "Duration and notation must describe the same rational time.",
        )


def _edit_note_identity(event, operation):
    note = event.element
    kind = operation["type"]
    value = operation.get("value")
    if kind in {"voice", "staff"}:
        if content(note, kind, "1") != operation.get("expected"):
            raise EditError(
                "old-value-mismatch",
                "Voice/staff expected value differs from current state.",
            )
        if (
            not isinstance(value, str)
            or not value
            or (kind == "staff" and (not value.isdigit() or int(value) < 1))
        ):
            raise EditError(
                "invalid-note-identity",
                "Voice must be nonempty; staff must be a positive integer string.",
            )
        replace_note_children(note, kind, [make(note, kind, value)])
        return
    old = dict(
        kind="rest"
        if child(note, "rest") is not None
        else "note"
        if child(note, "pitch") is not None
        else "unpitched",
        pitch=pitch_value(note),
    )
    if old != operation.get("expected"):
        raise EditError(
            "old-value-mismatch", "Note/rest expected value differs from current state."
        )
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "pitch"}
        or value["kind"] not in {"note", "rest"}
    ):
        raise EditError(
            "invalid-note-kind", "Expected kind note/rest and explicit pitch or null."
        )
    if (
        child(note, "chord") is not None
        or child(note, "tie") is not None
        or note.findall(".//{*}tied")
        or child(note, "unpitched") is not None
    ):
        raise EditError(
            "unsupported-kind-conversion",
            "Chord members, unpitched notes and tied notes cannot be converted.",
        )
    next_note = note.getnext()
    if next_note is not None and child(next_note, "chord") is not None:
        raise EditError(
            "unsupported-kind-conversion", "A chord anchor cannot become a rest."
        )
    if value["kind"] == "rest":
        if value["pitch"] is not None:
            raise EditError("invalid-note-kind", "Rest pitch must be null.")
        replace_note_children(note, "pitch", [])
        replace_note_children(note, "accidental", [])
        replace_note_children(note, "rest", [make(note, "rest")])
    else:
        pitch = value["pitch"]
        if (
            not isinstance(pitch, dict)
            or set(pitch) != {"step", "alter", "octave", "accidental"}
            or pitch["step"] not in list("ABCDEFG")
            or type(pitch["octave"]) is not int
            or not 0 <= pitch["octave"] <= 9
            or Fraction(pitch["alter"]).denominator != 1
            or pitch["accidental"] is not None
        ):
            raise EditError(
                "invalid-pitch",
                "Conversion requires a valid pitch with accidental=null; use a subsequent pitch operation for an explicit accidental.",
            )
        replace_note_children(note, "rest", [])
        element = make(note, "pitch")
        element.extend(
            make(element, k, str(Fraction(pitch[k])) if k == "alter" else str(pitch[k]))
            for k in ("step", "alter", "octave")
        )
        replace_note_children(note, "pitch", [element])
