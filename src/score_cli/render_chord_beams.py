"""Normalize proven duplicate chord beams in the Verovio render copy only."""
from __future__ import annotations

from typing import Any

from lxml import etree


def normalize_chord_beams(root: Any, compatibility: dict) -> int:
    ns = etree.QName(root).namespace
    tag = lambda name: f"{{{ns}}}{name}" if ns else name
    removed = groups = 0
    unchecked = []

    def normalize(notes: list[Any], part_id: str | None, measure: str | None):
        nonlocal removed, groups
        if len(notes) < 2 or not any(note.findall(tag("beam")) for note in notes):
            return
        beams = [note.findall(tag("beam")) for note in notes]
        # Restrict to ordinary same-lane, same-value chords. Do not infer beam
        # ownership for cross-staff, grace, conflicting, fanned or identified beams.
        signature = lambda note: (
            note.findtext(tag("voice"), "1"), note.findtext(tag("staff"), "1"),
            note.findtext(tag("duration")), note.findtext(tag("type")),
            len(note.findall(tag("dot"))), note.findtext(tag("stem")),
            note.get("print-object", "yes"), note.get("print-spacing", "yes"),
        )
        beam_signature = lambda items: [
            (tuple(sorted(beam.attrib.items())), (beam.text or "").strip())
            for beam in items
        ]
        valid = (
            bool(beams[0])
            and all(signature(note) == signature(notes[0]) for note in notes)
            and all(note.find(tag("pitch")) is not None or
                    note.find(tag("unpitched")) is not None for note in notes)
            and not any(note.find(tag(name)) is not None
                        for note in notes for name in ("grace", "cue", "rest"))
            and all(beam_signature(items) == beam_signature(beams[0]) for items in beams)
            and all(set(beam.attrib) <= {"number"} and not len(beam)
                    and (beam.text or "").strip() in
                    {"begin", "continue", "end", "forward hook", "backward hook"}
                    for items in beams for beam in items)
        )
        numbers = [beam.get("number", "1") for beam in beams[0]]
        valid = valid and len(numbers) == len(set(numbers)) and all(
            number in {str(i) for i in range(1, 9)} for number in numbers
        )
        if not valid:
            unchecked.append(dict(partId=part_id, printedMeasure=measure,
                                  reason="unproven-chord-beam-equivalence"))
            return
        for note, items in zip(notes[1:], beams[1:]):
            for beam in items:
                note.remove(beam)
                removed += 1
        groups += 1

    for part in root.findall(tag("part")):
        for measure in part.findall(tag("measure")):
            notes: list[Any] = []
            for child in measure:
                if child.tag == tag("note") and child.find(tag("chord")) is not None:
                    if notes:
                        notes.append(child)
                    continue
                normalize(notes, part.get("id"), measure.get("number"))
                notes = [child] if child.tag == tag("note") else []
            normalize(notes, part.get("id"), measure.get("number"))
    if groups or unchecked:
        compatibility["duplicateChordBeams"] = dict(
            adapter="verovio-6.3-duplicate-chord-beams", renderCopyOnly=True,
            normalizedChords=groups, removedElements=removed, unchecked=unchecked,
            sourceXmlUnchanged=True,
        )
    return removed
