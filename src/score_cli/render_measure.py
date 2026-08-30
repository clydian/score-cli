"""Render one printed measure from a fully laid-out MusicXML score."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

import resvg_py
import verovio

from .musicxml_input import read_musicxml

HORIZONTAL_PADDING = 100.0
VERTICAL_PADDING = 500.0
SYSTEM_PADDING = 100.0
OUTPUT_SCALE = 4.0
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"

ElementTree.register_namespace("", SVG_NAMESPACE)
ElementTree.register_namespace("xlink", XLINK_NAMESPACE)


class RenderMeasureError(ValueError):
    """Raised when a printed measure cannot be rendered unambiguously."""


@dataclass(frozen=True, slots=True)
class RenderResult:
    input_path: Path
    output_path: Path
    printed_measure: str
    scope: Literal["measure", "system"]
    source_page: int
    source_page_count: int
    rendered_measures_on_source_page: tuple[str, ...]
    bytes: int


@dataclass(frozen=True, slots=True)
class _Box:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class _RenderedMeasure:
    label: str
    measure_box: _Box
    system_box: _Box


def render_printed_measure(
    *,
    input_path: str | Path,
    measure: str | int,
    output_path: str | Path,
    scope: Literal["measure", "system"] = "measure",
) -> RenderResult:
    """Render an exact MusicXML measure number or its system to a cropped PNG."""

    source = Path(input_path)
    destination = Path(output_path)
    printed_measure = str(measure)

    if not printed_measure:
        raise RenderMeasureError("A printed measure number is required.")
    if scope not in {"measure", "system"}:
        raise RenderMeasureError(f'Unsupported render scope "{scope}".')
    if destination.suffix.lower() != ".png":
        raise RenderMeasureError("The output path must end in .png.")

    xml = read_musicxml(source)
    verovio.enableLog(verovio.LOG_OFF)
    toolkit = verovio.toolkit()
    toolkit.setOptions(
        {
            "inputFrom": "xml",
            "breaks": "encoded",
            "pageWidth": 2100,
            "pageHeight": 2970,
            "scale": 40,
            "svgViewBox": True,
            "svgAdditionalAttribute": ["measure@n"],
            "svgBoundingBoxes": True,
            "svgContentBoundingBoxes": True,
            "mnumInterval": 1,
        }
    )

    if not toolkit.loadData(xml):
        raise RenderMeasureError(f'Verovio could not load "{source}".')

    page_count = toolkit.getPageCount()
    rendered_pages: dict[int, tuple[str, ...]] = {}
    matches: list[tuple[int, _RenderedMeasure]] = []

    for page in range(1, page_count + 1):
        measures = _find_rendered_measures(toolkit.renderToSVG(page))
        rendered_pages[page] = tuple(candidate.label for candidate in measures)
        matches.extend(
            (page, candidate)
            for candidate in measures
            if candidate.label == printed_measure
        )

    if not matches:
        raise RenderMeasureError(
            f'Printed measure "{printed_measure}" was not found in the rendered score.'
        )
    if len(matches) > 1:
        pages = ", ".join(str(page) for page in dict.fromkeys(page for page, _ in matches))
        raise RenderMeasureError(
            f'Printed measure "{printed_measure}" is ambiguous in the rendered score '
            f"(pages {pages})."
        )

    source_page, match = matches[0]
    toolkit.setOptions({"svgBoundingBoxes": False, "svgContentBoundingBoxes": False})
    clean_svg = toolkit.renderToSVG(source_page)
    box = match.measure_box if scope == "measure" else match.system_box
    padding_x = HORIZONTAL_PADDING if scope == "measure" else SYSTEM_PADDING
    padding_y = VERTICAL_PADDING if scope == "measure" else SYSTEM_PADDING
    cropped_svg = _crop_rendered_page(
        clean_svg,
        box,
        padding_x=padding_x,
        padding_y=padding_y,
    )
    png = bytes(
        resvg_py.svg_to_bytes(
            svg_string=cropped_svg.decode("utf-8"),
            background="#ffffff",
            zoom=OUTPUT_SCALE,
        )
    )
    _write_atomically(destination, png)

    return RenderResult(
        input_path=source.resolve(),
        output_path=destination.resolve(),
        printed_measure=printed_measure,
        scope=scope,
        source_page=source_page,
        source_page_count=page_count,
        rendered_measures_on_source_page=rendered_pages[source_page],
        bytes=len(png),
    )


def _find_rendered_measures(svg: str) -> list[_RenderedMeasure]:
    root = ElementTree.fromstring(svg)
    measures: list[_RenderedMeasure] = []

    for system in root.iter(f"{{{SVG_NAMESPACE}}}g"):
        system_classes = set(system.get("class", "").split())
        if "system" not in system_classes or "bounding-box" in system_classes:
            continue
        system_box = _find_content_box(system, "system")
        if system_box is None:
            continue

        for measure in system.findall(f"{{{SVG_NAMESPACE}}}g"):
            measure_classes = set(measure.get("class", "").split())
            if "measure" not in measure_classes or "bounding-box" in measure_classes:
                continue
            label = measure.get("data-n")
            measure_box = _find_content_box(measure, "measure")
            if label is None or measure_box is None:
                continue
            measures.append(
                _RenderedMeasure(
                    label=label,
                    measure_box=measure_box,
                    system_box=system_box,
                )
            )

    return measures


def _find_content_box(owner: ElementTree.Element, role: str) -> _Box | None:
    for group in owner.findall(f"{{{SVG_NAMESPACE}}}g"):
        classes = set(group.get("class", "").split())
        if not {role, "content-bounding-box"}.issubset(classes):
            continue
        rectangle = group.find(f"{{{SVG_NAMESPACE}}}rect")
        if rectangle is None:
            return None
        try:
            return _Box(
                x=float(rectangle.attrib["x"]),
                y=float(rectangle.attrib["y"]),
                width=float(rectangle.attrib["width"]),
                height=float(rectangle.attrib["height"]),
            )
        except (KeyError, ValueError):
            return None
    return None


def _crop_rendered_page(
    svg: str,
    box: _Box,
    *,
    padding_x: float = HORIZONTAL_PADDING,
    padding_y: float = VERTICAL_PADDING,
) -> bytes:
    root = ElementTree.fromstring(svg)
    outer_view_box = _parse_view_box(root.get("viewBox"))
    inner = next(
        (
            element
            for element in root.iter(f"{{{SVG_NAMESPACE}}}svg")
            if "definition-scale" in element.get("class", "").split()
        ),
        None,
    )
    if inner is None:
        raise RenderMeasureError("Rendered SVG is missing its Verovio definition-scale viewBox.")
    inner_view_box = _parse_view_box(inner.get("viewBox"))

    page_margin = next(
        (
            element
            for element in root.iter(f"{{{SVG_NAMESPACE}}}g")
            if "page-margin" in element.get("class", "").split()
        ),
        None,
    )
    translation_x, translation_y = _translation(
        page_margin.get("transform") if page_margin is not None else None
    )
    scale_x = outer_view_box.width / inner_view_box.width
    scale_y = outer_view_box.height / inner_view_box.height
    crop = _Box(
        x=box.x + translation_x - padding_x,
        y=box.y + translation_y - padding_y,
        width=box.width + padding_x * 2,
        height=box.height + padding_y * 2,
    )

    root.set("viewBox", f"0 0 {_number(crop.width * scale_x)} {_number(crop.height * scale_y)}")
    inner.set(
        "viewBox",
        " ".join(_number(value) for value in (crop.x, crop.y, crop.width, crop.height)),
    )
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _parse_view_box(value: str | None) -> _Box:
    if value is None:
        raise RenderMeasureError("Rendered SVG is missing a required viewBox.")
    try:
        x, y, width, height = (float(part) for part in value.split())
    except (ValueError, TypeError) as error:
        raise RenderMeasureError(f'Invalid SVG viewBox "{value}".') from error
    if width <= 0 or height <= 0:
        raise RenderMeasureError(f'Invalid SVG viewBox "{value}".')
    return _Box(x=x, y=y, width=width, height=height)


def _translation(transform: str | None) -> tuple[float, float]:
    if transform is None:
        return 0.0, 0.0
    match = re.search(r"translate\(\s*([^,\s]+)\s*,\s*([^)\s]+)\s*\)", transform)
    if match is None:
        return 0.0, 0.0
    return float(match.group(1)), float(match.group(2))


def _number(value: float) -> str:
    return f"{value:.12g}"


def _write_atomically(output_path: Path, data: bytes) -> None:
    destination = output_path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
