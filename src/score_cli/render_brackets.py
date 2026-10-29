"""Report positioned direction lines that Verovio 6.3 cannot preserve."""
from __future__ import annotations

from fractions import Fraction

from lxml import etree


def _height(bracket: etree._Element) -> Fraction | None:
    # Without an explicit default-y, the renderer chooses the vertical origin.
    value = bracket.get("default-y")
    if value is None:
        return None
    try:
        return Fraction(value) + Fraction(bracket.get("relative-y", "0"))
    except (ValueError, ZeroDivisionError):
        return None


def _positive_integer(value: str) -> str | None:
    try:
        number = int(value)
    except ValueError:
        return None
    return str(number) if number > 0 else None


def direction_bracket_warnings(root: etree._Element) -> list[dict]:
    """Warn only for paired brackets with proven unequal endpoint heights.

    This is a bounded positioning warning, not a claim that ordinary horizontal
    brackets or repeat endings are unsupported. Keep the MusicXML unchanged.
    """
    namespace = etree.QName(root).namespace

    def tag(name: str) -> str:
        return f"{{{namespace}}}{name}" if namespace else name

    warnings = []
    for part in root.findall(tag("part")):
        pending: dict[tuple[str, str], tuple[etree._Element, str | None, int]] = {}
        ambiguous: set[tuple[str, str]] = set()
        for ordinal, measure in enumerate(part.findall(tag("measure")), 1):
            for direction in measure.findall(tag("direction")):
                staff = _positive_integer(direction.findtext(tag("staff"), "1"))
                if staff is None:
                    continue
                for bracket in direction.findall(f"{tag('direction-type')}/{tag('bracket')}"):
                    number = _positive_integer(bracket.get("number", "1"))
                    if number is None:
                        continue
                    key = (staff, number)
                    kind = bracket.get("type")
                    if kind not in {"start", "stop"} or key in ambiguous:
                        continue
                    current = (bracket, measure.get("number"), ordinal)
                    other = pending.pop(key, None)
                    if other is None:
                        pending[key] = current
                        continue
                    if other[0].get("type") == kind:
                        # Repeated same-kind endpoints cannot prove a pairing.
                        ambiguous.add(key)
                        continue
                    # Start/stop refer to score order; stop can appear first in
                    # the XML. Number reuse, however, follows document order.
                    start, end = (current, other) if kind == "start" else (other, current)
                    start_y, stop_y = _height(start[0]), _height(end[0])
                    if start_y is None or stop_y is None or start_y == stop_y:
                        continue
                    warnings.append(dict(
                        code="verovio-sloped-direction-bracket-risk",
                        partId=part.get("id"), printedMeasure=start[1],
                        measureOrdinal=start[2], staff=staff,
                        bracketNumber=key[1], endPrintedMeasure=end[1],
                        endMeasureOrdinal=end[2],
                        message=(
                            "Verovio 6.3 does not preserve the staff and endpoint heights "
                            "of this explicitly sloped direction bracket. The line may "
                            "be flattened, misplaced, or omitted in the preview. Check "
                            "this part/measure with an independent renderer and the "
                            "original score. Do not change source XML to match this preview."
                        ),
                    ))
    return warnings
