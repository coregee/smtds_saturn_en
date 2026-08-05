"""Render shared MAZE/AUTOMAP dungeon locations as proportional strips."""

import hashlib
import json
import struct
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.dungeon_locations.model import (
    AUTOMAP_ASCII_CHOICES_DRAWER_SITE,
    AUTOMAP_ASCII_DRAWER,
    AUTOMAP_ASCII_NO_DATA_DRAWER_SITE,
    AUTOMAP_DELETE_DRAWER,
    AUTOMAP_DELETE_DRAWER_SITE,
    AUTOMAP_DELETE_SURFACE,
    AUTOMAP_DRAW_DESCRIPTOR,
    AUTOMAP_MARKER_PIXEL_LIMIT,
    AUTOMAP_NO_DATA_POINTER,
    AUTOMAP_NO_POINTER,
    AUTOMAP_RAW_DRAWER,
    AUTOMAP_YES_POINTER,
    BASE,
    BOTTOM_CODE,
    FONT16_BASE,
    KAI_FILE_COUNT,
    KAI_NAME_START,
    KAI_RECORD_COUNT,
    KAI_RECORD_SIZE,
    KAI_SOURCE_CATALOG_SHA256,
    LABEL_GAP,
    LABEL_SENTINEL,
    LANDING_RECORD_START,
    LANDING_SPECS,
    SPECS,
    TOP_CODE,
    KaiSpec,
    LandingSpec,
    LocationSpec,
)
from engine.script.fixed_text_fields.generated import (
    load_runtime_byte_fields,
    load_runtime_fields,
)
from engine.script.generated_asset import load_runtime_ui
from engine.script.patching import BinaryTarget, BytePatch, DigestPatch, PatchGroup
from engine.script.static_text import load_static_asset
from text.script.dungeon_locations import ASSET_PATH as DUNGEON_ASSET_PATH
from text.script.dungeon_locations import (
    RECORD_COUNT,
    RECORD_SIZE,
    TEXT_BYTES,
    record_kind,
)
from text.script.dungeon_locations import SOURCE_PATH as DUNGEON_SOURCE_PATH
from tools.sh2asm import assemble

EXTRACTED_ROOT = DEFAULT_CONTEXT.extracted_root
TEXT_GENERATED_ROOT = DEFAULT_CONTEXT.text_generated_root
METRICS_PATH = DEFAULT_CONTEXT.font_generated_root / "font16_metrics.json"
FONT16_PATH = DEFAULT_CONTEXT.build_root / "FONT16.FON"
ASM_ROOT = Path(__file__).with_name("asm")
AUTOMAP_ASCII_ASSET = Path("ascii_fields/AUTOMAPC.BIN.marker_ui.json")
AUTOMAP_WORD_ASSET = Path("fixed_words/AUTOMAPC.BIN.system.json")
AUTOMAP_SOURCE = Path("AUTOMAPC.BIN")
MARKER_UI_ORDER = (
    "marker_no_data",
    "marker_delete",
    "marker_yes",
    "marker_no",
)
MARKER_UI_ASCII_FIELDS = {
    "marker_no_data": 0x9AA8,
    "marker_yes": 0xA5E0,
    "marker_no": 0xA5E4,
}
MARKER_UI_DELETE_OFFSET = 0xA69C
MARKER_UI_CELL_LIMIT = 4


@dataclass(frozen=True)
class MarkerUiStrip:
    name: str
    bitmap: bytes
    cells: int
    width: int


def load_metrics(path: Path = METRICS_PATH) -> tuple[bytes, dict[str, int]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 2 or not document.get("complete"):
        raise ValueError(f"{path}: incomplete FONT16 metrics")
    code_limit = document["width_table"]["code_limit"]
    if not isinstance(code_limit, int) or not 1 <= code_limit <= 0x7FFF:
        raise ValueError(f"{path}: invalid width-table limit")
    widths = bytearray(code_limit)
    codes = {}
    for row in document["glyphs"]:
        code = row["code"]
        advance = row["advance"]
        if not 0 <= code < code_limit or not 1 <= advance <= 0xFF:
            raise ValueError(f"{path}: invalid glyph metrics")
        widths[code] = advance
        for text in (row["text"], *row.get("aliases", ())):
            if len(text) == 1:
                codes.setdefault(text, code)
    return bytes(widths), codes


@cache
def static_asset(context: EngineBuildContext = DEFAULT_CONTEXT):
    return load_static_asset(
        DUNGEON_ASSET_PATH,
        DUNGEON_SOURCE_PATH,
        context.text_generated_root,
        context.extracted_root,
    )


@cache
def runtime_metrics(
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[bytes, dict[str, int]]:
    return load_metrics(context.font_generated_root / "font16_metrics.json")


def load_location_texts(
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[str, ...]:
    asset = static_asset(context)
    output = []
    for index in range(RECORD_COUNT):
        name = record_kind(index)
        try:
            block = asset.blocks[name]
        except KeyError as error:
            raise ValueError(f"dungeon-location asset is missing {name}") from error
        if block.storage != "bytes":
            raise ValueError(f"dungeon-location block {name} is not bytes")
        raw = asset.data[block.offset : block.offset + block.size]
        if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
            raise ValueError(f"dungeon-location block {name} is not one string")
        output.append(raw[:-1].decode("ascii"))
    return tuple(output)


@cache
def location_texts(
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[str, ...]:
    return load_location_texts(context)


CANONICAL_TABLE_PATH = EXTRACTED_ROOT / DUNGEON_SOURCE_PATH


def text_width(
    text: str,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> int:
    widths, codes = runtime_metrics(context)
    width = 0
    for character in text:
        try:
            code = codes[character]
        except KeyError as error:
            raise ValueError(
                f"unsupported dungeon-location character {character!r}"
            ) from error
        if code >= len(widths) or not widths[code]:
            raise ValueError(f"dungeon-location glyph {code} has no width")
        width += widths[code]
    return width


def floor_text(raw: int) -> str:
    floor = raw - 256 if raw >= 128 else raw
    if floor == 0:
        return ""
    return f"B{-floor}F" if floor < 0 else f"{floor}F"


def location_lines(
    text: str,
    floor_width: int,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[str, str]:
    lines = text.replace("\r\n", "\n").replace("{n}", "\n").split("\n")
    if len(lines) > 2:
        raise ValueError(f"location label has more than two lines: {text!r}")
    if len(lines) == 2:
        return lines[0], lines[1]
    if text_width(text, context) <= 64:
        return text, ""

    words = text.split()
    if len(words) < 2:
        return text, ""
    lower_limit = 64 - floor_width - (LABEL_GAP if floor_width else 0)
    candidates = []
    for split in range(1, len(words)):
        upper = " ".join(words[:split])
        lower = " ".join(words[split:])
        upper_width = text_width(upper, context)
        lower_width = text_width(lower, context)
        pressure = max(upper_width / 64, lower_width / max(1, lower_limit))
        candidates.append((pressure, abs(upper_width - lower_width), upper, lower))
    _pressure, _balance, upper, lower = min(candidates)
    return upper, lower


def load_marker_name_aliases(
    document: object,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> dict[str, str]:
    if not isinstance(document, dict):
        raise ValueError("dungeon marker names must be an object")
    aliases = {}
    names = set(location_texts(context))
    for full_name, marker_name in document.items():
        if (
            not isinstance(full_name, str)
            or full_name not in names
            or not isinstance(marker_name, str)
            or not marker_name
            or marker_name != marker_name.strip()
        ):
            raise ValueError("dungeon marker name mapping is invalid")
        if text_width(marker_name, context) >= text_width(full_name, context):
            raise ValueError(
                f"dungeon marker name {marker_name!r} does not shorten {full_name!r}"
            )
        aliases[full_name] = marker_name

    displayed = [
        aliases.get(name, name) for name in dict.fromkeys(location_texts(context))
    ]
    if len(displayed) != len(set(displayed)):
        raise ValueError("dungeon marker display names must remain unique")
    return aliases


def label_catalog(
    data: bytes,
    spec: LocationSpec,
    marker_aliases: dict[str, str] | None = None,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[tuple[str, str, int], ...]:
    labels = []
    for index, text in enumerate(location_texts(context)):
        floor = floor_text(data[spec.table_file + index * RECORD_SIZE])
        floor_width = text_width(floor, context) if floor else 0
        if spec.automap:
            display = (marker_aliases or {}).get(text, text)
            label = (display, "", floor_width)
        else:
            label = (*location_lines(text, floor_width, context), floor_width)
        if label not in labels:
            labels.append(label)
    if len(labels) > 0x100:
        raise ValueError("dungeon-location sentinel supports at most 256 labels")
    return tuple(labels)


def render_codes(
    font16: bytes,
    codes: tuple[int, ...],
    *,
    limit: int = 64,
    cells: int = 4,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> bytes:
    pixel_width = cells * 16
    if not 1 <= cells <= 8 or not 1 <= limit <= pixel_width:
        raise ValueError(f"invalid dungeon-location width limit {limit}")
    widths = runtime_metrics(context)[0]
    for code in codes:
        if code >= len(widths) or not widths[code]:
            raise ValueError(f"dungeon-location glyph {code} has no width")
    width = sum(widths[code] for code in codes)
    rows = [0] * 16
    x = 0
    for code in codes:
        cell = font16[code * 32 : (code + 1) * 32]
        if len(cell) != 32:
            raise ValueError(f"{FONT16_PATH}: glyph {code} exceeds the font")
        for row in range(16):
            glyph_row = struct.unpack_from(">H", cell, row * 2)[0]
            for column in range(16):
                if not glyph_row & (0x8000 >> column):
                    continue
                natural_x = x + column
                screen_x = natural_x * limit // width if width > limit else natural_x
                if screen_x < pixel_width:
                    rows[row] |= 1 << (pixel_width - 1 - screen_x)
        x += widths[code]

    output = bytearray()
    for cell_index in range(cells):
        shift = (cells - 1 - cell_index) * 16
        for row in rows:
            output.extend(struct.pack(">H", row >> shift & 0xFFFF))
    return bytes(output)


def render_label(
    font16: bytes,
    text: str,
    *,
    limit: int = 64,
    cells: int = 4,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> bytes:
    _widths, code_by_text = runtime_metrics(context)
    try:
        codes = tuple(code_by_text[character] for character in text)
    except KeyError as error:
        raise ValueError(
            f"unsupported dungeon-location character {error.args[0]!r}"
        ) from error
    return render_codes(font16, codes, limit=limit, cells=cells, context=context)


def load_marker_ui_codes(
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path | None = None,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> dict[str, tuple[int, ...]]:
    extracted_root = extracted_root or CANONICAL_TABLE_PATH.parent
    load_address, ascii_fields = load_runtime_byte_fields(
        AUTOMAP_ASCII_ASSET,
        generated_root,
        extracted_root,
        expected_source=AUTOMAP_SOURCE,
        max_bytes=10,
    )
    if load_address != BASE:
        raise ValueError("AUTOMAP marker ASCII asset has the wrong load address")
    actual_ascii = {field.name: field.file_offset for field in ascii_fields}
    if actual_ascii != MARKER_UI_ASCII_FIELDS:
        raise ValueError("AUTOMAP marker ASCII asset has unexpected fields or offsets")

    codes_by_name = {}
    for field in ascii_fields:
        try:
            text = field.data[:-1].decode("ascii")
            codes = tuple(runtime_metrics(context)[1][character] for character in text)
        except (UnicodeDecodeError, KeyError) as error:
            raise ValueError(
                f"AUTOMAP marker field {field.name!r} is not FONT16-compatible ASCII"
            ) from error
        codes_by_name[field.name] = codes

    word_load_address, word_fields = load_runtime_fields(
        AUTOMAP_WORD_ASSET,
        generated_root,
        extracted_root,
        expected_source=AUTOMAP_SOURCE,
        max_words=7,
    )
    if word_load_address != BASE or len(word_fields) != 1:
        raise ValueError("AUTOMAP marker word asset has the wrong runtime shape")
    delete = word_fields[0]
    if (
        delete.name != "marker_delete"
        or delete.file_offset != MARKER_UI_DELETE_OFFSET
        or len(delete.words) != 7
        or any(word == 0 for word in delete.words)
    ):
        raise ValueError("AUTOMAP marker delete field has the wrong runtime shape")
    codes_by_name[delete.name] = delete.words

    if set(codes_by_name) != set(MARKER_UI_ORDER):
        raise ValueError("AUTOMAP marker runtime fields do not match the contract")
    return {name: codes_by_name[name] for name in MARKER_UI_ORDER}


def build_marker_ui_strips(
    font16: bytes,
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path | None = None,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[MarkerUiStrip, ...]:
    codes_by_name = load_marker_ui_codes(generated_root, extracted_root, context)
    widths = runtime_metrics(context)[0]
    strips = []
    for name in MARKER_UI_ORDER:
        codes = codes_by_name[name]
        if any(code >= len(widths) or not widths[code] for code in codes):
            raise ValueError(f"AUTOMAP marker field {name!r} has an invalid glyph")
        width = sum(widths[code] for code in codes)
        cells = max(1, (width + 15) // 16)
        if width > 64 or cells > MARKER_UI_CELL_LIMIT:
            raise ValueError(
                f"AUTOMAP marker field {name!r} is {width}px/{cells} cells; "
                "maximum is 64px/4 cells"
            )
        strips.append(
            MarkerUiStrip(
                name=name,
                bitmap=render_codes(font16, codes, context=context),
                cells=cells,
                width=width,
            )
        )
    return tuple(strips)


def build_label_bitmaps(
    font16: bytes,
    labels: tuple[tuple[str, str, int], ...],
    *,
    automap: bool = False,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> bytes:
    output = bytearray()
    for upper, lower, floor_width in labels:
        if automap:
            if lower:
                raise ValueError("AUTOMAP marker labels must use one display name")
            automap_label_geometry(upper, floor_width, context)
            output.extend(
                render_label(
                    font16,
                    upper,
                    limit=128,
                    cells=8,
                    context=context,
                )
            )
            continue
        lower_limit = 64 - floor_width - (LABEL_GAP if lower and floor_width else 0)
        if lower and lower_limit < 1:
            raise ValueError(f"no room for location lower row {lower!r}")
        output.extend(render_label(font16, upper, context=context))
        output.extend(
            render_label(
                font16,
                lower,
                limit=max(1, lower_limit),
                context=context,
            )
        )
    return bytes(output)


def automap_label_geometry(
    name: str,
    floor_width: int,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[int, int]:
    name_width = text_width(name, context)
    append_offset = (
        max(0, name_width - 64) + LABEL_GAP if floor_width and name_width >= 64 else 0
    )
    right_edge = max(name_width, 64 + append_offset + floor_width)
    if right_edge > AUTOMAP_MARKER_PIXEL_LIMIT:
        raise ValueError(
            f"AUTOMAP marker label {name!r} reaches {right_edge}px; "
            f"limit is {AUTOMAP_MARKER_PIXEL_LIMIT}px"
        )
    return append_offset, right_edge


def label_append_offsets(
    labels: tuple[tuple[str, str, int], ...],
    *,
    automap: bool = False,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> bytes:
    offsets = bytearray()
    for upper, lower, floor_width in labels:
        if automap:
            if lower:
                raise ValueError("AUTOMAP marker labels must use one display name")
            append_offset, _right_edge = automap_label_geometry(
                upper, floor_width, context
            )
            offsets.append(append_offset)
            continue
        lower_limit = 64 - floor_width - (LABEL_GAP if lower and floor_width else 0)
        if lower and lower_limit < 1:
            raise ValueError(f"no room for location lower row {lower!r}")
        lower_width = (
            min(text_width(lower, context), max(1, lower_limit)) if lower else 0
        )
        append_offset = lower_width + (LABEL_GAP if lower and floor_width else 0)
        if append_offset + floor_width > 64:
            raise ValueError(f"location floor does not fit after {lower!r}")
        offsets.append(append_offset)
    return bytes(offsets)


def patched_table(
    data: bytes,
    spec: LocationSpec,
    labels: tuple[tuple[str, str, int], ...],
    marker_aliases: dict[str, str] | None = None,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> bytes:
    table = bytearray(
        data[spec.table_file : spec.table_file + RECORD_COUNT * RECORD_SIZE]
    )
    for index, text in enumerate(location_texts(context)):
        offset = index * RECORD_SIZE
        if table[offset + 1] != 0 or not any(table[offset + 2 : offset + TEXT_BYTES]):
            raise ValueError(f"{spec.target.name}: invalid location record {index}")
        floor = floor_text(table[offset])
        floor_width = text_width(floor, context) if floor else 0
        if spec.automap:
            display = (marker_aliases or {}).get(text, text)
            label = (display, "", floor_width)
        else:
            label = (*location_lines(text, floor_width, context), floor_width)
        struct.pack_into(
            ">5H", table, offset + 2, LABEL_SENTINEL + labels.index(label), 0, 0, 0, 0
        )
    return bytes(table)


def canonical_prefix_replacements(
    canonical: bytes,
    labels: tuple[tuple[str, str, int], ...],
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> dict[bytes, bytes]:
    patched = patched_table(canonical, SPECS[0], labels, context=context)
    replacements = {}
    for index in range(RECORD_COUNT):
        offset = SPECS[0].table_file + index * RECORD_SIZE
        original_prefix = canonical[offset : offset + TEXT_BYTES]
        replacement_prefix = patched[
            index * RECORD_SIZE : index * RECORD_SIZE + TEXT_BYTES
        ]
        previous = replacements.setdefault(original_prefix, replacement_prefix)
        if previous != replacement_prefix:
            raise ValueError(
                "duplicate dungeon-location source records have different English labels"
            )
    return replacements


def canonical_name_replacements(
    canonical: bytes,
    labels: tuple[tuple[str, str, int], ...],
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> dict[tuple[int, bytes], bytes]:
    patched = patched_table(canonical, SPECS[0], labels, context=context)
    replacements = {}
    for index in range(RECORD_COUNT):
        source_offset = SPECS[0].table_file + index * RECORD_SIZE
        replacement_offset = index * RECORD_SIZE
        key = (
            canonical[source_offset],
            canonical[source_offset + 2 : source_offset + TEXT_BYTES],
        )
        replacement = patched[replacement_offset + 2 : replacement_offset + TEXT_BYTES]
        previous = replacements.setdefault(key, replacement)
        if previous != replacement:
            raise ValueError(
                "duplicate dungeon floor/name records have different English labels"
            )
    return replacements


def discover_kai_specs(
    replacements: dict[tuple[int, bytes], bytes],
    extracted_root: Path | None = None,
) -> tuple[KaiSpec, ...]:
    root = (extracted_root or CANONICAL_TABLE_PATH.parent) / "MAZEDATA"
    paths = tuple(sorted(root.glob("*KAI*.BIN")))
    if len(paths) != KAI_FILE_COUNT:
        raise ValueError(
            f"{root}: expected {KAI_FILE_COUNT} KAI files, found {len(paths)}"
        )

    catalog = hashlib.sha256()
    source_names = {name for _floor, name in replacements}
    specs = []
    record_count = 0
    for path in paths:
        original = path.read_bytes()
        source_sha256 = hashlib.sha256(original).hexdigest()
        catalog.update(path.name.encode("ascii"))
        catalog.update(b"\0")
        catalog.update(bytes.fromhex(source_sha256))

        offsets = []
        for offset in range(KAI_NAME_START, len(original) - 9, KAI_RECORD_SIZE):
            key = (original[offset - 1], original[offset : offset + 10])
            if key not in replacements:
                break
            offsets.append(offset)
        if not offsets:
            raise ValueError(f"{path}: has no leading KAI location records")

        discovered = set()
        for name in source_names:
            position = original.find(name)
            while position >= 0:
                discovered.add(position)
                position = original.find(name, position + 1)
        if tuple(sorted(discovered)) != tuple(offsets):
            expected = ", ".join(f"{offset:#x}" for offset in offsets)
            found = ", ".join(f"{offset:#x}" for offset in sorted(discovered)) or "none"
            raise ValueError(
                f"{path}: expected KAI location names at {expected}; found {found}"
            )

        relative = Path("MAZEDATA") / path.name
        specs.append(KaiSpec(relative, source_sha256, tuple(offsets)))
        record_count += len(offsets)

    if catalog.hexdigest() != KAI_SOURCE_CATALOG_SHA256:
        raise ValueError(f"{root}: KAI source catalog hash changed")
    if record_count != KAI_RECORD_COUNT:
        raise ValueError(
            f"{root}: expected {KAI_RECORD_COUNT} KAI location records, "
            f"found {record_count}"
        )
    return tuple(specs)


def validate_text_mirror(
    data: bytes,
    spec: LocationSpec,
    canonical: bytes | None = None,
) -> None:
    canonical = CANONICAL_TABLE_PATH.read_bytes() if canonical is None else canonical
    for index in range(RECORD_COUNT):
        canonical_start = SPECS[0].table_file + index * RECORD_SIZE
        target_start = spec.table_file + index * RECORD_SIZE
        if (
            canonical[canonical_start : canonical_start + TEXT_BYTES]
            != data[target_start : target_start + TEXT_BYTES]
        ):
            raise ValueError(
                f"{spec.target.name}: location record {index} does not match MAZE.BIN"
            )


def build_floor_cave(
    address: int,
    spec: LocationSpec,
    bitmaps: bytes,
    append_offsets: bytes,
    label_count: int,
    marker_strips: tuple[MarkerUiStrip, ...] = (),
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[bytes, dict[str, int]]:
    if bool(marker_strips) != spec.automap:
        raise ValueError(
            f"{spec.target.name}: marker strips must be present only for AUTOMAP"
        )
    wrapper_name = "automap_wrapper.s" if spec.automap else "maze_wrapper.s"
    source_parts = [(ASM_ROOT / wrapper_name).read_text(encoding="utf-8")]
    if spec.automap:
        source_parts.append((ASM_ROOT / "marker_ui.s").read_text(encoding="utf-8"))
    source_parts.append((ASM_ROOT / "floor_compositor.s").read_text(encoding="utf-8"))
    source = "\n".join(source_parts)
    widths, codes = runtime_metrics(context)
    symbols = {
        "TOP_CODE": TOP_CODE,
        "BOTTOM_CODE": BOTTOM_CODE,
        "TOP_ADDR": FONT16_BASE + TOP_CODE * 32,
        "BOTTOM_ADDR": FONT16_BASE + BOTTOM_CODE * 32,
        "FONT_BASE": FONT16_BASE,
        "CODE_0": codes["0"],
        "CODE_B": codes["B"],
        "CODE_F": codes["F"],
        "RETURN_ADDR": spec.return_address,
        "DRAW_NAME": spec.stock_name_drawer,
        "LABEL_BASE": LABEL_SENTINEL,
        "LABEL_COUNT": label_count,
    }
    marker_by_name = {strip.name: strip for strip in marker_strips}
    if spec.automap and tuple(marker_by_name) != MARKER_UI_ORDER:
        raise ValueError("AUTOMAP marker strips are not in canonical order")

    def marker_symbols(addresses: dict[str, int]) -> dict[str, int]:
        if not spec.automap:
            return {}
        yes_width = marker_by_name["marker_yes"].width
        no_width = marker_by_name["marker_no"].width
        return {
            "NO_DATA_POINTER": AUTOMAP_NO_DATA_POINTER,
            "YES_POINTER": AUTOMAP_YES_POINTER,
            "NO_POINTER": AUTOMAP_NO_POINTER,
            "ASCII_DRAWER": AUTOMAP_ASCII_DRAWER,
            "RAW_DRAWER": AUTOMAP_RAW_DRAWER,
            "DRAW_DESCRIPTOR": AUTOMAP_DRAW_DESCRIPTOR,
            "DELETE_SURFACE": AUTOMAP_DELETE_SURFACE,
            "NO_DATA_BITMAP": addresses["marker_no_data"],
            "DELETE_BITMAP": addresses["marker_delete"],
            "YES_BITMAP": addresses["marker_yes"],
            "NO_BITMAP": addresses["marker_no"],
            "NO_DATA_CELLS": marker_by_name["marker_no_data"].cells,
            "DELETE_CELLS": marker_by_name["marker_delete"].cells,
            "YES_CELLS": marker_by_name["marker_yes"].cells,
            "NO_CELLS": marker_by_name["marker_no"].cells,
            "NO_X_BIAS": max(0, yes_width - no_width),
        }

    marker_probe_addresses = {
        name: address + 0x1000 + index * 0x100
        for index, name in enumerate(MARKER_UI_ORDER)
    }
    probe = assemble(
        source,
        address,
        symbols={
            **symbols,
            **marker_symbols(marker_probe_addresses),
            "WIDTHS": address + 0x300,
            "APPEND_OFFSETS": address + 0x600,
            "BITMAPS": address + 0x800,
        },
    )
    if probe.warnings:
        raise ValueError(
            f"{spec.target.name}: dungeon-location warnings: {probe.warnings}"
        )
    widths_address = address + len(probe)
    append_offsets_address = widths_address + len(widths)
    if append_offsets_address & 3:
        raise ValueError("dungeon-location append-offset table is not aligned")
    bitmaps_address = (append_offsets_address + len(append_offsets) + 3) & ~3
    marker_bitmap_start = (bitmaps_address + len(bitmaps) + 3) & ~3
    marker_addresses = {}
    marker_cursor = marker_bitmap_start
    for strip in marker_strips:
        marker_addresses[strip.name] = marker_cursor
        marker_cursor += len(strip.bitmap)
    code = assemble(
        source,
        address,
        symbols={
            **symbols,
            **marker_symbols(marker_addresses),
            "WIDTHS": widths_address,
            "APPEND_OFFSETS": append_offsets_address,
            "BITMAPS": bitmaps_address,
        },
    )
    if code.warnings:
        raise ValueError(
            f"{spec.target.name}: dungeon-location warnings: {code.warnings}"
        )
    entry = "automap_entry" if spec.automap else "maze_entry"
    if code.labels[entry] != address:
        raise ValueError(f"{spec.target.name}: dungeon-location entry moved")
    payload = bytearray(code)
    payload.extend(widths)
    payload.extend(append_offsets)
    payload.extend(bytes((-len(payload)) % 4))
    if address + len(payload) != bitmaps_address:
        raise ValueError(f"{spec.target.name}: dungeon-location bitmap address drifted")
    payload.extend(bitmaps)
    payload.extend(bytes(marker_bitmap_start - address - len(payload)))
    for strip in marker_strips:
        if address + len(payload) != marker_addresses[strip.name]:
            raise ValueError(
                f"{spec.target.name}: marker bitmap {strip.name} address drifted"
            )
        payload.extend(strip.bitmap)
    return bytes(payload), code.labels


def build_group(
    spec: LocationSpec,
    extracted_root: Path | None = None,
    font16_path: Path = FONT16_PATH,
    canonical: bytes | None = None,
    generated_root: Path = TEXT_GENERATED_ROOT,
    marker_aliases: dict[str, str] | None = None,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> PatchGroup:
    extracted_root = extracted_root or CANONICAL_TABLE_PATH.parent
    source_path = extracted_root / spec.target.path
    original = source_path.read_bytes()
    actual_sha256 = hashlib.sha256(original).hexdigest()
    if actual_sha256 != spec.source_sha256:
        raise ValueError(
            f"{spec.target.name}: expected SHA-256 {spec.source_sha256}, "
            f"found {actual_sha256}"
        )
    validate_text_mirror(original, spec, canonical)
    font16 = font16_path.read_bytes()
    if len(font16) < 1872 * 32:
        raise ValueError(f"{font16_path}: FONT16 build is incomplete")

    if spec.automap and marker_aliases is None:
        raise ValueError("AUTOMAP marker display names were not supplied")
    labels = label_catalog(original, spec, marker_aliases, context)
    bitmaps = build_label_bitmaps(
        font16,
        labels,
        automap=spec.automap,
        context=context,
    )
    append_offsets = label_append_offsets(
        labels,
        automap=spec.automap,
        context=context,
    )
    marker_strips = (
        build_marker_ui_strips(font16, generated_root, extracted_root, context)
        if spec.automap
        else ()
    )
    cave_address = BASE + spec.cave_file
    cave, cave_labels = build_floor_cave(
        cave_address,
        spec,
        bitmaps,
        append_offsets,
        len(labels),
        marker_strips,
        context,
    )
    if spec.cave_file + len(cave) > spec.cave_limit:
        raise ValueError(
            f"{spec.target.name}: dungeon-location cave ends at "
            f"{spec.cave_file + len(cave):#x}, limit is {spec.cave_limit:#x}"
        )

    hook_address = BASE + spec.hook_file
    pool_address = BASE + spec.pool_file
    hook = assemble(
        f"mov.l {pool_address:#x},r0\njmp @r0\nnop",
        hook_address,
    )
    if hook.warnings or len(hook) != 6:
        raise ValueError(f"{spec.target.name}: invalid dungeon-location hook")

    entry = cave_labels["automap_entry" if spec.automap else "maze_entry"]
    wrapper = cave_labels[
        "automap_name_wrapper" if spec.automap else "maze_name_wrapper"
    ]
    marker_patches = ()
    if spec.automap:
        marker_ascii = cave_labels["marker_ascii_vwf"]
        marker_delete = cave_labels["marker_delete_vwf"]
        marker_patches = (
            BytePatch(
                "marker_no_data_drawer_pointer",
                AUTOMAP_ASCII_NO_DATA_DRAWER_SITE,
                struct.pack(">I", AUTOMAP_ASCII_DRAWER),
                struct.pack(">I", marker_ascii),
            ),
            BytePatch(
                "marker_choice_drawer_pointer",
                AUTOMAP_ASCII_CHOICES_DRAWER_SITE,
                struct.pack(">I", AUTOMAP_ASCII_DRAWER),
                struct.pack(">I", marker_ascii),
            ),
            BytePatch(
                "marker_delete_drawer_pointer",
                AUTOMAP_DELETE_DRAWER_SITE,
                struct.pack(">I", AUTOMAP_DELETE_DRAWER),
                struct.pack(">I", marker_delete),
            ),
        )
    table_size = RECORD_COUNT * RECORD_SIZE
    table_original = original[spec.table_file : spec.table_file + table_size]
    patches = (
        BytePatch("renderer_cave", cave_address, bytes(len(cave)), cave),
        BytePatch(
            "floor_hook",
            hook_address,
            original[spec.hook_file : spec.hook_file + len(hook)],
            bytes(hook),
        ),
        BytePatch(
            "floor_hook_target",
            pool_address,
            original[spec.pool_file : spec.pool_file + 4],
            struct.pack(">I", entry),
        ),
        BytePatch(
            "name_drawer_pointer",
            BASE + spec.name_pointer_file,
            struct.pack(">I", spec.stock_name_drawer),
            struct.pack(">I", wrapper),
        ),
        *marker_patches,
        DigestPatch(
            "location_table",
            BASE + spec.table_file,
            hashlib.sha256(table_original).hexdigest(),
            patched_table(original, spec, labels, marker_aliases, context),
        ),
    )
    return PatchGroup("dungeon_locations", spec.target, patches)


def build_landing_group(
    spec: LandingSpec,
    replacements: dict[bytes, bytes],
    extracted_root: Path | None = None,
) -> PatchGroup:
    source_path = (extracted_root or CANONICAL_TABLE_PATH.parent) / spec.path
    original = source_path.read_bytes()
    actual_sha256 = hashlib.sha256(original).hexdigest()
    if actual_sha256 != spec.source_sha256.lower():
        raise ValueError(
            f"{spec.path}: expected SHA-256 {spec.source_sha256.lower()}, "
            f"found {actual_sha256}"
        )

    offsets = tuple(
        LANDING_RECORD_START + index * RECORD_SIZE for index in range(spec.record_count)
    )
    discovered = tuple(
        offset
        for offset in range(len(original) - TEXT_BYTES + 1)
        if original[offset : offset + TEXT_BYTES] in replacements
    )
    if discovered != offsets:
        expected = ", ".join(f"{offset:#x}" for offset in offsets)
        found = ", ".join(f"{offset:#x}" for offset in discovered) or "none"
        raise ValueError(
            f"{spec.path}: expected mirrored location records at {expected}; "
            f"found {found}"
        )

    patches = []
    for index, offset in enumerate(offsets):
        prefix = original[offset : offset + TEXT_BYTES]
        patches.append(
            BytePatch(
                f"landing_location_{index:02d}",
                offset,
                prefix,
                replacements[prefix],
            )
        )
    target = BinaryTarget(spec.path.name, spec.path, 0)
    return PatchGroup("dungeon_locations", target, tuple(patches))


def build_kai_group(
    spec: KaiSpec,
    replacements: dict[tuple[int, bytes], bytes],
    extracted_root: Path | None = None,
) -> PatchGroup:
    source_path = (extracted_root or CANONICAL_TABLE_PATH.parent) / spec.path
    original = source_path.read_bytes()
    actual_sha256 = hashlib.sha256(original).hexdigest()
    if actual_sha256 != spec.source_sha256:
        raise ValueError(
            f"{spec.path}: expected SHA-256 {spec.source_sha256}, found {actual_sha256}"
        )

    patches = []
    for index, offset in enumerate(spec.name_offsets):
        source = original[offset : offset + 10]
        key = (original[offset - 1], source)
        try:
            replacement = replacements[key]
        except KeyError as error:
            raise ValueError(
                f"{spec.path}: unknown floor/name record at {offset:#x}"
            ) from error
        patches.append(
            BytePatch(
                f"kai_location_{index:02d}",
                offset,
                source,
                replacement,
            )
        )

    target = BinaryTarget(spec.path.name, spec.path, 0)
    return PatchGroup("dungeon_locations", target, tuple(patches))


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    canonical = (context.extracted_root / "MAZE.BIN").read_bytes()
    marker_aliases = load_marker_name_aliases(
        load_runtime_ui(context).section("dungeon_marker_names"),
        context,
    )
    canonical_labels = label_catalog(canonical, SPECS[0], context=context)
    landing_replacements = canonical_prefix_replacements(
        canonical,
        canonical_labels,
        context,
    )
    kai_replacements = canonical_name_replacements(
        canonical,
        canonical_labels,
        context,
    )
    kai_specs = discover_kai_specs(kai_replacements, context.extracted_root)
    font16_path = context.build_root / "FONT16.FON"
    return (
        *(
            build_group(
                spec,
                context.extracted_root,
                font16_path,
                canonical,
                context.text_generated_root,
                marker_aliases,
                context,
            )
            for spec in SPECS
        ),
        *(
            build_landing_group(spec, landing_replacements, context.extracted_root)
            for spec in LANDING_SPECS
        ),
        *(
            build_kai_group(spec, kai_replacements, context.extracted_root)
            for spec in kai_specs
        ),
    )
