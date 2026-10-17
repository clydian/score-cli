"""Ties follow exact musical endpoints, with conservative cross-voice matching."""

import hashlib

import pytest
from lxml import etree as ET

from score_cli.edit_score import edit_score
from score_cli.validation import validate_score


def note(voice, kind, pitch="A", number="1", duration=2, staff=1):
    endpoint = f'<tie type="{kind}"/>' if kind else ""
    notation = (
        f'<notations><tied type="{kind}" number="{number}"/></notations>'
        if kind
        else ""
    )
    return (
        f"<note><pitch><step>{pitch}</step><octave>3</octave></pitch>"
        f"<duration>{duration}</duration>{endpoint}<voice>{voice}</voice>"
        f"<type>{'half' if duration == 6 else 'quarter'}</type>"
        f"{'<dot/>' if duration == 6 else ''}<staff>{staff}</staff>{notation}</note>"
    )


def write_score(tmp_path, measures, *, beats=1, parts=None):
    parts = parts or {"P1": measures}
    definitions = "".join(
        f'<score-part id="{p}"><part-name>Voice</part-name></score-part>' for p in parts
    )
    content = ""
    for pid, ms in parts.items():
        content += f'<part id="{pid}">'
        for i, body in enumerate(ms, 1):
            attrs = (
                (
                    f"<attributes><divisions>2</divisions><staves>2</staves>"
                    f"<time><beats>{beats}</beats><beat-type>4</beat-type></time></attributes>"
                )
                if i == 1
                else ""
            )
            content += f'<measure number="{i}">{attrs}{body}</measure>'
        content += "</part>"
    path = tmp_path / "input.musicxml"
    path.write_text(
        f'<score-partwise version="4.0"><part-list>{definitions}</part-list>{content}</score-partwise>'
    )
    return path


def tie_diagnostics(path):
    return [
        d for d in validate_score(input_path=path)["diagnostics"] if "tie" in d["code"]
    ]


def test_crossvoice_contiguous_tie_is_valid(tmp_path):
    path = write_score(
        tmp_path,
        [note("2", "start", duration=6), note("1", "stop", duration=6)],
        beats=3,
    )
    assert not tie_diagnostics(path)


def test_crossvoice_start_and_stop_are_matched_in_score_time_not_xml_order(tmp_path):
    body = (
        "<forward><duration>2</duration><voice>1</voice></forward>"
        + note("1", "stop")
        + "<backup><duration>4</duration></backup>"
        + note("2", "start")
        + "<forward><duration>2</duration><voice>2</voice></forward>"
    )
    path = write_score(tmp_path, [body], beats=2)
    assert not tie_diagnostics(path)


def test_exact_voice_wins_before_unique_crossvoice_candidate(tmp_path):
    start = (
        note("1", "start")
        + "<backup><duration>2</duration></backup>"
        + note("2", "start")
    )
    stop = (
        note("3", "stop")
        + "<backup><duration>2</duration></backup>"
        + note("1", "stop")
    )
    path = write_score(tmp_path, [start, stop])
    assert not tie_diagnostics(path)


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_unison_crossvoice_starts_are_ambiguous_in_either_xml_order(
    tmp_path, reverse
):
    voices = ["1", "2"] if not reverse else ["2", "1"]
    start = (
        note(voices[0], "start")
        + "<backup><duration>2</duration></backup>"
        + note(voices[1], "start")
    )
    path = write_score(tmp_path, [start, note("3", "stop")])
    codes = {d["code"] for d in tie_diagnostics(path)}
    assert {"ambiguous-tie", "ambiguous-tied", "unclosed-tie", "unclosed-tied"} <= codes


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_unison_crossvoice_stops_do_not_consume_first_in_xml_order(
    tmp_path, reverse
):
    voices = ["2", "3"] if not reverse else ["3", "2"]
    stop = (
        note(voices[0], "stop")
        + "<backup><duration>2</duration></backup>"
        + note(voices[1], "stop")
    )
    path = write_score(tmp_path, [note("1", "start"), stop])
    diagnostics = tie_diagnostics(path)
    assert len([d for d in diagnostics if d["code"] == "ambiguous-tie"]) == 2
    assert len([d for d in diagnostics if d["code"] == "ambiguous-tied"]) == 2


@pytest.mark.parametrize("field", ["pitch", "number", "time", "part"])
def test_crossvoice_fallback_does_not_join_incompatible_endpoints(tmp_path, field):
    start, stop = note("1", "start"), note("2", "stop")
    if field == "pitch":
        stop = note("2", "stop", pitch="B")
    if field == "number":
        stop = note("2", "stop", number="2")
    if field == "time":
        start += "<note><rest/><duration>2</duration><voice>1</voice><type>quarter</type></note>"
    if field == "part":
        path = write_score(tmp_path, [], parts={"P1": [start], "P2": [stop]})
    else:
        path = write_score(tmp_path, [start, stop], beats=2 if field == "time" else 1)
    codes = {d["code"] for d in tie_diagnostics(path)}
    assert {"orphan-tied", "unclosed-tied"} <= codes
    if field != "number":
        assert {"orphan-tie", "unclosed-tie"} <= codes


def test_unique_crossvoice_tie_can_change_staff_within_the_part(tmp_path):
    path = write_score(
        tmp_path, [note("left", "start", staff=2), note("right", "stop", staff=1)]
    )
    assert not tie_diagnostics(path)


def test_same_voice_nonadjacent_tie_still_reports_time_error(tmp_path):
    path = write_score(
        tmp_path,
        [
            note("1", "start")
            + "<note><rest/><duration>2</duration><voice>1</voice><type>quarter</type></note>",
            note("1", "stop"),
        ],
        beats=2,
    )
    assert "nonadjacent-tie" in {d["code"] for d in tie_diagnostics(path)}


def test_hash_bound_common_chord_edit_preserves_real_crossvoice_tie(tmp_path):
    start = note("2", "start", duration=6)
    end = (
        note("1", "", pitch="B", duration=6)
        + "<backup><duration>6</duration></backup>"
        + note("2", "stop", duration=6)
    )
    path = write_score(tmp_path, [start, end], beats=3)
    tree = ET.parse(str(path))
    old = tree.find("part/measure[@number='2']")
    new = ET.fromstring(ET.tostring(old))
    upper, lower = new.findall("note")
    lower.find("voice").text = "1"
    lower.insert(0, ET.Element("chord"))
    new.remove(new.find("backup"))
    output = tmp_path / "edited.musicxml"
    xml = lambda e: ET.tostring(e, encoding="unicode", with_tail=False)
    report = edit_score(
        input_path=path,
        changeset={
            "schemaVersion": "2",
            "inputSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "operations": [
                {
                    "id": "common-stem",
                    "type": "replace-measure",
                    "target": {"partId": "P1", "printedMeasure": "2"},
                    "expected": [xml(old)],
                    "value": xml(new),
                    "discard": [xml(old.find("backup")), xml(old.findall("note")[1])],
                }
            ],
        },
        output_path=output,
    )
    assert report["status"] == "applied"
    assert not tie_diagnostics(output)
    assert (
        ET.parse(str(output)).find("part/measure[@number='2']/note/chord") is not None
    )


def test_parallel_unisons_keep_each_exact_voice_even_when_xml_order_reverses(tmp_path):
    start = (
        note("1", "start")
        + "<backup><duration>2</duration></backup>"
        + note("2", "start")
    )
    stop = (
        note("2", "stop")
        + "<backup><duration>2</duration></backup>"
        + note("1", "stop")
    )
    path = write_score(tmp_path, [start, stop])
    assert not tie_diagnostics(path)


def test_zero_duration_grace_endpoints_keep_legacy_part_behavior(tmp_path):
    grace = (
        "<note><grace/><pitch><step>A</step><octave>3</octave></pitch>"
        '<tie type="start"/><voice>1</voice><type>eighth</type>'
        '<notations><tied type="start" number="1"/></notations></note>'
    )
    path = write_score(tmp_path, [grace + note("1", "stop")])
    assert not tie_diagnostics(path)


def test_duplicate_same_voice_unisons_remain_errors(tmp_path):
    start = (
        note("1", "start")
        + "<backup><duration>2</duration></backup>"
        + note("1", "start")
    )
    path = write_score(tmp_path, [start, note("1", "stop")])
    codes = {d["code"] for d in tie_diagnostics(path)}
    assert {
        "duplicate-tie-start",
        "duplicate-tied-start",
        "ambiguous-tie",
        "ambiguous-tied",
    } <= codes


def test_unpitched_display_position_is_not_a_known_crossvoice_tie_pitch(tmp_path):
    start, stop = note("1", "start"), note("2", "stop")
    pitched = "<pitch><step>A</step><octave>3</octave></pitch>"
    unpitched = "<unpitched><display-step>A</display-step><display-octave>3</display-octave></unpitched>"
    path = write_score(
        tmp_path, [start.replace(pitched, unpitched), stop.replace(pitched, unpitched)]
    )
    codes = {d["code"] for d in validate_score(input_path=path)["diagnostics"]}
    assert {
        "unsupported-unpitched-sound",
        "orphan-tie",
        "orphan-tied",
        "unclosed-tie",
        "unclosed-tied",
    } <= codes
