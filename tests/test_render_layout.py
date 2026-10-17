from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import score_cli.render_measure as renderer

NS = '{http://www.w3.org/2000/svg}'


def dense_cjk_score(path):
    note = '<note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>16th</type><lyric><syllabic>single</syllabic><text>啦</text></lyric></note>'
    measures = ''.join(f'<measure number="{i}">' + ('<print new-system="yes"/>' if i in (1, 7) else '') + ('<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>' if i == 1 else '') + note * 16 + '</measure>' for i in range(1, 13))
    path.write_text('<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Alto</part-name></score-part></part-list><part id="P1">' + measures + '</part></score-partwise>')


def lyric_geometry(svg):
    root = ET.fromstring(svg)
    measure = next(g for g in root.iter(NS + 'g') if g.get('class') == 'measure' and g.get('data-n') == '1')
    texts = [t for g in measure.iter(NS + 'g') if g.get('class') == 'syl' for t in g.iter(NS + 'text')]
    xs = [float(t.get('x')) for t in texts]
    em = max(float(n.get('font-size', '0').removesuffix('px')) for t in texts for n in t.iter())
    return len(texts), min(b - a for a, b in zip(xs, xs[1:])), em


def test_auto_reflow_separates_dense_cjk_lyrics_without_rewriting_xml(tmp_path, monkeypatch):
    source = tmp_path / 'dense.musicxml'
    dense_cjk_score(source)
    original = source.read_bytes()
    svgs = []
    rasterize = renderer._rasterize_svg

    def capture(svg):
        svgs.append(svg)
        return rasterize(svg)

    monkeypatch.setattr(renderer, '_rasterize_svg', capture)
    renderer.render_printed_measure(input_path=source, measure='1', scope='system', output_path=tmp_path / 'before.png')
    count, gap, em = lyric_geometry(svgs[-1])
    assert count == 16 and gap < em, 'fixture must reproduce compressed full-width CJK syllables'
    result = renderer.render_printed_measure(input_path=source, measure='1', scope='system', output_path=tmp_path / 'after.png', breaks='auto', lyric_word_space=2.5)
    count, gap, em = lyric_geometry(svgs[-1])
    assert count == 16 and gap >= em
    assert source.read_bytes() == original
    assert result.render_parameters['breaks'] == 'auto'
    assert result.render_parameters['lyricWordSpace'] == 2.5


@pytest.mark.parametrize('kwargs', [
    {'breaks': 'invalid'}, {'page_width': 99}, {'page_width': True},
    {'page_width': 100001}, {'lyric_word_space': -1},
    {'lyric_word_space': float('nan')}, {'lyric_word_space': float('inf')},
    {'lyric_word_space': 11},
    {'lyric_word_space': 10**1000},
    {'lyric_top_min_margin': -1}, {'lyric_top_min_margin': 8.1},
    {'lyric_top_min_margin': float('nan')}, {'lyric_top_min_margin': float('inf')},
    {'lyric_top_min_margin': True}, {'lyric_top_min_margin': 10**1000},
])
@pytest.mark.parametrize('mode', ['single', 'range'])
def test_invalid_layout_does_not_create_output(tmp_path, kwargs, mode):
    output = tmp_path / 'bad.png'
    with pytest.raises(renderer.RenderMeasureError):
        if mode == 'single':
            renderer.render_printed_measure(input_path=tmp_path / 'not-read.xml', measure='1', output_path=output, **kwargs)
        else:
            renderer.render_range(input_path=tmp_path / 'not-read.xml', start='1', output_directory=output, **kwargs)
    assert not output.exists()


def test_cli_range_records_requested_layout_and_keeps_xml(tmp_path, capsys):
    import json
    from score_cli.cli import main

    source = tmp_path / 'dense.musicxml'
    dense_cjk_score(source)
    original = source.read_bytes()
    assert main(['render', str(source), '--from-measure', '1', '--to-measure', '2', '--breaks', 'auto', '--page-width', '2400', '--lyric-word-space', '2.5', '--lyric-top-min-margin', '4', '--output', str(tmp_path / 'range')]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['selectedMeasures'] == ['1', '2']
    assert report['renderParameters']['breaks'] == 'auto'
    assert report['renderParameters']['pageWidth'] == 2400
    assert report['renderParameters']['lyricWordSpace'] == 2.5
    assert report['renderParameters']['lyricTopMinMargin'] == 4.0
    assert json.loads((tmp_path / 'range/manifest.json').read_text()) == report
    assert source.read_bytes() == original


def low_cjk_score(path):
    """Owned C4 ledger underlay followed by E4 locks a common verse baseline."""
    path.write_text('<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Alto</part-name></score-part></part-list><part id="P1">'
                    '<measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>'
                    '<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type><lyric><text>琶</text></lyric></note></measure>'
                    '<measure number="2"><note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>whole</type><lyric><text>琶</text></lyric></note></measure></part></score-partwise>')


def ink_clearance(svg):
    """Measure separately rasterized actual glyph/ledger ink, not text baseline."""
    import copy
    import io
    from PIL import Image, ImageChops

    root = ET.fromstring(svg)
    measure = next(g for g in root.iter(NS + 'g') if g.get('class') == 'measure' and g.get('data-n') == '1')
    lyric = next(g for g in measure.iter(NS + 'g') if g.get('class') == 'syl')
    head = next(g for g in measure.iter(NS + 'g') if g.get('class') == 'notehead')
    ledger = next(g for g in measure.iter(NS + 'g') if g.get('class') == 'ledgerLines below')
    text = next(lyric.iter(NS + 'text'))
    x, y = float(text.attrib['x']), float(text.attrib['y'])
    boxes = []
    for items in ((head, ledger), (lyric,)):
        isolated = ET.Element(NS + 'svg', {'viewBox': f'{x-100} {y-1000} 1000 1500', 'width': '250', 'height': '375'})
        for defs in root.findall(NS + 'defs'):
            isolated.append(copy.deepcopy(defs))
        for item in items:
            isolated.append(copy.deepcopy(item))
        image = Image.open(io.BytesIO(renderer._rasterize_svg(ET.tostring(isolated)))).convert('RGB')
        box = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).convert('L').point(lambda p: 255 if p > 100 else 0).getbbox()
        assert box is not None, 'actual note/lyric ink must be present'
        boxes.append(box)
    return boxes[1][1] - boxes[0][3]


@pytest.mark.parametrize('mode', ['single', 'range'])
def test_lyric_vertical_clearance_avoids_owned_c4_cjk_collision(tmp_path, monkeypatch, mode):
    source = tmp_path / 'low.musicxml'
    low_cjk_score(source)
    original = source.read_bytes()
    svgs = []
    rasterize = renderer._rasterize_svg

    def capture(svg):
        svgs.append(svg)
        return rasterize(svg)

    monkeypatch.setattr(renderer, '_rasterize_svg', capture)
    def render(label, **kwargs):
        if mode == 'single':
            return renderer.render_printed_measure(input_path=source, measure='1', scope='system', output_path=tmp_path / f'{label}.png', **kwargs).render_parameters
        return renderer.render_range(input_path=source, start='1', end='2', output_directory=tmp_path / label, **kwargs)['renderParameters']
    before = render('before')
    baseline_svg = svgs[-1]
    # ink_clearance uses the original rasterizer to avoid capture recursion.
    monkeypatch.setattr(renderer, '_rasterize_svg', rasterize)
    old_gap = ink_clearance(baseline_svg)
    monkeypatch.setattr(renderer, '_rasterize_svg', capture)
    after = render('after', lyric_top_min_margin=4)
    repaired_svg = svgs[-1]
    monkeypatch.setattr(renderer, '_rasterize_svg', rasterize)
    new_gap = ink_clearance(repaired_svg)
    assert old_gap <= 0, 'fixture must reproduce ledger/head against CJK upper strokes'
    assert new_gap >= 10 and new_gap > old_gap
    assert before['lyricTopMinMargin'] == 2.0
    assert after['lyricTopMinMargin'] == 4
    assert source.read_bytes() == original


@pytest.mark.parametrize('mode', ['single', 'range'])
@pytest.mark.parametrize('value', ['nan', 'inf', '-1', '9'])
def test_cli_invalid_vertical_clearance_writes_nothing(tmp_path, capsys, mode, value):
    from score_cli.cli import main

    output = tmp_path / ('absent.png' if mode == 'single' else 'absent')
    selection = ['--measure', '1'] if mode == 'single' else ['--from-measure', '1']
    with pytest.raises(SystemExit) as exc:
        main(['render', str(tmp_path / 'not-read.xml'), *selection,
              '--lyric-top-min-margin=' + value, '--output', str(output)])
    assert exc.value.code == 1
    assert 'finite and from 0 to 8' in capsys.readouterr().err
    assert not output.exists()


def test_vertical_clearance_default_keeps_existing_render(tmp_path):
    source = tmp_path / 'low.musicxml'
    low_cjk_score(source)
    default = tmp_path / 'default.png'
    explicit = tmp_path / 'explicit.png'
    renderer.render_printed_measure(input_path=source, measure='1', output_path=default)
    renderer.render_printed_measure(input_path=source, measure='1', output_path=explicit, lyric_top_min_margin=2)
    assert default.read_bytes() == explicit.read_bytes()
