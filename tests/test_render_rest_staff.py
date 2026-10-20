from pathlib import Path
import re
from xml.etree import ElementTree as ET

import pytest
import verovio

import score_cli.render_measure as renderer

SVG = '{http://www.w3.org/2000/svg}'


def fixture():
    return '''<score-partwise version="4.0"><part-list><score-part id="P"><part-name>Piano</part-name></score-part></part-list><part id="P"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes><note id="left-rest"><rest measure="yes"/><duration>4</duration><voice>2</voice><staff>2</staff></note><backup><duration>4</duration></backup><note id="right-note"><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>3</voice><type>whole</type><staff>1</staff></note></measure></part></score-partwise>'''


def assert_left_rest(svg, staff_index=1):
    root = ET.fromstring(svg)
    staves = [g for g in root.iter(SVG + 'g') if g.get('class') == 'staff']
    lines = [float(p.get('d').split()[1]) for p in staves[staff_index].findall(SVG + 'path')][:5]
    rest = next(g for g in root.iter(SVG + 'g') if g.get('id') == 'left-rest')
    transform = rest.find(SVG + 'use').get('transform')
    y = float(re.search(r'translate\([^,]+,\s*([\d.-]+)\)', transform).group(1))
    assert min(lines) <= y <= max(lines), 'left-hand rest must be on bass staff'


@pytest.mark.parametrize('mode', ['single', 'range'])
def test_actual_renderer_preserves_explicit_rest_staff(tmp_path: Path, monkeypatch, mode):
    p = tmp_path / 'score.musicxml'
    p.write_text(fixture())
    original = p.read_bytes()
    images = []
    rasterize = renderer._rasterize_svg

    def capture(svg):
        images.append(svg)
        return rasterize(svg)

    monkeypatch.setattr(renderer, '_rasterize_svg', capture)
    if mode == 'single':
        renderer.render_printed_measure(input_path=p, measure='1', output_path=tmp_path / 'one.png')
    else:
        renderer.render_range(input_path=p, start='1', output_directory=tmp_path / 'range')
    assert_left_rest(images[-1])
    assert p.read_bytes() == original


def test_raw_import_is_red_and_adapter_changes_actual_geometry():
    from score_cli.render_rests import load_render_score
    raw = verovio.toolkit()
    assert raw.loadData(fixture())
    with pytest.raises(AssertionError, match='bass staff'):
        assert_left_rest(raw.renderToSVG(1))
    fixed = verovio.toolkit()
    report = {}
    assert load_render_score(fixed, fixture(), report)
    assert_left_rest(fixed.renderToSVG(1))
    assert report['explicitRestStaff']['relocatedLayers'] == 1
    assert report['explicitRestStaff']['unchecked'] == []


def test_source_part_staff_numbers_are_not_global_mei_numbers():
    from score_cli.render_rests import load_render_score
    xml = fixture().replace('<part-list>', '<part-list><score-part id="V"><part-name>Voice</part-name></score-part>')
    other = '<part id="V"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><note id="other-note"><pitch><step>E</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note></measure></part>'
    xml = xml.replace('<part id="P">', other + '<part id="P">')
    tk = verovio.toolkit()
    assert load_render_score(tk, xml, {})
    assert_left_rest(tk.renderToSVG(1), staff_index=2)


def test_namespace_and_anonymous_notes_keep_source_bytes():
    from score_cli.render_rests import load_render_score
    xml = fixture().replace(' id="left-rest"', '').replace(' id="right-note"', '')
    xml = xml.replace('<score-partwise ', '<score-partwise xmlns="http://www.musicxml.org/ns/musicxml" ', 1)
    tk = verovio.toolkit()
    report = {}
    assert load_render_score(tk, xml, report)
    mei = ET.fromstring(tk.getMEI())
    ns = '{http://www.music-encoding.org/ns/mei}'
    staff2 = next(s for s in mei.iter(ns + 'staff') if s.get('n') == '2')
    assert len(list(staff2.iter(ns + 'mRest'))) == 1
    assert report['explicitRestStaff']['relocatedLayers'] == 1


@pytest.mark.parametrize('replacement', [
    'id="left-rest" xml:id="different"', 'id="right-note"',
])
def test_conflicting_source_identities_fail_closed(replacement):
    from score_cli.render_rests import load_render_score
    xml = fixture().replace('id="left-rest"', replacement)
    with pytest.raises(ValueError, match='identities|unambiguous'):
        load_render_score(verovio.toolkit(), xml, {})


def test_mixed_cross_staff_voice_is_not_relocated_as_a_single_staff_voice():
    from score_cli.render_rests import load_render_score
    xml = fixture().replace('<rest measure="yes"/><duration>4</duration>', '<rest/><duration>2</duration>')
    xml = xml.replace('<backup><duration>4</duration></backup>', '<note id="cross-note"><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><voice>2</voice><type>half</type><staff>1</staff></note><backup><duration>4</duration></backup>')
    tk = verovio.toolkit()
    report = {}
    assert load_render_score(tk, xml, report)
    assert report['explicitRestStaff']['relocatedLayers'] == 0
    assert report['explicitRestStaff']['unchecked'][0]['reason'] == 'mixed-or-unmapped-layer'


def test_above_lyrics_and_pitched_midi_values_survive_rest_relocation():
    from score_cli.render_rests import load_render_score
    xml = fixture().replace('</type><staff>1', '</type><lyric number="1" placement="above"><text>ABOVE</text></lyric><staff>1')
    # Put lyric after staff as required by MusicXML, independently of adapter.
    xml = xml.replace('<lyric number="1" placement="above"><text>ABOVE</text></lyric><staff>1</staff>', '<staff>1</staff><lyric number="1" placement="above"><text>ABOVE</text></lyric>')
    raw = verovio.toolkit()
    assert raw.loadData(xml)
    raw.renderToMIDI()
    tk = verovio.toolkit()
    report = {}
    assert load_render_score(tk, xml, report)
    tk.renderToMIDI()
    assert tk.getMIDIValuesForElement('right-note') == raw.getMIDIValuesForElement('right-note')
    assert_left_rest(tk.renderToSVG(1))
    ns = '{http://www.music-encoding.org/ns/mei}'
    verse = next(ET.fromstring(tk.getMEI()).iter(ns + 'verse'))
    assert verse.get('place') == 'above'
    assert report['explicitAboveLyrics']['mappedVerseElements'] == 1


def test_variable_staff_count_is_reported_without_guessing():
    from score_cli.render_rests import load_render_score
    xml = fixture().replace('</part>', '<measure number="2"><attributes><staves>1</staves></attributes><note><rest measure="yes"/><duration>4</duration></note></measure></part>')
    class Recorder:
        def loadData(self, value):
            assert value == xml
            return True
    report = {}
    assert load_render_score(Recorder(), xml, report)
    assert report['explicitRestStaff']['unchecked'] == [{'partId': 'P', 'reason': 'variable-staff-count'}]


def test_hidden_rests_imported_as_spaces_are_not_treated_as_visible_rests():
    from score_cli.render_rests import load_render_score
    xml = fixture().replace('</part>', '<measure number="2"><note print-object="no" id="hidden"><rest/><duration>4</duration><voice>2</voice><type>whole</type><staff>2</staff></note><backup><duration>4</duration></backup><note id="upper2"><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><voice>3</voice><type>whole</type><staff>1</staff></note></measure></part>')
    tk = verovio.toolkit()
    report = {}
    assert load_render_score(tk, xml, report)
    assert_left_rest(tk.renderToSVG(1))
    assert report['explicitRestStaff']['relocatedLayers'] == 1


def test_implicit_initial_one_staff_then_explicit_two_is_not_assumed_constant():
    from score_cli.render_rests import load_render_score
    xml = fixture().replace('<staves>2</staves>', '')
    xml = xml.replace('</part>', '<measure number="2"><attributes><staves>2</staves></attributes><note><rest/><duration>4</duration><staff>2</staff></note></measure></part>')
    class Recorder:
        def loadData(self, value):
            assert value == xml
            return True
    report = {}
    assert load_render_score(Recorder(), xml, report)
    assert report['explicitRestStaff']['unchecked'][0]['reason'] == 'variable-staff-count'
