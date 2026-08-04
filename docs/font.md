# Font module

`font/` owns Saturn font configuration, editable glyph images, atlas mappings,
encoding metadata, and generated advance metrics. For setup and full builds,
see the [root README](../README.md).

## Paths

| Path | Purpose |
| --- | --- |
| `image/<file>/glyph_####.png` | Editable per-glyph images. |
| `atlas/` | Source (`*_original.png`) and repacked (`*_replaced.png`) reference sheets plus glyph mappings. |
| `config/` | Per-font binary, atlas, preview, and source-font settings. |
| `source/` | Third-party fonts used by the default repack. |
| `generated/` | Reproducible glyph-code and advance-metric contracts for text and engine code. |
| `script/` | Extraction and repacking entry points. |

Bundled fonts retain their adjacent licenses and provenance files. See the
[repository license](../LICENSE) for scope.

## Binary format

Pixels are most-significant-bit first. One-bit fonts pack eight pixels per byte;
four-bit fonts pack two. The codec can also parse four two-bit pixels per byte,
although no identified font currently uses that mode.

| File | Size | Bpp | Row bytes | Glyph bytes | Glyphs |
| --- | --- | --: | ---: | ---: | ---: |
| `FONT6.FON` | 6x8 | 4 | 3 | 24 | 14 |
| `FNT8X12.FON` | 8x12 | 1 | 1 | 12 | 72 |
| `FNT12X12.FON` | 12x12 | 1 | 2 | 32 | 52 |
| `FONT8.FON` | 8x8 | 1 | 1 | 8 | 256 |
| `FONT12.FON` | 12x12 | 1 | 2 | 32 | 432 |
| `FONT16.FON` | 16x16 | 1 | 2 | 32 | 1,872 |
| `ICON.FON` | 12x12 | 4 | 6 | 72 | 21 |
| `KANJI.FON` | 16x16 | 1 | 2 | 32 | 7,806 |

`MMP/KANJI.FON` is byte-identical to the root `KANJI.FON` and is not extracted
as a second editable set.

## Configuration and atlases

Each `config/*.json` defines binary dimensions, bit depth, row and glyph
strides, atlas columns and scale, and optional TTF/OTF/TTC rendering settings.
Its `atlas.file` names the matching JSON in `atlas/`, which owns all glyph-index
knowledge. Descriptive keys under the top-level `atlas` object are organizational
only.

A range mapping assigns consecutive characters:

```json
{
  "replace": true,
  "start": 12,
  "characters": "0123456789"
}
```

`replace` defaults to `false`. `start` accepts an integer or a string with an
optional `0x` prefix.

An array mapping assigns individual decimal or hexadecimal index keys:

```json
{
  "replace": true,
  "0x15": "a",
  "22": { "ー": "-" },
  "28": { "♀": null }
}
```

A string is the shared read/write character. An object maps the extraction
character to its repack character; `null` disables replacement for that glyph
even when `replace` is true. Text extraction uses the read value. Repacking uses
the write value only when the configured source font provides it.

## Generated metrics and runtime constraints

- Every rendered `replace: true` FONT16 cell publishes its actual atlas index
  and advance to `generated/font16_metrics.json`. The sparse table uses those
  indices directly; zero entries keep stock fixed-width behavior.
- The advance table begins at font cell 1728 as data. Those cells are not a
  second English glyph allocation.
- Replacement cells beyond `advance_table.code_limit` are rendered but omitted
  from the table and metrics manifest. The three CONFIG-only compound cells
  near the end of FONT16 fit nine-cell footer records and use widths embedded
  by the CONFIG engine patch.
- Every generated FONT8 replacement leaves scanline eight blank because stock
  consumers rely on it; the demon-analysis table exposes nonblank row-eight
  pixels at the top of its viewport. `config/font8.json` shifts descenders in
  `gjpqy,` up one pixel without changing other baselines.
- Some EVENT screens treated kana cells as precomposed labels.
  `itemname_runtime` reconstructs the shop summary's `Inv.` pair, while
  `status_ui` rewrites `REVIEW` and `STATUS` aliases to stock Latin codes. This
  preserves the narrow English assignments without corrupting stock labels.

## Repacking

Each glyph resolves independently in this order:

1. Render from the configured font when `use_font_file` is enabled and the
   glyph exists.
2. Load a valid editable PNG when present.
3. Decode the glyph from the original `.FON`.

The current `FONT12.FON` configuration renders Latin replacements from the
bundled OFL-licensed Ark Pixel font. If it cannot render a glyph, repacking
falls back first to its extracted PNG and then to
`rom/extracted/FONT12.FON`.

By default, repacking updates `font/image/` glyph PNGs, writes the font below
`rom/build/`, and creates `font/atlas/<font>_replaced.png`. Use
`--preview-only` to avoid updating glyph images or build output.

Run from the repository root:

```powershell
python -B -m font.script.extract
python -B -m font.script.repack FONT8.FON
python -B -m font.script.repack FONT12.FON --preview-only
python -B -m font.script.repack FONT16.FON --check
```

Extraction preserves existing glyph images unless `--overwrite` is passed.
`--check` rebuilds the selected font in memory and verifies its binary and
generated metrics without rewriting glyph images, atlas sheets, or outputs.
