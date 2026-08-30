from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from score_cli.cli import main
from score_cli.inspect_measure import (
    MeasureInspectionError,
    inspect_printed_measure,
    outline_score,
)

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLE_SCORE = FIXTURES / "three-measures.musicxml"
COMPLEX_SCORE = FIXTURES / "complex-measure.musicxml"


def test_inspects_all_parts_with_inherited_context_and_lossless_elements() -> None:
    before = hashlib.sha256(COMPLEX_SCORE.read_bytes()).hexdigest()

    inspection = inspect_printed_measure(
        input_path=COMPLEX_SCORE,
        measure="X1",
        include_elements=True,
    )
    document = inspection.as_dict()

    assert set(document) == {"schemaVersion", "measure", "parts", "diagnostics"}
    assert document["schemaVersion"] == "1"
    assert document["measure"] == {"printedNumber": "X1"}
    assert [(part["partId"], part["partName"]) for part in document["parts"]] == [
        ("P1", "Choir")
    ]

    measure = document["parts"][0]["measure"]
    context = measure["context"]
    assert context["divisions"] == 2
    assert context["staves"] == 2
    assert context["attributes"]["key"]["1"]["fifths"] == -1
    assert context["attributes"]["time"]["1"]["beats"] == ["3"]
    assert set(context["attributes"]["clef"]) == {"1", "2"}

    events = measure["events"]
    assert [event["offset"] for event in events] == ["0", "0", "1/2", "0"]
    assert [event["duration"] for event in events] == ["1/2", "1/2", "1/2", "3"]
    assert events[0]["pitch"] == {"step": "F", "alter": "1", "octave": 4}
    assert events[0]["lyrics"][0]["text"] == "你"
    assert events[0]["ties"][0]["attributes"]["type"] == "start"
    assert [notation["name"] for notation in events[0]["notations"]] == [
        "tied",
        "slur",
        "articulations",
        "technical",
    ]
    assert events[1]["chord"] is True
    assert events[2]["kind"] == "rest"
    assert events[3]["voice"] == "2"
    assert events[3]["staff"] == 2

    assert measure["directions"][0]["text"] == "dolce"
    assert measure["directions"][0]["sound"]["attributes"]["tempo"] == "120"
    assert measure["harmonies"][0]["offset"] == "0"
    assert measure["barlines"][0]["barStyle"] == "light-heavy"
    assert measure["barlines"][0]["repeat"]["attributes"]["direction"] == "backward"
    assert [element["name"] for element in measure["elements"]] == [
        "print",
        "direction",
        "harmony",
        "note",
        "note",
        "note",
        "backup",
        "note",
        "grouping",
        "bookmark",
        "barline",
    ]
    bookmark = next(
        element for element in measure["elements"] if element["name"] == "bookmark"
    )
    assert bookmark["value"]["attributes"]["id"] == "inspection-bookmark"
    assert not _contains_key(document, "raw")
    serialized_document = json.dumps(document, ensure_ascii=False)
    assert "Complex inspection fixture" not in serialized_document
    assert "Example Composer" not in serialized_document
    assert "part-abbreviation" not in serialized_document
    assert "inputBytes" not in serialized_document
    assert "inputSha256" not in serialized_document
    assert hashlib.sha256(COMPLEX_SCORE.read_bytes()).hexdigest() == before

    serialized = json.loads(inspection.to_json())
    assert serialized == document
    assert "Measure X1" in inspection.to_text()
    assert "F#4 lyric 你" in inspection.to_text()


def test_inspects_compressed_musicxml(tmp_path: Path) -> None:
    input_path = tmp_path / "fixture.mxl"
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles>
</container>"""
    with ZipFile(input_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("score.musicxml", SIMPLE_SCORE.read_bytes())

    document = inspect_printed_measure(input_path=input_path, measure="X1").as_dict()

    assert set(document) == {"schemaVersion", "measure", "parts", "diagnostics"}
    assert document["measure"] == {"printedNumber": "X1"}
    assert [part["partId"] for part in document["parts"]] == ["P1", "P2"]


def test_default_inspection_omits_lossless_elements() -> None:
    document = inspect_printed_measure(
        input_path=COMPLEX_SCORE,
        measure="X1",
    ).as_dict()

    measure = document["parts"][0]["measure"]
    assert "elements" not in measure
    assert not _contains_key(measure["context"], "element")


def test_inspection_can_select_one_part() -> None:
    document = inspect_printed_measure(
        input_path=SIMPLE_SCORE,
        measure="X1",
        part="P2",
    ).as_dict()

    assert [part["partId"] for part in document["parts"]] == ["P2"]
    assert document["parts"][0]["measure"]["events"][0]["pitch"]["step"] == "B"

    with pytest.raises(MeasureInspectionError, match='Part "missing" was not found'):
        inspect_printed_measure(
            input_path=SIMPLE_SCORE,
            measure="X1",
            part="missing",
        )


def test_outlines_parts_and_ordered_measure_numbers() -> None:
    outline = outline_score(input_path=SIMPLE_SCORE)
    document = outline.as_dict()

    assert document == {
        "schemaVersion": "1",
        "parts": [
            {"partId": "P1", "partName": "Upper"},
            {"partId": "P2", "partName": "Lower"},
        ],
        "measureNumbers": ["1", "X1", "3"],
        "diagnostics": [],
    }
    assert json.loads(outline.to_json()) == document


def test_repeated_printed_number_in_one_sequence_is_ambiguous(tmp_path: Path) -> None:
    score = tmp_path / "repeated.musicxml"
    score.write_text(
        """<score-partwise version="4.0">
<part-list><score-part id="P1"><part-name>Part</part-name></score-part></part-list>
<part id="P1">
  <measure number="1"><attributes><divisions>1</divisions></attributes><note><rest/><duration>1</duration></note></measure>
  <measure number="1"><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note></measure>
</part></score-partwise>""",
        encoding="utf-8",
    )

    with pytest.raises(MeasureInspectionError, match="occurs 2 times"):
        inspect_printed_measure(input_path=score, measure="1")

    outline = outline_score(input_path=score).as_dict()
    assert outline["measureNumbers"] == ["1", "1"]
    assert [diagnostic["code"] for diagnostic in outline["diagnostics"]] == [
        "duplicate-measure-number"
    ]


def test_inspects_score_timewise(tmp_path: Path) -> None:
    score = tmp_path / "timewise.musicxml"
    score.write_text(
        """<score-timewise version="4.0">
<part-list><score-part id="P1"><part-name>Part</part-name></score-part></part-list>
<measure number="1"><part id="P1"><attributes><divisions>2</divisions><time><beats>2</beats><beat-type>4</beat-type></time></attributes><note><rest/><duration>4</duration></note></part></measure>
<measure number="2"><part id="P1"><note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration></note></part></measure>
</score-timewise>""",
        encoding="utf-8",
    )

    document = inspect_printed_measure(input_path=score, measure="2").as_dict()

    assert document["measure"] == {"printedNumber": "2"}
    measure = document["parts"][0]["measure"]
    assert measure["context"]["divisions"] == 2
    assert measure["events"][0]["duration"] == "1"
    assert measure["events"][0]["eventId"].startswith("P1:m2:")
    assert outline_score(input_path=score).as_dict()["measureNumbers"] == ["1", "2"]


def test_cli_outputs_json_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["inspect", str(SIMPLE_SCORE), "--measure", "X1"])

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["measure"]["printedNumber"] == "X1"
    assert all("elements" not in part["measure"] for part in document["parts"])


def test_cli_outlines_score_and_can_include_one_parts_elements(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["outline", str(SIMPLE_SCORE)]) == 0
    outline = json.loads(capsys.readouterr().out)
    assert outline["measureNumbers"] == ["1", "X1", "3"]

    assert (
        main(
            [
                "inspect",
                str(SIMPLE_SCORE),
                "--measure",
                "X1",
                "--part",
                "P1",
                "--include-elements",
            ]
        )
        == 0
    )
    inspection = json.loads(capsys.readouterr().out)
    assert [part["partId"] for part in inspection["parts"]] == ["P1"]
    assert "elements" in inspection["parts"][0]["measure"]


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key(child, key) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False
