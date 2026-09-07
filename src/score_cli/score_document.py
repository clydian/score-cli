"""Preserving XML document and immutable-snapshot musical locations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile, BadZipFile

from lxml import etree as ET

VERSION = "1"


class ScoreError(ValueError):
    """A machine-readable failure with a stable code and location."""

    def __init__(
        self,
        code: str,
        message: str,
        location: dict | None = None,
        operation_id: str | None = None,
    ):
        super().__init__(message)
        self.diagnostic = dict(
            code=code,
            severity="error",
            location=location or {},
            reason=message,
            operationId=operation_id,
        )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def name(element: ET._Element) -> str:
    if not isinstance(element.tag, str):
        return ""
    qname = ET.QName(element)
    root_namespace = ET.QName(element.getroottree().getroot()).namespace
    return qname.localname if qname.namespace == root_namespace else element.tag


def children(element: ET._Element, tag: str) -> list[ET._Element]:
    if not isinstance(element.tag, str):
        return []
    namespace = ET.QName(element).namespace
    return [e for e in element if name(e) == tag and ET.QName(e).namespace == namespace]


def child(element: ET._Element, tag: str) -> ET._Element | None:
    return next(iter(children(element, tag)), None)


def content(element: ET._Element, tag: str, default: str = "") -> str:
    found = child(element, tag)
    return found.text or default if found is not None else default


def make(
    parent: ET._Element, tag: str, text: str | None = None, **attrs: str
) -> ET._Element:
    ns = ET.QName(parent).namespace
    element = ET.Element(f"{{{ns}}}{tag}" if ns else tag, attrib=attrs)
    element.text = text
    return element


NOTE_ORDER = "grace cue chord pitch unpitched rest duration tie instrument footnote level voice type dot accidental time-modification stem notehead notehead-text staff beam notations lyric play listen".split()


def insert_note(note: ET._Element, element: ET._Element) -> None:
    rank = NOTE_ORDER.index(name(element))
    for index, existing in enumerate(note):
        if name(existing) in NOTE_ORDER and NOTE_ORDER.index(name(existing)) > rank:
            note.insert(index, element)
            return
    note.append(element)


def replace_note_children(
    note: ET._Element, tag: str, elements: list[ET._Element]
) -> None:
    old = children(note, tag)
    position = note.index(old[0]) if old else None
    for e in old:
        note.remove(e)
    for e in elements:
        if position is None:
            insert_note(note, e)
        else:
            note.insert(position, e)
            position += 1


def tree_data(element: ET._Element) -> dict[str, Any]:
    """Prefix-independent XML semantics; retain unknown elements and attributes."""
    return {
        "tag": element.tag if isinstance(element.tag, str) else name(element),
        "attributes": dict(element.attrib),
        "text": (element.text or "").strip(),
        "children": [tree_data(e) for e in element if isinstance(e.tag, str)],
    }


@dataclass
class Event:
    element: ET._Element
    location: dict[str, Any]
    divisions: Fraction
    duration: Fraction
    measure_ordinal: int
    context: dict[str, Any]

    @property
    def offset(self) -> Fraction:
        return Fraction(self.location["offset"])


@dataclass
class TimelinePosition:
    element: ET._Element
    part_id: str
    printed_measure: str
    measure_ordinal: int
    element_index: int
    note_index: int
    cursor_before: Fraction
    offset: Fraction
    duration: Fraction
    divisions: Fraction
    context: dict[str, Any]


def pitch_value(note: ET._Element) -> dict | None:
    pitch = child(note, "pitch")
    if pitch is None:
        return None
    return dict(
        step=content(pitch, "step"),
        alter=str(Fraction(content(pitch, "alter", "0"))),
        octave=int(content(pitch, "octave")),
        accidental=content(note, "accidental") or None,
    )


class ScoreDocument:
    def __init__(self, data: bytes):
        try:
            parser = ET.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                remove_comments=False,
                remove_pis=False,
                strip_cdata=False,
            )
            self.tree = ET.parse(BytesIO(data), parser)
        except ET.XMLSyntaxError as exc:
            raise ScoreError("parse-error", str(exc)) from exc
        self.root = self.tree.getroot()
        if name(self.root) not in {"score-partwise", "score-timewise"}:
            raise ScoreError(
                "unsupported-root", "Expected score-partwise or score-timewise."
            )
        if any(isinstance(e, ET._Entity) for e in self.root.iter()):
            raise ScoreError(
                "unsupported-entity", "Entity references cannot be safely edited."
            )
        if any(name(e) in {"image", "link"} for e in self.root.iter()):
            raise ScoreError(
                "unsupported-resource",
                "Linked resources cannot be preserved in standalone output.",
            )

    @classmethod
    def read(cls, path: str | Path, *, data: bytes | None = None) -> ScoreDocument:
        path = Path(path)
        data = path.read_bytes() if data is None else data
        if path.suffix.lower() == ".mxl":
            try:
                with ZipFile(BytesIO(data)) as archive:
                    entries = [n for n in archive.namelist() if not n.endswith("/")]
                    container = cls._container(archive)
                    score_entries = [
                        n for n in entries if not n.startswith("META-INF/")
                    ]
                    if len(score_entries) != 1 or container not in score_entries:
                        raise ScoreError(
                            "unsupported-mxl-resources",
                            "MXL must contain exactly the declared score and META-INF/container.xml; attachments are unsupported.",
                        )
                    if set(entries) != {container, "META-INF/container.xml"}:
                        raise ScoreError(
                            "unsupported-mxl-resources",
                            "Additional container resources are unsupported.",
                        )
                    data = archive.read(container)
            except (BadZipFile, KeyError, ET.XMLSyntaxError) as exc:
                raise ScoreError("parse-error", f"Invalid MXL: {exc}") from exc
        elif path.suffix.lower() not in {".xml", ".musicxml"}:
            raise ScoreError("unsupported-format", "Expected .xml, .musicxml or .mxl.")
        return cls(data)

    @staticmethod
    def _container(archive: ZipFile) -> str:
        root = ET.fromstring(
            archive.read("META-INF/container.xml"),
            ET.XMLParser(resolve_entities=False, no_network=True),
        )
        files = root.findall(".//{*}rootfile")
        if len(files) != 1:
            raise ScoreError(
                "unsupported-mxl-resources", "Exactly one MXL rootfile is supported."
            )
        return files[0].get("full-path", "")

    def serialize(self) -> bytes:
        return ET.tostring(self.tree, encoding="UTF-8", xml_declaration=True)

    def measures(self) -> list[tuple[str, str, int, ET._Element, ET._Element]]:
        result = []
        if name(self.root) == "score-partwise":
            for part in children(self.root, "part"):
                for ordinal, measure in enumerate(children(part, "measure"), 1):
                    result.append(
                        (
                            part.get("id", ""),
                            measure.get("number", ""),
                            ordinal,
                            measure,
                            measure,
                        )
                    )
        else:
            for ordinal, measure in enumerate(children(self.root, "measure"), 1):
                for part in children(measure, "part"):
                    result.append(
                        (
                            part.get("id", ""),
                            measure.get("number", ""),
                            ordinal,
                            part,
                            measure,
                        )
                    )
        return result

    def timeline(self) -> list[TimelinePosition]:
        positions = []
        contexts: dict[str, dict] = {}
        for part, printed, ordinal, measure, _ in self.measures():
            context = contexts.setdefault(part, {"divisions": Fraction(1)})
            cursor = Fraction(0)
            last_offset = cursor
            note_index = 0
            for element_index, element in enumerate(measure):
                tag = name(element)
                before = cursor
                offset = cursor
                duration = Fraction(0)
                if tag == "attributes":
                    if child(element, "divisions") is not None:
                        context["divisions"] = Fraction(content(element, "divisions"))
                        if context["divisions"] <= 0:
                            raise ScoreError(
                                "invalid-divisions",
                                "Divisions must be positive.",
                                dict(partId=part, printedMeasure=printed),
                            )
                    for key in (
                        "transpose",
                        "clef",
                        "time",
                        "key",
                        "staff-details",
                        "staves",
                    ):
                        for item in children(element, key):
                            context[f"{key}:{item.get('number', 'all')}"] = tree_data(
                                item
                            )
                elif tag in {"note", "backup", "forward"}:
                    duration = (
                        Fraction(content(element, "duration", "0"))
                        / context["divisions"]
                    )
                    if tag == "backup":
                        cursor -= duration
                    elif tag == "forward":
                        cursor += duration
                    else:
                        note_index += 1
                        is_chord = child(element, "chord") is not None
                        if not is_chord:
                            last_offset = cursor
                        offset = last_offset
                        if not is_chord and child(element, "grace") is None:
                            cursor += duration
                elif tag in {"direction", "harmony", "figured-bass"}:
                    offset += (
                        Fraction(content(element, "offset", "0")) / context["divisions"]
                    )
                positions.append(
                    TimelinePosition(
                        element,
                        part,
                        printed,
                        ordinal,
                        element_index,
                        note_index,
                        before,
                        offset,
                        duration,
                        context["divisions"],
                        dict(context),
                    )
                )
        return positions

    def events(self) -> list[Event]:
        return [
            Event(
                p.element,
                dict(
                    partId=p.part_id,
                    printedMeasure=p.printed_measure,
                    staff=content(p.element, "staff", "1"),
                    voice=content(p.element, "voice", "1"),
                    offset=str(p.offset),
                    eventIndex=p.note_index,
                ),
                p.divisions,
                p.duration,
                p.measure_ordinal,
                p.context,
            )
            for p in self.timeline()
            if name(p.element) == "note"
        ]

    def locate(self, target: dict) -> Event:
        required = {
            "partId",
            "printedMeasure",
            "staff",
            "voice",
            "offset",
            "eventIndex",
        }
        if (
            set(target) != required
            or not all(isinstance(target[k], str) for k in required - {"eventIndex"})
            or type(target["eventIndex"]) is not int
        ):
            raise ScoreError(
                "invalid-locator",
                "Note locator requires exact string fields and a one-based integer eventIndex.",
                target,
            )
        matches = [
            m
            for m in self.measures()
            if m[0] == target["partId"] and m[1] == target["printedMeasure"]
        ]
        if len(matches) != 1:
            raise ScoreError(
                "ambiguous-measure" if matches else "target-missing",
                "Printed measure must occur exactly once in the part.",
                target,
            )
        found = [event for event in self.events() if event.location == target]
        if len(found) != 1:
            raise ScoreError(
                "target-missing",
                "No unique note matches the complete snapshot locator.",
                target,
            )
        return found[0]


def placed_offsets(document: ScoreDocument) -> dict:
    """Track unchanged direction/harmony placement across a transaction."""
    return {
        p.element: p.offset
        for p in document.timeline()
        if name(p.element) in {"direction", "harmony", "figured-bass"}
    }
