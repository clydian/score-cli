"""Render one printed measure from a fully laid-out MusicXML score."""

from __future__ import annotations

import base64
import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

import resvg_py
import verovio
from fontTools.ttLib import TTFont

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


def _rasterize_svg(svg: bytes) -> bytes:
    """Load Verovio's embedded music-text fonts explicitly for resvg.

    resvg does not load CSS @font-face data URLs. Without the font, SMuFL
    private-use characters (for example metronome notes) can silently become
    unrelated glyphs from a system fallback font.
    """
    text = svg.decode("utf-8")
    embedded = dict.fromkeys(re.findall(
        r"url\(data:application/font-woff2[^,]*;base64,([A-Za-z0-9+/=\s]+)\)",
        text,
    ))
    with tempfile.TemporaryDirectory(prefix="score-cli-fonts-") as directory:
        font_files = []
        for index, payload in enumerate(embedded):
            path = Path(directory) / f"music-text-{index}.ttf"
            data = base64.b64decode("".join(payload.split()), validate=True)
            with TTFont(io.BytesIO(data)) as font:
                font.flavor = None
                font.save(path)
            font_files.append(str(path))
        return bytes(resvg_py.svg_to_bytes(
            svg_string=text,
            background="#ffffff",
            zoom=OUTPUT_SCALE,
            font_files=font_files,
        ))


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
    measure_number_interval: int = 1,
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

    _validate_measure_number_interval(measure_number_interval)
    xml = read_musicxml(source)
    verovio.enableLog(verovio.LOG_OFF)
    toolkit = verovio.toolkit()
    toolkit.setOptions(
        {
            "inputFrom": "xml",
            "breaks": "encoded",
            "pageWidth": 2100,
            "footer": "none",
            "pageHeight": 2970,
            "scale": 40,
            "svgViewBox": True,
            "svgAdditionalAttribute": ["measure@n"],
            "svgBoundingBoxes": True,
            "svgContentBoundingBoxes": True,
            "mnumInterval": measure_number_interval,
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
        pages = ", ".join(
            str(page) for page in dict.fromkeys(page for page, _ in matches)
        )
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
    png = _rasterize_svg(cropped_svg)
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
        system_box = _include_lyric_extent(system, system_box)

        for measure in system.findall(f"{{{SVG_NAMESPACE}}}g"):
            measure_classes = set(measure.get("class", "").split())
            if "measure" not in measure_classes or "bounding-box" in measure_classes:
                continue
            label = measure.get("data-n")
            measure_box = _find_content_box(measure, "measure")
            if label is None or measure_box is None:
                continue
            measure_box = _include_lyric_extent(measure, measure_box)
            measure_box = _include_ending_extent(system, measure_box)
            measures.append(
                _RenderedMeasure(
                    label=label,
                    measure_box=measure_box,
                    system_box=system_box,
                )
            )

    return measures


def _validate_measure_number_interval(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 64:
        raise RenderMeasureError("Measure number interval must be an integer from 0 to 64.")


def _include_ending_extent(system: ElementTree.Element, box: _Box) -> _Box:
    """Volta brackets are system milestones, outside their measure groups.

    Include the vertical bounds of endings that overlap this measure's crop.
    Keep horizontal bounds local: a long bracket must not pull unrelated bars
    into a single-measure or selected-range image.
    """
    top, bottom = box.y, box.y + box.height
    for group in system.iter(f"{{{SVG_NAMESPACE}}}g"):
        classes = set(group.get("class", "").split())
        if "ending" not in classes or "bounding-box" in classes:
            continue
        ending = _find_content_box(group, "ending", box_class="bounding-box")
        if (
            ending is None
            or ending.x >= box.x + box.width
            or ending.x + ending.width <= box.x
        ):
            continue
        top = min(top, ending.y)
        bottom = max(bottom, ending.y + ending.height)
    return _Box(box.x, top, box.width, bottom - top)


def _include_lyric_extent(owner: ElementTree.Element, box: _Box) -> _Box:
    """Verovio 6.3's content boxes omit SVG lyric text.

    Its syllable text uses absolute definition-unit baselines, with the font
    size on nested tspans. Reserve an em above and below each baseline so
    verses and descenders survive both system and measure crops.
    """
    top, bottom = box.y, box.y + box.height
    for group in owner.iter(f"{{{SVG_NAMESPACE}}}g"):
        if "syl" not in group.get("class", "").split():
            continue
        for text in group.iter(f"{{{SVG_NAMESPACE}}}text"):
            try:
                baseline = float(text.attrib["y"])
                sizes = [
                    float(element.get("font-size", "0").removesuffix("px"))
                    for element in text.iter()
                ]
            except (KeyError, ValueError):
                continue
            size = max(sizes, default=0)
            top = min(top, baseline - size)
            bottom = max(bottom, baseline + size)
    return _Box(box.x, top, box.width, bottom - top)


def _find_content_box(
    owner: ElementTree.Element, role: str, *, box_class: str = "content-bounding-box"
) -> _Box | None:
    for group in owner.findall(f"{{{SVG_NAMESPACE}}}g"):
        classes = set(group.get("class", "").split())
        if not {role, box_class}.issubset(classes):
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
        except KeyError, ValueError:
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
        raise RenderMeasureError(
            "Rendered SVG is missing its Verovio definition-scale viewBox."
        )
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

    root.set(
        "viewBox",
        f"0 0 {_number(crop.width * scale_x)} {_number(crop.height * scale_y)}",
    )
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


def render_range(
    *,
    input_path: str | Path,
    start: str,
    end: str | None = None,
    context: int = 0,
    output_directory: str | Path,
    measure_number_interval: int = 1,
) -> dict:
    """Crop consecutive selected measures per system; manifest is the commit marker."""
    from dataclasses import asdict
    from importlib.metadata import version
    from .inspect_measure import outline_score
    from .edit_score import publish_files, json_bytes
    from .score_document import sha256

    _validate_measure_number_interval(measure_number_interval)
    if type(context) is not int or context < 0:
        raise RenderMeasureError("Context must be a nonnegative integer.")
    source = Path(input_path)
    directory = Path(output_directory)
    if directory.exists():
        raise RenderMeasureError("Range output directory must be new.")
    outline = outline_score(input_path=source).as_dict()
    if outline["diagnostics"]:
        raise RenderMeasureError(
            "Range rendering needs an unambiguous, consistent measure sequence."
        )
    sequence = outline["measureNumbers"]
    end = start if end is None else end
    if (
        not isinstance(start, str)
        or not isinstance(end, str)
        or start not in sequence
        or end not in sequence
    ):
        raise RenderMeasureError(
            "Range endpoints must be exact printed measure strings in the score."
        )
    first, last = sequence.index(start), sequence.index(end)
    if first > last:
        raise RenderMeasureError("Range endpoints are reversed in document order.")
    selected = sequence[
        max(0, first - context) : min(len(sequence), last + context + 1)
    ]
    xml = read_musicxml(source)
    verovio.enableLog(verovio.LOG_OFF)
    toolkit = verovio.toolkit()
    options = dict(
        inputFrom="xml",
        breaks="encoded",
        pageWidth=2100,
        footer="none",
        pageHeight=2970,
        scale=40,
        svgViewBox=True,
        svgAdditionalAttribute=["measure@n"],
        svgBoundingBoxes=True,
        svgContentBoundingBoxes=True,
        mnumInterval=measure_number_interval,
    )
    toolkit.setOptions(options)
    if not toolkit.loadData(xml):
        raise RenderMeasureError("Verovio could not load the score.")
    matches: dict[str, list] = {m: [] for m in selected}
    for page in range(1, toolkit.getPageCount() + 1):
        for candidate in _find_rendered_measures(toolkit.renderToSVG(page)):
            if candidate.label in matches:
                matches[candidate.label].append((page, candidate))
    if any(len(found) != 1 for found in matches.values()):
        raise RenderMeasureError(
            "Each selected measure must occur exactly once in the rendered score."
        )
    groups: dict[tuple, list] = {}
    for measure in selected:
        page, candidate = matches[measure][0]
        b = candidate.system_box
        key = (page, b.x, b.y, b.width, b.height)
        groups.setdefault(key, []).append(candidate)
    toolkit.setOptions({"svgBoundingBoxes": False, "svgContentBoundingBoxes": False})
    images = []
    files = {}
    for index, (key, candidates) in enumerate(groups.items(), 1):
        page = key[0]
        left = min(c.measure_box.x for c in candidates)
        top = min(c.measure_box.y for c in candidates)
        right = max(c.measure_box.x + c.measure_box.width for c in candidates)
        bottom = max(c.measure_box.y + c.measure_box.height for c in candidates)
        box = _Box(left, top, right - left, bottom - top)
        clean = toolkit.renderToSVG(page)
        cropped = _crop_rendered_page(clean, box, padding_y=SYSTEM_PADDING)
        root = ElementTree.fromstring(cropped)
        inner = next(
            e
            for e in root.iter(f"{{{SVG_NAMESPACE}}}svg")
            if "definition-scale" in e.get("class", "").split()
        )
        crop = _parse_view_box(inner.get("viewBox"))
        outer = _parse_view_box(root.get("viewBox"))
        png = _rasterize_svg(cropped)
        filename = f"{index:03d}-page-{page}.png"
        files[directory / filename] = png
        images.append(
            dict(
                path=filename,
                sha256=sha256(png),
                measures=[c.label for c in candidates],
                renderedScorePage=page,
                sourcePdfPage=None,
                crop=asdict(crop),
                coordinateUnit="verovio-definition-units",
                definitionToSvgScale=dict(
                    x=outer.width / crop.width, y=outer.height / crop.height
                ),
                rasterZoom=OUTPUT_SCALE,
            )
        )
    manifest = dict(
        schemaVersion="1",
        inputSha256=sha256(source.read_bytes()),
        toolVersion=version("score-cli"),
        rendererVersion=toolkit.getVersion(),
        renderParameters=options,
        requested=dict(start=start, end=end, context=context),
        selectedMeasures=selected,
        contextClipped=dict(
            before=first - context < 0, after=last + context >= len(sequence)
        ),
        renderedScorePageCount=toolkit.getPageCount(),
        images=images,
    )
    files[directory / "manifest.json"] = json_bytes(manifest)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        publish_files(files)
    except BaseException:
        directory.rmdir()
        raise
    return manifest
