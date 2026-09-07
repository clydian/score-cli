"""Version-bound, explicitly scoped human/source review evidence."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .score_document import ScoreDocument, ScoreError, sha256
from .structure_mapping import mapping_rows, location_key

STATES = ("unreviewed", "needs-fix", "needs-review", "verified")


def _file(path):
    path = Path(path)
    return dict(path=str(path.resolve()), sha256=sha256(path.read_bytes()))


def _target(document, target):
    if not isinstance(target.get("partId"), str) or not isinstance(
        target.get("printedMeasure"), str
    ):
        raise ScoreError(
            "invalid-review-target", "Part and printed measure must be exact strings."
        )
    if (
        sum(
            1
            for p, m, *_ in document.measures()
            if p == target["partId"] and m == target["printedMeasure"]
        )
        != 1
    ):
        raise ScoreError(
            "ambiguous-review-target",
            "Review target must select exactly one part/measure.",
        )
    if (
        not isinstance(target.get("checks"), list)
        or not target["checks"]
        or not all(isinstance(c, str) and c.strip() for c in target["checks"])
    ):
        raise ScoreError(
            "missing-check-scope",
            "Record must list concrete checks; a partial check never verifies the entire measure.",
        )


def create_calibration(*, input_path, source_pdf, targets):
    document = ScoreDocument.read(input_path)
    ids = set()
    records = []
    for target in targets:
        _target(document, target)
        identity = target.get("id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ScoreError(
                "invalid-record-id", "Review IDs must be unique nonempty strings."
            )
        ids.add(identity)
        records.append(dict(target, state="unreviewed", evidence=[], history=[]))
    if not records:
        raise ScoreError("missing-records", "At least one review target is required.")
    return dict(
        schemaVersion="1",
        targetMusicXml=_file(input_path),
        sourcePdf=_file(source_pdf),
        records=records,
    )


def calibration_status(record, *, input_path, source_pdf, edit_report=None):
    if record.get("schemaVersion") != "1":
        raise ScoreError(
            "unsupported-contract", "Expected calibration schemaVersion 1."
        )
    result = deepcopy(record)
    current_score = _file(input_path)
    current_pdf = _file(source_pdf)
    rows = None
    if edit_report is not None:
        if (
            edit_report.get("inputSha256") != record["targetMusicXml"]["sha256"]
            or edit_report.get("outputSha256") != current_score["sha256"]
            or edit_report.get("schemaVersion") != "2"
        ):
            raise ScoreError(
                "stale-structure-report",
                "Structure report must bind the recorded input and current output SHA-256.",
            )
        mapping = edit_report.get("structure", {}).get("mapping")
        if not isinstance(mapping, dict) or not isinstance(
            mapping.get("measures"), list
        ):
            raise ScoreError(
                "invalid-mapping",
                "Structure report must provide complete measure mapping.",
            )
        before_keys = [
            location_key(row["before"])
            for row in mapping["measures"]
            if row.get("before") is not None
        ]
        current = ScoreDocument.read(input_path)
        rows = mapping_rows(
            before_keys, [(p, m) for p, m, *_ in current.measures()], mapping
        )
    missing = []
    for item in result["records"]:
        if item.get("state") not in STATES:
            raise ScoreError("invalid-review-state", "Unknown review state.")
        reasons = []
        if rows is not None:
            original_location = {k: item[k] for k in ("partId", "printedMeasure")}
            matches = [r for r in rows if r["before"] == original_location]
            if len(matches) != 1:
                raise ScoreError(
                    "incomplete-mapping",
                    "Recorded location must have exactly one mapping row.",
                )
            destination = matches[0]["after"]
            reasons.append(
                "structure-mapped" if destination is not None else "target-removed"
            )
            item.setdefault("history", []).append(
                dict(
                    structureMapping=matches[0],
                    inputSha256=edit_report["inputSha256"],
                    outputSha256=edit_report["outputSha256"],
                )
            )
            if destination is None:
                item["targetRemoved"] = True
            else:
                item.update(destination)

        if current_score["sha256"] != record["targetMusicXml"]["sha256"]:
            reasons.append("target-score-changed")
        if current_pdf["sha256"] != record["sourcePdf"]["sha256"]:
            reasons.append("source-pdf-changed")
        for evidence in item.get("evidence", []):
            path = Path(evidence["path"])
            if not path.is_file() or sha256(path.read_bytes()) != evidence.get(
                "sha256"
            ):
                reasons.append("evidence-missing-or-changed")
                missing.append(dict(recordId=item["id"], path=str(path)))
        if item["state"] == "verified":
            if (
                not item.get("evidence")
                or not item.get("reviewer")
                or not item.get("conclusion")
                or not item.get("reviewedAt")
                or not item.get("sourceLocation")
                or not item.get("checks")
            ):
                reasons.append("incomplete-review-evidence")
                missing.append(
                    dict(recordId=item["id"], reason="incomplete-review-evidence")
                )
            if (
                item.get("verifiedMusicXmlSha256") != current_score["sha256"]
                or item.get("verifiedSourcePdfSha256") != current_pdf["sha256"]
            ):
                reasons.append("verified-version-stale")
        if reasons and item["state"] != "unreviewed":
            item["state"] = "needs-review"
        item["invalidationReasons"] = sorted(set(reasons))
    if rows is not None:
        result["targetMusicXml"] = current_score
    counts = Counter(item["state"] for item in result["records"])
    result["counts"] = {s: counts[s] for s in STATES}
    result["missingEvidence"] = missing
    result["currentMusicXml"] = current_score
    result["currentSourcePdf"] = current_pdf
    return result


def update_record(
    record,
    *,
    record_id,
    state,
    input_path,
    source_pdf,
    reviewer="",
    conclusion="",
    source_location=None,
    evidence=(),
    edit_reports=(),
    edit_report=None,
):
    if state not in STATES:
        raise ScoreError("invalid-review-state", "Unknown review state.")
    result = calibration_status(
        record, input_path=input_path, source_pdf=source_pdf, edit_report=edit_report
    )
    matches = [r for r in result["records"] if r["id"] == record_id]
    if len(matches) != 1:
        raise ScoreError("record-missing", "Expected one review record ID.")
    item = matches[0]
    allowed = {
        "unreviewed": {"needs-fix", "verified"},
        "needs-fix": {"needs-review"},
        "needs-review": {"verified", "needs-fix"},
        "verified": {"needs-review", "needs-fix"},
    }
    if state not in allowed[item["state"]]:
        raise ScoreError(
            "invalid-review-transition", f"Cannot move {item['state']} to {state}."
        )
    if item.get("targetRemoved"):
        raise ScoreError(
            "removed-review-target",
            "Deleted objects cannot inherit a review by reusing their printed number; create a new record.",
        )
    _target(ScoreDocument.read(input_path), item)
    files = [_file(path) for path in evidence]
    reports = [_file(path) for path in edit_reports]
    if state == "verified":
        location = source_location or {}
        if (
            not reviewer.strip()
            or not conclusion.strip()
            or not files
            or type(location.get("page")) is not int
            or location["page"] < 1
            or type(location.get("system")) is not int
            or location["system"] < 1
            or not isinstance(location.get("measures"), list)
            or not location["measures"]
            or not all(isinstance(m, str) and m for m in location["measures"])
        ):
            raise ScoreError(
                "missing-review-evidence",
                "Verified requires reviewer, conclusion, evidence files, source PDF page/system/measure strings and explicit check scope.",
            )
    now = datetime.now(timezone.utc).isoformat()
    item["history"].append(
        dict(
            fromState=item["state"],
            toState=state,
            at=now,
            reviewer=reviewer,
            conclusion=conclusion,
            musicXmlSha256=result["currentMusicXml"]["sha256"],
            sourcePdfSha256=result["currentSourcePdf"]["sha256"],
            evidence=files,
            editReports=reports,
        )
    )
    item.update(
        state=state,
        reviewer=reviewer,
        conclusion=conclusion,
        reviewedAt=now,
        sourceLocation=source_location,
        evidence=files,
        editReports=reports,
        invalidationReasons=[],
    )
    if state == "verified":
        item.update(
            verifiedMusicXmlSha256=result["currentMusicXml"]["sha256"],
            verifiedSourcePdfSha256=result["currentSourcePdf"]["sha256"],
        )
    # Rebind the container only after stale sibling conclusions were downgraded.
    result["targetMusicXml"] = result.pop("currentMusicXml")
    result["sourcePdf"] = result.pop("currentSourcePdf")
    result.pop("counts", None)
    result.pop("missingEvidence", None)
    return result
