from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import verovio

from score_cli.render_measure import _find_rendered_measures


@pytest.mark.parametrize("verses", [1, 2, 4])
def test_bottom_staff_verses_fit_in_measure_and_system_crop(verses):
    source = ET.parse(Path(__file__).parent / "fixtures/three-measures.musicxml")
    for note in source.findall("part[@id='P2']/measure/note"):
        for number in range(1, verses + 1):
            lyric = ET.SubElement(note, "lyric", number=str(number))
            ET.SubElement(lyric, "text").text = "gypsy"
    toolkit = verovio.toolkit()
    toolkit.setOptions({
        "inputFrom": "xml", "breaks": "encoded",
        "svgBoundingBoxes": True, "svgContentBoundingBoxes": True,
        "svgAdditionalAttribute": ["measure@n"],
    })
    assert toolkit.loadData(ET.tostring(source.getroot(), encoding="unicode"))
    svg = toolkit.renderToSVG(1)
    ns = "{http://www.w3.org/2000/svg}"
    root = ET.fromstring(svg)
    # The source's last lyric baseline is an independent visible-content
    # reference: Verovio's own content boxes stop above it in 6.3.
    baselines = [
        float(text.attrib["y"])
        for text in root.iter(f"{ns}text")
        if "gypsy" in "".join(text.itertext())
    ]
    assert baselines
    bottom = max(baselines)
    measures = _find_rendered_measures(svg)
    assert measures
    assert max(m.measure_box.y + m.measure_box.height for m in measures) > bottom
    assert max(m.system_box.y + m.system_box.height for m in measures) > bottom
