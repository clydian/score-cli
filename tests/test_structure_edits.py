"""Structural repair through the public transaction boundary."""

import hashlib
from pathlib import Path

import pytest
from lxml import etree as ET

from score_cli.edit_score import edit_score, EditError

NOTE = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type></note>"
ATTR = "<attributes><divisions>1</divisions></attributes>"


@pytest.mark.parametrize("old,new,expected", [
    ('<part-abbreviation font-style="italic">Voice</part-abbreviation>', "S", "S"),
    ("", "S", "S"),
    ('<part-abbreviation>Voice</part-abbreviation>', None, None),
    ('<part-abbreviation>Voice</part-abbreviation>', "omitted", "Voice"),
])
def test_rename_part_abbreviation_replays_without_changing_music(tmp_path, old, new, expected):
    path = source(tmp_path)
    path.write_text(path.read_text().replace('</part-name>', '</part-name>'+old))
    before = ET.parse(str(path))
    serialize = lambda e: ET.tostring(e, encoding="unicode", with_tail=False)
    value = dict(id="P1", name="Soprano", instruments={})
    if new != "omitted":
        value["abbreviation"] = new
    operation = dict(id="name", type="rename-part", target={"partId":"P1"},
                     expected=[serialize(before.find("part-list/score-part")), serialize(before.find("part"))], value=value)
    preview = run(path, [operation], dry_run=True)
    report = run(path, [operation])
    after = ET.parse(str(tmp_path/"out.xml"))
    assert preview["outputSha256"] == report["outputSha256"]
    assert after.findtext("part-list/score-part/part-name") == "Soprano"
    assert after.findtext("part-list/score-part/part-abbreviation") == expected
    assert serialize(before.find("part")) == serialize(after.find("part"))
    if "font-style" in old:
        assert after.find("part-list/score-part/part-abbreviation").get("font-style") == "italic"


@pytest.mark.parametrize("abbreviation", ["", 1, {}, []])
def test_invalid_abbreviation_does_not_publish_partial_transaction(tmp_path, abbreviation):
    path = source(tmp_path)
    tree = ET.parse(str(path))
    serialize = lambda e: ET.tostring(e, encoding="unicode", with_tail=False)
    operation = dict(id="name", type="rename-part", target={"partId":"P1"},
                     expected=[serialize(tree.find("part-list/score-part")),serialize(tree.find("part"))],
                     value=dict(id="P1", name="Soprano", instruments={}, abbreviation=abbreviation))
    with pytest.raises(EditError):
        run(path, [operation])
    assert not (tmp_path/"out.xml").exists()
    assert not (tmp_path/"out.xml.edit.json").exists()


def test_abbreviation_display_override_is_not_silently_left_stale(tmp_path):
    path = source(tmp_path)
    path.write_text(path.read_text().replace('</part-name>', '</part-name><part-abbreviation-display><display-text>Voice</display-text></part-abbreviation-display>'))
    tree = ET.parse(str(path))
    serialize = lambda e: ET.tostring(e, encoding="unicode", with_tail=False)
    operation = dict(id="name", type="rename-part", target={"partId":"P1"},
                     expected=[serialize(tree.find("part-list/score-part")),serialize(tree.find("part"))],
                     value=dict(id="P1",name="Soprano",instruments={},abbreviation="S"))
    with pytest.raises(EditError,match="display override"):
        run(path,[operation])
    assert not (tmp_path/"out.xml").exists()


def source(tmp_path):
    path = tmp_path / "source.musicxml"
    path.write_text(
        '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="0" implicit="yes">'
        + ATTR
        + NOTE
        + '</measure><measure number="X1" implicit="yes">'
        + NOTE
        + "</measure></part></score-partwise>"
    )
    return path


def run(path, operations, *, dry_run=False, name="out.xml"):
    return edit_score(
        input_path=path,
        output_path=path.parent / name,
        dry_run=dry_run,
        changeset=dict(
            schemaVersion="2",
            inputSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            operations=operations,
        ),
    )


def locator():
    return dict(
        partId="P1", printedMeasure="0", staff="1", voice="1", offset="0", eventIndex=1
    )


def test_insert_event_reference_is_stable_and_dry_run_replays(tmp_path):
    path = source(tmp_path)
    operations = [
        dict(
            id="insert",
            type="insert-event",
            target=locator(),
            expected=[NOTE],
            value=NOTE,
            position="after",
            timeline="shift-following",
            inherit="effective-context",
            bind="new-note",
        ),
        dict(
            id="pitch",
            type="pitch",
            target={"ref": "new-note"},
            expected=dict(step="C", alter="0", octave=4, accidental=None),
            value=dict(step="D", alter="0", octave=4, accidental=None),
        ),
    ]
    preview = run(path, operations, dry_run=True)
    assert not (tmp_path / "out.xml").exists()
    report = run(path, operations)
    assert report["outputSha256"] == preview["outputSha256"]
    root = ET.parse(str(tmp_path / "out.xml"))
    assert root.xpath('//measure[@number="0"]/note/pitch/step/text()') == ["C", "D"]
    assert root.xpath('//measure[@number="X1"]/note/pitch/step/text()') == ["C"]
    assert report["structure"]["operations"][0]["operationId"] == "insert"


def test_delete_requires_each_discard_and_rejects_detached_later_target(tmp_path):
    path = source(tmp_path)
    delete = dict(
        id="delete",
        type="delete-event",
        target=locator(),
        expected=[NOTE],
        value=None,
        discard=[NOTE],
        timeline="shift-following",
    )
    with pytest.raises(EditError, match="discard"):
        run(path, [dict(delete, discard=[])])
    later = dict(
        id="later",
        type="pitch",
        target=locator(),
        expected=dict(step="C", alter="0", octave=4, accidental=None),
        value=dict(step="D", alter="0", octave=4, accidental=None),
    )
    with pytest.raises(EditError, match="removed"):
        run(path, [delete, later])
    assert not (tmp_path / "out.xml").exists()
    report = run(path, [delete])
    assert report["structure"]["operations"][0]["deleted"] == [NOTE]
    assert not ET.parse(str(tmp_path / "out.xml")).xpath('//measure[@number="0"]/note')


def test_replace_measure_lists_removed_semantics_and_preserves_unchanged_nodes(
    tmp_path,
):
    path = source(tmp_path)
    extra = '<direction><direction-type><words>dolce</words></direction-type></direction><harmony><root><root-step>C</root-step></root></harmony><sound tempo="80"/><barline location="right"><bar-style>light-light</bar-style></barline><unknown keep="yes"/>'
    path.write_text(path.read_text().replace(ATTR + NOTE, ATTR + NOTE + extra))
    old = '<measure number="0" implicit="yes">' + ATTR + NOTE + extra + "</measure>"
    new = old.replace(NOTE, NOTE.replace("<step>C", "<step>D"))
    operation = dict(
        id="replace",
        type="replace-measure",
        target={"partId": "P1", "printedMeasure": "0"},
        expected=[old],
        value=new,
        discard=[NOTE],
    )
    report = run(path, [operation])
    ledger = report["structure"]["operations"][0]
    assert ledger["deleted"] == [NOTE]
    assert any("dolce" in s for s in ledger["preserved"])
    assert extra in (tmp_path / "out.xml").read_text()
    with pytest.raises(EditError, match="discard"):
        run(path, [dict(operation, discard=[])], name="bad.xml")


def test_logical_measure_operations_are_atomic_across_parts_and_labels_are_strings(
    tmp_path,
):
    path = source(tmp_path)
    tree = ET.parse(str(path))
    import copy

    part = copy.deepcopy(tree.find("part"))
    part.set("id", "P2")
    tree.getroot().append(part)
    definition = copy.deepcopy(tree.find("part-list/score-part"))
    definition.set("id", "P2")
    tree.find("part-list").append(definition)
    path.write_bytes(ET.tostring(tree))
    old = '<measure number="0" implicit="yes">' + ATTR + NOTE + "</measure>"
    inserted = '<measure number="A" implicit="yes">' + NOTE + "</measure>"
    insert = dict(
        id="insert",
        type="insert-measure",
        target={"printedMeasure": "0"},
        expected=[old, old],
        position="after",
        inherit="effective-context",
        value={"P1": inserted, "P2": inserted},
    )
    report = run(path, [insert])
    out = ET.parse(str(tmp_path / "out.xml"))
    assert [p.xpath("measure/@number") for p in out.findall("part")] == [
        ["0", "A", "X1"],
        ["0", "A", "X1"],
    ]
    with pytest.raises(EditError):
        run(path, [dict(insert, value={"P1": inserted})], name="bad.xml")
    assert not (tmp_path / "bad.xml").exists()
    renumber = dict(
        id="numbers",
        type="renumber-measures",
        target={"printedMeasures": ["0", "X1"]},
        expected=[
            old,
            old,
            '<measure number="X1" implicit="yes">' + NOTE + "</measure>",
            '<measure number="X1" implicit="yes">' + NOTE + "</measure>",
        ],
        value={"0": "X1", "X1": "0"},
    )
    report = run(path, [renumber], name="renumber.xml")
    assert ET.parse(str(tmp_path / "renumber.xml")).find("part").xpath(
        "measure/@number"
    ) == ["X1", "0"]
    assert (
        report["structure"]["mapping"]["measures"][0]["after"]["printedMeasure"] == "X1"
    )
    with pytest.raises(EditError):
        run(path, [dict(renumber, value={"0": "X1", "X1": "X1"})], name="collision.xml")
    delete = dict(
        id="remove",
        type="delete-measure",
        target={"printedMeasure": "X1"},
        expected=['<measure number="X1" implicit="yes">' + NOTE + "</measure>"] * 2,
        value=None,
        discard=['<measure number="X1" implicit="yes">' + NOTE + "</measure>"] * 2,
    )
    run(path, [delete], name="delete.xml")
    assert [
        p.xpath("measure/@number")
        for p in ET.parse(str(tmp_path / "delete.xml")).findall("part")
    ] == [["0"], ["0"]]


def test_part_operations_keep_definitions_instruments_groups_and_order(tmp_path):
    path = source(tmp_path)
    definition = '<score-part id="P1"><part-name>Voice</part-name></score-part>'
    part_xml = ET.tostring(ET.parse(str(path)).find("part"), encoding="unicode")
    rename = dict(
        id="rename",
        type="rename-part",
        target={"partId": "P1"},
        expected=[definition, part_xml],
        value={"id": "Singer", "name": "Soprano", "instruments": {}},
    )
    report = run(path, [rename])
    out = ET.parse(str(tmp_path / "out.xml"))
    assert out.find("part").get("id") == "Singer"
    assert out.findtext("part-list/score-part/part-name") == "Soprano"
    new_definition = '<score-part id="P2"><part-name>Voice</part-name><score-instrument id="I2"><instrument-name>Voice</instrument-name></score-instrument><midi-instrument id="I2"><midi-channel>2</midi-channel></midi-instrument></score-part>'
    new_part = part_xml.replace('id="P1"', 'id="P2"')
    add = dict(
        id="add",
        type="add-part",
        target={"partId": "P1"},
        expected=[definition, part_xml],
        position="before",
        value={"definition": new_definition, "content": [new_part]},
    )
    run(path, [add], name="add.xml")
    added = tmp_path / "add.xml"
    assert ET.parse(str(added)).xpath("/score-partwise/part/@id") == ["P2", "P1"]
    part_list = "<part-list>" + new_definition + definition + "</part-list>"
    reordered = (
        '<part-list><part-group type="start" number="1"><group-symbol>brace</group-symbol></part-group>'
        + definition
        + new_definition
        + '<part-group type="stop" number="1"/></part-list>'
    )
    reorder = dict(
        id="order",
        type="reorder-parts",
        target={},
        expected=[part_list],
        value=reordered,
    )
    run(added, [reorder], name="order.xml")
    assert ET.parse(str(tmp_path / "order.xml")).xpath("/score-partwise/part/@id") == [
        "P1",
        "P2",
    ]
    delete = dict(
        id="delete",
        type="delete-part",
        target={"partId": "P2"},
        expected=[new_definition, new_part],
        value=None,
        discard=[new_definition, new_part],
    )
    run(added, [delete], name="remove-part.xml")
    assert ET.parse(str(tmp_path / "remove-part.xml")).xpath("//score-instrument") == []
    with pytest.raises(EditError):
        run(
            added,
            [dict(rename, value={"id": "P2", "name": "same", "instruments": {}})],
            name="bad-part.xml",
        )
    assert not (tmp_path / "bad-part.xml").exists()


def test_merge_requires_explicit_source_map_and_accounts_for_every_semantic(tmp_path):
    path = source(tmp_path)
    import copy

    tree = ET.parse(str(path))
    definition = copy.deepcopy(tree.find("part-list/score-part"))
    definition.set("id", "Fragment")
    tree.find("part-list").append(definition)
    body = copy.deepcopy(tree.find("part"))
    body.set("id", "Fragment")
    body.find("measure/note/pitch/step").text = "G"
    tree.getroot().append(body)
    path.write_bytes(ET.tostring(tree))
    original = path.read_bytes()
    to_xml = lambda e: ET.tostring(e, encoding="unicode", with_tail=False)
    expected = [
        to_xml(definition),
        to_xml(body),
        to_xml(tree.find("part-list/score-part")),
        to_xml(tree.find("part")),
    ]
    discarded = (
        [to_xml(definition)]
        + [to_xml(e) for e in body.findall("measure")[1]]
        + [to_xml(e) for e in tree.find("part/measure")]
    )
    merge = dict(
        id="merge",
        type="merge-part",
        target={"sourcePartId": "Fragment", "targetPartId": "P1"},
        expected=expected,
        value={
            "measures": {"0": "0"},
            "voices": {"1": "1"},
            "staves": {"1": "1"},
            "instruments": {},
            "destination": "replace",
            "sourceDisposition": "delete-part",
            "wrapperPolicy": "keep-target",
            "contextPolicy": "require-equal",
        },
        discard=discarded,
    )
    report = run(path, [merge])
    assert path.read_bytes() == original
    out = ET.parse(str(tmp_path / "out.xml"))
    assert out.xpath("/score-partwise/part/@id") == ["P1"]
    assert out.findtext("part/measure/note/pitch/step") == "G"
    assert report["structure"]["operations"][0]["moved"]
    with pytest.raises(EditError):
        run(path, [dict(merge, discard=discarded[:-1])], name="lost.xml")
    assert not (tmp_path / "lost.xml").exists()
    with pytest.raises(EditError):
        run(
            path,
            [dict(merge, value=dict(merge["value"], measures={"0": "0", "X1": "0"}))],
            name="ambiguous.xml",
        )


def test_dangling_instrument_and_empty_groups_block_publication(tmp_path):
    path = source(tmp_path)
    definition = '<score-part id="P1"><part-name>Voice</part-name></score-part>'
    body = ET.tostring(ET.parse(str(path)).find("part"), encoding="unicode")
    added_body = body.replace('id="P1"', 'id="P2"').replace(
        "<voice>", '<instrument id="MISSING"/><voice>'
    )
    operation = dict(
        id="add",
        type="add-part",
        target={"partId": "P1"},
        expected=[definition, body],
        position="after",
        value={"definition": definition.replace("P1", "P2"), "content": [added_body]},
    )
    with pytest.raises(EditError, match="instrument"):
        run(path, [operation])
    assert not (tmp_path / "out.xml").exists()
    group = (
        '<part-list><part-group type="start" number="1"/><part-group type="stop" number="1"/>'
        + definition
        + "</part-list>"
    )
    with pytest.raises(EditError, match="group"):
        run(
            path,
            [
                dict(
                    id="group",
                    type="reorder-parts",
                    target={},
                    expected=["<part-list>" + definition + "</part-list>"],
                    value=group,
                )
            ],
        )


def test_compare_maps_renumbering_and_reports_structural_additions(tmp_path):
    from score_cli.compare import compare_scores

    path = source(tmp_path)
    old = '<measure number="0" implicit="yes">' + ATTR + NOTE + "</measure>"
    report = run(
        path,
        [
            dict(
                id="renumber",
                type="renumber-measures",
                target={"printedMeasures": ["0"]},
                expected=[old],
                value={"0": "A"},
            )
        ],
    )
    comparison = compare_scores(
        before_path=path,
        after_path=tmp_path / "out.xml",
        mapping=report["structure"]["mapping"],
    )
    assert comparison["notationDifferences"] == []
    assert comparison["unaligned"] == []
    assert comparison["structureDifferences"]
    bad = {
        "measures": [
            {
                "before": {"partId": "P1", "printedMeasure": "0"},
                "after": {"partId": "P1", "printedMeasure": "X1"},
            }
        ]
    }
    with pytest.raises(EditError):
        compare_scores(before_path=path, after_path=tmp_path / "out.xml", mapping=bad)
    inserted = '<measure number="A" implicit="yes">' + NOTE + "</measure>"
    added = run(
        path,
        [
            dict(
                id="new",
                type="insert-measure",
                target={"printedMeasure": "0"},
                expected=[old],
                position="after",
                inherit="effective-context",
                value={"P1": inserted},
            )
        ],
        name="added.xml",
    )
    comparison = compare_scores(
        before_path=path,
        after_path=tmp_path / "added.xml",
        mapping=added["structure"]["mapping"],
    )
    assert comparison["added"][0]["location"] == {"partId": "P1", "printedMeasure": "A"}
    assert not comparison["notationDifferences"]
    assert added["comparison"]["added"][0]["location"]["printedMeasure"] == "A"


def test_calibration_mapping_invalidates_verified_and_does_not_reuse_numbers(tmp_path):
    from score_cli.calibration import (
        create_calibration,
        update_record,
        calibration_status,
    )

    path = source(tmp_path)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF synthetic test")
    evidence = tmp_path / "proof.txt"
    evidence.write_text("Synthetic test evidence")
    record = create_calibration(
        input_path=path,
        source_pdf=pdf,
        targets=[dict(id="r", partId="P1", printedMeasure="0", checks=["pitch"])],
    )
    record = update_record(
        record,
        record_id="r",
        state="verified",
        input_path=path,
        source_pdf=pdf,
        reviewer="test",
        conclusion="test only",
        source_location={"page": 1, "system": 1, "measures": ["0"]},
        evidence=[evidence],
    )
    old = '<measure number="0" implicit="yes">' + ATTR + NOTE + "</measure>"
    other = '<measure number="X1" implicit="yes">' + NOTE + "</measure>"
    report = run(
        path,
        [
            dict(
                id="swap",
                type="renumber-measures",
                target={"printedMeasures": ["0", "X1"]},
                expected=[old, other],
                value={"0": "X1", "X1": "0"},
            )
        ],
    )
    status = calibration_status(
        record, input_path=tmp_path / "out.xml", source_pdf=pdf, edit_report=report
    )
    assert status["records"][0]["printedMeasure"] == "X1"
    assert status["records"][0]["state"] == "needs-review"
    assert "structure-mapped" in status["records"][0]["invalidationReasons"]
    with pytest.raises(EditError):
        calibration_status(record, input_path=path, source_pdf=pdf, edit_report=report)


@pytest.mark.parametrize("timewise", [False, True])
def test_created_measure_and_nested_event_can_be_referenced_without_indices(
    tmp_path, timewise
):
    path = source(tmp_path)
    if timewise:
        tree = ET.parse(str(path))
        root = tree.getroot()
        part = root.find("part")
        root.remove(part)
        root.tag = "score-timewise"
        for measure in part:
            wrapper = ET.SubElement(root, "measure", dict(measure.attrib))
            body = ET.SubElement(wrapper, "part", id="P1")
            body.extend(list(measure))
        path.write_bytes(ET.tostring(tree))
    old = ET.tostring(
        ET.parse(str(path)).find("measure" if timewise else "part/measure"),
        encoding="unicode",
    )
    new_note = NOTE.replace("<note>", '<note id="N-new">')
    new = (
        '<measure number="A" implicit="yes">'
        + ('<part id="P1">' if timewise else "")
        + new_note
        + ("</part>" if timewise else "")
        + "</measure>"
    )
    insert = dict(
        id="insert",
        type="insert-measure",
        target={"printedMeasure": "0"},
        expected=[old],
        position="after",
        inherit="effective-context",
        value=new if timewise else {"P1": new},
        bind="new-measure",
        bindings={"new-event": "N-new"},
    )
    pitch = dict(
        id="change",
        type="pitch",
        target={"ref": "new-event"},
        expected=dict(step="C", alter="0", octave=4, accidental=None),
        value=dict(step="E", alter="0", octave=4, accidental=None),
    )
    run(path, [insert, pitch])
    assert ET.parse(str(tmp_path / "out.xml")).xpath(
        '//note[@id="N-new"]/pitch/step/text()'
    ) == ["E"]
    bad = dict(pitch, target={"ref": "not-created"})
    with pytest.raises(EditError):
        run(path, [bad, insert], name="bad-reference.xml")


def test_renumbering_preserves_existing_diagnostic_identity(tmp_path):
    path = source(tmp_path)
    path.write_text(
        path.read_text().replace(
            ATTR,
            ATTR
            + "<attributes><time><beats>1</beats><beat-type>8</beat-type></time></attributes>",
        )
    )
    old = ET.tostring(ET.parse(str(path)).find("part/measure"), encoding="unicode")
    report = run(
        path,
        [
            dict(
                id="number",
                type="renumber-measures",
                target={"printedMeasures": ["0"]},
                expected=[old],
                value={"0": "A"},
            )
        ],
    )
    assert any(
        d["code"] == "measure-overflow"
        and d["origin"] == "existing"
        and d["location"]["printedMeasure"] == "A"
        for d in report["diagnosticsAfter"]
    )


def test_insert_into_empty_measure_with_explicit_edge_anchor(tmp_path):
    path = source(tmp_path)
    path.write_text(path.read_text().replace(ATTR + NOTE, ATTR))
    old = '<measure number="0" implicit="yes">' + ATTR + "</measure>"
    run(
        path,
        [
            dict(
                id="fill",
                type="insert-event",
                target={"partId": "P1", "printedMeasure": "0"},
                expected=[old],
                value=NOTE,
                position="end",
                timeline="shift-following",
                inherit="effective-context",
            )
        ],
    )
    assert (
        ET.parse(str(tmp_path / "out.xml")).findtext("part/measure/note/pitch/step")
        == "C"
    )


def test_namespaced_add_part_and_comment_deletion_are_lossless(tmp_path):
    path = source(tmp_path)
    path.write_text(
        path.read_text()
        .replace("<score-partwise ", '<score-partwise xmlns="urn:musicxml" ')
        .replace(NOTE, NOTE + "<!--retain-->")
    )
    tree = ET.parse(str(path))
    ns = {"m": "urn:musicxml"}
    definition = ET.tostring(
        tree.find("m:part-list/m:score-part", ns), encoding="unicode"
    )
    body = ET.tostring(tree.find("m:part", ns), encoding="unicode")
    run(
        path,
        [
            dict(
                id="add",
                type="add-part",
                target={"partId": "P1"},
                expected=[definition, body],
                position="after",
                value={
                    "definition": definition.replace("P1", "P2"),
                    "content": [body.replace("P1", "P2")],
                },
            )
        ],
    )
    assert len(ET.parse(str(tmp_path / "out.xml")).findall("m:part", ns)) == 2
    assert (tmp_path / "out.xml").read_text().count("<!--retain-->") == 4


def test_real_audiveris_fragment_replays_and_matches_source_checked_melody(tmp_path):
    import json

    fixture = Path(__file__).parent / "fixtures/structure/cantate-fragments.musicxml"
    changes = json.loads(fixture.with_name("cantate-merge.changes.json").read_text())
    output = tmp_path / "merged.musicxml"
    report = edit_score(input_path=fixture, changeset=changes, output_path=output)
    tree = ET.parse(str(output))
    assert tree.xpath("/score-partwise/part/@id") == ["P1"]
    # Independently transcribed from source PDF page 1, system 1, Soprano I.
    expected = [
        [("A", "4", "4"), ("A", "4", "4"), ("A", "4", "4")],
        [("A", "4", "6"), ("A", "4", "2"), ("B", "4", "4")],
        [("C", "5", "6"), ("C", "5", "2"), ("D", "5", "4")],
        [("B", "4", "12")],
        [("B", "4", "8"), ("C", "5", "4")],
        [("C", "5", "4"), ("D", "5", "4"), ("E", "5", "4")],
        [("E", "5", "4"), ("F", "5", "4"), ("F", "5", "4")],
        [("F", "5", "6"), ("E", "5", "2"), ("D", "5", "4")],
    ]
    actual = [
        [
            (
                n.findtext("pitch/step"),
                n.findtext("pitch/octave"),
                n.findtext("duration"),
            )
            for n in m.findall("note")
        ]
        for m in tree.findall("part/measure")[:8]
    ]
    assert actual == expected
    assert not [d for d in report["diagnosticsAfter"] if d["origin"] != "existing"]
    assert [d["code"] for d in report["diagnosticsAfter"]] == ["incomplete-voice"]
    proof = Path(__file__).parents[1] / "docs/evidence/issue-2/after.musicxml"
    assert report["outputSha256"] == hashlib.sha256(proof.read_bytes()).hexdigest()


def test_deleted_measure_direction_cannot_be_edited_later(tmp_path):
    path = source(tmp_path)
    direction = "<direction><direction-type><dynamics><p/></dynamics></direction-type></direction>"
    path.write_text(
        path.read_text()
        .replace(ATTR, ATTR + direction)
        .replace(
            '<measure number="X1" implicit="yes">',
            '<measure number="X1" implicit="yes">' + ATTR,
        )
    )
    old = ET.tostring(ET.parse(str(path)).find("part/measure"), encoding="unicode")
    delete = dict(
        id="remove",
        type="delete-measure",
        target={"printedMeasure": "0"},
        expected=[old],
        value=None,
        discard=[old],
    )
    dynamics = dict(
        id="dynamics",
        type="dynamics",
        target=dict(
            partId="P1",
            printedMeasure="0",
            staff="1",
            voice="",
            offset="0",
            directionIndex=1,
        ),
        expected="p",
        value="f",
    )
    with pytest.raises(EditError) as error:
        run(path, [delete, dynamics])
    assert error.value.diagnostic["code"] == "detached-target"
    assert error.value.diagnostic["operationId"] == "dynamics"
    assert not (tmp_path / "out.xml").exists()


def test_merge_cannot_silently_drop_source_part_level_content(tmp_path):
    import json

    fixture = Path(__file__).parent / "fixtures/structure/cantate-fragments.musicxml"
    path = tmp_path / "source.musicxml"
    path.write_text(
        fixture.read_text().replace(
            '<part id="P6">',
            '<part id="P6"><!--source-proof--><?proof retain?><extension origin="audiveris"/>',
        )
    )
    operation = json.loads(fixture.with_name("cantate-merge.changes.json").read_text())[
        "operations"
    ][0]
    operation["expected"][1] = ET.tostring(
        ET.parse(str(path)).find('part[@id="P6"]'), encoding="unicode", with_tail=False
    )
    with pytest.raises(EditError) as error:
        run(path, [operation])
    assert error.value.diagnostic["code"] == "undeclared-semantic-deletion"
    assert not (tmp_path / "out.xml").exists()
    operation["discard"] += [
        "<!--source-proof-->",
        "<?proof retain?>",
        '<extension origin="audiveris"/>',
    ]
    report = run(path, [operation])
    assert "<!--source-proof-->" in report["structure"]["operations"][0]["deleted"]


def test_new_reference_kinds_cannot_cross_part_and_measure_operations(tmp_path):
    path = source(tmp_path)
    definition = ET.tostring(
        ET.parse(str(path)).find("part-list/score-part"), encoding="unicode"
    )
    body = ET.tostring(ET.parse(str(path)).find("part"), encoding="unicode")
    new_definition, new_body = definition.replace("P1", "P2"), body.replace("P1", "P2")
    add = dict(
        id="add",
        type="add-part",
        target={"partId": "P1"},
        expected=[definition, body],
        value={"definition": new_definition, "content": [new_body]},
        position="after",
        bind="new-part",
    )
    wrong = dict(
        id="wrong",
        type="delete-measure",
        target={"ref": "new-part"},
        expected=[new_definition, new_body],
        value=None,
        discard=[new_definition, new_body],
    )
    with pytest.raises(EditError) as error:
        run(path, [add, wrong])
    assert error.value.diagnostic["code"] == "reference-kind"
    assert not (tmp_path / "out.xml").exists()
    report = run(path, [add, dict(wrong, type="delete-part")])
    assert ET.parse(str(tmp_path / "out.xml")).xpath("/score-partwise/part/@id") == [
        "P1"
    ]
