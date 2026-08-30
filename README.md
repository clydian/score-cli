# score-cli

Render one printed MusicXML measure as one PNG for visual comparison with the source score.

The full score is laid out first. `score-cli` then locates the requested measure in that
rendered layout and crops its graphical bounds, so spacing and staff positions remain the
same as they were in the surrounding system.

## Requirements

- [uv](https://docs.astral.sh/uv/). The project pins the latest stable Python 3.14
  release and lets uv install it when needed.

## Usage

```bash
uv sync
uv run score-cli render "/path/to/score.musicxml" \
  --measure 41 \
  --output tmp/measure-41.png
```

The `score-cli` entry point accepts the same arguments:

```bash
uv run score-cli render score.mxl --measure X1 --output measure-X1.png
```

To capture the complete staff system containing the target measure, including its
line-start notation, barlines, instrument labels, and every printed measure number:

```bash
uv run score-cli render score.mxl \
  --measure X1 \
  --scope system \
  --output system-X1.png
```

`--scope` accepts `measure` (the default) or `system`. System scope includes every
staff in the target measure's rendered system.

`--measure` matches the exact MusicXML `<measure number="...">` value. It is a
string selector, so printed numbers such as `0` and `X1` are supported. Inputs may be
uncompressed `.musicxml` / `.xml` files or compressed `.mxl` files.

## V1 scope

- Input: one MusicXML or compressed MusicXML file.
- Selector: the measure's printed number.
- Output: one measure or complete staff-system PNG cropped from the fully rendered score.

Editing, event export, comparison manifests, and multi-measure context are outside the V1 scope.
