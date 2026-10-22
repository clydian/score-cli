from pathlib import Path
from lxml import etree
import pytest
import verovio
from score_cli.render_input import prepare_render_input
from score_cli.render_measure import render_printed_measure, render_range

FIXTURE = Path(__file__).parent / 'fixtures/nonfirst-part-key-change.musicxml'


def test_real_verovio_drops_nonfirst_change_and_warning_preserves_xml():
    xml = FIXTURE.read_text()
    toolkit = verovio.toolkit()
    assert toolkit.loadData(xml)
    mei = etree.fromstring(toolkit.getMEI().encode())
    assert not mei.findall('.//{*}measure[@n="2"]//{*}keySig')
    assert not mei.findall('.//{*}section/{*}scoreDef')
    prepared = prepare_render_input(xml)
    assert prepared.xml == xml
    warnings = prepared.compatibility['warnings']
    assert len(warnings) == 1
    assert warnings[0]['partId'] == 'B'
    assert warnings[0]['printedMeasure'] == '2'
    assert warnings[0]['sourceFifths'] == '-4'
    assert 'independent renderer' in warnings[0]['message']


@pytest.mark.parametrize('kind', ['single-part', 'redundant', 'shared-first-part'])
def test_known_unaffected_key_declarations_are_not_reported(kind):
    root = etree.parse(str(FIXTURE)).getroot()
    first, second = root.findall('part')
    if kind == 'single-part':
        root.remove(first)
        root.find('part-list').remove(root.find('part-list/score-part'))
    elif kind == 'redundant':
        second.find('measure/attributes/key/fifths').text = '-4'
    else:
        attrs = etree.SubElement(first.findall('measure')[1], 'attributes')
        key = etree.SubElement(attrs, 'key')
        etree.SubElement(key, 'fifths').text = '-4'
    assert prepare_render_input(etree.tostring(root).decode()).compatibility['warnings'] == []


@pytest.mark.parametrize('mode', ['single', 'range'])
def test_actual_render_reports_risk_and_keeps_source(tmp_path, mode):
    source = tmp_path / 'score.musicxml'
    source.write_bytes(FIXTURE.read_bytes())
    before = source.read_bytes()
    if mode == 'single':
        result = render_printed_measure(input_path=source, measure='2', output_path=tmp_path / 'one.png')
        report = result.render_input_compatibility
    else:
        result = render_range(input_path=source, start='2', output_directory=tmp_path / 'range')
        report = result['renderInputCompatibility']
    assert report['warnings'][0]['partId'] == 'B'
    assert source.read_bytes() == before


def test_cli_prints_actionable_warning_to_stderr(tmp_path, capsys):
    from score_cli.cli import main
    assert main(['render', str(FIXTURE), '--measure', '2', '--output', str(tmp_path / 'two.png')]) == 0
    captured = capsys.readouterr()
    assert 'Warning [verovio-nonfirst-part-key-change-risk] part B, measure 2' in captured.err
    assert 'independent renderer' in captured.err
    assert 'Rendered measure' in captured.out


def _staff_sequence(keys):
    root = etree.parse(str(FIXTURE)).getroot()
    second = root.findall('part')[1]
    second.clear(keep_tail=True)
    second.set('id', 'B')
    for index, declarations in enumerate(keys, 1):
        measure = etree.SubElement(second, 'measure', number=str(index))
        attributes = etree.SubElement(measure, 'attributes')
        for staff, fifths in declarations:
            key = etree.SubElement(attributes, 'key', **({'number': str(staff)} if staff else {}))
            etree.SubElement(key, 'fifths').text = str(fifths)
    return etree.tostring(root).decode()


def test_all_staff_reset_after_numbered_override_is_a_real_change():
    xml = _staff_sequence([[(None, 1)], [(1, -4)], [(None, 1)]])
    warnings = prepare_render_input(xml).compatibility['warnings']
    assert [(w['measureOrdinal'], w['staff']) for w in warnings] == [(2, '1'), (3, 'all')]


def test_all_staff_reset_clears_stale_numbered_state():
    xml = _staff_sequence([[(None, 1)], [(1, -4)], [(None, -3)], [(1, -3)]])
    warnings = prepare_render_input(xml).compatibility['warnings']
    assert [(w['measureOrdinal'], w['staff']) for w in warnings] == [(2, '1'), (3, 'all')]


def test_staff_state_does_not_leak_across_parts_and_namespaced_input():
    xml = _staff_sequence([[(None, 1)], [(1, -4)]])
    root = etree.fromstring(xml.encode())
    import copy
    third = copy.deepcopy(root.findall('part')[1])
    third.set('id', 'C')
    third.findall('measure')[1].find('attributes/key/fifths').text = '1'
    root.append(third)
    for node in root.iter():
        node.tag = '{urn:owned:musicxml}' + node.tag
    warnings = prepare_render_input(etree.tostring(root).decode()).compatibility['warnings']
    assert [(w['partId'], w['staff']) for w in warnings] == [('B', '1')]
