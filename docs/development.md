# Development guide

This page is the cross-package map for maintainers. Package-specific binary
formats, commands, and runtime evidence remain in the other files under
`docs/`.

## Repository flow

The parent build runs packages in dependency order:

```text
rom/original
    -> disc extraction -> rom/extracted
    -> font -> generated metrics and built fonts
    -> text -> generated contracts and built text files
    -> visual / FMV -> changed asset replacements
    -> engine -> composed runtime-patched binaries
    -> disc -> playable image and optional release patch
```

`disc/` is the terminal consumer. Asset packages (`font/`, `text/`, `visual/`,
and `fmv/`) must not import `engine/` or `disc/`. Engine features consume
generated contracts and built assets; they do not read `text/corpus/`.

Every engine factory receives an `EngineBuildContext`. Extracted inputs,
generated font and text inputs, and build outputs must be resolved through that
context. Text-owned generated inputs have two validated boundaries:
`RuntimeUiContract` supplies sectioned UI labels, names, and terminology, while
`StaticTextAsset` supplies byte-oriented replacements for static source files
such as CONFIG, MAP, NAME, SAVE, LOAD, and the EVENT fusion prompt. Features
must not reopen the underlying runtime-UI sections or `text/corpus/` sources.

## Ownership

| Change | Canonical owner |
| --- | --- |
| Translation text, review state, and tokens | `text/corpus/` |
| Text-free binary layout facts | `text/layout/` |
| Text formats, dialects, encodings, and wrapping | `text/script/` |
| Font configuration, atlases, and source fonts | `font/config/`, `font/atlas/`, and `font/source/` |
| Translated still images and their registration | `visual/translation_images/` and `visual/translation_images.json` |
| FMV subtitles and movie registration | `fmv/subtitles/` and `fmv/catalog.json` |
| Runtime addresses, ABI facts, assembly, and patch composition | `engine/script/` |
| Disc extraction, sectors, manifests, and release patching | `disc/` |
| Shared repository paths and safe path checks | `project_paths.py` and `safe_paths.py` |

Do not hand-edit generated or built outputs. Package `generated/` directories,
`font/image/`, `visual/image/`, `fmv/decoded/`, `rom/extracted/`, and
`rom/build/` are derived or local workspaces. Original media and all local
build outputs are user-owned; do not delete or replace them as cleanup.

Shared format behavior stays with its format package. Runtime hooks and
verified target addresses stay in `engine/`. Shared engine rendering or packed
text algorithms belong under `engine/script/text_render/`, not inside another
feature's `patch.py`.

## Validation levels

Run the source-only repository gate after Python, documentation, or corpus
changes:

```powershell
python -B -m tools.validate_source
```

It checks Ruff formatting and correctness, focused mypy, all unittest
discovery, the translation audit, the SH-2 assembler, lazy engine capability
discovery, and the parent build plan.

Use package checks while iterating. For engine changes, the existing built
binaries are a byte-parity oracle:

```powershell
python -B -m engine.script.build --check
python -B build --check
```

These checks require the corresponding local extracted and built artifacts.
They establish structural and byte-level parity, not screen presentation. A
visible or timing-sensitive change still requires a cold boot in an emulator or
on hardware using the runtime-evidence guidance in [engine.md](engine.md).

## Change checklist

1. Edit the canonical source owned by the relevant package.
2. Keep dependency direction and generated-contract boundaries intact.
3. Add focused tests beside the owner; use root `tests/` for cross-package rules.
4. Run the owning package's focused tests or `--check` command.
5. Run `python -B -m tools.validate_source`.
6. For generated or runtime changes, run the appropriate build check and record
   runtime evidence when static parity cannot prove behavior.

When adding a text source or format, update registration, extraction,
repacking, editor capacity, and preview coverage together. When adding an
engine capability, keep its registry import lazy, accept `EngineBuildContext`,
consume validated generated inputs, and add address/ABI tests next to the
feature.
