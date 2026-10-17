"""A source-calibration regression through the public validation boundary."""

from pathlib import Path

import pytest
from lxml import etree as ET

from score_cli.validation import validate_score

FIXTURE = Path(__file__).parent / "fixtures/note-order/finzi-notations-after-lyric.musicxml"


def test_finzi_appended_tenuto_after_lyric_is_located_without_rewriting_source():
    original = FIXTURE.read_bytes()
    report = validate_score(input_path=FIXTURE)
    diagnostics = [d for d in report["diagnostics"] if d["code"] == "notations-after-lyric"]
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["severity"] == "error"
    assert diagnostic["location"]["partId"] == "P1"
    assert diagnostic["location"]["printedMeasure"] == "28"
    assert diagnostic["location"]["eventIndex"] == 1
    assert report["status"] == "invalid"
    assert FIXTURE.read_bytes() == original


@pytest.mark.parametrize("prefix", [None, "m"])
def test_default_and_prefixed_musicxml_namespace_have_same_error(tmp_path, prefix):
    tree = ET.parse(str(FIXTURE))
    namespace = "http://www.musicxml.org/ns/musicxml"
    for element in tree.getroot().iter():
        if isinstance(element.tag, str):
            element.tag = f"{{{namespace}}}{element.tag}"
    ET.cleanup_namespaces(tree, top_nsmap={prefix: namespace})
    path = tmp_path / "namespaced.musicxml"
    path.write_bytes(ET.tostring(tree))
    diagnostic = validate_score(input_path=path)["diagnostics"]
    assert [d["code"] for d in diagnostic] == ["notations-after-lyric"]


@pytest.mark.parametrize(
    "tail",
    [
        '<notations><articulations><tenuto/></articulations></notations><lyric><text>word</text></lyric>',
        '<notations/><notations/><lyric><text>one</text></lyric><lyric><text>two</text></lyric>',
        '<lyric><text>word</text></lyric><ext:notations/>',
        '<ext:lyric/><notations/>',
        '<ext:lyric/><ext:notations/>',
        '<notations/><!-- preserved comment --><lyric><text>word</text></lyric><?proof keep?>',
    ],
)
def test_legal_order_and_foreign_extension_names_do_not_trigger_rule(tmp_path, tail):
    from test_edit_score import score

    path = score(tmp_path, '<note><pitch><step>C</step><octave>4</octave></pitch><duration>8</duration><type>whole</type>' + tail + '</note>')
    original = path.read_bytes()
    report = validate_score(input_path=path)
    assert not [d for d in report["diagnostics"] if d["code"] == "notations-after-lyric"]
    assert path.read_bytes() == original


def test_late_notations_is_invalid_even_with_earlier_notations(tmp_path):
    from test_edit_score import score

    path = score(tmp_path, '<note><pitch><step>C</step><octave>4</octave></pitch><duration>8</duration><type>whole</type><notations/><lyric><text>word</text></lyric><notations/></note>')
    report = validate_score(input_path=path)
    assert [d["code"] for d in report["diagnostics"]] == ["notations-after-lyric"]


def test_structural_edit_rejects_new_note_order_error_without_output(tmp_path):
    from score_cli.edit_score import EditError, edit_score
    from test_warning_acknowledgments import transaction

    element = ET.parse(str(FIXTURE)).find(".//note")
    assert element is not None
    note = ET.tostring(element).decode().replace('<duration>8</duration>', '<duration>4</duration>')
    source, changes = transaction(tmp_path, after=note)
    original = source.read_bytes()
    output = tmp_path / "invalid.musicxml"
    with pytest.raises(EditError) as caught:
        edit_score(input_path=source, changeset=changes, output_path=output)
    assert caught.value.diagnostic["code"] == "introduced-diagnostic"
    assert "notations-after-lyric" in str(caught.value.diagnostic["reason"])
    assert source.read_bytes() == original
    assert not output.exists()
    assert not Path(str(output) + ".edit.json").exists()


def test_reports_narrow_coverage_without_claiming_full_schema():
    report = validate_score(input_path=FIXTURE)
    assert "notations-before-lyric-note-order" in report["coverage"]["checked"]
    assert "full-musicxml-schema" in report["coverage"]["unchecked"]
