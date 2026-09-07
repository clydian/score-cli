"""Snapshot locators for directions, separate from note event indices."""

from dataclasses import dataclass
from lxml import etree as ET
from fractions import Fraction

from .score_document import ScoreError, child, children, content, make, name


@dataclass
class DirectionTarget:
    element: ET._Element
    measure: ET._Element
    location: dict
    ordinal: int
    insertion_index: int | None = None

    def attach(self):
        if self.element.getparent() is None:
            assert self.insertion_index is not None
            self.measure.insert(self.insertion_index, self.element)


def resolve_direction(document, target, cache):
    required = {
        "partId",
        "printedMeasure",
        "staff",
        "voice",
        "offset",
        "directionIndex",
    }
    if (
        set(target) != required
        or type(target["directionIndex"]) is not int
        or target["directionIndex"] < 0
        or not all(isinstance(target[k], str) for k in required - {"directionIndex"})
    ):
        raise ScoreError(
            "invalid-direction-locator",
            "Direction locator requires exact string fields and directionIndex >= 0.",
        )
    key = tuple(sorted(target.items()))
    if key in cache:
        return cache[key]
    matches = [
        m
        for m in document.measures()
        if m[0] == target["partId"] and m[1] == target["printedMeasure"]
    ]
    if len(matches) != 1:
        raise ScoreError(
            "ambiguous-direction-measure", "Direction measure must be unique.", target
        )
    _, _, ordinal, measure, _ = matches[0]
    events = [
        e
        for e in document.events()
        if e.location["partId"] == target["partId"] and e.measure_ordinal == ordinal
    ]
    divisions = events[0].divisions if events else Fraction(1)
    cursor = Fraction(0)
    found = None
    index = 0
    insertion_index = 0
    for position, element in enumerate(measure):
        tag = name(element)
        if tag == "attributes":
            if child(element, "divisions") is not None:
                divisions = Fraction(content(element, "divisions"))
            if cursor == 0:
                insertion_index = position + 1
        elif (
            tag == "note"
            and child(element, "chord") is None
            and child(element, "grace") is None
        ):
            cursor += Fraction(content(element, "duration", "0")) / divisions
        elif tag in {"backup", "forward"}:
            cursor += (
                Fraction(content(element, "duration", "0"))
                / divisions
                * (-1 if tag == "backup" else 1)
            )
        elif tag == "direction":
            index += 1
            if index == target["directionIndex"]:
                if (
                    target["staff"] != content(element, "staff", "1")
                    or target["voice"] != content(element, "voice", "")
                    or target["offset"]
                    != str(
                        cursor + Fraction(content(element, "offset", "0")) / divisions
                    )
                ):
                    raise ScoreError(
                        "target-missing",
                        "Direction does not match the snapshot location.",
                        target,
                    )
                found = DirectionTarget(element, measure, target, ordinal)
    if target["directionIndex"] == 0:
        # A virtual start-of-measure anchor. Offsets are deliberately restricted so
        # a later duration edit cannot silently move a newly placed direction.
        if target["offset"] != "0":
            raise ScoreError(
                "unsupported-direction-anchor",
                "New directions currently use offset=0; edit existing directions for other offsets.",
            )
        element = make(measure, "direction")
        if target["voice"]:
            element.append(make(element, "voice", target["voice"]))
        element.append(make(element, "staff", target["staff"]))
        found = DirectionTarget(element, measure, target, ordinal, insertion_index)
    if found is None:
        raise ScoreError("target-missing", "Direction index was not found.", target)
    cache[key] = found
    return found


def _symbols(target, tag):
    return [
        e for t in children(target.element, "direction-type") for e in children(t, tag)
    ]


def _append(target, symbol):
    wrapper = make(target.element, "direction-type")
    wrapper.append(symbol)
    target.element.insert(0, wrapper)
    target.attach()


def _remove(symbol):
    parent = symbol.getparent()
    parent.remove(symbol)
    if len(parent) == 0:
        parent.getparent().remove(parent)


def edit_dynamics(target, operation):
    symbols = _symbols(target, "dynamics")
    if len(symbols) > 1 or (symbols and len(symbols[0]) != 1):
        raise ScoreError(
            "ambiguous-dynamics", "Expected at most one simple dynamics symbol."
        )
    old = name(symbols[0][0]) if symbols else None
    if old != operation.get("expected"):
        raise ScoreError("old-value-mismatch", "Dynamics differs from expected value.")
    value = operation.get("value")
    if value not in {
        None,
        "p",
        "pp",
        "ppp",
        "pppp",
        "f",
        "ff",
        "fff",
        "ffff",
        "mp",
        "mf",
        "sf",
        "sfp",
        "sfz",
        "fp",
        "rfz",
        "fz",
    }:
        raise ScoreError("unsupported-dynamics", "Unsupported dynamics mark.")
    if symbols:
        if value is None:
            _remove(symbols[0])
        else:
            symbols[0][0].tag = make(symbols[0], value).tag
    elif value is not None:
        symbol = make(target.element, "dynamics")
        symbol.append(make(symbol, value))
        _append(target, symbol)
    if (
        not children(target.element, "direction-type")
        and target.element.getparent() is not None
    ):
        target.element.getparent().remove(target.element)


def edit_wedge(start, end, operation):
    number = operation.get("number")
    if (
        not isinstance(number, str)
        or not number.isdigit()
        or not 1 <= int(number) <= 16
        or type(operation.get("expected")) is not bool
        or operation.get("value") not in {None, "crescendo", "diminuendo"}
    ):
        raise ScoreError(
            "invalid-wedge",
            "Wedge requires number 1-16, boolean expected and crescendo/diminuendo/null.",
        )
    if (
        start.location["partId"] != end.location["partId"]
        or start.location["staff"] != end.location["staff"]
        or start.location["voice"] != end.location["voice"]
        or (start.ordinal, Fraction(start.location["offset"]))
        >= (end.ordinal, Fraction(end.location["offset"]))
    ):
        raise ScoreError(
            "invalid-wedge",
            "Wedge endpoints must be ordered on the same part, staff and voice.",
        )
    endpoints = []
    for target, role in [(start, "start"), (end, "stop")]:
        found = [
            s
            for s in _symbols(target, "wedge")
            if s.get("number", "1") == number
            and (
                s.get("type") in {"crescendo", "diminuendo"}
                if role == "start"
                else s.get("type") == "stop"
            )
        ]
        if len(found) > 1 or bool(found) != operation["expected"]:
            raise ScoreError(
                "old-value-mismatch", "Wedge endpoints differ from expected state."
            )
        endpoints.append((target, role, found))
    for target, role, found in endpoints:
        value = operation["value"]
        if found and value is None:
            _remove(found[0])
        elif found:
            found[0].set("type", value if role == "start" else "stop")
        elif value:
            _append(
                target,
                make(
                    target.element,
                    "wedge",
                    type=value if role == "start" else "stop",
                    number=number,
                ),
            )
        if (
            not children(target.element, "direction-type")
            and target.element.getparent() is not None
        ):
            target.element.getparent().remove(target.element)
