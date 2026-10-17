from pathlib import Path
import xml.etree.ElementTree as ET
import verovio
import pytest
from score_cli import render_measure

FIXTURE = Path(__file__).parent / 'fixtures/senza-direction-offset.musicxml'

def test_free_meter_later_part_retains_direction_offsets(tmp_path, monkeypatch):
    real_factory = verovio.toolkit
    instances = []
    class Capture:
        def __init__(self):
            self.inner = real_factory()
            instances.append(self.inner)
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def renderToSVG(self, page):
            svg = self.inner.renderToSVG(page)
            return svg
    monkeypatch.setattr(verovio, 'toolkit', Capture)
    render_measure.render_printed_measure(input_path=FIXTURE, measure='86', output_path=tmp_path/'86.png')
    mei = ET.fromstring(instances[-1].getMEI())
    hairpins = mei.findall('.//{http://www.music-encoding.org/ns/mei}hairpin')
    assert [(h.get('tstamp'), h.get('tstamp2')) for h in hairpins] == [('3', '0m+5'), ('3', '0m+5')]


def _toolkit(xml):
    from score_cli.render_input import prepare_render_input
    prepared = prepare_render_input(xml)
    toolkit = verovio.toolkit()
    assert toolkit.loadData(prepared.xml)
    return toolkit, prepared


def _times(toolkit, family='hairpin'):
    return [(h.get('staff'), h.get('tstamp'), h.get('tstamp2'))
            for h in ET.fromstring(toolkit.getMEI()).findall(f'.//{{http://www.music-encoding.org/ns/mei}}{family}')]


def test_offbeat_negative_offset_backup_and_cross_bar_endpoint():
    root = ET.fromstring(FIXTURE.read_text())
    for part in root.findall('part'):
        m = part.findall('measure')[1]
        directions = m.findall('direction')
        for d in directions:
            m.remove(d)
        # Cursor returns to zero for the second voice, then reaches four again.
        m.append(ET.fromstring('<backup><duration>16</duration></backup>'))
        m.append(ET.fromstring('<note><rest/><duration>16</duration><voice>2</voice><type>whole</type></note>'))
        start = directions[1]  # Fixture serializes stop before start.
        assert start.find('direction-type/wedge').get('type') == 'diminuendo'
        start.find('offset').text = '-10'  # 4q - 2.5q = 1.5q
        m.append(start)
        word = ET.fromstring('<direction><direction-type><words>already present</words></direction-type><offset>-10</offset></direction>')
        m.append(word)
        next_bar = ET.SubElement(part, 'measure', number='87')
        next_bar.append(ET.fromstring('<note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><type>whole</type></note>'))
        stop = directions[0]
        stop.find('offset').text = '-14'  # next bar .5q
        next_bar.append(stop)
    toolkit, prepared = _toolkit(ET.tostring(root, encoding='unicode'))
    assert _times(toolkit) == [('1', '2.5', '1m+1.5'), ('2', '2.5', '1m+1.5')]
    assert [(s, t) for s, t, _ in _times(toolkit, 'dir')] == [('1', '2.5'), ('2', '2.5')]
    assert len(prepared.compatibility['omittedRedundantTimeDeclarations']) == 1


def test_normalization_preserves_all_other_xml_and_never_writes_source(tmp_path):
    from score_cli.render_input import prepare_render_input
    from lxml import etree
    xml = FIXTURE.read_text()
    prepared = prepare_render_input(xml)
    before = etree.fromstring(xml.encode(), etree.XMLParser(remove_blank_text=True))
    after = etree.fromstring(prepared.xml.encode(), etree.XMLParser(remove_blank_text=True))
    assert after.find('part/measure[@number="86"]/attributes/time/senza-misura') is not None
    redundant = before.findall('part')[1].find('measure[@number="86"]/attributes/time')
    redundant.getparent().remove(redundant)
    assert etree.tostring(before, method='c14n') == etree.tostring(after, method='c14n')
    source = tmp_path/'source.musicxml'
    source.write_text(xml)
    saved = source.read_bytes()
    render_measure.render_printed_measure(input_path=source, measure='86', output_path=tmp_path/'proof.png')
    assert source.read_bytes() == saved


def test_range_render_reports_adapter_and_source_hash(tmp_path):
    import hashlib
    from score_cli.render_measure import render_range
    result = render_range(input_path=FIXTURE, start='86', end='86', output_directory=tmp_path/'range')
    assert result['inputSha256'] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert result['renderInputCompatibility']['omittedRedundantTimeDeclarations'] == [
        {'partId': 'P2', 'measureOrdinal': 2, 'printedMeasure': '86'}]


@pytest.mark.parametrize('mutation', ['prior-unit', 'numbered', 'visibility', 'independent', 'mixed'])
def test_unproven_shared_meter_is_unchanged_and_reported(mutation):
    from score_cli.render_input import prepare_render_input
    root = ET.fromstring(FIXTURE.read_text())
    second = root.findall('part')[1]
    prior = second.find('measure/attributes/time')
    free = second.find('measure[@number="86"]/attributes/time')
    if mutation == 'prior-unit':
        prior.find('beat-type').text = '8'
    elif mutation == 'numbered':
        free.set('number', '1')
    elif mutation == 'visibility':
        free.set('print-object', 'no')
    elif mutation == 'independent':
        first = root.find('part/measure[@number="86"]/attributes/time')
        first.clear()
        ET.SubElement(first, 'beats').text = '3'
        ET.SubElement(first, 'beat-type').text = '4'
    else:
        ET.SubElement(prior, 'beats').text = '2'
        ET.SubElement(prior, 'beat-type').text = '8'
    xml = ET.tostring(root, encoding='unicode')
    prepared = prepare_render_input(xml)
    assert prepared.xml == xml
    assert prepared.compatibility['omittedRedundantTimeDeclarations'] == []
    assert prepared.compatibility['unchecked']


def test_three_parts_keep_first_visible_free_label_and_all_source_notes():
    import copy
    from score_cli.render_input import prepare_render_input
    root = ET.fromstring(FIXTURE.read_text())
    third = copy.deepcopy(root.findall('part')[1])
    third.set('id', 'P3')
    root.append(third)
    definition = copy.deepcopy(root.find('part-list/score-part'))
    definition.set('id', 'P3')
    root.find('part-list').append(definition)
    for senza in root.findall('.//senza-misura'):
        senza.text = 'Free, not a printed metrical signature'
    xml = ET.tostring(root, encoding='unicode')
    prepared = prepare_render_input(xml)
    after = ET.fromstring(prepared.xml)
    assert [s.text for s in after.findall('.//senza-misura')] == ['Free, not a printed metrical signature']
    assert [ET.canonicalize(ET.tostring(n), strip_text=True) for n in after.findall('.//note')] == [ET.canonicalize(ET.tostring(n), strip_text=True) for n in root.findall('.//note')]
    toolkit, _ = _toolkit(xml)
    assert _times(toolkit) == [('1', '3', '0m+5'), ('2', '3', '0m+5'), ('3', '3', '0m+5')]
