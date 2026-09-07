import json
from score_cli.cli import main
from test_edit_score import score, changes, pitch_operation


def test_cli_edit_validate_compare_and_structured_failure(tmp_path, capsys):
    source = score(tmp_path)
    change = tmp_path / "changes.json"
    change.write_text(json.dumps(changes(source, [pitch_operation()])))
    output = tmp_path / "fixed.xml"
    assert (
        main(
            [
                "edit",
                str(source),
                "--changes",
                str(change),
                "--output",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    assert not output.exists()
    assert (
        main(["edit", str(source), "--changes", str(change), "--output", str(output)])
        == 0
    )
    capsys.readouterr()
    assert main(["validate", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["coverage"]["checked"]
    assert main(["compare", str(source), str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "different"
    assert (
        main(["edit", str(source), "--changes", str(change), "--output", str(output)])
        == 1
    )
    assert (
        json.loads(capsys.readouterr().err)["diagnostics"][0]["code"]
        == "output-conflict"
    )
