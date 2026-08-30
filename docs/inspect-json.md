# Inspect JSON contract

`score-cli inspect` returns information about exactly one logical MusicXML measure.
The current `schemaVersion` is `"1"`.

## Boundary

The document deliberately excludes the input path, file size, hashes, MusicXML
headers, credits, and neighboring measures. The only inherited data is the effective
musical context required to interpret the target measure, such as divisions, key,
time, clef, transpose, and staff count.

One occurrence of the printed number in each part is normal: those part-measures are
combined into one logical measure. If the number repeats within a single part or a
timewise measure sequence, selection is ambiguous and inspection fails.

## Top-level fields

- `schemaVersion`: contract version.
- `measure.printedNumber`: exact MusicXML measure number selected by `--measure`.
- `parts`: target-measure content grouped by part. `partId` and `partName` identify
  each part; `measure` contains only that part's target measure.
- `diagnostics`: target-related warnings or informational messages, each with
  `severity`, `code`, `message`, and optional `partId`.

## Per-part measure

- `attributes`, `implicit`, `nonControlling`, and `width`: attributes on the target
  `<measure>` element.
- `context`: effective musical state at the first timed event. Attribute families
  are keyed by their MusicXML `number` and contain common normalized fields.
- `duration`: final cursor and furthest event end in quarter-note units.
- `events`: notes, rests, chord members, grace/cue notes, pitch, voice, staff,
  duration, accidentals, ties, beams, notation, lyrics, and display properties.
- `directions`, `harmonies`, `figuredBass`, and `barlines`: normalized placed objects.
- `attributeChanges`: attribute changes inside the target measure and the effective
  context after each change.

By default, `elements` is omitted. Passing `--include-elements` adds every direct
child of the target measure in original order, with cursor offsets and a recursive
`value` preserving names, attributes, text, namespaces, and child order. It also adds
the original effective attribute `element` representations under `context`.

Normalized offsets and durations are rational strings in quarter-note units, such as
`"0"`, `"1"`, and `"3/2"`. Event IDs are scoped to the selected measure using part,
printed measure number, staff, voice, rational offset, and event index.

`elements` is semantically complete for the target measure, but not a byte-for-byte
XML archive: indentation, namespace prefixes, comments, processing instructions, and
DTD spelling may be normalized by the XML parser.

The JSON reports what MusicXML contains; it does not prove agreement with a source
PDF or image.

## Part selection

`--part` accepts one exact MusicXML part ID. When present, `parts` contains only that
part and diagnostics unrelated to other parts are not returned. An unknown part or a
part without the selected measure is an error.

## Score outline

`score-cli outline` is the discovery interface used before measure inspection. It
returns:

- `schemaVersion`
- `parts`, containing `partId` and `partName`
- `measureNumbers`, preserving score order and string labels such as `0` and `X1`
- `diagnostics` for duplicate numbers or inconsistent partwise measure sequences

For `score-partwise`, the first part defines the outline order and other parts are
checked against it. For `score-timewise`, the root measure order is used directly.
The outline contains no notes, headers, measure contents, or file metadata.
