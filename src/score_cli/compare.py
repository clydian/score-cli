"""Explicit ordinal alignment and bounded notation/sounding comparison."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from .score_document import (
    ScoreDocument,
    child,
    children,
    content,
    name,
    pitch_value,
    sha256,
    tree_data,
)
from .validation import validate_document


def event_value(event) -> dict:
    note = event.element
    return dict(
        pitch=pitch_value(note),
        kind="rest"
        if child(note, "rest") is not None
        else "note"
        if child(note, "pitch") is not None
        else "unpitched",
        offset=str(event.offset),
        duration=str(event.duration),
        voice=event.location["voice"],
        staff=event.location["staff"],
        notation=[
            tree_data(e)
            for e in note
            if name(e)
            in {
                "type",
                "dot",
                "time-modification",
                "grace",
                "chord",
                "tie",
                "notations",
                "lyric",
                "rest",
                "unpitched",
            }
        ],
        context={k: v for k, v in event.context.items() if k != "divisions"},
    )


def sounding_pitch(event) -> dict:
    pitch = pitch_value(event.element)
    if pitch is None:
        return dict(
            status="rest"
            if child(event.element, "rest") is not None
            else "inconclusive",
            value=None,
        )
    if any(child(event.element, k) is not None for k in ("instrument", "play")):
        return dict(
            status="inconclusive",
            value=None,
            reason="Instrument-specific playback is not resolved.",
        )
    shift = Fraction(0)
    transpose = event.context.get(
        "transpose:" + event.location["staff"], event.context.get("transpose:all")
    )
    if transpose:
        values = {e["tag"].rsplit("}", 1)[-1]: e["text"] for e in transpose["children"]}
        if "double" in values or "chromatic" not in values:
            return dict(
                status="inconclusive",
                value=None,
                reason="Unsupported transpose expression.",
            )
        shift = Fraction(values["chromatic"]) + 12 * int(
            values.get("octave-change", "0")
        )
    value = (
        12 * (pitch["octave"] + 1)
        + dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[pitch["step"]]
        + Fraction(pitch["alter"])
        + shift
    )
    return dict(status="determinate", value=str(value))


def compare_scores(*, before_path: str | Path, after_path: str | Path) -> dict:
    before_data, after_data = (
        Path(before_path).read_bytes(),
        Path(after_path).read_bytes(),
    )
    return dict(
        compare_documents(
            ScoreDocument.read(before_path, data=before_data),
            ScoreDocument.read(after_path, data=after_data),
        ),
        beforeSha256=sha256(before_data),
        afterSha256=sha256(after_data),
    )


def compare_documents(before: ScoreDocument, after: ScoreDocument) -> dict:
    report: dict = dict(
        schemaVersion="1",
        status="equal-within-coverage",
        alignment="exact part / printed measure / all-note ordinal; voice identity must agree",
        notationDifferences=[],
        soundingDifferences=[],
        unaligned=[],
        added=[],
        removed=[],
        coverage=dict(
            checked=[
                "written-pitch",
                "offset",
                "duration",
                "rest",
                "lyrics",
                "notations",
                "directions",
                "context",
            ],
            unchecked=[
                "source-pdf-correctness",
                "performance",
                "unknown-extension-meaning",
            ],
        ),
    )
    left_measures = before.measures()
    right_measures = after.measures()
    left_structure = [(p, m, o) for p, m, o, _, _ in left_measures]
    right_structure = [(p, m, o) for p, m, o, _, _ in right_measures]
    if left_structure != right_structure or len(
        {(p, m) for p, m, _ in left_structure}
    ) != len(left_structure):
        report["unaligned"].append(
            dict(
                reason="Different or ambiguous part/measure structure.",
                before=left_structure,
                after=right_structure,
            )
        )
        report["status"] = "inconclusive"
        return report
    left_events, right_events = before.events(), after.events()
    uncertain = False
    for (part, printed, ordinal, left, _), (_, _, _, right, _) in zip(
        left_measures, right_measures
    ):
        location = dict(partId=part, printedMeasure=printed)
        a = [
            e
            for e in left_events
            if e.location["partId"] == part and e.measure_ordinal == ordinal
        ]
        b = [
            e
            for e in right_events
            if e.location["partId"] == part and e.measure_ordinal == ordinal
        ]
        if len(a) != len(b):
            report["unaligned"].append(
                dict(
                    location=location,
                    reason="Note counts differ; no sequence guessing.",
                    beforeCount=len(a),
                    afterCount=len(b),
                )
            )
            for field, events in [("removed", a), ("added", b)]:
                report[field].extend(
                    dict(
                        location=e.location,
                        alignment="unmatched-candidate",
                        value=event_value(e),
                    )
                    for e in events
                )
        else:
            for first, second in zip(a, b):
                if first.location["voice"] != second.location["voice"]:
                    report["unaligned"].append(
                        dict(
                            location=first.location,
                            reason="Voice identity differs; no automatic voice mapping.",
                        )
                    )
                    continue
                av, bv = event_value(first), event_value(second)
                fields = [k for k in av if av[k] != bv[k]]
                if fields:
                    report["notationDifferences"].append(
                        dict(
                            location=first.location,
                            fields=fields,
                            before={k: av[k] for k in fields},
                            after={k: bv[k] for k in fields},
                        )
                    )
                sa, sb = sounding_pitch(first), sounding_pitch(second)
                if "inconclusive" in {sa["status"], sb["status"]}:
                    uncertain = True
                    report["soundingDifferences"].append(
                        dict(
                            location=first.location,
                            status="inconclusive",
                            before=sa,
                            after=sb,
                        )
                    )
                elif sa["value"] != sb["value"]:
                    report["soundingDifferences"].append(
                        dict(
                            location=first.location,
                            status="determinate",
                            before=sa["value"],
                            after=sb["value"],
                        )
                    )
        context_a = [
            tree_data(e) for e in left if isinstance(e.tag, str) and name(e) != "note"
        ]
        context_b = [
            tree_data(e) for e in right if isinstance(e.tag, str) and name(e) != "note"
        ]
        if context_a != context_b:
            report["notationDifferences"].append(
                dict(
                    location=location,
                    fields=["measure-context-and-directions"],
                    before=context_a,
                    after=context_b,
                )
            )
    report["validationBefore"] = validate_document(before)
    report["validationAfter"] = validate_document(after)
    if (
        report["unaligned"]
        or uncertain
        or any(
            r["status"] in {"invalid", "inconclusive"}
            for r in [report["validationBefore"], report["validationAfter"]]
        )
    ):
        report["status"] = "inconclusive"
    elif report["notationDifferences"] or report["soundingDifferences"]:
        report["status"] = "different"
    return report
