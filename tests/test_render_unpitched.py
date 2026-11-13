from pathlib import Path

from lxml import etree
import pytest
import verovio

from score_cli.render_rests import load_render_score
from score_cli.render_unpitched import normalize_unpitched_positions


def score(clef, step, octave, attributes=''):
    return (f'<score-partwise version="4.0"><part-list><score-part id="P">'
            '<part-name>Voice</part-name></score-part></part-list><part id="P">'
            f'<measure number="132"><attributes><divisions>1</divisions><time>'
            f'<beats>4</beats><beat-type>4</beat-type></time>{clef}{attributes}</attributes>'
            f'<note id="spoken"><unpitched><display-step>{step}</display-step>'
            f'<display-octave>{octave}</display-octave></unpitched><duration>1</duration>'
            '<voice>1</voice><type>quarter</type><stem>down</stem><notehead>x</notehead>'
            '<lyric><text>下</text></lyric></note><note id="pitched"><pitch><step>C</step>'
            '<octave>4</octave></pitch><duration>3</duration><voice>1</voice>'
            '<type>half</type><dot/></note></measure></part></score-partwise>')


@pytest.mark.parametrize('clef,step,octave', [
    ('<clef><sign>F</sign><line>4</line></clef>', 'A', 3),
    ('<clef><sign>G</sign><line>2</line><clef-octave-change>-1</clef-octave-change></clef>', 'F', 4),
    ('<clef><sign>C</sign><line>3</line></clef>', 'G', 4),
])
def test_source_top_line_spoken_heads_stay_on_top_line(tmp_path: Path, clef, step, octave):
    # Independently read staff positions: bass A3, octave-down treble F4,
    # and alto G4 are all on the fifth line, MEI loc=8.
    source = tmp_path / 'spoken.musicxml'
    source.write_text(score(clef, step, octave))
    original = source.read_bytes()
    raw = verovio.toolkit()
    assert raw.loadData(source.read_text())
    raw.renderToMIDI()
    toolkit = verovio.toolkit()
    report = {}
    assert load_render_score(toolkit, source.read_text(), report)
    mei = etree.fromstring(toolkit.getMEI().encode())
    spoken = mei.xpath('//*[@xml:id="spoken"]')[0]
    assert spoken.get('loc') == '8'
    assert spoken.get('head.shape') == 'x'
    assert spoken.find('.//{*}syl').text == '下'
    assert spoken.get('pname') is None  # Never turn speaking into a pitched note.
    toolkit.renderToMIDI()
    assert toolkit.getMIDIValuesForElement('pitched') == raw.getMIDIValuesForElement('pitched')
    assert source.read_bytes() == original
    assert report['unpitchedDisplayPositions']['renderCopyOnly']
    assert report['unpitchedDisplayPositions']['playbackVerified'] is False


def test_clef_change_and_namespace_are_followed():
    xml = score('<clef><sign>G</sign><line>2</line></clef>', 'F', 5)
    xml = xml.replace('</part>', '<measure number="133"><attributes><clef><sign>F</sign>'
                      '<line>4</line></clef></attributes><note><unpitched><display-step>A</display-step>'
                      '<display-octave>3</display-octave></unpitched><duration>4</duration>'
                      '<type>whole</type></note></measure></part>')
    xml = xml.replace('<score-partwise ', '<score-partwise xmlns="http://www.musicxml.org/ns/musicxml" ')
    root = etree.fromstring(xml.encode())
    report = {}
    assert normalize_unpitched_positions(root, report) == 1
    assert root.findall('.//{*}display-octave')[0].text == '5'
    assert root.findall('.//{*}display-octave')[1].text == '5'
    assert report['unpitchedDisplayPositions']['normalizedNotes'][0]['printedMeasure'] == '133'


@pytest.mark.parametrize('change', ['missing-clef', 'non-five-line', 'octave-shift', 'malformed', 'unknown-clef'])
def test_ambiguous_contexts_remain_unchanged_and_reported(change):
    root = etree.fromstring(score('<clef><sign>F</sign><line>4</line></clef>', 'A', 3).encode())
    if change == 'missing-clef':
        clef = root.find('.//clef'); clef.getparent().remove(clef)
    elif change == 'non-five-line':
        etree.SubElement(etree.SubElement(root.find('.//attributes'), 'staff-details'), 'staff-lines').text = '1'
    elif change == 'octave-shift':
        root.find('part/measure').insert(1, etree.fromstring('<direction><direction-type><octave-shift type="down" size="8"/></direction-type></direction>'))
    elif change == 'malformed':
        root.find('.//display-octave').text = 'invalid'
    else:
        root.find('.//clef/sign').text = 'TAB'
    before = etree.tostring(root)
    report = {}
    assert normalize_unpitched_positions(root, report) == 0
    assert etree.tostring(root) == before
    assert len(report['unpitchedDisplayPositions']['unchecked']) == 1


def test_percussion_and_empty_unpitched_are_not_reinterpreted():
    root = etree.fromstring(score('<clef><sign>percussion</sign></clef>', 'G', 5).encode())
    before = etree.tostring(root); report = {}
    assert normalize_unpitched_positions(root, report) == 0
    assert etree.tostring(root) == before
    unpitched = root.find('.//unpitched')
    for child in list(unpitched):unpitched.remove(child)
    before = etree.tostring(root)
    assert normalize_unpitched_positions(root, report) == 0
    assert etree.tostring(root) == before


def test_unnumbered_staff_lines_apply_to_all_staves():
    root = etree.fromstring(score('<staves>2</staves><clef number="2"><sign>F</sign><line>4</line></clef>', 'A', 3, '<staff-details><staff-lines>1</staff-lines></staff-details>').encode())
    note = root.find('.//note'); etree.SubElement(note, 'staff').text = '2'
    before = etree.tostring(root); report = {}
    assert normalize_unpitched_positions(root, report) == 0
    assert etree.tostring(root) == before
    assert report['unpitchedDisplayPositions']['unchecked'][0]['staff'] == '2'
