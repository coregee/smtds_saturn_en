# Runtime patch engine

`engine/` owns verified SH-2 addresses and original bytes, runtime code, code
caves, and composition of generated text and font assets into executable
overlays. It consumes earlier-stage contracts and writes patched files under
`rom/build/`.

## Commands

Run from the repository root:

```powershell
python -B -m engine.script.build --list
python -B -m engine.script.build <capabilities>
python -B -m engine.script.build --check <capabilities>
```

Omit `<capabilities>` to build or check all registered patches. Use the parent
pipeline to regenerate or verify the playable test disc:

```powershell
python -B build
python -B build --check
```

Add `--release` only for the strict manifest-bound publishing pipeline.

## Architecture

`engine.script.registry` holds ordered, lazy module/factory descriptors. Each
selected factory receives an immutable `EngineBuildContext` containing the
extracted, generated-font, generated-text, and build roots. Importing a feature
must not read files, assemble code, or construct patches.

Feature packages use these boundaries where applicable:

- `model.py`: immutable targets, addresses, layouts, and ABI facts
- `data.py` or `assets.py`: validated generated inputs and binary tables
- `runtime.py` and `asm/*.s`: executable routines and cave composition
- `patch.py`: `BytePatch`, `CodePatch`, and `PatchGroup` construction

Shared rendering and packed-record algorithms belong under
`engine/script/text_render/`; features must not import another feature's
`patch.py` for reuse.

Text-owned runtime strings arrive through
`text/generated/runtime_ui/engine.json`. The shared loader checks the contract
digest, section bindings, and font-metric bindings before patch construction.
Engine code must not read `text/corpus/` directly.

## Capabilities

| Capability | Primary targets |
| --- | --- |
| `config_ui` | `CFG_SET.BIN` |
| `combat_packed_fetch`, `combat_vwf` | `COMBAT.BIN`, `NORMCOM.BIN` |
| `dungeon_locations` | `MAZE.BIN`, `AUTOMAPC.BIN`, location mirrors |
| `equipment_ui`, `itemname_runtime` | `EVENT.BIN`, `NORMCOM.BIN` |
| `event_vwf`, `event_packed_fetch`, `fusion_menu` | `EVENT.BIN` |
| `fixed_text_fields` | Engine-owned binaries with generated fixed fields |
| `hosi_messages` | `HOSI.BIN` |
| `map_ui` | `MAP2D.BIN` |
| `msgr_text` | `MSGR.COF` |
| `name_runtime` | NAME, EVENT, MSGR, SAVE, and LOAD targets |
| `normcom_help` | `NORMCOM.BIN` |
| `saveload_ui` | `SAVE.BIN`, `LOAD.BIN` |
| `smallfont_vwf` | `NORMCOM.BIN`, `COMBAT.BIN`, `MAZE.BIN` |
| `status_ui` | `NORMCOM.BIN`, `EVENT.BIN`, `DA_3D.BIN`, `LEVEL_UP.BIN` |

`python -B -m engine.script.build --list` is authoritative.

## Runtime interfaces

The runtime layer consumes text and font outputs without taking ownership of
their editable sources:

| Interface | Contract |
| --- | --- |
| EVENT and MSGR dialogue | `event_vwf`, `event_packed_fetch`, and `msgr_text` provide proportional FONT16 rendering, packed-stream decoding, choice menus, and complete dynamic inserts. |
| COMBAT dialogue | `combat_packed_fetch` and `combat_vwf` preserve the three-row VM, progressive text, confirm fast-forward, page controls, the 320-pixel layout, and stock blank-cell advances. |
| Names and saves | `name_runtime` owns the five eight-character ASCII fields, derived FONT16/FONT8 rows, EVENT/MSGR inserts, and SAVE/LOAD consumers. `saveload_ui` composes translated strings and visual selector assets into both overlays. |
| Fixed interfaces | `config_ui`, `map_ui`, `normcom_help`, `dungeon_locations`, `hosi_messages`, and `fixed_text_fields` consume digest-bound text blocks and preserve each overlay's native storage and renderer ABI. |
| Compact-name consumers | `smallfont_vwf` and `itemname_runtime` redirect visible FONT8 consumers to complete names while retaining stock fixed records as compatibility data. |
| Equipment, fusion, and status | `equipment_ui`, `fusion_menu`, and `status_ui` own their complete multi-overlay patch sets so text, code, and precomposed graphics cannot overwrite one another. |

EVENT raw-choice inserts `0x8006` and `0x8007` use the separate stock path at
`0x06030bb4`. `name_runtime` redirects the first/last-name literals at
`0x06030d14` and `0x06030d1c`, replaces the three-glyph drawer with an
eight-glyph proportional loop, and returns the exact final X. MSGR applies the
same contract at `0x0606c63c`, with literals at `0x0606c79c` and `0x0606c7a4`.
Without the VWF capabilities, the loop detects the retained stock blitter and
reads its live fixed advance rather than treating the function's return value
as a glyph width.

### Runtime invariants and diagnostics

- EVENT's `0x0602bb50` and MSGR's `0x0606ebfc` phase gates remain stock.
  Progressive pacing counts actual blits after wait, page, and control handling.
- COMBAT's confirm-mode drain at `0x06059680..0x0605972a` and copier pointer at
  `0x060597d0` remain stock. Normal-mode pacing uses a separate visible budget.
- A committed COMBAT raw-zero cell is stored as private marker `0x07ff`, measured
  and rendered as a blank 16-pixel advance. Cleared, unused grid cells remain raw
  zero and are skipped, so preserving stock separators does not draw padding.
- Generate equipment stock references with
  `python -B -m engine.script.equipment_ui.reference`; use `--check` only after
  the ignored source-derived listing exists.
- The confirmed fusion-status chain is `0x06041f8c` -> `0x060414d0` ->
  `0x0602f272` (`DA52.EVC`) -> `0x0605751c`. It is separate from NORMCOM status.

Exact targets, load addresses, hook bytes, cave bounds, and ABI details are
maintained with each feature's `model.py`, runtime/assembly sources, and tests.

## Binary safety

`BinaryTarget` maps runtime addresses to file offsets by subtracting the target
load address. Every `BytePatch` declares its expected original bytes and an
equal-length replacement; application rejects bounds violations, overlap, stale
source bytes, and size mismatches before writing an output.

`CodePatch` assembles the original and replacement SH-2 at the real runtime
address and requires equal byte lengths. Non-trivial routines belong in `.s`
files. The assembler self-test checks known encodings independently through
Capstone. Fixed text in engine-owned binaries arrives as digest-bound generated
assets and is composed with code patches rather than emitted as a competing
whole-file replacement.

## Runtime verification

Visible or runtime-sensitive changes require a cold boot in an emulator or on
hardware. Source and byte-level checks do not establish rendering, timing,
transitions, input behavior, or save compatibility. Keep new reverse-engineering
evidence with its owning feature and cover stable addresses and ABIs in focused
tests. Record the built Track 1 hash, emulator or hardware, BIOS/boot method,
setup and input, and observed result with runtime evidence.
