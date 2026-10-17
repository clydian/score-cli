"""Exact review of legal partial-voice warnings at the public transaction seam."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from score_cli.edit_score import EditError, edit_score


ATTRIBUTES = "<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
WHOLE = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>"
PARTIAL = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>3</duration><voice>1</voice><type>half</type><dot/></note><backup><duration>3</duration></backup><note><pitch><step>G</step><octave>3</octave></pitch><duration>4</duration><voice>2</voice><type>whole</type></note>"


def transaction(tmp_path, *, after=PARTIAL):
    source = tmp_path / "input.musicxml"
    before = '<measure number="25">' + ATTRIBUTES + WHOLE + "</measure>"
    source.write_text(
        '<score-partwise version="4.0"><part-list><score-part id="P5"><part-name>Piano</part-name></score-part></part-list><part id="P5">'
        + '<measure number="24">'
        + ATTRIBUTES
        + WHOLE
        + "</measure>"
        + before
        + "</part></score-partwise>"
    )
    changes = dict(
        schemaVersion="2",
        inputSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        operations=[
            dict(
                id="source-piano-m25",
                type="replace-measure",
                target=dict(partId="P5", printedMeasure="25"),
                expected=[before],
                value='<measure number="25">' + ATTRIBUTES + after + "</measure>",
                discard=[WHOLE],
            )
        ],
    )
    return source, changes


def rejected_review(source, changes, output):
    with pytest.raises(EditError) as caught:
        edit_score(input_path=source, changeset=changes, output_path=output)
    assert caught.value.diagnostic["code"] == "introduced-diagnostic"
    assert not output.exists()
    assert not Path(str(output) + ".edit.json").exists()
    return caught.value.diagnostic["warningReview"]


def acknowledge(changes, review):
    changes["acknowledgedWarnings"] = dict(
        outputSha256=review["outputSha256"],
        entries=[
            dict(
                diagnostic=d,
                rationale="Original PDF p4 system1: shared final lower note; no missing performed rest.",
            )
            for d in review["diagnostics"]
        ],
    )


def test_partial_voice_is_blocked_until_exact_review_then_replays_without_filler(
    tmp_path,
):
    source, changes = transaction(tmp_path)
    original = source.read_bytes()
    review = rejected_review(source, changes, tmp_path / "unreviewed.xml")
    assert len(review["diagnostics"]) == 1
    diagnostic = review["diagnostics"][0]
    assert diagnostic == dict(
        code="incomplete-voice",
        severity="warning",
        location=dict(partId="P5", printedMeasure="25", measureOrdinal=2, voice="1"),
        reason="Voice ends at 3, before meter 4; may be intentional incomplete notation.",
    )
    acknowledge(changes, review)
    output = tmp_path / "reviewed.xml"
    dry = edit_score(
        input_path=source, changeset=changes, output_path=output, dry_run=True
    )
    assert not output.exists()
    report = edit_score(input_path=source, changeset=changes, output_path=output)
    assert source.read_bytes() == original
    assert report["outputSha256"] == dry["outputSha256"] == review["outputSha256"]
    assert report["warningAcknowledgments"] == changes["acknowledgedWarnings"]
    assert report["diagnosticsAfter"][0]["severity"] == "warning"
    assert report["diagnosticsAfter"][0]["origin"] == "new-or-unmatched"
    assert "<rest" not in output.read_text()
    assert output.read_text().count("<note>") == 3
    assert json.loads(Path(str(output) + ".edit.json").read_text()) == report


@pytest.mark.parametrize(
    "field,value",
    [
        ("reason", "Other gap"),
        (
            "location",
            dict(partId="P5", printedMeasure="26", measureOrdinal=2, voice="1"),
        ),
        ("code", "voice-gap"),
    ],
)
def test_changed_warning_cannot_reuse_a_review(tmp_path, field, value):
    source, changes = transaction(tmp_path)
    review = rejected_review(source, changes, tmp_path / "unreviewed.xml")
    acknowledge(changes, review)
    changes["acknowledgedWarnings"]["entries"][0]["diagnostic"][field] = value
    with pytest.raises(EditError) as caught:
        edit_score(
            input_path=source, changeset=changes, output_path=tmp_path / "no.xml"
        )
    assert caught.value.diagnostic["code"] == "introduced-diagnostic"
    assert not (tmp_path / "no.xml").exists()


@pytest.mark.parametrize(
    "change",
    [
        "output-hash",
        "duplicate",
        "rationale",
        "error-severity",
        "unknown-entry",
        "unknown-diagnostic",
        "v1",
    ],
)
def test_acknowledgment_contract_fails_closed(tmp_path, change):
    source, changes = transaction(tmp_path)
    review = rejected_review(source, changes, tmp_path / "unreviewed.xml")
    acknowledge(changes, review)
    ack = changes["acknowledgedWarnings"]
    if change == "output-hash":
        ack["outputSha256"] = "0" * 64
    if change == "duplicate":
        ack["entries"].append(deepcopy(ack["entries"][0]))
    if change == "rationale":
        ack["entries"][0]["rationale"] = "   "
    if change == "error-severity":
        ack["entries"][0]["diagnostic"]["severity"] = "error"
    if change == "unknown-entry":
        ack["entries"][0]["allowAll"] = True
    if change == "unknown-diagnostic":
        ack["entries"][0]["diagnostic"]["allLocations"] = True
    if change == "v1":
        changes["schemaVersion"] = "1"
    with pytest.raises(EditError):
        edit_score(
            input_path=source, changeset=changes, output_path=tmp_path / "no.xml"
        )
    assert not (tmp_path / "no.xml").exists()
    assert not (tmp_path / "no.xml.edit.json").exists()


def test_old_review_cannot_authorize_changed_output_or_changed_input(tmp_path):
    source, changes = transaction(tmp_path)
    review = rejected_review(source, changes, tmp_path / "unreviewed.xml")
    acknowledge(changes, review)
    # Same warning, different musical payload. Input remains the same snapshot.
    changes["operations"][0]["value"] = changes["operations"][0]["value"].replace(
        "<step>G</step>", "<step>A</step>"
    )
    with pytest.raises(EditError) as caught:
        edit_score(
            input_path=source, changeset=changes, output_path=tmp_path / "changed.xml"
        )
    assert caught.value.diagnostic["code"] == "stale-warning-acknowledgment"
    source.write_text(source.read_text() + "\n")
    with pytest.raises(EditError) as caught:
        edit_score(
            input_path=source, changeset=changes, output_path=tmp_path / "stale.xml"
        )
    assert caught.value.diagnostic["code"] == "stale-input"


def test_error_remains_blocking_even_with_a_previous_exact_warning_review(tmp_path):
    source, changes = transaction(tmp_path)
    review = rejected_review(source, changes, tmp_path / "unreviewed.xml")
    acknowledge(changes, review)
    # The warning still matches, but voice 2 now has contradictory duration notation.
    changes["operations"][0]["value"] = changes["operations"][0]["value"].replace(
        "<type>whole</type>", "<type>half</type>"
    )
    with pytest.raises(EditError) as caught:
        edit_score(
            input_path=source, changeset=changes, output_path=tmp_path / "error.xml"
        )
    assert caught.value.diagnostic["code"] == "introduced-diagnostic"
    assert "duration-notation-mismatch" in caught.value.diagnostic["reason"]
    assert "warningReview" not in caught.value.diagnostic
    assert not (tmp_path / "error.xml").exists()


def test_one_review_cannot_hide_an_additional_new_warning(tmp_path):
    extra = "<backup><duration>4</duration></backup><note><pitch><step>E</step><octave>3</octave></pitch><duration>2</duration><voice>3</voice><type>half</type></note>"
    source, changes = transaction(tmp_path, after=PARTIAL + extra)
    review = rejected_review(source, changes, tmp_path / "unreviewed.xml")
    assert len(review["diagnostics"]) == 2
    acknowledge(changes, review)
    changes["acknowledgedWarnings"]["entries"].pop()
    with pytest.raises(EditError) as caught:
        edit_score(
            input_path=source, changeset=changes, output_path=tmp_path / "missing.xml"
        )
    assert caught.value.diagnostic["code"] == "introduced-diagnostic"
    assert not (tmp_path / "missing.xml").exists()


def test_acknowledging_an_existing_warning_is_rejected_as_unused(tmp_path):
    source, changes = transaction(tmp_path)
    review = rejected_review(source, changes, tmp_path / "unreviewed.xml")
    acknowledge(changes, review)
    output = tmp_path / "partial.xml"
    report = edit_score(input_path=source, changeset=changes, output_path=output)
    # A no-op replay against the new snapshot has only an existing warning.
    measure = changes["operations"][0]["value"]
    again = dict(
        schemaVersion="2",
        inputSha256=report["outputSha256"],
        operations=[
            dict(
                id="unchanged",
                type="replace-measure",
                target=dict(partId="P5", printedMeasure="25"),
                expected=[measure],
                value=measure,
                discard=[],
            )
        ],
    )
    dry = edit_score(
        input_path=output,
        changeset=again,
        output_path=tmp_path / "dry.xml",
        dry_run=True,
    )
    again["acknowledgedWarnings"] = deepcopy(changes["acknowledgedWarnings"])
    again["acknowledgedWarnings"]["outputSha256"] = dry["outputSha256"]
    with pytest.raises(EditError) as caught:
        edit_score(
            input_path=output, changeset=again, output_path=tmp_path / "unused.xml"
        )
    assert caught.value.diagnostic["code"] == "unused-warning-acknowledgment"
    assert not (tmp_path / "unused.xml").exists()


def test_cli_rejection_exposes_review_without_publishing_a_score(tmp_path, capsys):
    from score_cli.cli import main

    source, changes = transaction(tmp_path)
    changes_path = tmp_path / "changes.json"
    changes_path.write_text(json.dumps(changes))
    output = tmp_path / "blocked.xml"
    assert (
        main(
            [
                "edit",
                str(source),
                "--changes",
                str(changes_path),
                "--output",
                str(output),
                "--dry-run",
            ]
        )
        == 1
    )
    result = capsys.readouterr()
    assert not result.out
    failure = json.loads(result.err)
    assert failure["status"] == "failed"
    review = failure["diagnostics"][0]["warningReview"]
    assert len(review["outputSha256"]) == 64
    assert review["diagnostics"][0]["severity"] == "warning"
    assert not output.exists()
    assert not Path(str(output) + ".edit.json").exists()
