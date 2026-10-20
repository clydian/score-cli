from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import verovio

import score_cli.render_measure as renderer
from score_cli.render_lyrics import load_render_score

NS = '{http://www.w3.org/2000/svg}'


def fixture(number='1', namespace=False):
    xml = f'''<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><note id="preserve"><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type><lyric number="{number}" placement="above"><syllabic>single</syllabic><text>ABOVE</text></lyric><lyric number="2"><text>BELOW</text></lyric></note></measure></part></score-partwise>'''
    return xml.replace('<score-partwise ', '<score-partwise xmlns="http://www.musicxml.org/ns/musicxml" ', 1) if namespace else xml


def assert_geometry(svg):
    root = ET.fromstring(svg)
    staff = next(g for g in root.iter(NS + 'g') if g.get('class') == 'staff')
    lines = [float(x.get('d').split()[1]) for x in staff.findall(NS + 'path')][:5]
    assert len(lines) == 5
    texts = {''.join(t.itertext()).strip(): float(t.get('y')) for g in root.iter(NS + 'g') if g.get('class') == 'syl' for t in g.iter(NS + 'text')}
    assert texts['ABOVE'] < min(lines), 'source above lyric must be above staff, not just present'
    assert texts['BELOW'] > max(lines), 'default below lyric must remain below'


@pytest.mark.parametrize('mode', ['single', 'range'])
@pytest.mark.parametrize('namespace', [False, True])
def test_actual_renderer_respects_above_and_default_below(tmp_path, monkeypatch, mode, namespace):
    p = tmp_path / 'source.musicxml'
    p.write_text(fixture(namespace=namespace))
    original = p.read_bytes()
    images = []
    rasterize = renderer._rasterize_svg

    def capture(svg):
        images.append(svg)
        return rasterize(svg)

    monkeypatch.setattr(renderer, '_rasterize_svg', capture)
    if mode == 'single':
        result = renderer.render_printed_measure(input_path=p, measure='1', output_path=tmp_path / 'single.png')
        report = result.render_input_compatibility
    else:
        result = renderer.render_range(input_path=p, start='1', output_directory=tmp_path / 'range')
        report = result['renderInputCompatibility']
    assert_geometry(images[-1])
    assert p.read_bytes() == original
    assert report['explicitAboveLyrics']['mappedVerseElements'] == 1


def test_raw_verovio_import_drops_placement_but_mei_adapter_preserves_music():
    xml = fixture()
    raw = verovio.toolkit()
    assert raw.loadData(xml)
    with pytest.raises(AssertionError, match='source above lyric'):
        assert_geometry(raw.renderToSVG(1))
    before = ET.fromstring(raw.getMEI())
    adapted = verovio.toolkit()
    assert load_render_score(adapted, xml, {})
    assert_geometry(adapted.renderToSVG(1))
    after = ET.fromstring(adapted.getMEI())
    # ID/layout/header serialization may differ; music and verse text survive.
    music = lambda root: [(e.tag.split('}')[-1], {k: v for k, v in e.attrib.items() if k not in ('{http://www.w3.org/XML/1998/namespace}id', 'place')}, e.text) for e in root.iter() if e.tag.split('}')[-1] in ('note', 'rest', 'chord', 'verse', 'syl')]
    assert music(before) == music(after)


@pytest.mark.parametrize('number', ['name', '0', '2'])
def test_ambiguous_or_unsupported_verse_does_not_guess(number):
    with pytest.raises(ValueError, match='unique positive numeric'):
        load_render_score(verovio.toolkit(), fixture(number=number), {})


def test_two_voices_and_two_above_verses_do_not_move_other_part_or_below():
    xml = fixture().replace('<lyric number="2">', '<lyric number="3">')
    xml = xml.replace('</note>', '<lyric number="2" placement="above"><text>SECOND</text></lyric></note>', 1)
    xml = xml.replace('</measure>', '<backup><duration>4</duration></backup><note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><voice>2</voice><type>whole</type><lyric number="4"><text>LOWVOICE</text></lyric></note></measure>', 1)
    xml = xml.replace('</part-list>', '<score-part id="P2"><part-name>Other</part-name></score-part></part-list>')
    other = fixture().split('<part id="P1">')[1].split('</part>')[0].replace('ABOVE', 'UNRELATED').replace(' placement="above"', '').replace('id="preserve"', 'id="other"')
    xml = xml.replace('</score-partwise>', '<part id="P2">' + other + '</part></score-partwise>')
    tk = verovio.toolkit()
    report = {}
    assert load_render_score(tk, xml, report)
    assert report['explicitAboveLyrics']['mappedVerseElements'] == 2
    mei = ET.fromstring(tk.getMEI())
    places = {''.join(v.itertext()).strip(): v.get('place') for v in mei.iter() if v.tag.endswith('}verse')}
    assert places['ABOVE'] == places['SECOND'] == 'above'
    assert places['LOWVOICE'] is None
    assert places['UNRELATED'] is None


def test_default_below_uses_original_load_without_roundtrip():
    class Recorder:
        def __init__(self):
            self.calls = []
        def loadData(self, xml):
            self.calls.append(xml)
            return True
    xml = fixture().replace(' placement="above"', '')
    tk = Recorder()
    report = {}
    assert load_render_score(tk, xml, report)
    assert tk.calls == [xml]
    assert report == {}


def test_note_identity_and_lyric_extenders_survive_and_foreign_lyric_is_ignored():
    xml = fixture().replace('<text>ABOVE</text>', '<text>ABOVE</text><extend type="start"/>')
    xml = xml.replace('</measure>', '<note><rest/><duration>0</duration><type>quarter</type><x:lyric xmlns:x="urn:extension" placement="above"><x:text>FOREIGN</x:text></x:lyric></note></measure>')
    tk = verovio.toolkit()
    report = {}
    assert load_render_score(tk, xml, report)
    mei = ET.fromstring(tk.getMEI())
    assert any(e.get('{http://www.w3.org/XML/1998/namespace}id') == 'preserve' for e in mei.iter())
    assert report['explicitAboveLyrics']['mappedVerseElements'] == 1
    assert any(e.get('con') == 'u' for e in mei.iter() if e.tag.endswith('}syl'))


def test_duplicate_note_ids_fail_without_guessing_voice():
    xml = fixture().replace('</measure>', '<note id="preserve"><rest/><duration>0</duration></note></measure>')
    with pytest.raises(ValueError, match='unambiguous note ID'):
        load_render_score(verovio.toolkit(), xml, {})


def test_conflicting_id_and_xml_id_do_not_drop_alias_references():
    xml = fixture().replace('id="preserve"', 'id="preserve" xml:id="different"')
    with pytest.raises(ValueError, match='conflicting id and xml:id'):
        load_render_score(verovio.toolkit(), xml, {})
