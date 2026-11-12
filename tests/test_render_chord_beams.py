from pathlib import Path

from lxml import etree
import pytest
import verovio

from score_cli.render_rests import load_render_score


def score():
    def note(step, chord, beam):
        return (f'<note>{"<chord/>" if chord else ""}<pitch><step>{step}</step>'
                '<octave>4</octave></pitch><duration>1</duration><voice>1</voice>'
                f'<type>eighth</type><staff>1</staff><beam number="1">{beam}</beam></note>')
    return ('<score-partwise version="4.0"><part-list><score-part id="P">'
            '<part-name>Piano</part-name></score-part></part-list><part id="P">'
            '<measure number="1"><attributes><divisions>2</divisions><time>'
            '<beats>4</beats><beat-type>4</beat-type></time><staves>2</staves>'
            '<clef number="1"><sign>G</sign><line>2</line></clef>'
            '<clef number="2"><sign>F</sign><line>4</line></clef></attributes>'
            + note('C', False, 'begin') + note('E', True, 'begin')
            + note('D', False, 'end') + note('F', True, 'end')
            + '<note id="after-chord-rest"><rest/><duration>2</duration><voice>1</voice>'
            '<type>quarter</type><staff>1</staff></note>'
            '<note id="right-half-rest"><rest/><duration>4</duration><voice>1</voice>'
            '<type>half</type><staff>1</staff></note><backup><duration>8</duration></backup>'
            '<note id="left-whole-rest"><rest measure="yes"/><duration>8</duration>'
            '<voice>2</voice><staff>2</staff></note></measure></part></score-partwise>')


def test_actual_renderer_keeps_rests_after_repeated_chord_beams(tmp_path: Path):
    source = tmp_path / 'score.musicxml'
    source.write_text(score())
    original = source.read_bytes()
    toolkit = verovio.toolkit()
    report = {}
    assert load_render_score(toolkit, source.read_text(), report)
    mei = etree.fromstring(toolkit.getMEI().encode())
    for identity in ['after-chord-rest', 'right-half-rest', 'left-whole-rest']:
        elements = mei.xpath('//*[@xml:id=$identity]', identity=identity)
        assert len(elements) == 1
        assert etree.QName(elements[0]).localname in ('rest', 'mRest')
    assert len(mei.xpath('//*[local-name()="note"]')) == 4
    assert source.read_bytes() == original
    assert report['duplicateChordBeams']['removedElements'] == 2


@pytest.mark.parametrize('change', ['staff', 'value', 'id', 'fan', 'voice', 'hidden'])
def test_ambiguous_chord_beams_are_not_normalized(change):
    from score_cli.render_chord_beams import normalize_chord_beams
    root = etree.fromstring(score().encode())
    chord_note = root.find('part/measure').findall('note')[1]
    if change in ('staff', 'voice'):
        chord_note.find(change).text = '2'
    elif change == 'value':
        chord_note.find('beam').text = 'end'
    elif change == 'hidden':
        chord_note.set('print-object', 'no')
    else:
        chord_note.find('beam').set(change, 'source-beam' if change == 'id' else 'accel')
    original = etree.tostring(chord_note)
    report = {}
    assert normalize_chord_beams(root, report) == 1  # Only the other safe chord.
    assert etree.tostring(chord_note) == original
    assert len(report['duplicateChordBeams']['unchecked']) == 1


def test_normalization_also_reaches_single_staff_import_without_rest_relocation():
    root = etree.fromstring(score().encode())
    measure = root.find('part/measure')
    measure.find('attributes/staves').text = '1'
    measure.find('attributes').remove(measure.find('attributes/clef[@number="2"]'))
    measure.remove(measure.find('backup'))
    measure.remove(measure.find('note[@id="left-whole-rest"]'))
    toolkit = verovio.toolkit()
    report = {}
    assert load_render_score(toolkit, etree.tostring(root, encoding='unicode'), report)
    mei = etree.fromstring(toolkit.getMEI().encode())
    assert len(mei.xpath('//*[@xml:id="after-chord-rest"]')) == 1
    assert len(mei.xpath('//*[local-name()="note"]')) == 4
    assert report['duplicateChordBeams']['removedElements'] == 2
