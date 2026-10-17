"""Conservative full-score timeline, notation, and paired-symbol diagnostics."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from .score_document import (
    ScoreDocument,
    ScoreError,
    child,
    children,
    content,
    name,
    pitch_value,
    sha256,
)

TYPE_QUARTERS = {
    key: Fraction(str(value))
    for key, value in {
        "maxima": 32,
        "long": 16,
        "breve": 8,
        "whole": 4,
        "half": 2,
        "quarter": 1,
        "eighth": "1/2",
        "16th": "1/4",
        "32nd": "1/8",
        "64th": "1/16",
        "128th": "1/32",
        "256th": "1/64",
        "512th": "1/128",
        "1024th": "1/256",
    }.items()
}
COVERAGE = dict(
    checked=[
        "part-and-measure-structure",
        "part-order-groups-and-instrument-references",
        "snapshot-locations",
        "cursor-and-divisions",
        "duration-notation",
        "voice-coverage",
        "pitch-rest-invariants",
        "tie-tied-slur-wedge-pairs",
    ],
    unchecked=[
        "source-pdf-correctness",
        "full-musicxml-schema",
        "instrument-playback",
        "microtonal-tuning",
        "repeat-playback",
        "engraving-correctness",
        "unknown-extension-semantics",
    ],
)


def notation_duration(note) -> Fraction | None:
    rest = child(note, "rest")
    # A full-measure rest uses the measure duration, regardless of its glyph.
    if rest is not None and rest.get("measure") == "yes":
        return None
    kind = content(note, "type")
    if not kind:
        return None
    if kind not in TYPE_QUARTERS:
        raise ScoreError("unsupported-note-type", f"Unsupported note type {kind}.")
    dots = len(children(note, "dot"))
    result = TYPE_QUARTERS[kind] * (2 - Fraction(1, 2**dots))
    ratio = child(note, "time-modification")
    if ratio is not None:
        actual = int(content(ratio, "actual-notes"))
        normal = int(content(ratio, "normal-notes"))
        if actual <= 0 or normal <= 0:
            raise ScoreError(
                "invalid-tuplet", "Tuplet actual/normal counts must be positive."
            )
        result *= Fraction(normal, actual)
    return result


def validate_score(*, input_path: str | Path) -> dict:
    data = Path(input_path).read_bytes()
    try:
        document = ScoreDocument.read(input_path, data=data)
        report = validate_document(document)
    except (ScoreError, ValueError, ZeroDivisionError) as exc:
        diagnostic = (
            exc.diagnostic
            if isinstance(exc, ScoreError)
            else dict(
                code="invalid-number",
                severity="error",
                location={},
                reason=str(exc),
                operationId=None,
            )
        )
        report = dict(
            schemaVersion="1",
            status="invalid",
            coverage=COVERAGE,
            diagnostics=[diagnostic],
        )
    return dict(report, inputSha256=sha256(data))


def validate_document(document: ScoreDocument) -> dict:
    diagnostics: list[dict] = []

    def add(code, location, reason, severity="error"):
        diagnostics.append(
            dict(
                code=code,
                severity=severity,
                location=location,
                reason=reason,
                operationId=None,
            )
        )

    try:
        events = document.events()
    except (ValueError, ZeroDivisionError) as exc:
        add("invalid-number", {}, str(exc))
        return dict(
            schemaVersion="1",
            status="invalid",
            coverage=COVERAGE,
            diagnostics=diagnostics,
        )
    _structure_references(document, add)
    measures = document.measures()
    sequences: dict[str, list[str]] = defaultdict(list)
    for part, printed, ordinal, _, _ in measures:
        location = dict(partId=part, printedMeasure=printed, measureOrdinal=ordinal)
        if not part or not printed:
            add(
                "missing-identity",
                location,
                "Part ID and exact printed number are required.",
            )
        if printed in sequences[part]:
            add(
                "duplicate-measure-number",
                location,
                "Printed measure locator is ambiguous.",
            )
        sequences[part].append(printed)
    part_list = child(document.root, "part-list")
    definitions = (
        []
        if part_list is None
        else [e.get("id") for e in children(part_list, "score-part")]
    )
    if (
        not definitions
        or len(definitions) != len(set(definitions))
        or set(definitions) != set(sequences)
    ):
        add(
            "part-structure",
            {},
            "Part-list must uniquely describe exactly the score parts.",
        )
    if name(document.root) == "score-partwise":
        ids = [e.get("id") for e in children(document.root, "part")]
        if len(ids) != len(set(ids)):
            add("duplicate-part", {}, "Part IDs are not unique.")
    if len({tuple(s) for s in sequences.values()}) > 1:
        add(
            "inconsistent-measure-sequence",
            {},
            "Parts have different printed measure sequences.",
        )
    grouped: dict[tuple, list] = defaultdict(list)
    for event in events:
        grouped[(event.location["partId"], event.measure_ordinal)].append(event)
    divisions: dict[str, Fraction] = {}
    meters: dict[str, Fraction | None] = {}
    staves: dict[str, int] = {}
    open_pairs: dict[tuple, tuple[dict, Fraction | None]] = {}
    slur_points: list[tuple] = []
    absolute_times: dict[str, Fraction] = defaultdict(Fraction)
    for part, printed, ordinal, measure, attributes in measures:
        loc = dict(partId=part, printedMeasure=printed, measureOrdinal=ordinal)
        cursor = Fraction(0)
        last_division_change = Fraction(0)
        event_list = grouped[(part, ordinal)]
        event_iter = iter(event_list)
        last = None
        directions = 0
        for element in measure:
            tag = name(element)
            try:
                if tag == "attributes":
                    if child(element, "staves") is not None:
                        staves[part] = int(content(element, "staves"))
                    if child(element, "divisions") is not None:
                        divisions[part] = Fraction(content(element, "divisions"))
                        last_division_change = cursor
                    for time in children(element, "time"):
                        if child(time, "senza-misura") is not None:
                            meters[part] = None
                        else:
                            beats = children(time, "beats")
                            units = children(time, "beat-type")
                            if len(beats) != len(units) or not beats:
                                add(
                                    "unsupported-meter",
                                    loc,
                                    "Cannot determine this time signature.",
                                    "inconclusive",
                                )
                                meters[part] = None
                            else:
                                meters[part] = sum(
                                    (
                                        sum(
                                            Fraction(x)
                                            for x in (b.text or "").split("+")
                                        )
                                        * 4
                                        / Fraction(u.text or "")
                                        for b, u in zip(beats, units)
                                    ),
                                    Fraction(0),
                                )
                    continue
                if (
                    tag in {"backup", "forward", "note"}
                    and child(element, "grace") is None
                ):
                    if part not in divisions:
                        add(
                            "missing-divisions",
                            loc,
                            "Duration has no effective divisions.",
                        )
                    raw = Fraction(content(element, "duration", "0"))
                    if raw <= 0:
                        add(
                            "invalid-duration",
                            loc,
                            "Non-grace duration must be positive.",
                        )
                duration = Fraction(content(element, "duration", "0")) / divisions.get(
                    part, Fraction(1)
                )
                if tag in {"backup", "forward"}:
                    after = cursor + duration * (-1 if tag == "backup" else 1)
                    if after < 0:
                        add(
                            "negative-cursor",
                            loc,
                            "Backup moves the measure cursor before zero.",
                        )
                    if after < last_division_change:
                        add(
                            "cursor-crosses-divisions",
                            loc,
                            "Backup crosses a mid-measure divisions change.",
                        )
                    cursor = after
                    last = None
                elif tag == "note":
                    event = next(event_iter)
                    event_loc = dict(event.location, measureOrdinal=ordinal)
                    if not event.location["staff"].isdigit() or not 1 <= int(
                        event.location["staff"]
                    ) <= staves.get(part, 1):
                        add(
                            "invalid-staff-reference",
                            event_loc,
                            "Note staff is outside the effective staves count.",
                        )
                    kinds = sum(
                        len(children(element, k))
                        for k in ("pitch", "rest", "unpitched")
                    )
                    if kinds != 1:
                        add(
                            "invalid-note-kind",
                            event_loc,
                            "A note needs exactly one pitch, rest or unpitched child.",
                        )
                    pitch = pitch_value(element)
                    if pitch is not None and (
                        pitch["step"] not in list("ABCDEFG")
                        or not 0 <= pitch["octave"] <= 9
                    ):
                        add("invalid-pitch", event_loc, "Invalid written pitch.")
                    grace = child(element, "grace") is not None
                    chord = child(element, "chord") is not None
                    if grace and child(element, "duration") is not None:
                        add(
                            "grace-duration",
                            event_loc,
                            "Grace notes must not carry duration.",
                        )
                    if chord:
                        if (
                            last is None
                            or child(element, "rest") is not None
                            or last.location["voice"] != event.location["voice"]
                            or duration > last.duration
                            or (child(last.element, "grace") is not None) != grace
                        ):
                            add(
                                "invalid-chord",
                                event_loc,
                                "Chord requires an adjacent anchor in the same voice and cannot outlast it.",
                            )
                    else:
                        last = event
                        if not grace:
                            cursor += duration
                    expected = notation_duration(element)
                    if expected is not None and not grace and expected != duration:
                        add(
                            "duration-notation-mismatch",
                            event_loc,
                            f"Notation gives {expected} quarters; duration gives {duration}.",
                        )
                    if (
                        expected is None
                        and not grace
                        and child(element, "rest") is None
                    ):
                        add(
                            "missing-note-type",
                            event_loc,
                            "Display duration is absent.",
                            "inconclusive",
                        )
                    if child(element, "unpitched") is not None:
                        add(
                            "unsupported-unpitched-sound",
                            event_loc,
                            "Unpitched sounding comparisons are not supported.",
                            "inconclusive",
                        )
                    if (
                        element.get("attack")
                        or element.get("release")
                        or element.get("dynamics")
                        or child(element, "play") is not None
                    ):
                        add(
                            "unsupported-playback-adjustment",
                            event_loc,
                            "Playback overrides are preserved but not interpreted.",
                            "inconclusive",
                        )
                    for family in ("tie", "tied", "slur"):
                        symbols = (
                            children(element, family)
                            if family == "tie"
                            else [
                                e
                                for n in children(element, "notations")
                                for e in children(n, family)
                            ]
                        )
                        # Continue is a cross-system formatting point. Some
                        # exporters duplicate it on the musical endpoint note.
                        endpoints = {
                            e.get("number", "1")
                            for e in symbols
                            if e.get("type") in {"start", "stop"}
                        }
                        for symbol in sorted(
                            symbols, key=lambda e: 0 if e.get("type") == "stop" else 1
                        ):
                            if (
                                family == "slur"
                                and symbol.get("type") == "continue"
                                and symbol.get("number", "1") in endpoints
                            ):
                                continue
                            key: tuple = (
                                part,
                                family,
                                event.location["voice"],
                                str(pitch)
                                if family in {"tie", "tied"}
                                else symbol.get("number", "1"),
                            )
                            # Display accidentals do not change sounding or tie identity.
                            if family in {"tie", "tied"} and pitch:
                                key = (
                                    part,
                                    family,
                                    event.location["voice"],
                                    pitch["step"],
                                    pitch["alter"],
                                    pitch["octave"],
                                )
                            if family == "slur":
                                key = (part, family, symbol.get("number", "1"))
                            if family == "tied":
                                key = (*key, symbol.get("number", "1"))
                            at = absolute_times[part] + event.offset
                            end = at + event.duration
                            if family == "slur":
                                slur_points.append(
                                    (symbol.get("type", ""), key, event_loc, at, end)
                                )
                                continue
                            _pair(
                                symbol.get("type", ""),
                                key,
                                event_loc,
                                at,
                                end,
                                open_pairs,
                                add,
                            )
                    tie_types = sorted(
                        e.get("type", "") for e in children(element, "tie")
                    )
                    tied_types = sorted(
                        e.get("type", "")
                        for n in children(element, "notations")
                        for e in children(n, "tied")
                        if e.get("type") in {"start", "stop"}
                    )
                    if tie_types != tied_types:
                        add(
                            "tie-expression-mismatch",
                            event_loc,
                            "Playback tie and notated tied endpoints differ.",
                            "warning",
                        )
                elif tag == "direction":
                    directions += 1
                    direction_loc = dict(loc, directionIndex=directions)
                    staff = content(element, "staff", "1")
                    if not staff.isdigit() or not 1 <= int(staff) <= staves.get(
                        part, 1
                    ):
                        add(
                            "invalid-staff-reference",
                            direction_loc,
                            "Direction staff is outside the effective staves count.",
                        )
                    for kind in children(element, "direction-type"):
                        for symbol in kind:
                            if name(symbol) == "wedge":
                                key = (
                                    part,
                                    "wedge",
                                    content(element, "staff", "1"),
                                    content(element, "voice", ""),
                                    symbol.get("number", "1"),
                                )
                                _pair(
                                    symbol.get("type", ""),
                                    key,
                                    direction_loc,
                                    None,
                                    None,
                                    open_pairs,
                                    add,
                                )
                            elif name(symbol) == "octave-shift":
                                add(
                                    "octave-shift-display-only",
                                    direction_loc,
                                    "Pitch already encodes the octave; octave-shift is not added to sounding pitch.",
                                    "info",
                                )
                elif tag in {"sound", "barline"} and (
                    child(element, "repeat") is not None or tag == "sound"
                ):
                    add(
                        "playback-context-unchecked",
                        loc,
                        "Repeat and sound playback routing is not interpreted.",
                        "inconclusive",
                    )
            except (ValueError, ZeroDivisionError, ScoreError) as exc:
                add(
                    "invalid-number"
                    if not isinstance(exc, ScoreError)
                    else exc.diagnostic["code"],
                    loc,
                    str(exc),
                )
        extent = max([cursor] + [e.offset + e.duration for e in event_list])
        meter = meters.get(part)
        flexible = (
            attributes.get("implicit") == "yes"
            or attributes.get("non-controlling") == "yes"
            or ordinal == 1
            or meter is None
        )
        if meter is not None and extent > meter:
            add("measure-overflow", loc, f"Extent {extent} exceeds meter {meter}.")
        voices: dict[str, list] = defaultdict(list)
        for e in event_list:
            if child(e.element, "grace") is None and child(e.element, "chord") is None:
                voices[e.location["voice"]].append(e)
        for voice, items in voices.items():
            end = Fraction(0)
            for e in sorted(items, key=lambda e: e.offset):
                if e.offset < end:
                    add(
                        "voice-overlap",
                        dict(e.location, measureOrdinal=ordinal),
                        "Non-chord events overlap in this voice.",
                    )
                elif e.offset > end:
                    add(
                        "voice-gap",
                        dict(e.location, measureOrdinal=ordinal),
                        f"Uncovered voice interval {end}..{e.offset}.",
                        "warning",
                    )
                end = max(end, e.offset + e.duration)
            if not flexible and meter and end < meter:
                add(
                    "incomplete-voice",
                    dict(loc, voice=voice),
                    f"Voice ends at {end}, before meter {meter}; may be intentional incomplete notation.",
                    "warning",
                )
        absolute_times[part] += (
            max(extent, meter or Fraction(0)) if not flexible else extent
        )
    # MusicXML serializes complete voices with backup, so XML order need not
    # follow musical time for slurs crossing hands or voices.
    for kind, key, location, at, end in sorted(
        slur_points, key=lambda p: (p[1][0], p[3], 0 if p[0] == "stop" else 1)
    ):
        _pair(kind, key, location, at, end, open_pairs, add)
    for key, (location, _) in open_pairs.items():
        add("unclosed-" + key[1], location, f"{key[1]} start has no matching stop.")
    status = (
        "invalid"
        if any(d["severity"] == "error" for d in diagnostics)
        else "inconclusive"
        if any(d["severity"] == "inconclusive" for d in diagnostics)
        else "valid-within-coverage"
    )
    return dict(
        schemaVersion="1", status=status, coverage=COVERAGE, diagnostics=diagnostics
    )


def _pair(kind, key, location, at, end, pairs, add):
    family = key[1]
    if family == "slur" and kind == "continue":
        if key not in pairs:
            add("orphan-slur", location, "slur continue has no matching start.")
        return
    if kind in {"stop", "continue"}:
        if key not in pairs:
            add(
                "orphan-" + family,
                location,
                f"{family} stop/continue has no matching start.",
            )
        else:
            _, expected_end = pairs.pop(key)
            if family == "tie" and at != expected_end:
                add(
                    "nonadjacent-tie",
                    location,
                    "Tie endpoints are not contiguous in score time.",
                )
    if kind in {"start", "continue", "crescendo", "diminuendo"}:
        if key in pairs:
            add(
                "duplicate-" + family + "-start",
                location,
                f"{family} number is already open.",
            )
        pairs[key] = (location, end)
    elif kind not in {"stop"}:
        add(
            "unsupported-" + family,
            location,
            f"Unsupported endpoint type {kind}.",
            "inconclusive",
        )


def _structure_references(document, add):
    """Check native part order, part groups and instrument ID/IDREF ownership."""
    part_list = child(document.root, "part-list")
    if part_list is None:
        return
    definitions = children(part_list, "score-part")
    ids = [p.get("id", "") for p in definitions]
    groups = {}
    seen_parts = 0
    for element in part_list:
        if name(element) == "score-part":
            seen_parts += 1
        elif name(element) == "part-group":
            number = element.get("number", "1")
            kind = element.get("type")
            if kind == "start" and number not in groups:
                groups[number] = seen_parts
            elif kind == "stop" and number in groups:
                if groups.pop(number) == seen_parts:
                    add(
                        "empty-part-group",
                        {},
                        "Part group must contain at least one part.",
                    )
            else:
                add(
                    "invalid-part-group",
                    {},
                    "Part group start/stop numbers must pair uniquely.",
                )
    if groups:
        add("unclosed-part-group", {}, "Part group start has no stop.")
    owners = {}
    for definition in definitions:
        pid = definition.get("id", "")
        for instrument in children(definition, "score-instrument"):
            identity = instrument.get("id")
            if not identity or identity in owners or identity in ids:
                add(
                    "duplicate-instrument-id",
                    dict(partId=pid),
                    "Instrument IDs must be present and globally unique.",
                )
            owners[identity] = pid
    for definition in definitions:
        pid = definition.get("id", "")
        for e in definition.iter():
            if name(e) in {"midi-instrument", "midi-device", "instrument"}:
                if name(e) == "midi-device" and e.get("id") is None:
                    continue
                if owners.get(e.get("id")) != pid:
                    add(
                        "invalid-instrument-reference",
                        dict(partId=pid),
                        "Instrument reference must resolve within its part.",
                    )
    parents = (
        [document.root]
        if name(document.root) == "score-partwise"
        else children(document.root, "measure")
    )
    for parent in parents:
        if [p.get("id", "") for p in children(parent, "part")] != ids:
            add(
                "part-order",
                {},
                "Native part order must match part-list in every measure.",
            )
    for pid, printed, ordinal, measure, _ in document.measures():
        for e in measure.iter():
            if name(e) in {"instrument", "midi-instrument", "midi-device"}:
                if name(e) == "midi-device" and e.get("id") is None:
                    continue
                if owners.get(e.get("id")) != pid:
                    add(
                        "invalid-instrument-reference",
                        dict(
                            partId=pid, printedMeasure=printed, measureOrdinal=ordinal
                        ),
                        "Instrument reference must resolve within its part.",
                    )
