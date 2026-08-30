# score-cli

Render one printed MusicXML measure as one PNG for visual comparison with the source score.

The full score is laid out first. `score-cli` then locates the requested measure in that
rendered layout and crops its graphical bounds, so spacing and staff positions remain the
same as they were in the surrounding system. Printed measure numbers are included in both
measure and system crops.

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

## Outlining a score

List the score's parts and ordered printed measure numbers before selecting a measure:

```bash
uv run score-cli outline score.mxl
```

The JSON contains only `schemaVersion`, `parts`, `measureNumbers`, and sequence
diagnostics. It does not include file metadata or musical events.

## Inspecting a measure

Return normalized JSON information for one printed measure:

```bash
uv run score-cli inspect score.mxl --measure 41
```

JSON is written to stdout, so it can be redirected or piped to another tool:

```bash
uv run score-cli inspect score.mxl --measure 41 > measure-41.json
```

The result contains only the selected logical measure. It aggregates that measure
across every part, resolves effective attributes such as divisions, key, time, and
clef, and normalizes notes, rests, voices, staves, offsets, durations, lyrics,
directions, harmony, notation, and barlines. Input-file metadata, score headers, and
neighboring measures are deliberately omitted. See
[the inspect JSON contract](docs/inspect-json.md).

To inspect one exact MusicXML part ID:

```bash
uv run score-cli inspect score.mxl --measure 41 --part P3
```

For a loss-preserving ordered representation of every MusicXML element inside the
target measure, opt in explicitly:

```bash
uv run score-cli inspect score.mxl --measure 41 --include-elements
```

For a concise human-readable view:

```bash
uv run score-cli inspect score.mxl --measure 41 --format text
```

The same printed number appearing once in each part is one logical measure and is
aggregated normally. Repeating the same printed number within a single part or
timewise measure sequence is ambiguous and returns an error.

## V1 scope

- Input: one MusicXML or compressed MusicXML file.
- Selector: the measure's printed number.
- Output: a score outline, one measure's JSON/text information, or one measure/system PNG.

Editing, event export, comparison manifests, and multi-measure context are outside the V1 scope.
