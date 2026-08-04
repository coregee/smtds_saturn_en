# Disc assembly and release patches

`disc/` validates and extracts the supported Rev B source, injects replacements
from `rom/build/`, writes a local BIN/CUE under `rom/build/disc/`, and creates a
decode-verified xdelta release patch. It never modifies the source image.
File locations come from the ISO9660 directory rather than a hard-coded LBA
table, and output track names are retained so the copied CUE remains valid.

## Source extraction

`config.json` binds the supported source by exact CUE topology, track sizes,
file types, indexes, and SHA-256 values. Place the configured CUE and both raw
BIN tracks under `rom/original/`, then run from the repository root:

```powershell
python -B -m disc.script.extract --list
python -B -m disc.script.extract
python -B -m disc.script.extract --check
```

The extractor writes the canonical 1,981-file mirror under `rom/extracted/`.
`--list` validates and lists the source without writing; `--check` verifies the
existing mirror. Extraction refuses to replace a differing file unless
`--overwrite` is passed explicitly. `--cue` may select a differently named CUE,
but that source must still match the configured contract.

## Development disc

```powershell
python -B build --plan
python -B build
python -B build --check
```

The root build refreshes every registered font, text, visual, FMV, and engine
output before assembling the canonical BIN/CUE under `rom/build/disc/`.
`--plan` shows those stages without running them, and `--check` verifies the
existing outputs without rewriting them. Load the CUE printed by the build
command.

The development build permits blank translation fields and Japanese capacity
fallbacks, but still rejects structural, size, source, and sector-integrity
errors. It does not generate xdelta, and removes an older default release patch
after rewriting the disc so that stale patch files are not mistaken for current
ones. Do not publish files from this output.

The explicit release mode instead enforces translation completion, creates a
hash-bound replacement manifest, assembles the disc, and generates xdelta in
that order:

```powershell
python -B build --release
python -B build --release --check
```

These commands reach the manifest, disc, and xdelta stages only after the
strict translation and fallback gates pass; an incomplete corpus stops earlier.
See the [release workflow](../README.md#building-a-release-patch). The underlying disc
module retains `--list` and other focused diagnostics for developers, but it is
not the normal full-build entry point.

## Replacement and sector rules

- A replacement path below `rom/build/` must match its path on the disc. For
  example, `rom/build/COMBDATA/TLK_BOY.EVE` replaces
  `COMBDATA/TLK_BOY.EVE`.
- Files under `rom/build/disc/` are never treated as replacement inputs.
- Ordinary binary replacements must be exactly the original size.
- CPK replacements may be smaller, but never larger. The builder preserves
  their original extent and LBA, zero-fills unused allocation, and updates both
  endian copies of the ISO9660 file size.
- Byte-identical replacements are verified but not rewritten.
- Changed 2048-byte payloads are written into their raw 2352-byte Mode 1
  sectors, then EDC and P/Q ECC are regenerated.

Verification covers changed directory-record sectors and every sector in a
shortened CPK's original allocation. The parser requires exactly one
`MODE1/2352` data track; other tracks, including the audio track, are copied
byte-for-byte.

## Xdelta artifact

The release patch covers only the verified raw `MODE1/2352` Track 1. The user
must retain a byte-identical original CUE and Track 2; neither is included in
the delta.

The default outputs are:

- `rom/build/disc/devil-summoner-rev-b-english.xdelta`
- `rom/build/disc/devil-summoner-rev-b-english.xdelta.json`

The JSON sidecar records the source revision, source and target Track 1 sizes
and SHA-256 values, unchanged-track contract, encoder settings, and patch size
and SHA-256. It contains no timestamps or absolute paths.

Patch creation requires
[xdelta3 3.2.0](https://github.com/jmacd/xdelta/releases/tag/v3.2.0) on `PATH`,
or an explicit executable:

```powershell
python -B build --release --xdelta C:\tools\xdelta3.exe
```

For reproducibility, the encoder uses a fixed application header and raw-input
settings, ignores the ambient `XDELTA` variable, and excludes local filenames
from the artifact. The sidecar's whole-file hashes define the source and target
identities. Generation writes a temporary candidate, decodes it, and compares
the reconstructed Track 1 byte-for-byte before publishing the patch and
sidecar. `--check` validates the sidecar and repeats that decode proof without
rewriting either file.

## Applying a released patch

Verify the original Track 1 SHA-256 against the sidecar, then decode to a new
path with xdelta3 3.2.0:

```powershell
xdelta3 -d -s "C:\original\Track 1.bin" `
  "C:\patch\devil-summoner-rev-b-english.xdelta" `
  "C:\patched\Track 1.bin"
```

Verify the result against the sidecar's target SHA-256. Copy the original CUE
and unchanged Track 2 beside it, preserving the filenames referenced by the
CUE, then load that CUE. Never overwrite the source image.

Only the `.xdelta` file and its matching JSON sidecar are release candidates.
Never publish the rebuilt Track 1, original Track 2, copied CUE, or any other
file under `rom/`.
