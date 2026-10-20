from pathlib import Path
import re
import pytest
from lxml import etree as ET
import verovio

from score_cli.render_rests import load_render_score

FIXTURE = Path(__file__).parent / 'fixtures/render/multivoice-measure-rest.musicxml'
MEI = '{http://www.music-encoding.org/ns/mei}'
SVG = '{http://www.w3.org/2000/svg}'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


def test_actual_whole_measure_rest_keeps_its_source_voice_and_downbeat():
    xml = FIXTURE.read_text()
    raw = verovio.toolkit()
    assert raw.loadData(xml)
    raw_mei = ET.fromstring(raw.getMEI().encode())
    rest = raw_mei.xpath('//*[@xml:id="upper-rest"]')[0]
    assert rest.getparent().get('n') == '2'  # The native importer really is red.

    raw.renderToMIDI()
    native_values = raw.getMIDIValuesForElement('lower-note')
    assert native_values['time'] == 0  # Native playback is right; engraving is wrong.

    tk = verovio.toolkit()
    report = {}
    assert load_render_score(tk, xml, report)
    mei = ET.fromstring(tk.getMEI().encode())
    rest = mei.xpath('//*[@xml:id="upper-rest"]')[0]
    lower = mei.xpath('//*[@xml:id="lower-note"]')[0]
    assert rest.getparent().get('n') == '1'
    assert lower.getparent().get('n') == '2'
    assert list(lower.getparent())[0] is lower
    tk.renderToMIDI()
    values = tk.getMIDIValuesForElement('lower-note')
    assert values['time'] == 0
    assert values['duration'] == 500
    assert values == native_values
    root = ET.fromstring(tk.renderToSVG(1).encode())
    xs = []
    for identity in ['reference', 'lower-note']:
        g = root.xpath(f'//*[@id="{identity}"]')[0]
        use = g.find(SVG + 'g[@class="notehead"]/' + SVG + 'use')
        xs.append(float(re.search(r'translate\(([-\d.]+)', use.get('transform')).group(1)))
    assert xs[0] == xs[1], 'simultaneous source downbeats must align'
    assert report['explicitRestStaff']['separatedMeasureRestVoices'] == 1
    assert FIXTURE.read_text() == xml


def test_rest_separation_preserves_actual_mei_music_and_controls():
    # Other-part chord/beam, ties/slurs, lyrics, tempo and directions must not
    # disappear or change when the rest's layer is repaired and MEI reloaded.
    xml = FIXTURE.read_text().replace(
        '<note id="reference">',
        '<direction><direction-type><words>Calmly</words></direction-type><sound tempo="80"/></direction><note id="reference">',
    ).replace(
        '<note><rest/><duration>3</duration><voice>1</voice><type>half</type><dot/></note>',
        '<note id="chord-tone"><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type></note>'
        '<note id="ref-two"><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><tie type="start"/><voice>1</voice><type>quarter</type><notations><tied type="start"/><slur type="start" number="1"/></notations><lyric><text>Ah</text><extend type="start"/></lyric></note>'
        '<note id="ref-three"><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><tie type="stop"/><voice>1</voice><type>half</type><notations><tied type="stop"/><slur type="stop" number="1"/></notations><lyric><extend type="stop"/></lyric></note>',
    )
    raw, fixed = verovio.toolkit(), verovio.toolkit()
    assert raw.loadData(xml)
    assert load_render_score(fixed, xml, {})
    def payload(toolkit):
        from collections import Counter
        root = ET.fromstring(toolkit.getMEI().encode())
        names = {'note', 'rest', 'mRest', 'chord', 'tie', 'slur', 'dir', 'dynam', 'tempo', 'space', 'mSpace', 'verse', 'syl'}
        return Counter((ET.QName(el).localname,
                        tuple(sorted((k, v) for k, v in el.attrib.items() if k != XML_ID)),
                        ''.join(el.itertext()).strip())
                       for el in root.iter() if ET.QName(el).localname in names)
    assert payload(raw) == payload(fixed)
    fixed.renderToMIDI()
    assert fixed.getMIDIValuesForElement('lower-note')['time'] == 0
    assert fixed.getMIDIValuesForElement('ref-two')['time'] == 750
    assert fixed.getMIDIValuesForElement('ref-three')['time'] == 1500


@pytest.mark.parametrize('mutation', ['partial', 'implicit', 'unknown-meter', 'nonnumeric-voice', 'grace', 'voice-has-note'])
def test_unproven_whole_rest_voice_is_not_reconstructed(mutation):
    xml = FIXTURE.read_text()
    root = ET.fromstring(xml.encode())
    measure = root.find('part[@id="Alto"]/measure')
    rest = measure.find('note[@id="upper-rest"]')
    if mutation == 'partial':
        rest.find('duration').text = '3'
    elif mutation == 'implicit':
        measure.set('implicit', 'yes')
    elif mutation == 'unknown-meter':
        attributes = measure.find('attributes')
        attributes.remove(attributes.find('time'))
    elif mutation == 'nonnumeric-voice':
        rest.find('voice').text = 'upper'
    elif mutation == 'grace':
        ET.SubElement(rest, 'grace')
    elif mutation == 'voice-has-note':
        measure.find('note[@id="lower-note"]/voice').text = '1'
    toolkit = verovio.toolkit()
    report = {}
    assert load_render_score(toolkit, ET.tostring(root).decode(), report)
    assert report.get('explicitRestStaff', {}).get('separatedMeasureRestVoices', 0) == 0


def test_namespaced_input_and_above_lyrics_combine_with_rest_voice_repair():
    xml = FIXTURE.read_text().replace('<score-partwise version="4.0">', '<score-partwise xmlns="http://www.musicxml.org/ns/musicxml" version="4.0">')
    xml = xml.replace('<type>quarter</type></note><note><rest/><duration>3</duration><voice>2', '<type>quarter</type><lyric placement="above"><text>word</text></lyric></note><note><rest/><duration>3</duration><voice>2')
    toolkit = verovio.toolkit()
    report = {}
    assert load_render_score(toolkit, xml, report)
    mei = ET.fromstring(toolkit.getMEI().encode())
    lower = mei.xpath('//*[@xml:id="lower-note"]')[0]
    assert lower.find(MEI + 'verse').get('place') == 'above'
    assert mei.xpath('//*[@xml:id="upper-rest"]')[0].getparent().get('n') == '1'
    toolkit.renderToMIDI()
    assert toolkit.getMIDIValuesForElement('lower-note')['time'] == 0
