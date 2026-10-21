"""Report source key changes Verovio 6.3 may omit; never alter the score."""
from __future__ import annotations

from typing import Any

from lxml import etree


def key_change_warnings(root: etree._Element) -> list[dict]:
    parts = root.findall("{*}part")
    if len(parts) < 2:
        return []
    first_measures = parts[0].findall("{*}measure")
    warnings = []

    def signature(key):
        return tuple((etree.QName(child).localname, child.text or "", tuple(sorted(child.attrib.items())))
                     for child in key if isinstance(child.tag, str))

    for part in parts[1:]:
        previous: dict[str, tuple[Any, ...]] = {}
        for ordinal, measure in enumerate(part.findall("{*}measure"), 1):
            for key in measure.findall("{*}attributes/{*}key"):
                staff = key.get("number", "all")
                value = signature(key)
                prior = previous.get(staff, previous.get("all"))
                previous[staff] = value
                if ordinal == 1 or prior == value:
                    continue
                first = first_measures[ordinal - 1] if ordinal <= len(first_measures) else None
                shared = [] if first is None else first.findall("{*}attributes/{*}key")
                # Only the first unnumbered declaration in the first part is
                # imported as a global scoreDef. Match identities and semantics
                # before treating it as evidence that this change is covered.
                if (first is not None and first.get("number") == measure.get("number")
                        and shared and not shared[0].attrib and not key.attrib
                        and signature(shared[0]) == value):
                    continue
                warnings.append(dict(
                    code="verovio-nonfirst-part-key-change-risk",
                    partId=part.get("id"), printedMeasure=measure.get("number"),
                    measureOrdinal=ordinal, staff=staff,
                    sourceFifths=key.findtext("{*}fifths"),
                    message=("Verovio 6.3 imports later key changes only from the first part. "
                             "This source declaration is not proven covered by that path; "
                             "the rendered key signature may disagree with valid XML. "
                             "Check this part/measure with an independent renderer and the original score. "
                             "Do not change source XML to match this preview."),
                ))
    return warnings
