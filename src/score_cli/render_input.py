"""Narrow, reported compatibility adaptations for Verovio's render copy."""
from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from .render_brackets import direction_bracket_warnings
from .render_keys import key_change_warnings


@dataclass(frozen=True, slots=True)
class RenderInput:
    xml: str
    compatibility: dict


def _tag(element: etree._Element) -> str:
    return etree.QName(element).localname


def _signature(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n", with_comments=False)


def _element_children(element: etree._Element) -> list[etree._Element]:
    # Comments and processing instructions have callable tags, not QNames.
    # Keep them in the render document; only element children define meter.
    return [child for child in element if isinstance(child.tag, str)]


def _simple_meter(time: etree._Element) -> bool:
    children = _element_children(time)
    return (
        not time.attrib
        and [_tag(child) for child in children] == ["beats", "beat-type"]
        and all((child.text or "").isdigit() and int(child.text or "0") > 0 for child in children)
    )


def prepare_render_input(xml: str) -> RenderInput:
    """Keep shared senza in the first part; omit only proven redundant copies.

    Verovio 6.3's non-first-part attributes importer reads a missing beat-type
    as zero. Direction timestamps then collapse to one. Its first-part path
    correctly retains the previous meter unit. Do not invent a beat-type or
    alter notes: let the already imported shared declaration govern rendering.
    Independent/staff-numbered/ambiguous meter contexts are left unchecked.
    """
    root = etree.fromstring(xml.encode(), etree.XMLParser(remove_blank_text=True))
    parts = root.findall("{*}part")
    applied: list[dict] = []
    unchecked: list[dict] = []
    first_contexts: dict[int, tuple[bytes | None, bytes | None]] = {}
    for part_index, part in enumerate(parts):
        previous_meter: bytes | None = None
        for ordinal, measure in enumerate(part.findall("{*}measure"), 1):
            times = measure.findall("{*}attributes/{*}time")
            if not times:
                continue
            if len(times) != 1:
                previous_meter = None
                if part_index:
                    unchecked.append(dict(partId=part.get("id"), measureOrdinal=ordinal,
                                          reason="multiple or staff-specific time declarations"))
                continue
            time = times[0]
            if time.find("{*}senza-misura") is not None:
                shared = first_contexts.get(ordinal)
                signature = _signature(time)
                if part_index == 0:
                    first_contexts[ordinal] = (signature, previous_meter)
                elif (not time.attrib and len(_element_children(time)) == 1 and previous_meter is not None
                      and shared == (signature, previous_meter)):
                    time.getparent().remove(time)
                    applied.append(dict(partId=part.get("id"), measureOrdinal=ordinal,
                                        printedMeasure=measure.get("number")))
                else:
                    unchecked.append(dict(partId=part.get("id"), measureOrdinal=ordinal,
                                          printedMeasure=measure.get("number"),
                                          reason="shared unnumbered senza and aligned prior meter not proven"))
            else:
                previous_meter = _signature(time) if _simple_meter(time) else None
    report = dict(
        adapter="verovio-6.3-shared-senza", renderCopyOnly=True,
        omittedRedundantTimeDeclarations=applied, unchecked=unchecked,
        warnings=key_change_warnings(root) + direction_bracket_warnings(root),
    )
    return RenderInput(
        etree.tostring(root, encoding="unicode") if applied else xml,
        report,
    )
