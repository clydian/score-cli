from pathlib import Path
import re
from xml.etree import ElementTree as ET
from PIL import Image
import score_cli.render_measure as renderer


def test_range_keeps_actual_octave_line_in_png(tmp_path, monkeypatch):
    seen = []
    rasterize = renderer._rasterize_svg
    def capture(svg):
        seen.append(svg)
        return rasterize(svg)
    monkeypatch.setattr(renderer, "_rasterize_svg", capture)
    result = renderer.render_range(input_path=Path(__file__).parent / "fixtures/ottava-crop.musicxml", start="2", end="3", output_directory=tmp_path / "images")
    ns = "{http://www.w3.org/2000/svg}"
    checked = 0
    for entry, svg in zip(result["images"], seen, strict=True):
        root = ET.fromstring(svg)
        margin = next(g for g in root.iter(ns+"g") if "page-margin" in g.get("class", "").split())
        dx, dy = renderer._translation(margin.get("transform"))
        crop = entry["crop"]
        image = Image.open(tmp_path / "images" / entry["path"]).convert("RGB")
        for group in root.iter(ns+"g"):
            if "octave" not in group.get("class", "").split():
                continue
            for path in group.findall(ns+"path"):
                match = re.fullmatch(r"M([\d.]+) ([\d.]+) L([\d.]+) ([\d.]+)", path.get("d", ""))
                if match is None:
                    continue
                x1,y1,x2,y2 = map(float, match.groups())
                x1,x2,y1,y2 = x1+dx,x2+dx,y1+dy,y2+dy
                if x2 <= crop["x"] or x1 >= crop["x"]+crop["width"]:
                    continue
                assert crop["y"] <= y1 == y2 <= crop["y"] + crop["height"]
                x = int((max(x1,crop["x"])-crop["x"])/crop["width"]*image.width)
                right = int((min(x2,crop["x"]+crop["width"])-crop["x"])/crop["width"]*image.width)
                y = int((y1-crop["y"])/crop["height"]*image.height)
                strip = image.crop((max(0,x),max(0,y-3),min(image.width,right),min(image.height,y+4)))
                assert min(max(pixel) for pixel in strip.get_flattened_data()) < 150
                checked += 1
    assert checked == 1
