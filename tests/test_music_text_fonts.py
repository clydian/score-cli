"""Music text must match the font's outlines, without system-font fallback."""

import io
from pathlib import Path

import pytest
import resvg_py
import verovio
from PIL import Image

from score_cli.render_measure import OUTPUT_SCALE, _rasterize_svg


@pytest.mark.parametrize("codepoint", ["ECA5", "ECB7", "ECA2"])
def test_metronome_text_matches_music_glyph_outline(codepoint):
    data = Path(verovio.__file__).parent / "data"
    css = (data / "Leipzig.css").read_text()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="120">'
        f'<style>{css}</style><text x="20" y="90" font-family="Leipzig" '
        f'font-size="100">&#x{codepoint};</text></svg>'
    )
    # Independent path-based reference: no CSS font or text shaping is involved.
    glyph = (data / "Leipzig" / f"{codepoint}.xml").read_text()
    reference = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="120">'
        f'<g transform="translate(20,90) scale(0.1)">{glyph}</g></svg>'
    )
    actual = Image.open(io.BytesIO(_rasterize_svg(svg.encode()))).convert("L")
    expected = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(
        svg_string=reference, background="#ffffff", zoom=OUTPUT_SCALE,
        skip_system_fonts=True,
    )))).convert("L")
    ink = lambda im: {i for i, v in enumerate(im.get_flattened_data()) if v < 128}
    a, b = ink(actual), ink(expected)
    assert a and b
    assert len(a & b) / len(a | b) > 0.95
