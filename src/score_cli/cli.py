"""Command-line interface for score-cli."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Sequence

from .inspect_measure import (
    ScoreInspectionError,
    inspect_printed_measure,
    outline_score,
)
from .musicxml_input import MusicXmlInputError
from .render_measure import RenderMeasureError, render_printed_measure, render_range
from .edit_score import edit_score, publish_files, json_bytes
from .score_document import ScoreError
from .validation import validate_score
from .compare import compare_scores
from .calibration import create_calibration, update_record, calibration_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="score-cli",
        description="Render or inspect one printed MusicXML measure.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="render one printed measure to a PNG")
    render.add_argument("input", help="input .musicxml, .xml, or .mxl score")
    render.add_argument(
        "--measure",
        required=False,
        help="exact printed measure number, such as 41, 0, or X1",
    )
    render.add_argument(
        "--scope",
        choices=("measure", "system"),
        default="measure",
        help="crop the measure or its complete staff system (default: measure)",
    )
    render.add_argument("--output", required=True, help="destination PNG path")

    render.add_argument("--from-measure", dest="start")
    render.add_argument("--to-measure", dest="end")
    render.add_argument("--context", type=int, default=0)
    render.add_argument(
        "--breaks", choices=("encoded", "auto"), default="encoded",
        help="keep encoded system breaks or reflow for inspection (default: encoded)",
    )
    render.add_argument(
        "--page-width", type=int, default=2100,
        help="Verovio page width, 100–100000 (default: 2100)",
    )
    render.add_argument(
        "--lyric-word-space", type=float, default=1.2,
        help="lyric word spacing, 0–10 (default: 1.2)",
    )
    render.add_argument(
        "--measure-number-interval", type=int, default=1,
        help="measure number density: 0 at system starts, 1 every measure (default), 2–64 every N measures",
    )
    edit = commands.add_parser(
        "edit", help="apply an input-hash-bound changeset to a new XML file"
    )
    edit.add_argument("input")
    edit.add_argument("--changes", required=True)
    edit.add_argument("--output", required=True)
    edit.add_argument("--dry-run", action="store_true")
    validate = commands.add_parser(
        "validate", help="report whole-score checks and coverage"
    )
    validate.add_argument("input")
    compare = commands.add_parser(
        "compare", help="compare notation with explicit alignment limits"
    )
    compare.add_argument("before")
    compare.add_argument("after")
    compare.add_argument("--mapping", help="JSON explicit parts/measures mapping")
    calibration = commands.add_parser(
        "calibration", help="manage version-bound review evidence"
    )
    calibration.add_argument("action", choices=["create", "status", "update"])
    calibration.add_argument("input")
    calibration.add_argument("--source-pdf", required=True)
    calibration.add_argument("--record")
    calibration.add_argument(
        "--edit-report", help="Hash-bound structure edit report for target migration"
    )
    calibration.add_argument(
        "--targets", help="JSON array of id/partId/printedMeasure/checks"
    )
    calibration.add_argument(
        "--update",
        help="JSON object with recordId/state/reviewer/conclusion/sourceLocation/evidence/editReports",
    )
    calibration.add_argument("--output", help="new calibration JSON file")

    outline = commands.add_parser(
        "outline",
        help="list parts and printed measure numbers",
    )
    outline.add_argument("input", help="input .musicxml, .xml, or .mxl score")

    inspect = commands.add_parser(
        "inspect",
        help="return complete structured information for one printed measure",
    )
    inspect.add_argument("input", help="input .musicxml, .xml, or .mxl score")
    inspect.add_argument(
        "--measure",
        required=True,
        help="exact printed measure number, such as 41, 0, or X1",
    )
    inspect.add_argument(
        "--part",
        help="return only the part with this exact MusicXML part ID",
    )
    inspect.add_argument(
        "--include-elements",
        action="store_true",
        help="include complete ordered MusicXML element representations",
    )
    inspect.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "text"),
        default="json",
        help="output format (default: json)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "edit":
            report = edit_score(
                input_path=arguments.input,
                changeset=json.loads(Path(arguments.changes).read_text()),
                output_path=arguments.output,
                dry_run=arguments.dry_run,
            )
            print(json_bytes(report).decode(), end="")
        elif arguments.command == "validate":
            report = validate_score(input_path=arguments.input)
            print(json_bytes(report).decode(), end="")
            return 1 if report["status"] == "invalid" else 0
        elif arguments.command == "compare":
            report = compare_scores(
                before_path=arguments.before,
                after_path=arguments.after,
                mapping=json.loads(Path(arguments.mapping).read_text())
                if arguments.mapping
                else None,
            )
            print(json_bytes(report).decode(), end="")
        elif arguments.command == "calibration":
            report = _calibration_command(arguments)
            print(json_bytes(report).decode(), end="")
        elif arguments.command == "render" and (
            arguments.start is not None
            or arguments.end is not None
            or arguments.context
        ):
            if arguments.start is not None and arguments.measure is not None:
                raise ScoreError(
                    "invalid-range", "Use --measure or --from-measure, not both."
                )
            if arguments.scope != "measure":
                raise ScoreError(
                    "invalid-range",
                    "Range rendering crops consecutive selected measures per system.",
                )
            report = render_range(
                input_path=arguments.input,
                start=arguments.start or arguments.measure,
                end=arguments.end,
                context=arguments.context,
                output_directory=arguments.output,
                measure_number_interval=arguments.measure_number_interval,
                breaks=arguments.breaks,
                page_width=arguments.page_width,
                lyric_word_space=arguments.lyric_word_space,
            )
            print(json_bytes(report).decode(), end="")
        elif arguments.command == "render":
            if arguments.measure is None:
                raise ScoreError(
                    "missing-measure", "Specify --measure or --from-measure."
                )
            result = render_printed_measure(
                input_path=arguments.input,
                measure=arguments.measure,
                output_path=arguments.output,
                scope=arguments.scope,
                measure_number_interval=arguments.measure_number_interval,
                breaks=arguments.breaks,
                page_width=arguments.page_width,
                lyric_word_space=arguments.lyric_word_space,
            )
            print(
                f"Rendered {result.scope} for printed measure "
                f'"{result.printed_measure}" from page '
                f"{result.source_page}/{result.source_page_count} "
                f"to {result.output_path}"
            )
        elif arguments.command == "outline":
            print(outline_score(input_path=arguments.input).to_json(), end="")
        else:
            inspection = inspect_printed_measure(
                input_path=arguments.input,
                measure=arguments.measure,
                part=arguments.part,
                include_elements=arguments.include_elements,
            )
            output = (
                inspection.to_json()
                if arguments.output_format == "json"
                else inspection.to_text()
            )
            print(output, end="")
    except ScoreError as error:
        print(
            json_bytes(
                dict(schemaVersion="1", status="failed", diagnostics=[error.diagnostic])
            ).decode(),
            end="",
            file=sys.stderr,
        )
        return 1
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
    ) as error:
        if arguments.command in {"edit", "validate", "compare", "calibration"}:
            print(
                json_bytes(
                    dict(
                        schemaVersion="1",
                        status="failed",
                        diagnostics=[
                            dict(
                                code="invalid-request",
                                severity="error",
                                location={},
                                reason=str(error),
                                operationId=None,
                            )
                        ],
                    )
                ).decode(),
                end="",
                file=sys.stderr,
            )
            return 1
        parser.exit(1, f"score-cli: {error}\n")
    except (
        ScoreInspectionError,
        MusicXmlInputError,
        RenderMeasureError,
        OSError,
        UnicodeError,
    ) as error:
        parser.exit(1, f"score-cli: {error}\n")
    return 0


def _calibration_command(arguments):
    common = dict(input_path=arguments.input, source_pdf=arguments.source_pdf)
    if arguments.action == "create":
        if not arguments.targets:
            raise ScoreError("missing-targets", "Create requires --targets.")
        report = create_calibration(
            **common, targets=json.loads(Path(arguments.targets).read_text())
        )
    else:
        if not arguments.record:
            raise ScoreError("missing-record", "Status/update requires --record.")
        record = json.loads(Path(arguments.record).read_text())
        if arguments.edit_report:
            common["edit_report"] = json.loads(Path(arguments.edit_report).read_text())
        if arguments.action == "status":
            report = calibration_status(record, **common)
        else:
            if not arguments.update:
                raise ScoreError("missing-update", "Update requires --update.")
            update = json.loads(Path(arguments.update).read_text())
            report = update_record(
                record,
                **common,
                record_id=update["recordId"],
                state=update["state"],
                reviewer=update.get("reviewer", ""),
                conclusion=update.get("conclusion", ""),
                source_location=update.get("sourceLocation"),
                evidence=update.get("evidence", []),
                edit_reports=update.get("editReports", []),
            )
    if arguments.action != "status" and not arguments.output:
        raise ScoreError(
            "missing-output", "Create/update requires a new --output JSON file."
        )
    if arguments.output:
        publish_files({Path(arguments.output): json_bytes(report)})
    return report


if __name__ == "__main__":
    raise SystemExit(main())
