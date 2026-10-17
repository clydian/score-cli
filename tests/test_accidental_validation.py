"""Imported and structural edits can preserve stale display accidentals."""
import pytest
from score_cli.validation import validate_score
from test_edit_score import score


@pytest.mark.parametrize('accidental,alter', [('natural','-1'),('flat','0'),('sharp','-1'),('double-sharp','1'),('flat-flat','-1')])
def test_locates_display_accidental_that_contradicts_sounding_alter(tmp_path, accidental, alter):
    path = score(tmp_path, f'<note><pitch><step>E</step><alter>{alter}</alter><octave>4</octave></pitch><duration>8</duration><voice>1</voice><type>whole</type><accidental cautionary="yes" parentheses="yes">{accidental}</accidental></note>')
    original = path.read_bytes()
    mismatches = [d for d in validate_score(input_path=path)['diagnostics'] if d['code'] == 'accidental-pitch-mismatch']
    assert len(mismatches) == 1
    assert mismatches[0]['severity'] == 'warning'
    assert mismatches[0]['location']['partId'] == 'P1'
    assert mismatches[0]['location']['printedMeasure'] == 'X1'
    assert mismatches[0]['location']['voice'] == '1'
    assert path.read_bytes() == original


@pytest.mark.parametrize('accidental,alter', [('natural',None),('flat','-1'),('sharp','1'),('double-sharp','2'),('flat-flat','-2'),('quarter-sharp','0.5'),('other','-1'),(None,'-1')])
def test_matching_courtesy_absent_and_uninterpreted_accidentals_are_preserved(tmp_path, accidental, alter):
    alteration = f'<alter>{alter}</alter>' if alter is not None else ''
    glyph = f'<accidental cautionary="yes">{accidental}</accidental>' if accidental else ''
    path = score(tmp_path, f'<note><pitch><step>E</step>{alteration}<octave>4</octave></pitch><duration>8</duration><type>whole</type>{glyph}</note>')
    assert not [d for d in validate_score(input_path=path)['diagnostics'] if d['code'] == 'accidental-pitch-mismatch']


def test_structural_edit_cannot_silently_introduce_stale_accidental(tmp_path):
    from test_warning_acknowledgments import transaction, rejected_review

    note = '<note><pitch><step>E</step><alter>-1</alter><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type><accidental>natural</accidental></note>'
    source, changes = transaction(tmp_path, after=note)
    review = rejected_review(source, changes, tmp_path / 'unreviewed.xml')
    assert [d['code'] for d in review['diagnostics']] == ['accidental-pitch-mismatch']
