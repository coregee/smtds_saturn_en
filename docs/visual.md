# Visual assets

`visual/` owns still-image extraction, validation, repacking, and the baked-text
review catalog. Movies belong to `fmv/`; the title screen is split between the
two packages.

## Translation image workflow

Run commands from the repository root. Extraction discovers registered image
records and creates the local hash manifest used by the repacker:

```powershell
python -B -m visual.script.extract
```

`visual/image/` is an ignored, intentionally sparse review workspace. Removing
a PNG excludes it from later extraction checks; pass `--restore-missing` to
recreate every registered image. `visual/generated/` is also ignored because
its manifest fingerprints the locally supplied disc.

Tracked translation assets are flat mirrors under
`visual/translation_images/`:

- `original/` contains immutable references;
- `translated/` is the sole repack input; and
- `visual/translation_images.json` maps each filename to its nested targets.

One PNG may update several targets only when their dimensions and decoded
pixels match. Eight wide environment labels use `horizontal` mappings: the
reference halves are joined left-to-right for editing, then cropped back to
their original widths during repacking. Validation rejects changed reference
pixels, invalid deduplication, missing, extra, or nested files, dimension drift,
and unknown targets.

Inspect, rebuild, and verify translated images with:

```powershell
python -B -m visual.script.repack --list
python -B -m visual.script.repack
python -B -m visual.script.repack --check
```

Change detection uses normalized pixels, so PNG metadata and compression do
not trigger a rebuild. A changed target rebuilds only its containing disc file
under `rom/build/`, preserving headers, model data, untouched textures, RGB555
high bits, and exact file length. Reverting every mapped image in a source
removes its stale replacement.

`SAVE.BIN` and `LOAD.BIN` are engine-composed exceptions: the visual stage
owns and validates their four shared storage-selector PNGs, then defers those
pixel changes to `saveload_ui`. The later engine stage applies them alongside
the overlays' code and text patches so neither whole-file rebuild can erase the
other.

The parent `python -B build` command uses `--if-extracted`; visual repacking
stays inactive until extraction has created the local manifest, then its output
is included in the regenerated canonical test disc.

## Registered formats and limits

The registry covers:

- model-described textures in `TEX3D/` and `MMP/*CHR.COF`;
- proven standalone RGB555 rasters;
- all 31 `TITLE.BIN` image records: three indexed title overlays, two RGB555
  start-prompt glyph sets, and the RGB555 Atlus copyright strip;
- four 104x24 RGB555 storage-selector sprites mirrored by `SAVE.BIN` and
  `LOAD.BIN`; and
- the 352x240 direct-color title raster in `TESTLOGO.COF`.

The three indexed title overlays use distinct runtime-bound RGB555 palettes.
Replacement indices are limited to the 198 main-logo entries updated by every
fade path and the 64 entries copied for each smaller overlay; unused bytes in
their physical 256-word blocks are never allocated. When one is edited, the
repacker preserves every palette index used by unchanged consumers and rebuilds
the free entries from the input PNG. For RGBA artwork, alpha-zero pixels remain
transparent while partial alpha is composited against the title's black matte
and stored as opaque RGB555 shades. This retains antialiased edges without a
visible alpha-to-coverage pattern; palette quantization occurs only when the
input exceeds the remaining entries. The `TITLE.BIN` registry is checked
against its image descriptors and palette bounds.
`TESTLOGO.COF` must retain its native dimensions and big-endian `0x80BBGGRR`
pixels, including the leading control byte. Missing, changed, or newly
discovered descriptors fail extraction rather than reducing coverage silently.

Archive records are accepted only when their pointer span equals
`width * height * 2`; unknown layouts are rejected.

Demon `.CHR` canvases are not registered because they need a separate indexed
sprite codec. Cinepak screens remain in `fmv/`. In particular,
`TAITLFIX.CPK` owns the animated occult-disc/moon-and-sun title background:

```powershell
python -B -m fmv.script.extract TAITLFIX.CPK
```

## Review catalog

`catalog.json` records each source fingerprint, review result, and any baked
text rows. Each row uses `jp` for the original text and `tr` for the active
target translation; here `tr` means *translation*, not Turkish. A row may also
retain `en` as an English source/reference when deriving another translation,
but validation and downstream work always treat `tr` as the target. Every
source has either a `text` array or a `no_text` explanation; reviewed MMP
graphics are included here as normal visual assets.

The asset-level `review` description records evidence for this visual catalog;
it is unrelated to the text corpus's per-translation `reviewed` and `excluded`
bookkeeping flags.

```powershell
python -B -m visual.script.validate
```

The parent `python -B build` command runs the same validation and regenerates
the canonical CUE. Repacking and byte checks establish asset integrity, but the
rebuilt CUE still requires visual testing.
