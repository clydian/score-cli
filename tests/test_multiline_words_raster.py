import io

from PIL import Image

from score_cli.render_measure import _rasterize_svg


def test_pretty_printed_preserved_multiline_words_have_both_lines_of_ink():
    # Verovio emits these nested tspans for MusicXML words with a newline.
    # With xml:space=preserve, resvg loses both lines when indentation at the
    # zero-sized text container precedes the explicitly sized leaf spans.
    svg = b'''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="120" viewBox="0 0 300 120">
      <text x="10" y="40" font-size="0px" font-family="serif">
        <tspan class="rend" xml:space="preserve">
          <tspan class="text"><tspan font-size="30px">Andante</tspan></tspan>
          <tspan class="lb"/>
          <tspan class="text" x="10" y="90"><tspan font-size="30px">a tempo</tspan></tspan>
        </tspan>
      </text>
    </svg>'''
    image = Image.open(io.BytesIO(_rasterize_svg(svg))).convert('RGB')
    scale = image.width / 300
    for y0, y1 in [(10, 45), (60, 95)]:
        region = image.crop((0, int(y0 * scale), int(260 * scale), int(y1 * scale)))
        pixels = region.load()
        assert sum(max(pixels[x, y]) < 128 for y in range(region.height) for x in range(region.width)) > 200


def test_preserves_leaf_spaces_inline_separators_and_zero_sized_hidden_text():
    # Formatting removal must not consume deliberate spaces between words,
    # turn font-size=0 text visible, or change the source SVG bytes.
    prefix = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><text x="10" y="40" font-size="0px">'
    suffix = '</text></svg>'
    content = '<tspan xml:space="preserve"><tspan font-size="30px">a  tempo</tspan> <tspan font-size="30px">dolce</tspan><tspan>hidden</tspan></tspan>'
    reference = (prefix + content + suffix).encode()
    formatted = (prefix + '\n  ' + content.replace('<tspan font-size="30px">a', '\n    <tspan font-size="30px">a', 1) + '\n' + suffix).encode()
    before = bytes(formatted)
    assert _rasterize_svg(formatted) == _rasterize_svg(reference)
    assert _rasterize_svg(reference) == _rasterize_svg(reference.replace(b'<tspan>hidden</tspan>', b''))
    assert formatted == before
