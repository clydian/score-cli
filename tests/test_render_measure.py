from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import score_cli.render_measure as render_measure_module
from score_cli.render_measure import RenderMeasureError, render_printed_measure

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "three-measures.musicxml"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_renders_a_non_numeric_printed_measure_from_the_full_score_layout(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "measure-X1.png"
    before = _sha256(FIXTURE_PATH.read_bytes())

    result = render_printed_measure(
        input_path=FIXTURE_PATH,
        measure="X1",
        output_path=output_path,
    )

    png = output_path.read_bytes()
    width, height = _png_dimensions(png)
    assert png.startswith(PNG_SIGNATURE)
    assert (width, height) == (344, 640)
    assert result.printed_measure == "X1"
    assert result.scope == "measure"
    assert result.rendered_measures_on_source_page == ("1", "X1", "3")
    assert _sha256(FIXTURE_PATH.read_bytes()) == before


def test_reads_compressed_musicxml_through_container_xml(tmp_path: Path) -> None:
    input_path = tmp_path / "fixture.mxl"
    output_path = tmp_path / "measure-3.png"
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles>
</container>"""
    with ZipFile(input_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("score.musicxml", FIXTURE_PATH.read_bytes())

    result = render_printed_measure(
        input_path=input_path,
        measure="3",
        output_path=output_path,
    )

    assert result.printed_measure == "3"
    assert len(output_path.read_bytes()) > 1_000


def test_reports_a_missing_printed_measure_without_creating_output(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "missing.png"

    with pytest.raises(RenderMeasureError, match='Printed measure "404" was not found'):
        render_printed_measure(
            input_path=FIXTURE_PATH,
            measure="404",
            output_path=output_path,
        )

    assert not output_path.exists()


def test_renders_the_complete_system_with_measure_numbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "system-X1.png"
    captured_svg: list[str] = []
    rasterize = render_measure_module.resvg_py.svg_to_bytes

    def capture_svg(**options: object) -> bytes:
        captured_svg.append(str(options["svg_string"]))
        return bytes(rasterize(**options))

    monkeypatch.setattr(render_measure_module.resvg_py, "svg_to_bytes", capture_svg)

    result = render_printed_measure(
        input_path=FIXTURE_PATH,
        measure="X1",
        output_path=output_path,
        scope="system",
    )

    png = output_path.read_bytes()
    assert _png_dimensions(png) == (1272, 512)
    assert result.scope == "system"
    assert len(captured_svg) == 1

    root = ElementTree.fromstring(captured_svg[0])
    namespace = "{http://www.w3.org/2000/svg}"
    measure_numbers = [
        "".join(group.itertext()).strip()
        for group in root.iter(f"{namespace}g")
        if "mNum" in group.get("class", "").split()
    ]
    assert measure_numbers == ["1", "X1", "3"]
    assert all(
        "bounding-box" not in element.get("class", "").split()
        for element in root.iter()
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_dimensions(data: bytes) -> tuple[int, int]:
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])
