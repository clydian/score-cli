# Verovio 6.3 later-part key-change warning

The minimal fixture `tests/fixtures/nonfirst-part-key-change.musicxml` has two
parts and two measures. A starts in four flats and does not change; B starts in
one sharp and changes to four flats in measure 2. Raw Verovio 6.3.0 import drops
B's measure-2 key in MEI. The actual CLI preview consequently retains one sharp.
This is already wrong before cropping or SVG rasterization.

Pinned upstream code explicitly handles only the first key change in the first
part: [iomusxml.cpp, version 6.3.0, lines 2086–2093](https://github.com/rism-digital/verovio/blob/version-6.3.0/src/iomusxml.cpp#L2086).
Its `ancestor::part[not(preceding-sibling::part)]` guard explains why rendering
only SATB or one voice may appear correct while the full score is wrong.
Copying the key into the first part changes independent-part semantics and is
not an acceptable source repair.

This patch reports risk rather than modifying MEI. It detects nonredundant
later-part declarations after the initial measure, skips an identical
unnumbered declaration in the first part at matching ordinal/printed number,
and reports the source part, measure, staff and fifths otherwise. It preserves
the XML byte-for-byte on this path. Unknown staff contexts are risk reports,
not a claim that all such declarations are definitely lost. It does not detect
every case where a global first-part change affects an independent part.

Run the real minimal reproduction and inspect stderr:

```sh
uv run score-cli render tests/fixtures/nonfirst-part-key-change.musicxml \
  --measure 2 --scope system --output tmp/nonfirst-key.png
uv run pytest tests/test_render_key_warnings.py
```

The PNG remains an inaccurate preview; the warning directs the reader to an
independent renderer and original score. Tests exercise actual Verovio import,
single/range rendering, CLI stderr and unaffected single-part, redundant and
shared-first-part declarations. Staff-state tests additionally cover unnumbered
resets after numbered overrides, clearing stale numbered state, namespace-aware
lookup and isolation between parts. No original user score is changed.
