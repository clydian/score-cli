"""Outline MusicXML scores and inspect one printed measure."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .musicxml_input import read_musicxml

SCHEMA_VERSION = "1"


class ScoreInspectionError(ValueError):
    """Raised when MusicXML cannot be inspected."""


class MeasureInspectionError(ScoreInspectionError):
    """Raised when a printed measure cannot be selected for inspection."""


@dataclass(frozen=True, slots=True)
class MeasureInspection:
    """A JSON-ready view of one printed measure."""

    _document: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return an independent copy of the inspection document."""

        return deepcopy(self._document)

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the inspection as UTF-8-friendly JSON."""

        return json.dumps(self._document, ensure_ascii=False, indent=indent) + "\n"

    def to_text(self) -> str:
        """Render a deterministic, intentionally concise human summary."""

        return _format_text(self._document)


@dataclass(frozen=True, slots=True)
class ScoreOutline:
    """A lightweight directory of parts and printed measure numbers."""

    _document: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return an independent copy of the outline document."""

        return deepcopy(self._document)

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the outline as UTF-8-friendly JSON."""

        return json.dumps(self._document, ensure_ascii=False, indent=indent) + "\n"


@dataclass(frozen=True, slots=True)
class _SelectedPart:
    part_id: str
    part_name: str
    content: ElementTree.Element
    measure_attributes: dict[str, str]
    ordinal: int
    context_before: dict[str, Any]


def inspect_printed_measure(
    *,
    input_path: str | Path,
    measure: str | int,
    part: str | None = None,
    include_elements: bool = False,
) -> MeasureInspection:
    """Return normalized data for one printed measure, optionally with XML elements."""

    printed_measure = str(measure)
    if not printed_measure:
        raise MeasureInspectionError("A printed measure number is required.")
    root = _read_score_root(input_path)
    root_type = _local_name(root.tag)
    definitions = _part_definitions(root)
    if root_type == "score-partwise":
        selected, diagnostics = _select_partwise(
            root,
            definitions,
            printed_measure,
            part,
        )
    elif root_type == "score-timewise":
        selected, diagnostics = _select_timewise(
            root,
            definitions,
            printed_measure,
            part,
        )

    parts: list[dict[str, Any]] = []
    for selected_part in selected:
        inspection, part_diagnostics = _inspect_part_measure(
            selected_part,
            include_elements=include_elements,
        )
        parts.append(inspection)
        diagnostics.extend(part_diagnostics)

    document = {
        "schemaVersion": SCHEMA_VERSION,
        "measure": {"printedNumber": printed_measure},
        "parts": parts,
        "diagnostics": diagnostics,
    }
    return MeasureInspection(document)


def outline_score(*, input_path: str | Path) -> ScoreOutline:
    """Return the parts and ordered printed measure numbers in a score."""

    root = _read_score_root(input_path)
    definitions = _part_definitions(root)
    root_type = _local_name(root.tag)
    diagnostics: list[dict[str, Any]] = []

    if root_type == "score-partwise":
        part_elements = [child for child in root if _local_name(child.tag) == "part"]
        part_ids = [element.get("id", "") for element in part_elements]
        sequences = {
            element.get("id", ""): [
                child.get("number", "")
                for child in element
                if _local_name(child.tag) == "measure"
            ]
            for element in part_elements
        }
        measure_numbers = next(iter(sequences.values()), [])
        for part_id, sequence in sequences.items():
            diagnostics.extend(_duplicate_measure_diagnostics(sequence, part_id))
            if sequence != measure_numbers:
                diagnostics.append(
                    _diagnostic(
                        "warning",
                        "inconsistent-measure-sequence",
                        "This part's printed measure sequence differs from the score outline.",
                        part_id=part_id,
                    )
                )
    else:
        measures = [child for child in root if _local_name(child.tag) == "measure"]
        measure_numbers = [element.get("number", "") for element in measures]
        part_ids = list(definitions)
        for measure_element in measures:
            for part_element in (
                child for child in measure_element if _local_name(child.tag) == "part"
            ):
                part_id = part_element.get("id", "")
                if part_id not in part_ids:
                    part_ids.append(part_id)
        diagnostics.extend(_duplicate_measure_diagnostics(measure_numbers))

    parts = [
        {
            "partId": part_id,
            "partName": _part_name(definitions.get(part_id), part_id),
        }
        for part_id in part_ids
    ]
    return ScoreOutline(
        {
            "schemaVersion": SCHEMA_VERSION,
            "parts": parts,
            "measureNumbers": measure_numbers,
            "diagnostics": diagnostics,
        }
    )


def _read_score_root(input_path: str | Path) -> ElementTree.Element:
    source = Path(input_path)
    xml = read_musicxml(source)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise ScoreInspectionError(
            f'Cannot parse MusicXML "{source}": {error}.'
        ) from error
    root_type = _local_name(root.tag)
    if root_type not in {"score-partwise", "score-timewise"}:
        raise ScoreInspectionError(f'Unsupported MusicXML root "{root_type}".')
    return root


def _duplicate_measure_diagnostics(
    measure_numbers: list[str],
    part_id: str | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for printed_number in measure_numbers:
        if printed_number in seen and printed_number not in duplicates:
            duplicates.append(printed_number)
        seen.add(printed_number)
    return [
        _diagnostic(
            "warning",
            "duplicate-measure-number",
            f'Printed measure number "{printed_number}" occurs more than once.',
            part_id=part_id,
        )
        for printed_number in duplicates
    ]


def _select_partwise(
    root: ElementTree.Element,
    definitions: dict[str, ElementTree.Element],
    printed_measure: str,
    part_id: str | None,
) -> tuple[list[_SelectedPart], list[dict[str, Any]]]:
    parts = [child for child in root if _local_name(child.tag) == "part"]
    if part_id is not None:
        parts = [part for part in parts if part.get("id") == part_id]
        if not parts:
            raise MeasureInspectionError(
                f'Part "{part_id}" was not found in the score.'
            )
    counts = {
        part.get("id", ""): sum(
            1
            for measure in part
            if _local_name(measure.tag) == "measure"
            and measure.get("number") == printed_measure
        )
        for part in parts
    }
    _require_unique_measure(printed_measure, max(counts.values(), default=0))
    selected: list[_SelectedPart] = []
    diagnostics: list[dict[str, Any]] = []

    for part in parts:
        part_id = part.get("id", "")
        definition = definitions.get(part_id)
        context = _empty_context()
        found = False

        for ordinal, measure_element in enumerate(
            (child for child in part if _local_name(child.tag) == "measure"),
            start=1,
        ):
            if measure_element.get("number") == printed_measure:
                selected.append(
                    _SelectedPart(
                        part_id=part_id,
                        part_name=_part_name(definition, part_id),
                        content=measure_element,
                        measure_attributes=dict(measure_element.attrib),
                        ordinal=ordinal,
                        context_before=deepcopy(context),
                    )
                )
                found = True
            _apply_measure_attributes(context, measure_element)

        if not found:
            diagnostics.append(
                _diagnostic(
                    "warning",
                    "measure-missing-in-part",
                    f'Printed measure "{printed_measure}" is missing from part {part_id}.',
                    part_id=part_id,
                )
            )

    if not selected:
        raise MeasureInspectionError(
            f'Printed measure "{printed_measure}" was not found.'
        )

    ordinals = {part.part_id: part.ordinal for part in selected}
    if len(set(ordinals.values())) > 1:
        diagnostics.append(
            _diagnostic(
                "warning",
                "inconsistent-part-ordinals",
                "The selected printed measure has different ordinal positions across parts.",
            )
        )

    return selected, diagnostics


def _select_timewise(
    root: ElementTree.Element,
    definitions: dict[str, ElementTree.Element],
    printed_measure: str,
    part_id: str | None,
) -> tuple[list[_SelectedPart], list[dict[str, Any]]]:
    measures = [child for child in root if _local_name(child.tag) == "measure"]
    matches = [
        measure for measure in measures if measure.get("number") == printed_measure
    ]
    _require_unique_measure(printed_measure, len(matches))
    target = matches[0]
    target_ordinal = measures.index(target) + 1
    contexts: dict[str, dict[str, Any]] = {}

    for measure_element in measures[: target_ordinal - 1]:
        for part in (
            child for child in measure_element if _local_name(child.tag) == "part"
        ):
            part_id = part.get("id", "")
            context = contexts.setdefault(part_id, _empty_context())
            _apply_measure_attributes(context, part)

    selected: list[_SelectedPart] = []
    target_parts = [child for child in target if _local_name(child.tag) == "part"]
    if part_id is not None:
        target_parts = [part for part in target_parts if part.get("id") == part_id]
        if not target_parts:
            raise MeasureInspectionError(
                f'Part "{part_id}" does not contain printed measure '
                f'"{printed_measure}".'
            )
    for part in target_parts:
        selected_part_id = part.get("id", "")
        definition = definitions.get(selected_part_id)
        selected.append(
            _SelectedPart(
                part_id=selected_part_id,
                part_name=_part_name(definition, selected_part_id),
                content=part,
                measure_attributes=dict(target.attrib),
                ordinal=target_ordinal,
                context_before=deepcopy(
                    contexts.get(selected_part_id, _empty_context())
                ),
            )
        )

    return selected, []


def _require_unique_measure(
    printed_measure: str,
    available: int,
) -> None:
    if available == 0:
        raise MeasureInspectionError(
            f'Printed measure "{printed_measure}" was not found in the score.'
        )
    if available > 1:
        raise MeasureInspectionError(
            f'Printed measure "{printed_measure}" is ambiguous because it occurs '
            f"{available} times in the same part or measure sequence."
        )


def _inspect_part_measure(
    selected: _SelectedPart,
    *,
    include_elements: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context = deepcopy(selected.context_before)
    context_at_start: dict[str, Any] | None = None
    cursor = Fraction(0)
    maximum_event_end = Fraction(0)
    last_note_offset = Fraction(0)
    note_index = 0
    element_names: set[str] = set()
    elements: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    directions: list[dict[str, Any]] = []
    harmonies: list[dict[str, Any]] = []
    figured_bass: list[dict[str, Any]] = []
    barlines: list[dict[str, Any]] = []
    attribute_changes: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for order, child in enumerate(selected.content, start=1):
        name = _local_name(child.tag)
        element_names.add(name)
        offset_before = cursor
        event_offset = cursor

        if name == "attributes":
            _apply_attributes(context, child)
            attribute_changes.append(
                {
                    "order": order,
                    "offset": _fraction(cursor),
                    "effectiveContextAfter": _context_to_data(
                        context,
                        include_elements=include_elements,
                    ),
                }
            )
        elif name == "note":
            is_chord = _child(child, "chord") is not None
            if is_chord:
                event_offset = last_note_offset
            else:
                last_note_offset = cursor
            note_index += 1
            event, duration = _note_event(
                child,
                selected,
                note_index,
                event_offset,
                context.get("divisions"),
                diagnostics,
            )
            events.append(event)
            maximum_event_end = max(maximum_event_end, event_offset + duration)
            if not is_chord and _child(child, "grace") is None:
                cursor += duration
        elif name == "backup":
            cursor -= _duration(
                child, context.get("divisions"), selected.part_id, diagnostics
            )
            if cursor < 0:
                diagnostics.append(
                    _diagnostic(
                        "warning",
                        "negative-measure-cursor",
                        "A backup moved the measure cursor before zero.",
                        part_id=selected.part_id,
                    )
                )
        elif name == "forward":
            cursor += _duration(
                child, context.get("divisions"), selected.part_id, diagnostics
            )
        elif name == "direction":
            event_offset = cursor + _offset(child, context.get("divisions"))
            directions.append(_direction(child, order, event_offset))
        elif name == "harmony":
            event_offset = cursor + _offset(child, context.get("divisions"))
            harmonies.append(_placed_element(child, order, event_offset))
        elif name == "figured-bass":
            event_offset = cursor
            figured_bass.append(_placed_element(child, order, event_offset))
        elif name == "barline":
            event_offset = cursor
            barlines.append(_barline(child, order, event_offset))

        if context_at_start is None and name in {"note", "backup", "forward"}:
            context_at_start = deepcopy(context)

        if include_elements:
            elements.append(
                {
                    "order": order,
                    "name": name,
                    "offsetBefore": _fraction(offset_before),
                    "effectiveOffset": _fraction(event_offset),
                    "offsetAfter": _fraction(cursor),
                    "value": _element_to_data(child),
                }
            )

    if context_at_start is None:
        context_at_start = deepcopy(context)

    unmodelled_names = sorted(
        {
            name
            for name in element_names
            if name
            not in {
                "attributes",
                "note",
                "backup",
                "forward",
                "direction",
                "harmony",
                "figured-bass",
                "barline",
            }
        }
    )
    if unmodelled_names:
        if include_elements:
            code = "elements-preserved-generically"
            message = (
                "Some elements have no normalized projection but are preserved in "
                "elements: "
            )
        else:
            code = "elements-available-on-request"
            message = (
                "Some elements have no normalized projection; use --include-elements "
                "to return them: "
            )
        diagnostics.append(
            _diagnostic(
                "info",
                code,
                message + ", ".join(unmodelled_names),
                part_id=selected.part_id,
            )
        )

    measure = {
        "attributes": selected.measure_attributes,
        "implicit": selected.measure_attributes.get("implicit") == "yes",
        "nonControlling": selected.measure_attributes.get("non-controlling") == "yes",
        "width": selected.measure_attributes.get("width"),
        "context": _context_to_data(
            context_at_start,
            include_elements=include_elements,
        ),
        "duration": {
            "cursorEnd": _fraction(cursor),
            "maximumEventEnd": _fraction(maximum_event_end),
            "unit": "quarter",
        },
        "events": events,
        "directions": directions,
        "harmonies": harmonies,
        "figuredBass": figured_bass,
        "barlines": barlines,
        "attributeChanges": attribute_changes,
    }
    if include_elements:
        measure["elements"] = elements
    return (
        {
            "partId": selected.part_id,
            "partName": selected.part_name,
            "measure": measure,
        },
        diagnostics,
    )


def _note_event(
    note: ElementTree.Element,
    selected: _SelectedPart,
    note_index: int,
    offset: Fraction,
    divisions: int | None,
    diagnostics: list[dict[str, Any]],
) -> tuple[dict[str, Any], Fraction]:
    duration = _duration(note, divisions, selected.part_id, diagnostics)
    voice = _child_text(note, "voice") or "1"
    staff = _integer_or_text(_child_text(note, "staff") or "1")
    pitch_element = _child(note, "pitch")
    rest_element = _child(note, "rest")
    unpitched_element = _child(note, "unpitched")
    if pitch_element is not None:
        kind = "note"
    elif unpitched_element is not None:
        kind = "unpitched"
    elif rest_element is not None:
        kind = "rest"
    else:
        kind = "unknown"

    printed_measure = selected.measure_attributes.get("number", "")
    event_id = (
        f"{selected.part_id}:m{printed_measure}:s{staff}:v{voice}:"
        f"o{_fraction(offset)}:e{note_index}"
    )
    event: dict[str, Any] = {
        "eventId": event_id,
        "order": note_index,
        "kind": kind,
        "offset": _fraction(offset),
        "duration": _fraction(duration),
        "durationDivisions": _integer_or_text(_child_text(note, "duration")),
        "unit": "quarter",
        "voice": voice,
        "staff": staff,
        "chord": _child(note, "chord") is not None,
        "grace": _optional_element(note, "grace"),
        "cue": _child(note, "cue") is not None,
        "printObject": note.get("print-object", "yes") != "no",
        "type": _child_text(note, "type"),
        "dots": len(_children(note, "dot")),
        "pitch": _pitch(pitch_element),
        "unpitched": _optional_element(note, "unpitched"),
        "rest": _optional_element(note, "rest"),
        "accidental": _optional_element(note, "accidental"),
        "timeModification": _optional_element(note, "time-modification"),
        "instrument": _optional_element(note, "instrument"),
        "stem": _child_text(note, "stem"),
        "notehead": _optional_element(note, "notehead"),
        "ties": [_element_to_data(element) for element in _children(note, "tie")],
        "beams": [_element_to_data(element) for element in _children(note, "beam")],
        "notations": [
            _element_to_data(child)
            for notations in _children(note, "notations")
            for child in notations
        ],
        "lyrics": [_lyric(element) for element in _children(note, "lyric")],
    }
    return event, duration


def _pitch(pitch: ElementTree.Element | None) -> dict[str, Any] | None:
    if pitch is None:
        return None
    return {
        "step": _child_text(pitch, "step"),
        "alter": _child_text(pitch, "alter"),
        "octave": _integer_or_text(_child_text(pitch, "octave")),
    }


def _lyric(lyric: ElementTree.Element) -> dict[str, Any]:
    return {
        "number": lyric.get("number"),
        "name": lyric.get("name"),
        "syllabic": _child_text(lyric, "syllabic"),
        "text": "".join(text.text or "" for text in _children(lyric, "text")),
        "extend": _optional_element(lyric, "extend"),
        "endLine": _child(lyric, "end-line") is not None,
        "endParagraph": _child(lyric, "end-paragraph") is not None,
    }


def _direction(
    direction: ElementTree.Element,
    order: int,
    offset: Fraction,
) -> dict[str, Any]:
    direction_types = [
        _element_to_data(child)
        for container in _children(direction, "direction-type")
        for child in container
    ]
    return {
        "order": order,
        "offset": _fraction(offset),
        "placement": direction.get("placement"),
        "voice": _child_text(direction, "voice"),
        "staff": _integer_or_text(_child_text(direction, "staff")),
        "types": direction_types,
        "text": " ".join(
            text.strip()
            for container in _children(direction, "direction-type")
            for text in container.itertext()
            if text.strip()
        ),
        "sound": _optional_element(direction, "sound"),
    }


def _placed_element(
    element: ElementTree.Element,
    order: int,
    offset: Fraction,
) -> dict[str, Any]:
    return {
        "order": order,
        "offset": _fraction(offset),
        "staff": _integer_or_text(_child_text(element, "staff")),
        "value": _element_to_data(element),
    }


def _barline(
    barline: ElementTree.Element,
    order: int,
    offset: Fraction,
) -> dict[str, Any]:
    return {
        "order": order,
        "offset": _fraction(offset),
        "location": barline.get("location", "right"),
        "barStyle": _child_text(barline, "bar-style"),
        "repeat": _optional_element(barline, "repeat"),
        "ending": _optional_element(barline, "ending"),
        "fermatas": [
            _element_to_data(element) for element in _children(barline, "fermata")
        ],
    }


def _duration(
    element: ElementTree.Element,
    divisions: int | None,
    part_id: str,
    diagnostics: list[dict[str, Any]],
) -> Fraction:
    duration_text = _child_text(element, "duration")
    if duration_text is None:
        return Fraction(0)
    try:
        duration_divisions = int(duration_text)
    except ValueError:
        diagnostics.append(
            _diagnostic(
                "warning",
                "invalid-duration",
                f'Invalid MusicXML duration "{duration_text}".',
                part_id=part_id,
            )
        )
        return Fraction(0)
    if not divisions:
        diagnostics.append(
            _diagnostic(
                "warning",
                "missing-divisions",
                "A duration could not be normalized because divisions is missing or zero.",
                part_id=part_id,
            )
        )
        return Fraction(0)
    return Fraction(duration_divisions, divisions)


def _offset(element: ElementTree.Element, divisions: int | None) -> Fraction:
    value = _child_text(element, "offset")
    if value is None or not divisions:
        return Fraction(0)
    try:
        return Fraction(int(value), divisions)
    except ValueError:
        return Fraction(0)


def _empty_context() -> dict[str, Any]:
    return {
        "divisions": None,
        "staves": None,
        "instruments": None,
        "attributes": {},
    }


def _apply_measure_attributes(
    context: dict[str, Any],
    measure: ElementTree.Element,
) -> None:
    for child in measure:
        if _local_name(child.tag) == "attributes":
            _apply_attributes(context, child)


def _apply_attributes(
    context: dict[str, Any],
    attributes: ElementTree.Element,
) -> None:
    for child in attributes:
        name = _local_name(child.tag)
        if name in {"divisions", "staves", "instruments"}:
            value = _integer_or_text(child.text)
            context[name] = value
            continue
        number = child.get("number", "1")
        context["attributes"].setdefault(name, {})[number] = _attribute_value(
            name,
            child,
        )


def _attribute_value(name: str, element: ElementTree.Element) -> dict[str, Any]:
    value: dict[str, Any] = {
        "number": element.get("number", "1"),
        "element": _element_to_data(element),
    }
    if name == "key":
        value.update(
            {
                "cancel": _integer_or_text(_child_text(element, "cancel")),
                "fifths": _integer_or_text(_child_text(element, "fifths")),
                "mode": _child_text(element, "mode"),
            }
        )
    elif name == "time":
        value.update(
            {
                "symbol": element.get("symbol"),
                "beats": [_text(child) for child in _children(element, "beats")],
                "beatTypes": [
                    _text(child) for child in _children(element, "beat-type")
                ],
                "senzaMisura": _child_text(element, "senza-misura"),
            }
        )
    elif name == "clef":
        value.update(
            {
                "sign": _child_text(element, "sign"),
                "line": _integer_or_text(_child_text(element, "line")),
                "octaveChange": _integer_or_text(
                    _child_text(element, "clef-octave-change")
                ),
            }
        )
    elif name == "transpose":
        value.update(
            {
                "diatonic": _integer_or_text(_child_text(element, "diatonic")),
                "chromatic": _integer_or_text(_child_text(element, "chromatic")),
                "octaveChange": _integer_or_text(_child_text(element, "octave-change")),
                "double": _child(element, "double") is not None,
            }
        )
    return value


def _context_to_data(
    context: dict[str, Any],
    *,
    include_elements: bool,
) -> dict[str, Any]:
    data = deepcopy(context)
    if include_elements:
        return data
    for numbered_attributes in data["attributes"].values():
        for attribute in numbered_attributes.values():
            attribute.pop("element", None)
    return data


def _part_definitions(
    root: ElementTree.Element,
) -> dict[str, ElementTree.Element]:
    part_list = next(
        (child for child in root if _local_name(child.tag) == "part-list"),
        None,
    )
    if part_list is None:
        return {}
    return {
        child.get("id", ""): child
        for child in part_list
        if _local_name(child.tag) == "score-part"
    }


def _part_name(definition: ElementTree.Element | None, part_id: str) -> str:
    if definition is None:
        return part_id
    part_name = _child(definition, "part-name")
    if part_name is None:
        return part_id
    return "".join(part_name.itertext()).strip() or part_id


def _element_to_data(element: ElementTree.Element) -> dict[str, Any]:
    namespace, name = _split_name(element.tag)
    data: dict[str, Any] = {"name": name}
    if namespace:
        data["namespace"] = namespace
    if element.attrib:
        data["attributes"] = {
            _qualified_name(key): value for key, value in element.attrib.items()
        }
    if element.text and element.text.strip():
        data["text"] = element.text
    children = []
    for child in element:
        child_data = _element_to_data(child)
        if child.tail and child.tail.strip():
            child_data["tail"] = child.tail
        children.append(child_data)
    if children:
        data["children"] = children
    return data


def _optional_element(
    parent: ElementTree.Element,
    name: str,
) -> dict[str, Any] | None:
    element = _child(parent, name)
    return _element_to_data(element) if element is not None else None


def _child(
    parent: ElementTree.Element | None,
    name: str,
) -> ElementTree.Element | None:
    if parent is None:
        return None
    return next(
        (child for child in parent if _local_name(child.tag) == name),
        None,
    )


def _children(
    parent: ElementTree.Element,
    name: str,
) -> list[ElementTree.Element]:
    return [child for child in parent if _local_name(child.tag) == name]


def _child_text(parent: ElementTree.Element | None, name: str) -> str | None:
    child = _child(parent, name)
    return _text(child) if child is not None else None


def _text(element: ElementTree.Element) -> str:
    return "".join(element.itertext()).strip()


def _split_name(name: str) -> tuple[str | None, str]:
    if name.startswith("{") and "}" in name:
        namespace, local = name[1:].split("}", 1)
        return namespace, local
    return None, name


def _local_name(name: str) -> str:
    return _split_name(name)[1]


def _qualified_name(name: str) -> str:
    namespace, local = _split_name(name)
    return f"{{{namespace}}}{local}" if namespace else local


def _integer_or_text(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _fraction(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else str(value)


def _diagnostic(
    severity: str,
    code: str,
    message: str,
    *,
    part_id: str | None = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if part_id is not None:
        diagnostic["partId"] = part_id
    return diagnostic


def _format_text(document: dict[str, Any]) -> str:
    lines = [f"Measure {document['measure']['printedNumber']}", ""]

    for part in document["parts"]:
        measure = part["measure"]
        lines.append(f"{part['partName']} [{part['partId']}]")
        context = measure["context"]
        context_fragments = _context_fragments(context)
        if context_fragments:
            lines.append("  Context: " + ", ".join(context_fragments))
        if not measure["events"]:
            lines.append("  No note/rest events")
        for event in measure["events"]:
            description = _event_description(event)
            lines.append(
                f"  {event['offset']}: {description}; duration "
                f"{event['duration']} quarter; staff {event['staff']}; "
                f"voice {event['voice']}"
            )
        for direction in measure["directions"]:
            text = direction.get("text") or "direction"
            lines.append(f"  {direction['offset']}: {text}")
        lines.append("")

    diagnostics = document["diagnostics"]
    if diagnostics:
        lines.append("Diagnostics")
        for diagnostic in diagnostics:
            lines.append(
                f"  [{diagnostic['severity']}] {diagnostic['code']}: "
                f"{diagnostic['message']}"
            )
    return "\n".join(lines).rstrip() + "\n"


def _context_fragments(context: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    divisions = context.get("divisions")
    if divisions is not None:
        fragments.append(f"divisions {divisions}")
    attributes = context.get("attributes", {})
    for key in attributes.get("key", {}).values():
        if key.get("fifths") is not None:
            fragments.append(f"key fifths {key['fifths']}")
    for time in attributes.get("time", {}).values():
        beats = "+".join(time.get("beats", []))
        beat_types = "+".join(time.get("beatTypes", []))
        if beats and beat_types:
            fragments.append(f"time {beats}/{beat_types}")
    return fragments


def _event_description(event: dict[str, Any]) -> str:
    if event["kind"] == "rest":
        description = "rest"
    elif event["kind"] == "note" and event["pitch"]:
        pitch = event["pitch"]
        description = f"{pitch['step']}{_alter_symbol(pitch['alter'])}{pitch['octave']}"
    else:
        description = event["kind"]
    lyrics = [lyric["text"] for lyric in event["lyrics"] if lyric["text"]]
    if lyrics:
        description += " lyric " + "/".join(lyrics)
    if event["chord"]:
        description += " chord"
    if event["grace"] is not None:
        description += " grace"
    return description


def _alter_symbol(value: str | None) -> str:
    return {
        "-2": "bb",
        "-1": "b",
        "0": "",
        "1": "#",
        "2": "x",
    }.get(value or "0", f"({value})")
