"""Command-line interface for score-cli."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .inspect_measure import (
    ScoreInspectionError,
    inspect_printed_measure,
    outline_score,
)
from .musicxml_input import MusicXmlInputError
from .render_measure import RenderMeasureError, render_printed_measure


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
        required=True,
        help="exact printed measure number, such as 41, 0, or X1",
    )
    render.add_argument(
        "--scope",
        choices=("measure", "system"),
        default="measure",
        help="crop the measure or its complete staff system (default: measure)",
    )
    render.add_argument("--output", required=True, help="destination PNG path")

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
        if arguments.command == "render":
            result = render_printed_measure(
                input_path=arguments.input,
                measure=arguments.measure,
                output_path=arguments.output,
                scope=arguments.scope,
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
    except (
        ScoreInspectionError,
        MusicXmlInputError,
        RenderMeasureError,
        OSError,
        UnicodeError,
    ) as error:
        parser.exit(1, f"score-cli: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
