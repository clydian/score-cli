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


def test_range_keeps_real_volta_brackets_and_numbers_inside_raster(tmp_path, monkeypatch):
    import re
    from xml.etree import ElementTree as ET
    from PIL import Image
    import score_cli.render_measure as renderer

    seen = []
    rasterize = renderer._rasterize_svg

    def capture(svg):
        seen.append(svg)
        return rasterize(svg)

    monkeypatch.setattr(renderer, "_rasterize_svg", capture)
    result = renderer.render_range(
        input_path=FIXTURE.with_name("volta-crop.musicxml"),
        start="X1", end="3", output_directory=tmp_path / "voltas",
    )
    ns = "{http://www.w3.org/2000/svg}"
    checked = 0
    for entry, svg in zip(result["images"], seen, strict=True):
        root = ET.fromstring(svg)
        crop = entry["crop"]
        margin = next(
            g for g in root.iter(ns + "g")
            if "page-margin" in g.get("class", "").split()
        )
        dx, dy = renderer._translation(margin.get("transform"))
        image = Image.open(tmp_path / "voltas" / entry["path"]).convert("RGB")
        for group in root.iter(ns + "g"):
            if "voltaBracket" not in group.get("class", "").split():
                continue
            label = group.find(ns + "text")
            assert label is not None and "".join(label.itertext()).strip() in {"1", "2"}
            path = group.find(ns + "path")
            assert path is not None
            segment = re.fullmatch(
                r"M([\d.]+) ([\d.]+) L([\d.]+) ([\d.]+)", path.attrib["d"]
            )
            assert segment is not None
            x1, y1, x2, y2 = map(float, segment.groups())
            x1, x2, y1, y2 = x1 + dx, x2 + dx, y1 + dy, y2 + dy
            assert crop["y"] <= y1 == y2 <= crop["y"] + crop["height"]
            # The actual bracket's middle must have dark pixels, rather than
            # merely remaining in an SVG tree outside the clipping viewBox.
            x = int(((x1 + x2) / 2 - crop["x"]) / crop["width"] * image.width)
            y = int((y1 - crop["y"]) / crop["height"] * image.height)
            region = image.crop((x - 2, max(0, y - 2), x + 3, y + 3))
            assert min(max(pixel) for pixel in region.get_flattened_data()) < 150
            size = max(
                float(element.get("font-size", "0").removesuffix("px"))
                for element in label.iter()
            )
            label_x = float(label.attrib["x"]) + dx
            baseline = float(label.attrib["y"]) + dy
            glyph = image.crop((
                int((label_x - crop["x"]) / crop["width"] * image.width),
                int((baseline - .75 * size - crop["y"]) / crop["height"] * image.height),
                int((label_x + size - crop["x"]) / crop["width"] * image.width),
                int((baseline - crop["y"]) / crop["height"] * image.height),
            ))
            assert min(max(pixel) for pixel in glyph.get_flattened_data()) < 150
            checked += 1
    assert checked == 2


@pytest.mark.parametrize("interval", [0, 4])
def test_range_records_optional_measure_number_interval(tmp_path, interval):
    result = render_range(
        input_path=FIXTURE, start="1", end="3",
        output_directory=tmp_path / str(interval), measure_number_interval=interval,
    )
    assert result["renderParameters"]["mnumInterval"] == interval


@pytest.mark.parametrize("interval", [-1, 65, True, 1.5])
def test_invalid_measure_number_interval_does_not_publish(tmp_path, interval):
    output = tmp_path / "invalid"
    with pytest.raises(RenderMeasureError, match="interval"):
        render_range(
            input_path=FIXTURE, start="1", output_directory=output,
            measure_number_interval=interval,
        )
    assert not output.exists()


def test_measure_number_density_changes_only_number_display(tmp_path, monkeypatch):
    from xml.etree import ElementTree as ET
    import score_cli.render_measure as renderer

    seen = []
    rasterize = renderer._rasterize_svg

    def capture(svg):
        seen.append(svg)
        return rasterize(svg)

    monkeypatch.setattr(renderer, "_rasterize_svg", capture)
    counts = []
    for interval in [0, 1]:
        result = renderer.render_range(
            input_path=FIXTURE, start="1", end="3",
            output_directory=tmp_path / str(interval), measure_number_interval=interval,
        )
        assert result["selectedMeasures"] == ["1", "X1", "3"]
        root = ET.fromstring(seen[-1])
        counts.append(sum(
            "mNum" in g.get("class", "").split()
            for g in root.iter("{http://www.w3.org/2000/svg}g")
        ))
    assert counts[0] < counts[1]
