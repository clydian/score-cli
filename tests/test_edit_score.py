"""Safe edit transactions through the public file interface."""

import hashlib
import json
from pathlib import Path

import pytest

from score_cli.edit_score import EditError, edit_score
from score_cli.inspect_measure import inspect_printed_measure


def score(tmp_path, notes=None):
    path = tmp_path / "input.musicxml"
    path.write_text(
        """<?xml version="1.0"?>
<!--before--><?proof keep?>
<score-partwise version="4.0" xmlns:ext="urn:proof">
<part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
<part id="P1"><measure number="X1" implicit="yes">
<attributes><divisions>2</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
"""
        + (
            notes
            or """<note ext:flag="keep"><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1</staff><lyric number="1"><text>Old</text></lyric></note>"""
        )
        + """
<!--inside--><ext:unknown ext:value="keep"/><direction><direction-type><words>keep me</words></direction-type></direction>
</measure></part></score-partwise><!--after-->"""
    )
    return path


def target(index=1, offset="0", **kwargs):
    return dict(
        partId="P1",
        printedMeasure="X1",
        staff="1",
        voice="1",
        offset=offset,
        eventIndex=index,
        **kwargs,
    )


def changes(path, operations):
    return {
        "schemaVersion": "1",
        "inputSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "operations": operations,
    }


def pitch_operation():
    return dict(
        id="pitch",
        type="pitch",
        target=target(),
        expected={"step": "C", "alter": "0", "octave": 4, "accidental": None},
        value={"step": "D", "alter": "0", "octave": 4, "accidental": None},
    )


def test_pitch_dry_run_replay_and_complete_xml_preservation(tmp_path):
    source = score(tmp_path)
    original = source.read_bytes()
    change = changes(source, [pitch_operation()])
    output = tmp_path / "fixed.musicxml"
    preview = edit_score(
        input_path=source, changeset=change, output_path=output, dry_run=True
    )
    assert preview["status"] == "dry-run"
    assert not output.exists()
    result = edit_score(input_path=source, changeset=change, output_path=output)
    assert source.read_bytes() == original
    assert result["outputSha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(Path(str(output) + ".edit.json").read_text()) == result
    assert (
        inspect_printed_measure(input_path=output, measure="X1").as_dict()["parts"][0][
            "measure"
        ]["events"][0]["pitch"]["step"]
        == "D"
    )
    xml = output.read_text()
    for kept in [
        "<!--before-->",
        "<?proof keep?>",
        "<!--inside-->",
        "<!--after-->",
        'ext:flag="keep"',
        '<ext:unknown ext:value="keep"/>',
        "keep me",
    ]:
        assert kept in xml
    replay = edit_score(
        input_path=source, changeset=change, output_path=tmp_path / "replay.xml"
    )
    assert result["outputSha256"] == replay["outputSha256"] == preview["outputSha256"]


def test_sequential_lyrics_and_mid_transaction_failure_leave_no_products(tmp_path):
    source = score(tmp_path)
    lyric = dict(
        id="lyric",
        type="lyric",
        target=target(),
        selector={"number": "1"},
        expected={"text": "Old", "syllabic": None},
        value={"text": "New", "syllabic": "single"},
    )
    bad_pitch = pitch_operation()
    bad_pitch["expected"]["step"] = "F"
    with pytest.raises(EditError) as error:
        edit_score(
            input_path=source,
            changeset=changes(source, [lyric, bad_pitch]),
            output_path=tmp_path / "failed.xml",
        )
    assert error.value.diagnostic["code"] == "old-value-mismatch"
    assert error.value.diagnostic["operationId"] == "pitch"
    assert not (tmp_path / "failed.xml").exists()
    assert not (tmp_path / "failed.xml.edit.json").exists()
    second = dict(lyric, id="again", expected=lyric["value"], value=None)
    report = edit_score(
        input_path=source,
        changeset=changes(source, [lyric, second]),
        output_path=tmp_path / "done.xml",
    )
    assert "<lyric" not in (tmp_path / "done.xml").read_text()
    assert report["status"] == "applied"


@pytest.mark.parametrize("problem", ["stale", "output", "ambiguous", "locator"])
def test_snapshot_and_destination_conflicts_fail_closed(tmp_path, problem):
    source = score(tmp_path)
    output = tmp_path / "fixed.xml"
    operation = pitch_operation()
    if problem == "ambiguous":
        source.write_text(
            source.read_text().replace("</part>", '<measure number="X1"/></part>')
        )
    change = changes(source, [operation])
    if problem == "stale":
        source.write_text(source.read_text() + "\n")
    if problem == "output":
        output.write_text("keep")
    if problem == "locator":
        operation["target"]["voice"] = "2"
    with pytest.raises(EditError):
        edit_score(input_path=source, changeset=change, output_path=output)
    assert not Path(str(output) + ".edit.json").exists()
    if problem == "output":
        assert output.read_text() == "keep"


def test_duration_updates_notation_and_original_snapshot_targets(tmp_path):
    source = score(
        tmp_path,
        """<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note><note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>""",
    )
    source.write_text(
        source.read_text().replace(
            "<direction><direction-type><words>keep me</words></direction-type></direction>",
            "",
        )
    )
    operation = dict(
        id="duration",
        type="duration",
        target=target(),
        expected={
            "duration": "1",
            "type": "quarter",
            "dots": 0,
            "timeModification": None,
        },
        value={"duration": "2", "type": "half", "dots": 0, "timeModification": None},
        timeline="shift-following",
    )
    second = pitch_operation()
    second["target"] = target(2, "1")
    output = tmp_path / "duration.xml"
    report = edit_score(
        input_path=source,
        changeset=changes(source, [operation, second]),
        output_path=output,
    )
    events = inspect_printed_measure(input_path=output, measure="X1").as_dict()[
        "parts"
    ][0]["measure"]["events"]
    assert events[0]["duration"] == "2"
    assert events[1]["offset"] == "2"
    assert events[1]["pitch"]["step"] == "D"
    assert report["comparison"]["notationDifferences"]
    assert (
        report["diagnosticMatching"] == "exact-code-severity-location-reason-multiset"
    )


def test_edit_that_introduces_timeline_error_is_atomic(tmp_path):
    source = score(tmp_path)
    op = dict(
        id="duration",
        type="duration",
        target=target(),
        expected={
            "duration": "1",
            "type": "quarter",
            "dots": 0,
            "timeModification": None,
        },
        value={"duration": "8", "type": "breve", "dots": 0, "timeModification": None},
        timeline="shift-following",
    )
    with pytest.raises(EditError) as error:
        edit_score(
            input_path=source,
            changeset=changes(source, [op]),
            output_path=tmp_path / "overflow.xml",
        )
    assert error.value.diagnostic["code"] == "introduced-diagnostic"
    assert not (tmp_path / "overflow.xml").exists()


@pytest.mark.parametrize(
    ("kind", "expected", "value", "check"),
    [
        ("voice", "1", "2", "<voice>2</voice>"),
        ("staff", "1", "2", "<staff>2</staff>"),
        (
            "kind",
            {
                "kind": "note",
                "pitch": {"step": "C", "alter": "0", "octave": 4, "accidental": None},
            },
            {"kind": "rest", "pitch": None},
            "<rest/>",
        ),
    ],
)
def test_voice_staff_and_note_rest_edits_preserve_duration(
    tmp_path, kind, expected, value, check
):
    source = score(tmp_path)
    source.write_text(source.read_text().replace("<time>", "<staves>2</staves><time>"))
    operation = dict(
        id="change", type=kind, target=target(), expected=expected, value=value
    )
    output = tmp_path / "converted.xml"
    edit_score(
        input_path=source, changeset=changes(source, [operation]), output_path=output
    )
    assert check in output.read_text()
    assert "<duration>2</duration>" in output.read_text()


@pytest.mark.parametrize("family", ["tie", "slur"])
def test_pair_operations_create_and_remove_both_endpoints(tmp_path, family):
    source = score(
        tmp_path,
        """<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note><note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>""",
    )
    operation = dict(
        id="pair",
        type=family,
        start=target(),
        end=target(2, "1"),
        number="1",
        expected=False,
        value=True,
    )
    output = tmp_path / "paired.xml"
    report = edit_score(
        input_path=source, changeset=changes(source, [operation]), output_path=output
    )
    assert not [d for d in report["diagnosticsAfter"] if d["severity"] == "error"]
    assert 'type="start"' in output.read_text() and 'type="stop"' in output.read_text()
    removal = dict(operation, id="remove", expected=True, value=False)
    edit_score(
        input_path=output,
        changeset=changes(output, [removal]),
        output_path=tmp_path / "unpaired.xml",
    )
    assert 'type="start"' not in (tmp_path / "unpaired.xml").read_text()


def test_dynamics_and_cross_measure_wedge_use_direction_locators(tmp_path):
    source = score(tmp_path)
    source.write_text(
        source.read_text().replace(
            "</part>",
            '<measure number="0" implicit="yes"><note><rest/><duration>2</duration><type>quarter</type></note></measure></part>',
        )
    )
    start = dict(
        partId="P1",
        printedMeasure="X1",
        staff="1",
        voice="1",
        offset="0",
        directionIndex=0,
    )
    end = dict(start, printedMeasure="0")
    operations = [
        dict(id="dynamic", type="dynamics", target=start, expected=None, value="p"),
        dict(
            id="wedge",
            type="wedge",
            start=start,
            end=end,
            number="1",
            expected=False,
            value="crescendo",
        ),
    ]
    output = tmp_path / "directions.xml"
    result = edit_score(
        input_path=source, changeset=changes(source, operations), output_path=output
    )
    assert "<p/>" in output.read_text()
    assert 'type="crescendo"' in output.read_text()
    assert not [d for d in result["diagnosticsAfter"] if d["severity"] == "error"]
    assert "keep me" in output.read_text()


@pytest.mark.parametrize("format", ["timewise", "namespace", "mxl"])
def test_complete_document_formats_preserve_unknown_nodes(tmp_path, format):
    from zipfile import ZipFile

    source = score(tmp_path)
    xml = source.read_text()
    if format == "timewise":
        xml = (
            xml.replace("score-partwise", "score-timewise")
            .replace(
                '<part id="P1"><measure number="X1" implicit="yes">',
                '<measure number="X1" implicit="yes"><part id="P1">',
            )
            .replace("</measure></part>", "</part></measure>")
        )
    elif format == "namespace":
        xml = xml.replace(
            "<score-partwise ",
            '<score-partwise xmlns="http://www.musicxml.org/ns/musicxml" ',
        )
    elif format == "mxl":
        source = tmp_path / "input.mxl"
        with ZipFile(source, "w") as z:
            z.writestr(
                "META-INF/container.xml",
                '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>',
            )
            z.writestr("score.xml", xml)
    if format != "mxl":
        source.write_text(xml)
    output = tmp_path / "fixed.xml"
    edit_score(
        input_path=source,
        changeset=changes(source, [pitch_operation()]),
        output_path=output,
    )
    assert "<?proof keep?>" in output.read_text()
    assert "ext:unknown" in output.read_text()
    if format == "timewise":
        assert "<score-timewise" in output.read_text()
    assert (
        inspect_printed_measure(input_path=output, measure="X1").as_dict()["parts"][0][
            "measure"
        ]["events"][0]["pitch"]["step"]
        == "D"
    )


def test_mxl_attachments_and_external_entities_are_rejected(tmp_path):
    from zipfile import ZipFile

    source = score(tmp_path)
    compressed = tmp_path / "score.mxl"
    with ZipFile(compressed, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>',
        )
        z.writestr("score.xml", source.read_bytes())
        z.writestr("image.png", b"attachment")
    with pytest.raises(EditError, match="attachments"):
        edit_score(
            input_path=compressed,
            changeset=changes(compressed, [pitch_operation()]),
            output_path=tmp_path / "no.xml",
        )


def test_invalid_changeset_reports_operation_instead_of_raw_exception(tmp_path):
    source = score(tmp_path)
    op = pitch_operation()
    op["value"]["alter"] = "not a number"
    with pytest.raises(EditError) as exc:
        edit_score(
            input_path=source,
            changeset=changes(source, [op]),
            output_path=tmp_path / "no.xml",
        )
    assert exc.value.diagnostic["operationId"] == "pitch"


def test_duration_cannot_silently_move_an_unrelated_voice(tmp_path):
    source = score(
        tmp_path,
        """<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note><backup><duration>2</duration></backup><note><rest/><duration>2</duration><voice>2</voice><type>quarter</type></note>""",
    )
    op = dict(
        id="duration",
        type="duration",
        target=target(),
        expected={
            "duration": "1",
            "type": "quarter",
            "dots": 0,
            "timeModification": None,
        },
        value={"duration": "2", "type": "half", "dots": 0, "timeModification": None},
        timeline="shift-following",
    )
    with pytest.raises(EditError):
        edit_score(
            input_path=source,
            changeset=changes(source, [op]),
            output_path=tmp_path / "shifted.xml",
        )
    assert not (tmp_path / "shifted.xml").exists()


def test_duration_cannot_silently_retime_existing_directions(tmp_path):
    source = score(tmp_path)
    op = dict(
        id="duration",
        type="duration",
        target=target(),
        expected={
            "duration": "1",
            "type": "quarter",
            "dots": 0,
            "timeModification": None,
        },
        value={"duration": "2", "type": "half", "dots": 0, "timeModification": None},
        timeline="shift-following",
    )
    with pytest.raises(EditError, match="direction"):
        edit_score(
            input_path=source,
            changeset=changes(source, [op]),
            output_path=tmp_path / "retimed.xml",
        )


def test_extension_named_note_is_not_a_musicxml_event(tmp_path):
    source = score(tmp_path)
    source.write_text(
        source.read_text().replace(
            '<ext:unknown ext:value="keep"/>',
            "<ext:note><ext:duration>not-music</ext:duration></ext:note>",
        )
    )
    output = tmp_path / "extension.xml"
    edit_score(
        input_path=source,
        changeset=changes(source, [pitch_operation()]),
        output_path=output,
    )
    assert "<ext:duration>not-music</ext:duration>" in output.read_text()


def test_display_accidental_cannot_contradict_pitch(tmp_path):
    source = score(tmp_path)
    op = pitch_operation()
    op["value"]["accidental"] = "sharp"
    with pytest.raises(EditError):
        edit_score(
            input_path=source,
            changeset=changes(source, [op]),
            output_path=tmp_path / "wrong.xml",
        )
