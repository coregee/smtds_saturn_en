# Text module

`text/` owns the tracked source/target corpus, binary text formats, dialects,
encoding, layout, and generated text contracts. For setup, browser editing,
and full-disc builds, start with the [root README](../README.md).

## Ownership and layers

| Path | Contract |
| --- | --- |
| `corpus/` | Tracked Japanese, the editable active translation, review/exclusion state, optional language references, translator notes, and extraction metadata. This is the translation source of truth. |
| `layout/` | Tracked, text-free binary structure that extraction cannot infer. |
| `script/source_models.py` | Immutable source contracts. |
| `script/source_catalog/`, `script/sources.py` | Domain registrations, stable ordering, and source selection. |
| `script/formats/` | Binary storage such as EVE pointer banks. |
| `script/dialects/` | Control-code meanings. |
| `script/encoding/` | Character-to-word encoding. It consumes generated font metrics, not source font files. |
| `script/layouts/` | Runtime window geometry and layout rules. |
| `script/profiles.py` | Binds dialect, reader, encoding, layout, and required engine capabilities. |
| `script/message.py` | Resolves corpus messages through profiles without exposing those choices to formats. |
| `script/codec/` | Format-independent stock-glyph decoding. |
| `corpus/runtime_ui/`, `script/runtime_ui.py` | Runtime-patch strings and digest-bound section files, including `generated/runtime_ui/engine.json`. |
| `script/extract.py`, `script/repack.py` | Batch entry points; selection, codec preparation, and per-source work live in stage modules. |

The package implements eleven binary formats:

| Format | Storage and principal users |
| --- | --- |
| `eve` | Relocatable pointer banks used by five EVENT sources and sixteen COMBDATA talk sources. |
| `static_overlay` | Fixed spans relocated by engine patches: EVENT fusion confirmation, NAME, SAVE/LOAD, CONFIG, MAP2D, and dungeon locations. |
| `fixed_help` | Independent fixed-size BTL_HELP and NORMHELP records. |
| `name_description` | ITEMNAME and MAGNAME records with FONT8 names, FONT16 descriptions, and relocated full-name storage. |
| `indexed_bytes` | Pointer-indexed byte strings such as BTL_MES. |
| `indexed_words` | Pointer-indexed FONT16 strings in BTL_SRF and BUTU_SRF. |
| `fixed_bytes` | Fixed FONT8 records such as CHARNAME and DVLNAME. |
| `fixed_words` | Addressed FONT16 fields, including END_ROLL credit cells and system literals. |
| `mirrored_words` | One logical FONT16 table mirrored across binaries. |
| `deduplicated_words` | Irregular fixed fields sharing one logical value. |
| `ascii_fields` | Addressed NUL-terminated diagnostic strings. |

Format code owns storage; dialects own control codes; encodings own glyph
representation. EVENT and COMBDATA share the EVE layout but use different
dialects. Root EVE dialogue may run through `EVENT.BIN` or, for interior portrait
scenes, `MSGR.COF`. Its profile therefore requires both backends and
`name_runtime`; this is a consumer distinction, not another format.

## Commands

Run all commands from the repository root. Use `--list` for the authoritative
source names.

```powershell
python -B -m text.script.extract
python -B -m text.script.extract --list
python -B -m text.script.extract bosstalk
python -B -m text.script.repack
python -B -m text.script.repack --list
python -B -m text.script.repack evfile_0
python -B -m text.script.repack evfile_0 --message 34
python -B -m text.script.repack --select evfile_0:0
python -B -m text.script.audit_translations
python -B -m text.script.audit_translations --check
```

## Editing and validation

### Corpus language fields and review state

Every corpus text object has one active build target:

```json
{
  "jp": "original Japanese text",
  "tr": "active translation",
  "reviewed": false,
  "excluded": false
}
```

`tr` means *translation*, not Turkish. `reviewed` describes only the current
`tr` value. Saving any changed `tr`, including clearing it, sets `reviewed` to
`true`; the flag can also be toggled independently when reviewing an unchanged
line. `excluded` is independent review bookkeeping for text intentionally left
outside the ordinary review queue.

When extraction creates or regrounds a source whose `jp` is empty or contains
only whitespace and `{n}` line markers, that padding-only entry starts with
`excluded: true`. The current corpus migration marks 309 such placeholders.
Established entries retain their explicit state while source identity remains
stable, so this default does not override later review decisions.

The four UI statuses are mutually exclusive and use this precedence:
**Excluded**, **Reviewed**, **Translated** (a nonblank `tr`), then
**Untranslated**. Exclusion has no build semantics: it never bypasses token,
encoding, capacity, nonempty-translation, fallback, or release requirements.
Padding-only rows may remain blank because they have no translatable source,
not because they are excluded from review.
Extraction preserves `tr`, `reviewed`, and `excluded` while source identity is
stable. It resets that state only for a new or regrounded source identity, not
merely because a translator cleared `tr`.

For a translation derived from the current English, retain the original `jp`,
rename the existing `tr` key to `en`, then create a blank `tr` and set both
bookkeeping flags to `false`:

```json
{
  "jp": "original Japanese text",
  "en": "English reference text",
  "tr": "",
  "reviewed": false,
  "excluded": false
}
```

The optional `en` value is source/reference text, never a fallback build
target. The editor displays it in preference to `jp` when present, while
validation retains `jp` as the original source and opcode contract. Repacking
always consumes `tr`.

This schema is language-neutral, but the current translation assets are not
universally multilingual: the generated atlases and encoders are designed for
the project's Latin-script text. A target requiring unavailable characters,
diacritics, or another script must extend the font and encoding pipeline.

### Browser editor

```powershell
python -B -m text.editor
```

The loopback-only editor indexes every nested `jp`/`tr` pair under `corpus/`.
The file list, full-corpus header, and current query report separate counts for
Untranslated, Translated, Reviewed, and Excluded entries. The status selector
filters the result list using the precedence contract above, and entry cards
show the effective status.

The maintained preview paths use the same consumer profile, wrapper, dialect,
insert reservations, and generated metrics as the repacker. They distinguish
FONT16, FONT12, proportional FONT8, the mixed-width FNT8X12/FNT12X12 console,
and fixed-width 8x12 console text. Exact mapped surfaces use their real
geometry: FONT16 uses Ark Pixel's native 12-pixel raster, EVENT shows its
314-pixel usable region and three-pixel side margins, COMBAT uses 320 pixels,
and registered FONT8 runtime fields use their verified widths. Corpus metadata
selects FONT12 and raw-reader overrides, while shared entries expose their real
consumers as separate variants. A consumer whose window geometry is not proven
is explicitly labelled **advisory** and left unconstrained rather than being
assigned a guessed width.

For verified EVE dialogue choices, the editor renders the prompt with its one
to four options in a two-slot or four-slot visualization. Group membership and
option order are exact because they are recovered from the EVENT and COMBAT
reader opcodes. COMBAT groups retain both the lead and immediate prompt when a
choice script names both, so either corpus record exposes the same ordered
options, but only the final page of the final record is rendered as the prompt.
The COMBAT choice preview uses the verified runtime geometry: one 320-pixel
prompt row followed by one-row, 160-pixel option slots in a two-column grid. It
marks excess rows or pixel width as an exact overflow. EVENT choice window
geometry remains advisory until its runtime dimensions are mapped.

The capacity panel runs the owning format's canonical encoder against its
declared byte, word, pixel, row, or field budget. Exact checks identify native
fits, runtime-owned expansion, source fallback, encoding failures,
and hard overflow before an edit is saved. Formats whose result depends on the
rest of a relocatable body or on a generated shared dictionary also receive a
whole-body projection from the current corpus; those projections are labelled
**advisory** because a complete build can repack or retrain the shared data.
When no registered capacity contract exists, the editor reports that explicitly
instead of guessing from character count.

Saving changes only the selected `tr`, `reviewed`, and `excluded` scalar tokens,
preserves the rest of the file byte-for-byte, writes atomically, and rejects an
overwrite if any of those values changed on disk. Any changed `tr`, including
an empty replacement, is saved with `reviewed: true`; review-only and
exclusion-only changes do not rewrite the translation. Use `--no-browser` to
suppress automatic browser launch.

The sentence-aware wrapper is a one-time corpus migration, not build or preview
policy:

```powershell
python -B -m text.editor.apply_semantic_wrap --check
python -B -m text.editor.apply_semantic_wrap
```

It adds literal translation newlines only to FONT16 EVENT dialogue with no
authored break. It skips mixed/raw-reader fields and entries containing a
newline, `{n}`, `{NL}`, or `{OP:8001}`. Those newlines then remain authored
input; ordinary overflow wrapping is added only when needed.

### Token rules

Preserve punctuation, casing, and intentional stylisation. Solve encoding or
layout constraints in the tools or renderer rather than rewriting meaning.

The translation audit:

- reports empty `tr` fields and rejects tokens the target format cannot
  encode;
- reports the same four review-status totals as the editor across every
  canonical field, including excluded padding placeholders, while keeping
  padding-only rows out of the translatable-coverage denominator;
- requires every functional opcode, including pauses such as `{WAIT}` and
  `{BEAT}`, to occur as often as in Japanese;
- permits opcode reordering for target-language grammar, but not adding,
  removing, or changing opcode kinds or values;
- excludes `{first_name}` and `{last_name}` from parity counting so either may
  be swapped, added, or removed; and
- permits removal of layout-only `{n}` and `{NL}` because target layout and
  overflow wrapping own line placement.

Use this source-validation form while translations remain incomplete; the
explicit `python -B build --release` pipeline still rejects blank fields:

```powershell
python -B -m text.script.audit_translations --check --allow-empty
```

Word-based dialogue may use `{yen_symbol}` and `{mag_symbol}` for stock glyphs
`0x00c0` and `0x00c1`. The stock FONT16 hollow circle with radiating emphasis
strokes is `{maru_symbol}` (`0x0106`); it is distinct from the ordinary circle
at `0x010a`. Deliberately corrupted dialogue may use literal `♂` and
`←` for stock cells `0x00b8` and `0x00bf`, and `{white_square}` for
`0x00c0`. These cells retain a fixed 16-pixel advance rather than using the
Latin atlas.

Named inserts are dialect-specific:

| Token | EVENT word | COMBAT word |
| --- | ---: | ---: |
| `{demon_name}` | `0x8019` | `0x8010` |
| `{race}` | `0x801f` | `0x8012` |
| `{codename}` | `0x8023` | `0x8015` |
| `{first_name}`, `{last_name}` | `0x8006`, `0x8007` | - |
| `{city}`, `{ward}` | `0x801c`, `0x801b` | - |
| `{drink_name}`, `{item_name}` | `0x8017`, `0x8018` | - |
| `{event_id}` | `0x8022` | - |
| `{requested_item}`, `{offered_item}` | - | `0x8013`, `0x8014` |
| `{kyouji_name}`, `{rei_name}` | - | `0x8016`, `0x8017` |

Numeric `{INS:xxxx}` remains valid for reverse engineering and unknown insert
variants, but extraction emits a named token when known.

## EVE corpus

Each source is one JSON array under `corpus/eve/`. A logical record contains one
`jp`/`tr` pair, its `reviewed` and `excluded` state, and a `locations` array for
every physical page using it. Each location records bank, message, page,
original file offset, relative content range, and following boundary controls.
Concatenating every page's original content and controls reconstructs the source
message exactly.

Exact repeated Japanese pages within one source share one translation.
Extraction retains the translation, review state, and exclusion state by
bank/message/page coordinates while refreshing Japanese and metadata from the
binary and current atlases. Contextual variants may remain separate: split
their locations between otherwise identical records and give each a distinct
translation. Extraction preserves that split.

An EVE record may include a translator-authored `"note"`. Use it to explain how
a fragment combines with adjacent pages or branch context, describing the
complete construction rather than translating the fragment as a standalone
sentence. Extraction preserves the note with an established record and clears
it, like a stale translation and its bookkeeping state, when the message is
regrounded.

EVE pages split only at `0x8002` (window clear). `0x8003` is a wait: beside
`0x8002` or final `0x8000` it stays in `boundary_codes`; when dialogue
continues in the same window it becomes inline `{WAIT}`. Newlines remain inline
as `{n}`. A changed boundary or inline context clears that message's old
translation, review state, and exclusion state. Payload after the first
`0x8000` remains verbatim in the final page's `boundary_codes`.

A location has `"reader": "raw_u16"` only when it bypasses the text VM, which
selects the `event_menu` profile. COMBDATA defaults to `combat_dialogue`.
Likewise, `"font"` appears only for a nondefault runtime font. SHOPSMP's
Gouma-den options are raw-u16 FONT12 strings, while Victor's FONT12 prompt still
uses the EVENT VM; reader and font are therefore independent.

Use `python -B -m text.script.extract --check` to verify generated corpus data
without rewriting it.

## Other format contracts

### Static overlays and locations

- EVENT fusion confirmation, NAME, SAVE/LOAD, CONFIG, MAP2D, and MAZE speech
  option records live in
  `corpus/static/`. Records embed stable `kind` values, original spans,
  refreshed Japanese, and an editable target translation. SAVE is canonical
  for strings shared with LOAD. `fusion_confirmation_static` emits
  `EVENT.fusion_confirmation.json` for the engine's `status_ui` capability.
- Most static spans are FONT16. CONFIG controller actions index a private 12x12
  atlas in `CFG_SET.BIN`; repacking emits their translations as ASCII for the
  engine to rebuild it. The “change settings” and “finish settings” footers remain
  separate records. MAP2D destinations and its talk prompt are ASCII bitmap
  strips. MAP2D and MAZE speech choices retain source-owned raw FONT16 records,
  while their engine adapters precompose proportional `Yes`/`No` strips. Player
  city and ward come from `name_entry.json` and live `NAME_FW` rows.
- `corpus/locations/` is canonical for dungeon labels. MAZE's 144 physical
  records deduplicate to 24 Japanese labels; repacking expands them again.
  Extraction rejects conflicting translation definitions. AUTOMAP's matching
  12-byte floor/name prefixes must be byte-identical before receiving the same
  labels. The floor byte is dynamic and displays as `nF` or `BnF`. The engine
  also projects these translations into 56 landing records across 17
  `MAZEDATA/*ELV*.BIN` files after matching canonical prefixes.

Static overlays emit digest-bound blocks rather than competing engine-owned
whole files. The engine validates source, corpus, and font bindings before
composition.

### Fixed and indexed records

- BTL_HELP has 19 pair-packed FONT16, single-line records of 22 words;
  `smallfont_vwf` decodes them in COMBAT. NORMHELP has 24 pair-packed,
  two-line records of 42 words. Their
  `corpus/fixed_help/` rows own offsets and capacities; repacking preserves
  indentation and zero-fills unused words.
- ITEMNAME (287 records) and MAGNAME (255) use 96-byte
  `corpus/name_description/` records: four metadata bytes, an eight-byte FONT8
  name at `+0x04`, a 42-word FONT16 description at `+0x0c`, and padding.
  Repacking reserves `+0x5e` for a file-relative full-name pointer, leaving 41
  description words, and allocates `0xff`-terminated names only in verified
  zero padding. Names are limited to 32 encoded bytes and 80 pixels; the first
  eight bytes remain a stock-consumer fallback. Unknown metadata and
  untranslated content through its terminator remain byte-identical.
  `smallfont_vwf` handles pause ITEMNAME/MAGNAME grids, `itemname_runtime`
  handles ITEMNAME BUY/SELL and equipment lists, and MAGNAME descriptions use
  the packed NORMCOM callback.
- BTL_MES's `corpus/indexed_bytes/` source body starts at 0x800 after
  big-endian offsets to 358 `0x80`-terminated strings. Repacking reclaims the
  unused table tail and places the compacted body at 0x400; `smallfont_vwf`
  patches both COMBAT body-base literals while preserving the table ABI and
  exact file size. Bytes below `0x48` use FNT8X12; `0x48..0x7f` use FNT12X12
  from cell zero. Unknown visible cells use `{GLYPH:xx}`; controls use `{NUM}`
  or `{OP:xx}`. Extraction preserves translations by message index while
  refreshing Japanese through both atlases.
- BTL_SRF (363 rows) and BUTU_SRF (144) use a 0x400-byte big-endian pointer
  table followed by `0x8000`-terminated FONT16 strings, with word offsets.
  `corpus/indexed_words/` owns their indices and addresses. Unknown cells remain
  `{GLYPH:xxxx}`. Repacking relocates records with the shared dictionary; an
  engine hook decodes the selected record to bounded raw-u16 scratch.
- CHARNAME and DVLNAME rows in `corpus/fixed_bytes/` are eight-byte FONT8
  records identified by record number and address. A translation must fit both
  eight bytes and 64 pixels to replace the compatibility record directly.
  Longer names retain that physical record but are not release fallbacks when
  every visible consumer is redirected to a generated full-name pool. The
  repacker records all required capabilities atomically: CHARNAME's fixed
  dialogue record zero needs `status_ui` and `msgr_text`, records 1 through 5
  additionally need `smallfont_vwf`, `itemname_runtime`, and `fusion_menu`, and
  DVLNAME needs `status_ui`, `smallfont_vwf`, `combat_vwf`, `msgr_text`, and
  `fusion_menu`. Dynamic player selectors still use the entered codename.
  Zoma's mutable DVLNAME records 255 through 259 retain their stock eight-byte
  ABI and remain strict if they ever stop fitting; all currently contain
  `Shei` and fit.
- The 40 END_ROLL names in `corpus/fixed_words/` identify stable fields in the
  two 13-column credit grids. Zero runs decode as one surname/given-name space.
  Repacking emits every exact encoded name to the `fixed_text_fields` runtime.
  The main-credit consumer draws six proportional cells and both staff-test
  consumers draw seven; names wider than the main 96-pixel strip are compressed
  horizontally without changing or abbreviating the corpus wording.

### Fixed, mirrored, and deduplicated words

- AUTOMAP, COMBAT, END_ROLL, HOSI, LEVEL_UP, LOAD, and MAZE system literals use
  `fixed_words`. Each field declares terminator ownership and whether zero means
  spacing, a line break, or padding. A native over-capacity translation remains
  Japanese and is reported unless the field declares a larger runtime-owned
  capacity; those complete encoded records are emitted in the generated asset.
- MAZE's interaction prompt and 14 environment messages allow two-glyph
  packing into 18 runtime words despite 14-word source fields. Its engine
  composes complete messages across the stock 14-cell strip within a 224-pixel
  panel. Dynamic ITEMNAME values use the same compositor; currency keeps stock
  symbols and digits while moving `Obtained ` before the value and suppressing
  the Japanese suffix.
- COMBAT, MAZE, AUTOMAP, END_ROLL, HOSI, LEVEL_UP, and LOAD are engine-owned, so
  repacking emits `generated/fixed_words/` assets for the corresponding engine
  runtime.
  HOSI's eight full horoscope messages are word-boundary wrapped to at most
  three 20-cell rows, relocated into overlay padding, and selected by redirected
  source literals.
- `corpus/mirrored_words/` owns NORMCOM races (five mirrors with three- or
  four-word records) and affinities (three 17-word mirrors). Extraction rejects
  disagreement. All 43 race records are runtime-covered across NORMCOM, EVENT,
  DA_3D, COMBAT, and MSGR only when `status_ui`, `combat_vwf`, and `msgr_text`
  are emitted together. Affinity copies exist only in NORMCOM, EVENT, and
  DA_3D; the atomic `status_ui` capability redirects every visible consumer of
  their first 66 records to complete translated data. Capacity fallbacks in those
  verified domains are therefore reported as runtime-covered instead of
  Japanese release fallbacks. Affinity records 66-95 are a stock fallback
  reserve and all currently fit their physical fields.
- COMBAT's separate enemy-analysis table maps 66 five-word records to 41 short
  summaries in `COMBAT.analysis_affinities.json`. It uses a dedicated FONT8
  renderer and does not replace detailed NORMCOM affinity translations.
- `corpus/fixed_words/COMBAT.BIN.condition_messages.json` owns seven live
  16-voice condition blocks: charmed, happy, confused, enraged, talk-blocked,
  allied-veto, and full-moon. Each runtime selector indexes a complete 22-word
  record at `base + voice * 0x2c`; the corpus also owns the adjacent COMP signal
  record, for 113 independently translated records in total.
- A condition record, not each stock zero-delimited Japanese phrase, is the
  translation unit. English is packed contiguously, followed by one `0x8000`
  terminator and zero padding. This prevents fragment-local packing slack from
  becoming accidental visible spaces. The residual deduplicated COMBAT corpus
  owns only 14 logical/20 physical name and diagnostic fields outside the live
  condition table.
- SNDTEST and TEST3D use `corpus/ascii_fields/` rows with address, capacity, and
  NUL policy. Repacking preserves meaningful trailing spaces and rejects
  non-ASCII or over-capacity translations.

## Repacking and generated contracts

The repacker validates the corpus against a fresh extraction before reading
`tr`. An EVE message translates only when all source pages have nonempty
translations; partial messages preserve the complete Japanese stream. Layout
failures remain explicit fallbacks, while a complete translated EVE message
that exceeds its bank fails with required and available sizes.

Focused repacks report fallbacks. The explicit `python -B build --release`
pipeline adds `--fail-on-fallbacks`:

```powershell
python -B -m text.script.repack --check --fail-on-fallbacks
```

Outputs preserve source-relative paths under `rom/build/`; untranslated sources
remain byte-identical. Engine-owned overlays instead produce deterministic,
digest-bound, named `u16be` or byte JSON blocks under ignored `generated/`.
NAME uses FONT16 prompts and NUL-terminated ASCII controller labels; CONFIG uses
FONT16 labels plus ASCII actions and footers; EVENT fusion confirmation uses
FONT16 blocks consumed by `status_ui`; MAP2D and dungeon locations use ASCII
blocks. Regenerate these contracts after corpus edits. The final repack summary
reports required runtime capabilities, but repacking does not install engine
hooks.

### Layout and packed codec

EVENT uses generated FONT16 metrics for overflow wrapping and preserves manual
translation newlines as hard boundaries. Its build-time layout reserves an
eight-`W`/80-pixel value for dynamic EVENT/MSGR inserts.

COMBAT preserves each stock `0x8002` page/window clear and leaves automatic
line placement and any additional overflow pages to its live three-row
renderer. Within each stock page, the repacker encodes automatic line
boundaries as private marker `0x07fe`, which the runtime restores to a space,
and prefixes static words with exact-width markers. Insert words carry suffix
widths; compound or prefixed inserts use a hidden measure pass. Packed-stream
markers occupy `0x0750..0x07fe`. The runtime-only grid marker `0x07ff`
represents a committed stock zero separator and retains its native blank
16-pixel advance, while unused zero-filled grid cells remain invisible. The
renderer replays a complete word after an `0x8002` clear when the third row
overflows, preserves progressive glyph timing, and treats authored newlines as
hard `0x8001`.

Before rebuilding banks, the repacker trains up to 57 deterministic byte-pair
tokens from wrapped FONT16 VM streams. It writes
`generated/event_codec.json` and
`generated/event_codec_binding.json`, which binds the dictionary to every EVE
and indexed-word output using it. A subset repack removes other registered
dictionary outputs from `rom/build/` so incompatible generations cannot mix.

Two tokens occupy one 16-bit word. Tokens `0..62` are space, digits, and Latin
letters; `63..119` expand to two through seven common glyphs. Punctuation,
inline operations, and page controls remain direct 16-bit words. Packed words
have high bytes `0x08..0x7f`; subtract eight for the first token. The low byte
holds the biased second token, or `0x00` for an odd run. Thus `0x08` is a
present token zero and expands to the FONT16 space cell 267; it must not be
confused with an absent second token. Japanese glyph words use high bytes
`0x00..0x07`, controls use `0x80`, and raw zero remains padding or indentation.

COMBAT dialogue requires `combat_packed_fetch` and `combat_vwf`. BTL_SRF and
BUTU_SRF require only `combat_packed_fetch`. Negotiation choices remain packed
inside the fixed option grid. Raw EVENT menus remain direct u16. `event_menu`
additionally requires proportional raw-glyph wrappers in EVENT and MSGR.

### Focused builds

`--message` limits a one-source EVE build to one or more message indices.
Unselected messages remain byte-for-byte Japanese even if their corpus rows
contain translations. Repeat it for more indices; static sources remain atomic.

`--select SOURCE:INDEX[,INDEX...]` is the deterministic batch form. Every
registered EVE bank is rebuilt, with translations only at selected messages;
unlisted banks and messages remain Japanese. Fixed-help files and static assets
are rebuilt atomically. Repeat `--select` for more sources. `--check` validates
the exact selection.
