"""Real Verovio controls and public render/CLI compatibility warnings."""
from pathlib import Path
import copy
from hashlib import sha256
import json
import re

from lxml import etree
import pytest
import verovio

from score_cli.render_input import prepare_render_input
from score_cli.render_measure import render_printed_measure, render_range


FIXTURE = Path(__file__).parent / "fixtures/render/direction-bracket.musicxml"
WARNING = "verovio-sloped-direction-bracket-risk"


def test_real_verovio_loses_positioned_bracket_and_warning_preserves_xml():
    xml = FIXTURE.read_text()
    toolkit = verovio.toolkit()
    assert toolkit.loadData(xml)
    mei = etree.fromstring(toolkit.getMEI().encode())
    svg = etree.fromstring(toolkit.renderToSVG(1).encode())
    # Import retains the span's time, but loses its staff and endpoint heights.
    span, = mei.findall(".//{*}bracketSpan")
    assert span.get("tstamp") == "3"
    assert span.get("tstamp2") == "0m+4"
    assert span.get("staff") is None
    group, = svg.xpath('//*[contains(@class, "bracketSpan")]')
    assert len(group) == 0  # Missing even in the original, uncropped page SVG.

    prepared = prepare_render_input(xml)
    assert prepared.xml == xml
    warning, = prepared.compatibility["warnings"]
    assert warning["code"] == WARNING
    assert (warning["partId"], warning["printedMeasure"],
            warning["measureOrdinal"], warning["staff"]) == ("Piano", "X2", 1, "2")
    assert "independent renderer" in warning["message"]
    assert "source XML" in warning["message"]


@pytest.mark.parametrize("sloped", [False, True])
def test_first_staff_horizontal_line_draws_but_sloped_line_is_flattened(sloped):
    root = etree.parse(str(FIXTURE)).getroot()
    lead, piano = root.findall("part")
    root.remove(piano)
    root.find("part-list").remove(root.find("part-list/score-part[@id='Piano']"))
    measure = lead.find("measure")
    note = measure.find("note")
    note.find("duration").text = "24"
    note.find("type").text = "half"
    measure.append(copy.deepcopy(note))
    for index, direction in enumerate(piano.findall("measure/direction")):
        measure.insert(index + 1, direction)
        direction.find("staff").text = "1"
        direction.find("offset").text = str(index * 24)
        bracket = direction.find("direction-type/bracket")
        bracket.set("default-y", "-30" if sloped and index else "30")
    xml = etree.tostring(root).decode()
    toolkit = verovio.toolkit()
    assert toolkit.loadData(xml)
    svg = etree.fromstring(toolkit.renderToSVG(1).encode())
    path, = svg.xpath('//*[contains(@class, "bracketSpan")]/*[local-name()="path"]')
    coordinates = re.fullmatch(r"M([\d.-]+) ([\d.-]+) L([\d.-]+) ([\d.-]+)", path.get("d"))
    assert coordinates is not None
    assert coordinates[1] != coordinates[3]
    assert coordinates[2] == coordinates[4]  # Actual Verovio line is horizontal.
    prepared = prepare_render_input(xml)
    assert bool(prepared.compatibility["warnings"]) == sloped
    assert prepared.xml == xml


@pytest.mark.parametrize("mode", ["measure", "range"])
def test_actual_render_and_cli_report_position_risk_without_changing_source(tmp_path, capsys, mode):
    from score_cli.cli import main

    source = tmp_path / "score.musicxml"
    source.write_bytes(FIXTURE.read_bytes())
    before = source.read_bytes()
    if mode == "measure":
        result = render_printed_measure(input_path=source, measure="X2", output_path=tmp_path / "one.png")
        report = result.render_input_compatibility
        args = ["--measure", "X2", "--output", str(tmp_path / "cli.png")]
    else:
        result = render_range(input_path=source, start="X2", output_directory=tmp_path / "range")
        report = result["renderInputCompatibility"]
        args = ["--from-measure", "X2", "--output", str(tmp_path / "cli-range")]
    warning, = report["warnings"]
    assert (warning["code"], warning["partId"], warning["printedMeasure"], warning["staff"]) == (
        WARNING, "Piano", "X2", "2")
    assert main(["render", str(source), *args]) == 0
    captured = capsys.readouterr()
    assert f"Warning [{WARNING}] part Piano, measure X2 (ordinal 1)" in captured.err
    assert "independent renderer" in captured.err
    if mode == "measure":
        assert "Rendered measure" in captured.out
    else:
        assert json.loads(captured.out)["inputSha256"] == sha256(before).hexdigest()
    assert source.read_bytes() == before


def test_namespaced_cross_measure_pair_retains_both_source_locations():
    root = etree.parse(str(FIXTURE)).getroot()
    piano = root.findall("part")[1]
    first = piano.find("measure")
    stop = first.findall("direction")[1]
    first.remove(stop)
    last = etree.SubElement(piano, "measure", number="End")
    last.append(stop)
    for node in root.iter():
        node.tag = "{urn:owned:musicxml}" + node.tag
    xml = etree.tostring(root).decode()
    prepared = prepare_render_input(xml)
    warning, = prepared.compatibility["warnings"]
    assert (warning["printedMeasure"], warning["measureOrdinal"],
            warning["endPrintedMeasure"], warning["endMeasureOrdinal"],
            warning["bracketNumber"]) == ("X2", 1, "End", 2, "7")
    assert prepared.xml == xml


def test_positive_integer_lexical_variants_identify_the_same_staff_and_number():
    root = etree.parse(str(FIXTURE)).getroot()
    start, stop = root.findall("part")[1].findall("measure/direction")
    start.find("staff").text = " \t02\n"
    start.find("direction-type/bracket").set("number", "  +07 ")
    stop.find("staff").text = "2"
    stop.find("direction-type/bracket").set("number", "7")
    xml = etree.tostring(root).decode()
    prepared = prepare_render_input(xml)
    warning, = prepared.compatibility["warnings"]
    assert (warning["staff"], warning["bracketNumber"]) == ("2", "7")
    assert prepared.xml == xml


@pytest.mark.parametrize("foreign", ["part", "measure", "direction", "direction-type", "bracket"])
@pytest.mark.parametrize("namespace", ["", "urn:owned:musicxml"])
def test_foreign_namespace_extensions_are_not_musicxml_brackets(foreign, namespace):
    root = etree.parse(str(FIXTURE)).getroot()
    piano = root.findall("part")[1]
    targets = [piano] if foreign == "part" else piano.findall(f".//{foreign}")
    if namespace:
        for node in root.iter():
            node.tag = f"{{{namespace}}}" + node.tag
    for node in targets:
        node.tag = "{urn:foreign:extension}" + foreign
    xml = etree.tostring(root).decode()
    prepared = prepare_render_input(xml)
    assert not [w for w in prepared.compatibility["warnings"] if w["code"] == WARNING]
    assert prepared.xml == xml


@pytest.mark.parametrize("control", ["no-bracket", "no-height", "equal-height", "relative-cancels", "other-staff", "other-part"])
def test_unproven_or_horizontal_spans_are_not_reported(control):
    root = etree.parse(str(FIXTURE)).getroot()
    lead, piano = root.findall("part")
    first, stop = piano.findall("measure/direction")
    bracket = stop.find("direction-type/bracket")
    if control == "no-bracket":
        for direction in (first, stop):
            direction.getparent().remove(direction)
    elif control == "no-height":
        bracket.attrib.pop("default-y")
    elif control == "equal-height":
        bracket.set("default-y", "15.00")
    elif control == "relative-cancels":
        bracket.set("relative-y", "62.5")
    elif control == "other-staff":
        stop.find("staff").text = "1"
    else:
        piano.find("measure").remove(stop)
        lead.find("measure").append(stop)
    xml = etree.tostring(root).decode()
    prepared = prepare_render_input(xml)
    assert prepared.compatibility["warnings"] == []
    assert prepared.xml == xml


def test_reused_bracket_number_does_not_pair_unrelated_endpoints():
    root = etree.parse(str(FIXTURE)).getroot()
    measure = root.findall("part")[1].find("measure")
    start, stop = measure.findall("direction")
    stop.find("direction-type/bracket").set("default-y", "15")
    later_start, later_stop = copy.deepcopy(start), copy.deepcopy(stop)
    for index, direction in enumerate((later_start, later_stop), 3):
        direction.find("direction-type/bracket").set("default-y", "-47.5")
        measure.insert(index, direction)
    for direction, offset in zip(measure.findall("direction"), (0, 12, 24, 36)):
        direction.find("offset").text = str(offset)
    assert prepare_render_input(etree.tostring(root).decode()).compatibility["warnings"] == []


@pytest.mark.parametrize("kind, expected", [("horizontal", 0), ("sloped", 1)])
def test_reverse_document_order_pairs_stop_with_its_own_start(kind, expected):
    xml = (FIXTURE.parent / f"bracket-reversed-{kind}.musicxml").read_text()
    toolkit = verovio.toolkit()
    assert toolkit.loadData(xml)
    prepared = prepare_render_input(xml)
    assert len(prepared.compatibility["warnings"]) == expected
    assert prepared.xml == xml


def test_number_reuse_follows_document_order_even_when_score_times_overlap():
    root = etree.parse(str(FIXTURE)).getroot()
    measure = root.findall("part")[1].find("measure")
    start, stop = measure.findall("direction")
    stop.find("direction-type/bracket").set("default-y", "15")
    later_start, later_stop = copy.deepcopy(start), copy.deepcopy(stop)
    for index, direction in enumerate((later_start, later_stop), 3):
        direction.find("direction-type/bracket").set("default-y", "-47.5")
        measure.insert(index, direction)
    # A is q2–3, B q1–4: same staff/number, nonoverlapping in document order.
    for direction, offset in zip(measure.findall("direction"), (24, 36, 12, 48)):
        direction.find("offset").text = str(offset)
    xml = etree.tostring(root).decode()
    toolkit = verovio.toolkit()
    assert toolkit.loadData(xml)
    assert prepare_render_input(xml).compatibility["warnings"] == []


def test_repeat_endings_are_not_direction_brackets():
    xml = (FIXTURE.parents[1] / "volta-crop.musicxml").read_text()
    assert etree.fromstring(xml.encode()).findall(".//{*}ending")
    prepared = prepare_render_input(xml)
    assert not [w for w in prepared.compatibility["warnings"] if w["code"] == WARNING]
    assert prepared.xml == xml
