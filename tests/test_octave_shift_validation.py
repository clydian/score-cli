"""Locate incomplete ottava spans without changing sounding pitch or excerpts."""

import pytest

from score_cli.validation import validate_score


def direction(kind, *, staff=1, number=1, offset=0, voice=""):
    return (
        f'<direction><direction-type><octave-shift type="{kind}" number="{number}"/>'
        f'</direction-type><offset>{offset}</offset>'
        + (f"<voice>{voice}</voice>" if voice else "")
        + f"<staff>{staff}</staff></direction>"
    )


def validate(tmp_path, body, *, second_part=""):
    path = tmp_path / "ottava.musicxml"
    path.write_text(
        '<score-partwise version="4.0"><part-list><score-part id="P">'
        '<part-name>Piano</part-name></score-part>'
        + ('<score-part id="Q"><part-name>Other</part-name></score-part>' if second_part else "")
        + '</part-list><part id="P"><measure number="46"><attributes>'
        '<divisions>2</divisions><time><beats>4</beats><beat-type>4</beat-type></time>'
        '<staves>2</staves></attributes>'
        + body
        + '</measure></part>'
        + (f'<part id="Q"><measure number="46">{second_part}</measure></part>' if second_part else "")
        + '</score-partwise>'
    )
    original = path.read_bytes()
    result = validate_score(input_path=path)
    assert path.read_bytes() == original
    return result, [d for d in result["diagnostics"] if d["code"] != "octave-shift-display-only" and "octave-shift" in d["code"]]


@pytest.mark.parametrize("kind", ["up", "down"])
def test_unclosed_ottava_reports_start_location_as_warning(tmp_path, kind):
    result, diagnostics = validate(tmp_path, direction(kind))
    assert result["status"] == "valid-within-coverage"
    assert [(d["code"], d["severity"]) for d in diagnostics] == [("unclosed-octave-shift", "warning")]
    assert diagnostics[0]["location"] == dict(partId="P", printedMeasure="46", measureOrdinal=1, directionIndex=1, staff="1")


def test_stop_without_start_can_be_an_excerpt_and_does_not_fail_validation(tmp_path):
    result, diagnostics = validate(tmp_path, direction("stop"))
    assert result["status"] == "valid-within-coverage"
    assert [(d["code"], d["severity"]) for d in diagnostics] == [("orphan-octave-shift", "warning")]


def test_closed_span_can_cross_voice_and_measure(tmp_path):
    _, diagnostics = validate(tmp_path, direction("down", voice="1") + '<forward><duration>8</duration></forward></measure><measure number="47">' + direction("continue") + direction("stop", voice="2", offset=2))
    assert diagnostics == []


def test_pairs_follow_score_time_not_serialized_voice_order(tmp_path):
    # A later stop can appear in XML before an earlier start in another voice.
    _, diagnostics = validate(tmp_path, direction("stop", offset=4) + direction("down", voice="2", offset=0))
    assert diagnostics == []


def test_simultaneous_stop_then_restart_and_endpoint_continue_are_valid(tmp_path):
    _, diagnostics = validate(tmp_path, direction("down") + direction("down", offset=2) + direction("continue", offset=2) + direction("stop", offset=2) + direction("stop", offset=4))
    assert diagnostics == []


@pytest.mark.parametrize("mismatch", [dict(staff=2), dict(number=2)])
def test_staff_and_number_do_not_close_another_span(tmp_path, mismatch):
    _, diagnostics = validate(tmp_path, direction("down") + direction("stop", offset=2, **mismatch))
    assert {d["code"] for d in diagnostics} == {"orphan-octave-shift", "unclosed-octave-shift"}


@pytest.mark.parametrize("equivalent", [dict(staff="01"), dict(number="01")])
def test_numeric_lexical_variants_pair_without_rewriting_input(tmp_path, equivalent):
    _, diagnostics = validate(tmp_path, direction("down", **equivalent) + direction("stop", offset=2))
    assert diagnostics == []


def test_part_does_not_close_another_part_span(tmp_path):
    _, diagnostics = validate(tmp_path, direction("down"), second_part=direction("stop"))
    assert {d["code"] for d in diagnostics} == {"orphan-octave-shift", "unclosed-octave-shift"}


def test_duplicate_start_and_orphan_continue_are_visible(tmp_path):
    _, diagnostics = validate(tmp_path, direction("continue") + direction("down", offset=1) + direction("up", offset=2) + direction("stop", offset=3))
    assert {d["code"] for d in diagnostics} == {"orphan-octave-shift", "duplicate-octave-shift-start"}
