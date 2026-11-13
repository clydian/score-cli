"""Preserve clef-relative unpitched positions in Verovio 6.3's render copy."""
from __future__ import annotations

from typing import Any

from lxml import etree


def normalize_unpitched_positions(root: Any, compatibility: dict) -> int:
    """6.3 imports display-step/octave as treble positions for every clef.

    MusicXML defines them relative to the current clef. Convert only proven
    five-line G/F/C contexts to the equivalent treble position for this import.
    This does not give spoken notes pitch, or make their playback supported.
    """
    ns = etree.QName(root).namespace
    tag = lambda name: f"{{{ns}}}{name}" if ns else name
    steps = "CDEFGAB"
    anchors = {"G": 32, "F": 24, "C": 28}
    changed: list[dict] = []
    unchecked: list[dict] = []
    for part in root.findall(tag("part")):
        clefs: dict[str, tuple[str, int, int] | None] = {}
        lines: dict[str, int | None] = {}
        default_lines: int | None = 5
        has_octave_shift = bool(part.findall(".//" + tag("octave-shift")))
        for measure in part.findall(tag("measure")):
            for child in measure:
                if child.tag == tag("attributes"):
                    for clef in child.findall(tag("clef")):
                        staff = clef.get("number", "1")
                        try:
                            sign = clef.findtext(tag("sign"), "")
                            line = int(clef.findtext(tag("line"), "0"))
                            octave = int(clef.findtext(tag("clef-octave-change"), "0"))
                            clefs[staff] = (sign, line, octave)
                        except ValueError:
                            clefs[staff] = None
                    for details in child.findall(tag("staff-details")):
                        value = details.findtext(tag("staff-lines"))
                        if value is not None:
                            try:
                                line_count = int(value)
                            except ValueError:
                                line_count = None
                            if details.get("number") is None:
                                default_lines = line_count
                                lines.clear()
                            else:
                                lines[details.get("number")] = line_count
                elif child.tag == tag("note"):
                    unpitched = child.find(tag("unpitched"))
                    if unpitched is None:
                        continue
                    staff = child.findtext(tag("staff"), "1")
                    location = dict(partId=part.get("id"), printedMeasure=measure.get("number"), staff=staff)
                    step = unpitched.find(tag("display-step"))
                    octave_element = unpitched.find(tag("display-octave"))
                    # An empty unpitched is the staff middle line; no rewrite.
                    if step is None and octave_element is None:
                        continue
                    clef_context = clefs.get(staff)
                    try:
                        if (clef_context is None or lines.get(staff, default_lines) != 5 or has_octave_shift
                                or step is None or step.text not in steps or len(step.text or "") != 1
                                or octave_element is None):
                            raise ValueError
                        sign, line, clef_octave = clef_context
                        if sign == "percussion":
                            continue  # Defined as treble positions by MusicXML.
                        if sign not in anchors or not 1 <= line <= 5 or not -2 <= clef_octave <= 2:
                            raise ValueError
                        source_octave = int(octave_element.text or "")
                        if not 0 <= source_octave <= 9:
                            raise ValueError
                        source_diatonic = source_octave * 7 + steps.index(step.text)
                        loc = source_diatonic - anchors[sign] - 7 * clef_octave + 2 * (line - 1)
                        render_octave, render_step = divmod(loc + 30, 7)
                        if not 0 <= render_octave <= 9:
                            raise ValueError
                    except (ValueError, TypeError):
                        unchecked.append(dict(**location, reason="unproven-clef-relative-unpitched-position"))
                        continue
                    if (step.text, source_octave) == (steps[render_step], render_octave):
                        continue
                    changed.append(dict(**location, sourceStep=step.text, sourceOctave=source_octave,
                                        renderStep=steps[render_step], renderOctave=render_octave, staffLocation=loc))
                    step.text = steps[render_step]
                    octave_element.text = str(render_octave)
    if changed or unchecked:
        compatibility["unpitchedDisplayPositions"] = dict(
            adapter="verovio-6.3-clef-relative-unpitched", renderCopyOnly=True,
            sourceXmlUnchanged=True, normalizedNotes=changed, unchecked=unchecked,
            playbackVerified=False,
        )
    return len(changed)
