"""Keep explicit MusicXML rest staves in Verovio's render-only MEI."""
from __future__ import annotations

from collections import Counter
from typing import Any
from lxml import etree

from .render_lyrics import XML_ID, load_render_score as load_lyrics_score


def load_render_score(toolkit: Any, xml: str, compatibility: dict) -> bool:
    root = etree.fromstring(xml.encode())
    ns = etree.QName(root).namespace
    tag = lambda name: f"{{{ns}}}{name}" if ns else name
    counts = Counter(v for el in root.iter() for v in
                     {v for k, v in el.attrib.items() if k in ("id", XML_ID)})
    used = set(counts)
    expected: dict[str, str] = {}
    rests: list[str] = []
    variable_parts = []
    offset = serial = 0
    for part in root.findall(tag("part")):
        declarations = [int(s.text) for s in part.iter(tag("staves"))
                        if s.text and s.text.isascii() and s.text.isdigit()]
        effective_counts = set()
        current_count = 1
        for measure in part.findall(tag("measure")):
            saw_event = False
            for child in measure:
                if child.tag == tag("attributes"):
                    value = child.findtext(tag("staves"))
                    if value and value.isascii() and value.isdigit():
                        current_count = int(value)
                elif child.tag in (tag("note"), tag("forward")):
                    effective_counts.add(current_count)
                    saw_event = True
            if not saw_event:
                effective_counts.add(current_count)
        staves = max(declarations, default=1)
        if len(effective_counts) > 1:
            variable_parts.append(dict(partId=part.get("id"), reason="variable-staff-count"))
        if staves > 1 and len(set(declarations)) <= 1 and any(
                note.find(tag("rest")) is not None for note in part.iter(tag("note"))):
            for measure in part.findall(tag("measure")):
                for note in measure.findall(tag("note")):
                    staff_number = note.findtext(tag("staff"), "1")
                    if not staff_number.isascii() or not staff_number.isdigit() or not 1 <= int(staff_number) <= staves:
                        raise ValueError("Rest-staff rendering requires a valid explicit staff.")
                    if note.get("id") and note.get(XML_ID) and note.get("id") != note.get(XML_ID):
                        raise ValueError("Rest-staff note has conflicting id and xml:id identities.")
                    identity = note.get("id") or note.get(XML_ID)
                    if identity and counts[identity] != 1:
                        raise ValueError("Rest-staff rendering requires unambiguous note IDs.")
                    if not identity:
                        serial += 1
                        identity = f"scorecli-rest-note-{serial}"
                        while identity in used:
                            serial += 1
                            identity = f"scorecli-rest-note-{serial}"
                    note.attrib.pop(XML_ID, "")
                    note.set("id", identity)
                    used.add(identity)
                    expected[identity] = str(offset + int(staff_number))
                    if note.find(tag("rest")) is not None and note.get("print-object") != "no":
                        rests.append(identity)
        offset += staves
    if variable_parts:
        compatibility["explicitRestStaff"] = dict(
            adapter="verovio-6.3-mei-rest-staff", renderCopyOnly=True,
            relocatedLayers=0, unchecked=variable_parts, sourceXmlUnchanged=True,
        )
        return load_lyrics_score(toolkit, xml, compatibility)
    if not rests:
        return load_lyrics_score(toolkit, xml, compatibility)
    if not load_lyrics_score(toolkit, etree.tostring(root, encoding="unicode"), compatibility):
        return False
    mei = etree.fromstring(toolkit.getMEI().encode())
    mei_ns = etree.QName(mei).namespace
    mt = lambda name: f"{{{mei_ns}}}{name}"
    by_id = {el.get(XML_ID): el for el in mei.iter() if el.get(XML_ID)}
    moved = 0
    unchecked = []
    for identity in rests:
        rest = by_id.get(identity)
        if rest is None or rest.tag not in (mt("rest"), mt("mRest")):
            raise ValueError("Verovio did not retain an unambiguous rest identity.")
        layer = next((p for p in rest.iterancestors() if p.tag == mt("layer")), None)
        staff = None if layer is None else layer.getparent()
        if layer is None or staff is None or staff.tag != mt("staff"):
            raise ValueError("Verovio rest has no identifiable staff/layer.")
        rendered_measure = staff.getparent()
        if rendered_measure is None:
            raise ValueError("Verovio rest staff has no measure.")
        target = expected[identity]
        if staff.get("n") == target:
            continue
        # Relocate only a complete single-staff source voice. Splitting a
        # genuine cross-staff timeline would change its time/voice semantics.
        events = [el for el in layer.iter() if el.tag in (mt("note"), mt("rest"), mt("mRest")) or
                  (el.tag in (mt("space"), mt("mSpace")) and el.get(XML_ID) in expected)]
        destinations = {expected.get(el.get(XML_ID, "")) for el in events}
        destination = next((s for s in rendered_measure.findall(mt("staff")) if s.get("n") == target), None)
        occupied = destination is not None and any(
            other.get("n") == layer.get("n") for other in destination.findall(mt("layer")))
        if destinations != {target} or destination is None or occupied:
            unchecked.append(dict(noteId=identity, reason="mixed-or-unmapped-layer", sourceStaff=target))
            continue
        staff.remove(layer)
        destination.append(layer)
        for event in events:
            if event.get("staff") == target:
                event.attrib.pop("staff")
        if not staff.findall(mt("layer")):
            empty = etree.SubElement(staff, mt("layer"), n="1")
            etree.SubElement(empty, mt("mSpace"))
        moved += 1
    if moved:
        toolkit.setOptions({"inputFrom": "mei"})
        if not toolkit.loadData(etree.tostring(mei, encoding="unicode")):
            return False
    else:
        # Unaffected scores retain the original import, including its IDs.
        toolkit.setOptions({"inputFrom": "xml"})
        if not load_lyrics_score(toolkit, xml, compatibility):
            return False
    compatibility["explicitRestStaff"] = dict(
        adapter="verovio-6.3-mei-rest-staff", renderCopyOnly=True,
        relocatedLayers=moved, unchecked=unchecked, sourceXmlUnchanged=True,
    )
    return True
