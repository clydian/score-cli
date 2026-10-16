# score-cli

Inspect, safely edit, compare, and render MusicXML for source-score calibration.

The full score is laid out first. `score-cli` then locates the requested measure in that
rendered layout and crops its graphical bounds, so spacing and staff positions remain the
same as they were in the surrounding system. Printed measure numbers are included in both
measure and system crops.

Crop bounds include every verse below the bottom staff, even when Verovio's
graphical content bounds omit lyric text.

Music text (including metronome notes and metric proportions) uses Verovio's
embedded SMuFL font during PNG rasterization. No music-font installation is
required, and unrelated system fallback glyphs are not used for those symbols.

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

## Calibration workflow (contract v1)

See [editing and evidence contracts](docs/editing.md) for `edit --dry-run`,
`validate`, `compare`, range rendering, and version-bound calibration records.
Real excerpt inputs and replayable changesets are in `tests/fixtures/calibration/`;
[acceptance evidence](docs/issue-1-acceptance.md) distinguishes automated checks
from source PDF review and remaining limitations.

## Original command compatibility

- Input: one MusicXML or compressed MusicXML file.
- Selector: the measure's printed number.
- Output: a score outline, one measure's JSON/text information, or one measure/system PNG.

The original outline/inspect/single-measure render contracts remain unchanged.
Automatic PDF correctness judgments, playback, GUI, complex lyric
rewrites, and MXL repackaging remain outside the current scope.

### 结构修复

OMR 常把多个合唱声部都命名为 `Voice`。用 `rename-part` 校正名称时，
可在 `value` 同时传 `"abbreviation":"S"`（或 A/T/B），让后续系统也显示正确短名。
省略该字段保留已有短名，显式 null 删除；更新保留原短名的样式属性，拒绝隐式覆盖显示替代内容。

changeset v2 支持事件、小节和 part 的结构编辑，显式 Audiveris 碎片合并，以及 compare/校准清单的结构映射。所有删除逐项声明，失败不发布部分文件。参见 [结构编辑契约与示例](docs/structural-editing.md) 和 [真实碎片合并验收](docs/issue-2-acceptance.md)。
