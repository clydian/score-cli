"""Restore explicit lyric placement lost by Verovio 6.3's MusicXML importer."""
from __future__ import annotations

from typing import Any, Callable
from collections import Counter
from lxml import etree

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _closed_continuations(root: Any, tag: Callable[[str], str]) -> dict:
    """Prove empty continuation nodes belong to a closed source lyric lane."""
    proven = {}
    for part in root.findall(tag("part")):
        opened: dict = {}
        for measure in part.findall(tag("measure")):
            for note in measure.findall(tag("note")):
                for lyric in note.findall(tag("lyric")):
                    number = lyric.get("number", "1")
                    if number.isascii() and number.isdigit():
                        number = str(int(number))
                    lane = (note.findtext(tag("voice"), "1"),
                            note.findtext(tag("staff"), "1"), number)
                    extensions = lyric.findall(tag("extend"))
                    kind = extensions[0].get("type") if len(extensions) == 1 else None
                    pure = len(lyric) == 1 and len(extensions) == 1
                    if lyric.get("placement") != "above":
                        opened.pop(lane, None)
                    elif kind == "start" and lyric.find(tag("text")) is not None:
                        opened[lane] = (lyric, [])
                    elif kind == "continue" and pure and lane in opened:
                        opened[lane][1].append(lyric)
                    elif kind == "stop" and pure and lane in opened:
                        start, middle = opened.pop(lane)
                        for continuation in middle:
                            proven[continuation] = (start, lyric)
                    else:
                        opened.pop(lane, None)
    return proven


def load_render_score(toolkit: Any, xml: str, compatibility: dict) -> bool:
    """Use native MEI verse placement, only in the ephemeral render document.

    Identity is note ID plus a unique numeric verse number, never lyric text or
    document-wide lyric order. Unsupported mappings fail closed rather than
    silently assigning the source instruction to a different voice.
    """
    root = etree.fromstring(xml.encode())
    ns = etree.QName(root).namespace
    tag = lambda name: f"{{{ns}}}{name}" if ns else name
    records: list[tuple[str, str, Any]] = []
    continuations = _closed_continuations(root, tag)
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
                    records.append((identity, str(int(number)), lyric))
    if not records:
        return bool(toolkit.loadData(xml))
    if not toolkit.loadData(etree.tostring(root, encoding="unicode")):
        return False
    mei = etree.fromstring(toolkit.getMEI().encode())
    namespace = etree.QName(mei).namespace
    mei_tag = lambda name: f"{{{namespace}}}{name}"
    by_id = {el.get(XML_ID): el for el in mei.iter() if el.get(XML_ID)}
    mapped = {}
    omitted = []
    for identity, number, lyric in records:
        target = by_id.get(identity)
        verses = [] if target is None else [v for v in target.findall(mei_tag("verse")) if v.get("n") == number]
        if target is not None and not verses and lyric in continuations:
            omitted.append(lyric)
            continue
        if len(verses) != 1:
            raise ValueError("Verovio did not retain an unambiguous above-lyric note/verse mapping.")
        mapped[lyric] = verses[0]
    for lyric in omitted:
        start, stop = continuations[lyric]
        first, last = mapped.get(start), mapped.get(stop)
        if first is None or last is None or not any(
            syl.get("con") == "u" for syl in first.findall(mei_tag("syl"))
        ):
            raise ValueError("Verovio did not retain an unambiguous above-lyric extender span.")
    for verse in mapped.values():
        verse.set("place", "above")
    # The CLI explicitly selects MusicXML for the first load. Switch only the
    # input decoder for the already-imported MEI; keep all layout options.
    toolkit.setOptions({"inputFrom": "mei"})
    if not toolkit.loadData(etree.tostring(mei, encoding="unicode")):
        return False
    compatibility["explicitAboveLyrics"] = dict(
        adapter="verovio-6.3-mei-verse-placement", renderCopyOnly=True,
        mappedVerseElements=len(mapped), sourceXmlUnchanged=True,
        omittedContinuationElements=len(omitted),
    )
    return True
