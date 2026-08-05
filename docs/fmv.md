# FMV workflow

`fmv/` owns the root/BGDATA Sega FILM `.CPK` workflow: inventory, lossless
editable extraction, change detection, subtitles, Cinepak repacking, and
disc-ready output. Movie work requires `ffmpeg` and `ffprobe` on `PATH`.

## Catalog and extract

Run commands from the repository root:

```powershell
python -B -m fmv.script.catalog
python -B -m fmv.script.catalog --check
python -B -m fmv.script.extract
python -B -m fmv.script.extract --check
```

Tracked `fmv/catalog.json` records the size, SHA-256, codec, stream shape, and
timing of all 82 root/BGDATA CPKs, including silent movies. `catalog --all`
also inventories 395 COMBDATA battle animations; they are outside the default
editable set. Write that broader inventory to a local path so it cannot replace
the tracked catalog:

```powershell
python -B -m fmv.script.catalog --all --output fmv/generated/all_movies.json
```

Extraction writes lossless FFV1/PCM Matroska files below ignored
`fmv/decoded/`, preserving disc-relative paths. Ignored
`fmv/generated/movies.json` binds each editable's clean hash to its source CPK.
Registered files are preserved on reruns, and completed files are registered
incrementally after an interruption.

An unregistered existing MKV stops extraction rather than becoming a trusted
baseline. Adopt one only after independent verification:

```powershell
python -B -m fmv.script.extract BGDATA/MOVIE.CPK --adopt-existing
```

Use `--overwrite` to decode a known-clean baseline again. Both options reset
the comparison hash, so never use them on an edit that still needs repacking.

## Changed-only repacking

Edit the MKVs in place without changing width, height, frame rate, frame count,
or audio presence, rate, and channel count. Then run:

```powershell
python -B -m fmv.script.repack --list
python -B -m fmv.script.repack
python -B -m fmv.script.repack --check
```

Only editables whose clean hash differs, or which have a mirrored subtitle
script, produce CPKs under `rom/build/`. If neither condition applies, repacking
removes any stale replacement. `fmv/generated/repacked.json` binds each output
to the exact source CPK, MKV, subtitle script, bundled subtitle fonts, encoding
recipe, and output bytes. Normal builds reuse a matching existing CPK; changed
inputs, a missing output, or an output hash mismatch force regeneration.
`--check` rejects missing, stale, or unrelated replacements without encoding.
Cache hits refresh only the output timestamp so release-manifest ownership
remains explicit; the verified CPK bytes are not rewritten.

Tracked ASS/SRT files under `fmv/subtitles/` mirror CPK paths; for example,
`fmv/subtitles/BGDATA/START2.ass` applies automatically to
`BGDATA/START2.CPK`. Subtitle text, timing, and style participate in change
detection. Keep Japanese transcripts in `Comment` events and rendered English
in matching `Dialogue` events. Rendering uses the bundled OFL-licensed Ark
Pixel 16px proportional face through libass, not a system-font substitute.

For focused work:

```powershell
python -B -m fmv.script.repack BGDATA/SANZU.CPK
python -B -m fmv.script.repack BGDATA/SANZU.CPK `
  --subtitles fmv/subtitles/BGDATA/SANZU.ass
```

The explicit subtitle option accepts one selected movie and overrides its
mirrored tracked script.

## Saturn compatibility

Repacking encodes Cinepak and planar big-endian PCM, then restores the source
movie's Saturn-facing FILM ABI: version, `1/600` timebase, audio/video sample
schedule, PCM packet boundaries, Cinepak strip count and keyframe limit, and 4-byte
sample/strip/chunk alignment. These constraints come from the original CPK;
generic FFmpeg FILM/Cinepak output is not assumed compatible.

The repacker retries increasing Cinepak qscale values until the normalized CPK
fits its original disc allocation, then rejects any remaining media-contract
difference. These checks do not replace playback of the rebuilt CUE on an
emulator or Saturn.

## Disc and package boundaries

There is no FMV-specific injector. The parent build repacks available FMVs and
passes smaller CPKs to the shared disc builder, which preserves each
replacement's extent/LBA, zero-fills unused allocation, updates both ISO9660
size copies, and regenerates and verifies Mode 1 EDC/ECC:

```powershell
python -B build
python -B build --check
```

The default pipeline runs `fmv.script.repack --if-extracted` after visual
assets. A clean checkout stays inactive until extraction creates the local FMV
manifests; changed CPKs then enter the canonical test disc automatically. The
explicit `--release` mode adds them to the hash-bound release manifest.

Title-screen ownership is split: `TAITLFIX.CPK` provides the animated
occult-disc/moon-and-sun background, while `TITLE.BIN` wordmarks and emblems
belong to `visual/`.
