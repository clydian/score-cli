"""Restore explicit lyric placement lost by Verovio 6.3's MusicXML importer."""
from __future__ import annotations

from typing import Any
from collections import Counter
from lxml import etree

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def load_render_score(toolkit: Any, xml: str, compatibility: dict) -> bool:
    """Use native MEI verse placement, only in the ephemeral render document.

    Identity is note ID plus a unique numeric verse number, never lyric text or
    document-wide lyric order. Unsupported mappings fail closed rather than
    silently assigning the source instruction to a different voice.
    """
    root = etree.fromstring(xml.encode())
    ns = etree.QName(root).namespace
    tag = lambda name: f"{{{ns}}}{name}" if ns else name
    records: list[tuple[str, str]] = []
    identities = Counter(v for el in root.iter() for v in
                         {v for k, v in el.attrib.items() if k in ("id", XML_ID)})
    used = set(identities)
    serial = 0
    for part in root.findall(tag("part")):
        for measure in part.findall(tag("measure")):
            for note in measure.findall(tag("note")):
                lyrics = note.findall(tag("lyric"))
                above = [lyric for lyric in lyrics if lyric.get("placement") == "above"]
                if not above:
                    continue
                numbers = [str(int(value)) if value.isascii() and value.isdigit() else value
                           for lyric in lyrics for value in [lyric.get("number", "1")]]
                if note.get("id") and note.get(XML_ID) and note.get("id") != note.get(XML_ID):
                    raise ValueError("Above lyric note has conflicting id and xml:id identities.")
                identity = note.get("id") or note.get(XML_ID)
                if identity and identities[identity] != 1:
                    raise ValueError("Above lyric requires an unambiguous note ID for Verovio rendering.")
                if not identity:
                    serial += 1
                    identity = f"scorecli-above-note-{serial}"
                    while identity in used:
                        serial += 1
                        identity = f"scorecli-above-note-{serial}"
                # Preserve source identities/references; supply an ID only on
                # previously anonymous notes in the ephemeral render copy.
                note.attrib.pop(XML_ID, "")
                note.set("id", identity)
                used.add(identity)
                for lyric in above:
                    number = lyric.get("number", "1")
                    if not number.isascii() or not number.isdigit() or int(number) < 1 or numbers.count(str(int(number))) != 1:
                        raise ValueError("Above lyric requires a unique positive numeric verse number for Verovio rendering.")
                    records.append((identity, str(int(number))))
    if not records:
        return bool(toolkit.loadData(xml))
    if not toolkit.loadData(etree.tostring(root, encoding="unicode")):
        return False
    mei = etree.fromstring(toolkit.getMEI().encode())
    namespace = etree.QName(mei).namespace
    mei_tag = lambda name: f"{{{namespace}}}{name}"
    by_id = {el.get(XML_ID): el for el in mei.iter() if el.get(XML_ID)}
    for identity, number in records:
        target = by_id.get(identity)
        verses = [] if target is None else [v for v in target.findall(mei_tag("verse")) if v.get("n") == number]
        if len(verses) != 1:
            raise ValueError("Verovio did not retain an unambiguous above-lyric note/verse mapping.")
        verses[0].set("place", "above")
    # The CLI explicitly selects MusicXML for the first load. Switch only the
    # input decoder for the already-imported MEI; keep all layout options.
    toolkit.setOptions({"inputFrom": "mei"})
    if not toolkit.loadData(etree.tostring(mei, encoding="unicode")):
        return False
    compatibility["explicitAboveLyrics"] = dict(
        adapter="verovio-6.3-mei-verse-placement", renderCopyOnly=True,
        mappedVerseElements=len(records), sourceXmlUnchanged=True,
    )
    return True
