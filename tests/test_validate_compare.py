"""Musical checks report bounded coverage instead of claiming PDF correctness."""

import pytest

from score_cli.validation import validate_score
from test_edit_score import score


def test_chord_grace_tuplet_cross_staff_and_pickup_are_not_summed_as_one_voice(
    tmp_path,
):
    path = score(
        tmp_path,
        """
<note><grace/><pitch><step>D</step><octave>4</octave></pitch><voice>1</voice><type>eighth</type></note>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>
<note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>2</staff></note>
<backup><duration>2</duration></backup>
<note><rest/><duration>2</duration><voice>2</voice><type>quarter</type></note>""",
    )
    path.write_text(path.read_text().replace("<time>", "<staves>2</staves><time>"))
    report = validate_score(input_path=path)
    assert report["status"] == "valid-within-coverage"
    assert not [d for d in report["diagnostics"] if d["severity"] == "error"]
    assert "source-pdf-correctness" in report["coverage"]["unchecked"]


def test_negative_cursor_mismatched_duration_and_dangling_tie_are_located(tmp_path):
    path = score(
        tmp_path,
        """<backup><duration>2</duration></backup>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>3</duration><tie type="start"/><voice>1</voice><type>quarter</type><notations><tied type="start"/></notations></note>""",
    )
    report = validate_score(input_path=path)
    codes = {d["code"] for d in report["diagnostics"]}
    assert {"negative-cursor", "duration-notation-mismatch", "unclosed-tie"} <= codes
    assert report["status"] == "invalid"
    assert all(d["location"]["printedMeasure"] == "X1" for d in report["diagnostics"])


def test_compare_distinguishes_notation_and_sounding_without_double_octaves(tmp_path):
    from score_cli.compare import compare_scores

    path = score(tmp_path)
    before = path.read_text().replace(
        "</attributes>",
        "<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic><octave-change>-1</octave-change></transpose><clef><sign>G</sign><line>2</line><clef-octave-change>-1</clef-octave-change></clef></attributes>",
    )
    before = before.replace(
        "<note ext:",
        '<direction><direction-type><octave-shift type="down" size="8"/></direction-type></direction><note ext:',
    )
    path.write_text(before)
    other = tmp_path / "other.xml"
    other.write_text(before.replace("<step>C</step>", "<step>D</step>"))
    report = compare_scores(before_path=path, after_path=other)
    assert report["status"] == "different"
    diff = report["notationDifferences"][0]
    assert "pitch" in diff["fields"]
    assert report["soundingDifferences"][0]["before"] == "46"
    assert report["soundingDifferences"][0]["after"] == "48"
    other.write_text(before.replace("<voice>1</voice>", "<voice>2</voice>"))
    report = compare_scores(before_path=path, after_path=other)
    assert report["status"] == "inconclusive"
    assert report["unaligned"]


def test_tuplet_duration_is_rational_and_staff_reference_is_checked(tmp_path):
    path = score(
        tmp_path,
        """<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification><staff>9</staff></note>""",
    )
    path.write_text(
        path.read_text().replace("<divisions>2</divisions>", "<divisions>3</divisions>")
    )
    report = validate_score(input_path=path)
    codes = {d["code"] for d in report["diagnostics"]}
    assert "duration-notation-mismatch" not in codes
    assert "invalid-staff-reference" in codes


def test_notated_tie_numbers_must_pair_independently(tmp_path):
    path = score(
        tmp_path,
        """<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>quarter</type><tie type="start"/><notations><tied type="start" number="1"/></notations></note><note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>quarter</type><tie type="stop"/><notations><tied type="stop" number="2"/></notations></note>""",
    )
    codes = {d["code"] for d in validate_score(input_path=path)["diagnostics"]}
    assert {"unclosed-tied", "orphan-tied"} <= codes


def test_numbered_slur_can_cross_voice_without_false_dangling_error(tmp_path):
    path = score(
        tmp_path,
        """<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><notations><slur type="start" number="1"/></notations></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><voice>2</voice><type>quarter</type><notations><slur type="stop" number="1"/></notations></note>""",
    )
    diagnostics = validate_score(input_path=path)["diagnostics"]
    assert not [d for d in diagnostics if d["code"] in {"unclosed-slur", "orphan-slur"}]


def test_complete_measure_rest_uses_meter_not_whole_symbol(tmp_path):
    path = score(
        tmp_path,
        '<note><rest measure="yes"/><duration>6</duration><voice>1</voice><type>whole</type></note>',
    )
    path.write_text(path.read_text().replace("<beats>4</beats>", "<beats>3</beats>"))
    assert "duration-notation-mismatch" not in {
        d["code"] for d in validate_score(input_path=path)["diagnostics"]
    }
    path.write_text(path.read_text().replace(' measure="yes"', ""))
    assert "duration-notation-mismatch" in {
        d["code"] for d in validate_score(input_path=path)["diagnostics"]
    }


def test_slur_formatting_continue_at_endpoints_does_not_reopen_slur(tmp_path):
    def note(symbols):
        return (
            "<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><notations>"
            + symbols
            + "</notations></note>"
        )

    path = score(
        tmp_path,
        note('<slur type="start" number="1"/><slur type="continue" number="1"/>')
        + note('<slur type="continue" number="1"/>')
        + note('<slur type="continue" number="1"/><slur type="stop" number="1"/>'),
    )
    assert not [
        d for d in validate_score(input_path=path)["diagnostics"] if "slur" in d["code"]
    ]
    path.write_text(
        path.read_text()
        .replace('<slur type="start" number="1"/>', "")
        .replace('<slur type="stop" number="1"/>', "")
    )
    assert "orphan-slur" in {
        d["code"] for d in validate_score(input_path=path)["diagnostics"]
    }


def test_cross_staff_slur_pairs_in_score_time_not_xml_voice_order(tmp_path):
    path = score(
        tmp_path,
        """
<note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>
<note><pitch><step>D</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff><notations><slur type="stop" number="2"/></notations></note>
<backup><duration>4</duration></backup>
<note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><voice>2</voice><type>half</type><staff>2</staff><notations><slur type="start" number="2"/></notations></note>""",
    )
    path.write_text(path.read_text().replace("</time>", "</time><staves>2</staves>"))
    assert not [
        d for d in validate_score(input_path=path)["diagnostics"] if "slur" in d["code"]
    ]
    # An actually unmatched chronological stop must still fail.
    path.write_text(path.read_text().replace('<slur type="start" number="2"/>', ""))
    assert "orphan-slur" in {
        d["code"] for d in validate_score(input_path=path)["diagnostics"]
    }


def test_grace_slur_to_main_note_keeps_same_voice_source_order(tmp_path):
    path = score(
        tmp_path,
        '''<note><grace slash="yes"/><pitch><step>A</step><octave>3</octave></pitch><voice>1</voice><type>eighth</type><notations><slur type="start" number="2"/></notations></note>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><notations><slur type="stop" number="2"/></notations></note>''',
    )
    assert not [d for d in validate_score(input_path=path)["diagnostics"] if "slur" in d["code"]]
    path.write_text(path.read_text().replace('<slur type="start" number="2"/>', ''))
    assert "orphan-slur" in {d["code"] for d in validate_score(input_path=path)["diagnostics"]}


def test_slur_between_grace_notes_at_same_offset_keeps_note_order(tmp_path):
    path = score(
        tmp_path,
        '''<note><grace/><pitch><step>D</step><octave>4</octave></pitch><voice>1</voice><type>eighth</type><notations><slur type="start" number="1"/></notations></note>
<note><grace/><pitch><step>E</step><octave>4</octave></pitch><voice>1</voice><type>eighth</type><notations><slur type="stop" number="1"/></notations></note>
<note><pitch><step>F</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>''',
    )
    assert not [d for d in validate_score(input_path=path)["diagnostics"] if "slur" in d["code"]]


@pytest.mark.parametrize("voice,staff", [("2", "1"), ("1", "2")])
def test_same_time_cross_lane_grace_slur_does_not_guess_xml_order(tmp_path, voice, staff):
    path = score(
        tmp_path,
        '''<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><notations><slur type="stop" number="1"/></notations></note>
<backup><duration>2</duration></backup>
<note><grace/><pitch><step>D</step><octave>4</octave></pitch><voice>LANE_VOICE</voice><type>eighth</type><staff>LANE_STAFF</staff><notations><slur type="start" number="1"/></notations></note>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>LANE_VOICE</voice><type>quarter</type><staff>LANE_STAFF</staff></note>'''.replace('LANE_VOICE', voice).replace('LANE_STAFF', staff),
    )
    path.write_text(path.read_text().replace('</time>', '</time><staves>2</staves>'))
    codes = {d["code"] for d in validate_score(input_path=path)["diagnostics"]}
    assert {"orphan-slur", "unclosed-slur"} <= codes


def test_same_note_slur_stop_and_start_after_grace_still_close_then_open(tmp_path):
    path = score(
        tmp_path,
        '''<note><grace/><pitch><step>D</step><octave>4</octave></pitch><voice>1</voice><type>eighth</type><notations><slur type="start" number="1"/></notations></note>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><notations><slur type="start" number="1"/><slur type="stop" number="1"/></notations></note>
<note><pitch><step>F</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><notations><slur type="stop" number="1"/></notations></note>''',
    )
    assert not [d for d in validate_score(input_path=path)["diagnostics"] if "slur" in d["code"]]
