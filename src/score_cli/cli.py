"""Command-line interface for score-cli."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .musicxml_input import MusicXmlInputError
from .render_measure import RenderMeasureError, render_printed_measure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="score-cli",
        description=(
            "Render one printed MusicXML measure as it appears in the fully laid-out score."
        ),
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        result = render_printed_measure(
            input_path=arguments.input,
            measure=arguments.measure,
            output_path=arguments.output,
            scope=arguments.scope,
        )
    except (MusicXmlInputError, RenderMeasureError, OSError, UnicodeError) as error:
        parser.exit(1, f"score-cli: {error}\n")

    print(
        f'Rendered {result.scope} for printed measure "{result.printed_measure}" '
        f"from page {result.source_page}/{result.source_page_count} "
        f"to {result.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
