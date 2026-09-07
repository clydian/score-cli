import pytest
from score_cli.calibration import create_calibration, update_record, calibration_status
from score_cli.score_document import ScoreError
from test_edit_score import score


def test_verified_requires_evidence_and_invalidates_on_score_or_evidence_change(
    tmp_path,
):
    source = score(tmp_path)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic test source")
    image = tmp_path / "crop.png"
    image.write_bytes(b"synthetic evidence bytes")
    record = create_calibration(
        input_path=source,
        source_pdf=pdf,
        targets=[
            dict(id="m1", partId="P1", printedMeasure="X1", checks=["pitch:first-note"])
        ],
    )
    with pytest.raises(ScoreError):
        update_record(
            record,
            record_id="m1",
            state="verified",
            input_path=source,
            source_pdf=pdf,
            reviewer="Test reviewer",
            conclusion="Checked",
            source_location={"page": 1, "system": 1, "measures": ["X1"]},
            evidence=[],
        )
    verified = update_record(
        record,
        record_id="m1",
        state="verified",
        input_path=source,
        source_pdf=pdf,
        reviewer="Test reviewer",
        conclusion="First note pitch checked only",
        source_location={"page": 1, "system": 1, "measures": ["X1"]},
        evidence=[image],
    )
    assert (
        calibration_status(verified, input_path=source, source_pdf=pdf)["counts"][
            "verified"
        ]
        == 1
    )
    image.write_bytes(b"changed evidence")
    stale = calibration_status(verified, input_path=source, source_pdf=pdf)
    assert stale["counts"]["verified"] == 0
    assert stale["counts"]["needs-review"] == 1
    assert stale["missingEvidence"]
    source.write_text(source.read_text() + "\n")
    assert (
        calibration_status(verified, input_path=source, source_pdf=pdf)["records"][0][
            "state"
        ]
        == "needs-review"
    )
