from pathlib import Path
import json
import struct

import pytest

from score_cli.render_measure import render_range, RenderMeasureError

FIXTURE = Path(__file__).parent / "fixtures" / "three-measures.musicxml"


def test_range_follows_document_order_and_reports_crop_coordinates(tmp_path):
    source = tmp_path / "range.xml"
    xml = (
        FIXTURE.read_text()
        .replace('number="X1"', 'number="0"')
        .replace('number="1"', 'number="X1"')
    )
    source.write_text(xml)
    result = render_range(
        input_path=source,
        start="0",
        end="3",
        context=2,
        output_directory=tmp_path / "images",
    )
    assert result["selectedMeasures"] == ["X1", "0", "3"]
    assert result["contextClipped"] == {"before": True, "after": True}
    assert result["images"]
    assert json.loads((tmp_path / "images" / "manifest.json").read_text()) == result
    for entry in result["images"]:
        data = (tmp_path / "images" / entry["path"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        assert width > 20 and height > 20
        assert entry["coordinateUnit"] == "verovio-definition-units"
        assert entry["renderedScorePage"] >= 1
        assert entry["sourcePdfPage"] is None
        assert entry["crop"]["width"] > 0
    with pytest.raises((RenderMeasureError, FileExistsError)):
        render_range(
            input_path=source, start="0", end="3", output_directory=tmp_path / "images"
        )


def test_cross_page_range_is_ordered_and_contains_visible_ink(tmp_path):
    source = tmp_path / "pages.xml"
    xml = FIXTURE.read_text().replace(
        '<measure number="X1">', '<measure number="X1"><print new-page="yes"/>'
    )
    source.write_text(xml)
    result = render_range(
        input_path=source, start="1", end="3", output_directory=tmp_path / "pages"
    )
    assert [e["renderedScorePage"] for e in result["images"]] == [1, 2]
    assert [m for e in result["images"] for m in e["measures"]] == ["1", "X1", "3"]
    # Decode the actual PNG scanlines: a blank crop would contain no dark ink.
    # resvg's RGBA output uses PNG row filters, so use Pillow for pixel proof.
    from PIL import Image

    for entry in result["images"]:
        image = Image.open(tmp_path / "pages" / entry["path"]).convert("RGB")
        dark = sum(1 for r, g, b in image.get_flattened_data() if max(r, g, b) < 100)
        assert dark > 500


def test_generated_footer_does_not_enter_score_crops(tmp_path, monkeypatch):
    import score_cli.render_measure as renderer

    seen = []
    rasterize = renderer._rasterize_svg

    def capture(svg):
        seen.append(svg)
        return rasterize(svg)

    monkeypatch.setattr(renderer, "_rasterize_svg", capture)
    renderer.render_range(
        input_path=FIXTURE, start="1", end="3", output_directory=tmp_path / "range"
    )
    renderer.render_printed_measure(
        input_path=FIXTURE, measure="1", output_path=tmp_path / "single.png"
    )
    assert len(seen) >= 2
    assert all(b"engraved with Verovio" not in svg for svg in seen)
