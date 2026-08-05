"""COMBAT-specific FONT8 data, validation, and runtime builders."""

import struct
from pathlib import Path
from typing import Any

from engine.script.name.fields import CODENAME_BYTES
from engine.script.sh2 import assemble_checked
from engine.script.smallfont.model import BASE
from engine.script.smallfont.renderer import (
    build_character_panel_data,
    build_packed_full_name_drawer,
)
from engine.script.text_render.font16_vwf import (
    align_up,
    build_surface_blitter_cave,
    build_width_returning_surface_cave,
)
from engine.script.text_render.font_metrics import font16_width_layout

ASM_ROOT = Path(__file__).with_name("asm")

COMBAT_RACE_SOURCE = 0x06070DD0

COMBAT_RACE_SOURCE_STRIDE = 7

COMBAT_RACE_COUNT = 43

COMBAT_RACE_RECORD_SIZE = 8

COMBAT_DVL_SOURCE = 0x0023F5D0

COMBAT_DVL_COUNT = 319

COMBAT_STOCK_GLYPH = 0x06046BD0

COMBAT_COUNTED_DRAWER = 0x060500D8

COMBAT_NAME_MAX_WIDTH = 96

COMBAT_COUNTED_POINTER_SITES = (
    0x0604FD54,
    0x0605009C,
)

COMBAT_BTL_MES_BODY_BASE_SITES = (
    0x0604D29C,
    0x0604D5E0,
)

COMBAT_AFFINITY_SOURCE = 0x06070F5E

COMBAT_AFFINITY_COUNT = 66

COMBAT_AFFINITY_RECORD_SIZE = 10

COMBAT_AFFINITY_MAX_WIDTH = 112

COMBAT_AFFINITY_POINTER_SITE = 0x0604FF00

COMBAT_AFFINITY_STOCK_DRAWER = 0x06050130

COMBAT_SURFACE_DRAWER_POINTER = 0x0604DDCC

COMBAT_SURFACE_ADVANCE_SITE = 0x0604DD68

COMBAT_SURFACE_STOCK_DRAWER = 0x06046D48

COMBAT_HELP_DRAWER_POINTER = 0x06047A80

COMBAT_HELP_CURSOR_START_SITE = 0x060479BC

COMBAT_HELP_BASE_X_SCALE_SITE = 0x060479DA

COMBAT_HELP_NEWLINE_X_SITE = 0x06047A18

COMBAT_HELP_DRAW_X_SITE = 0x06047A1E

COMBAT_HELP_ADVANCE_SITE = 0x06047A26

COMBAT_HELP_CURSOR_WIDTH_SITE = 0x06047A28

COMBAT_HELP_PACKED_LIMIT = 128

COMBAT_HELP_PACKED_SPACE = 267

COMBAT_BATTLE_ITEM_STOCK_DRAWER = 0x060496BC

COMBAT_BATTLE_MENU_SKILL_POINTER_SITE = 0x060494D0

COMBAT_BATTLE_ITEM_POINTER_SITES = (
    0x06048220,
    0x06048410,
    0x06048774,
    0x060489F0,
    0x06048B70,
    0x06048D44,
    0x060490B4,
    0x0604933C,
    0x06049404,
    COMBAT_BATTLE_MENU_SKILL_POINTER_SITE,
    0x060495B4,
    0x060496A4,
)

COMBAT_BATTLE_ITEM_STRIDE = 0x6C

COMBAT_BATTLE_ITEM_Y_OFFSET = COMBAT_BATTLE_ITEM_STRIDE * 2

COMBAT_BATTLE_ITEM_MAX_WIDTH = 80

COMBAT_EVENT_ITEM_POINTER = 0x060526B0

COMBAT_EVENT_ITEM_STOCK_DRAWER = 0x060523D0

COMBAT_EVENT_ITEM_FRAMEBUFFER_POINTER = 0x060721DC

COMBAT_EVENT_ITEM_BASE_POINTER = 0x0607221C

COMBAT_EVENT_ITEM_COLUMN_WIDTH = 106

COMBAT_EVENT_ITEM_ROW_HEIGHT = 12

COMBAT_EVENT_ITEM_START_X = 16

COMBAT_EVENT_ITEM_START_Y = 4

COMBAT_EVENT_ITEM_MAX_WIDTH = 80

COMBAT_RESULT_LABEL_GLYPH_POINTER = 0x0604EF38

COMBAT_RESULT_NAME_POINTER = 0x0604EF4C

COMBAT_RESULT_CHARACTER_NAME_POINTER = 0x0604F010

COMBAT_RESULT_ITEM_POINTER = 0x0604EF54

COMBAT_RESULT_NAME_STOCK_DRAWER = 0x0604F168

COMBAT_RESULT_ITEM_STOCK_DRAWER = 0x0604F214

COMBAT_RESULT_NAME_DEST0 = 0x25E6902E

COMBAT_RESULT_NAME_DEST1 = 0x25E6905E

COMBAT_RESULT_ITEM_DESTINATIONS = (
    0x25E6B82E,
    0x25E6B85E,
    0x25E6C82E,
    0x25E6C85E,
)

COMBAT_RESULT_LABEL_SOURCES = {
    "life_stones": bytes.fromhex("5d4c45"),
    "beads": bytes.fromhex("5c41ce7546"),
}

COMBAT_FONT16_POINTER = 0x060721E0

COMBAT_GLYPH_PATTERN_LUT = 0x0606F124

COMBAT_GLYPH_MASK_LUT = 0x0606F144

COMBAT_SURFACE_MAX_WIDTH = 176

COMBAT_HELP_START_X = 16

COMBAT_HELP_MAX_WIDTH = 336

COMBAT_SMALLFONT_CAVE_LIMIT = 0x0C00

COMBAT_ANALYSIS_CAVE = 0x06021C00

COMBAT_ANALYSIS_CAVE_LIMIT = 0x06024000

COMBAT_ANALYSIS_SKILL_POINTER_SITE = 0x0604FEF0


def build_combat_race_pool(codes: dict[str, int], rows: list[dict]) -> bytes:
    races = tuple(
        row.get("tr", "").strip() for row in rows if row.get("table") == "races"
    )
    if len(races) != COMBAT_RACE_COUNT or not all(races):
        raise ValueError(
            f"runtime UI contract: expected {COMBAT_RACE_COUNT} translated races"
        )
    # COMBAT's demon-ID thresholds only select the first 42 records. Its
    # physical 43rd race record is blank rather than the general table's Human.
    races = (*races[:-1], "")
    pool = bytearray()
    for race in races:
        text = f"{race}:" if race else ""
        if len(text) > COMBAT_RACE_RECORD_SIZE:
            raise ValueError(
                f"COMBAT analysis race exceeds "
                f"{COMBAT_RACE_RECORD_SIZE} FONT8 cells: {text!r}"
            )
        try:
            encoded = bytes(codes[character] for character in text)
        except KeyError as error:
            raise ValueError(
                f"unsupported COMBAT analysis FONT8 character "
                f"{error.args[0]!r} in {text!r}"
            ) from error
        pool.extend(encoded)
        pool.extend(bytes(COMBAT_RACE_RECORD_SIZE - len(encoded)))
    return bytes(pool)


def build_combat_counted_drawer(
    address: int,
    blitter_address: int,
    widths_address: int,
    race_pool_address: int,
    name_offsets_address: int,
    name_pool_address: int,
) -> bytes:
    """Draw analyzer races/names by compact record content, not pointer identity."""
    source = (ASM_ROOT / "counted_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "RACE_SOURCE": COMBAT_RACE_SOURCE,
                "RACE_SOURCE_STRIDE": COMBAT_RACE_SOURCE_STRIDE,
                "RACE_COUNT": COMBAT_RACE_COUNT,
                "RACE_POOL": race_pool_address,
                "RACE_RECORD_SIZE": COMBAT_RACE_RECORD_SIZE,
                "DVL_SOURCE": COMBAT_DVL_SOURCE,
                "DVL_COUNT": COMBAT_DVL_COUNT,
                "NAME_OFFSETS": name_offsets_address,
                "NAME_POOL": name_pool_address,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STRIDE": 0x0200,
                "STOCK_GLYPH": COMBAT_STOCK_GLYPH,
                "STOCK_COUNTED": COMBAT_COUNTED_DRAWER,
            },
            context="COMBAT analysis small-font",
        )
    )


def encode_text(
    text: str,
    codes: dict[str, int],
    widths: bytes,
    max_width: int,
    context: str,
) -> list[int]:
    try:
        encoded = [codes[character] for character in text]
    except KeyError as error:
        raise ValueError(
            f"unsupported {context} character {error.args[0]!r} in {text!r}"
        ) from error
    width = sum(widths[code] for code in encoded)
    if width > max_width:
        raise ValueError(f"{context} exceeds {max_width}px ({width}px): {text!r}")
    return encoded


def build_combat_name_data(
    codes: dict[str, int],
    widths: bytes,
    rows: list[dict],
) -> tuple[bytes, bytes]:
    if (
        not isinstance(rows, list)
        or len(rows) != COMBAT_DVL_COUNT
        or any(
            not isinstance(row, dict)
            or row.get("record") != index
            or not isinstance(row.get("tr"), str)
            or not row["tr"].strip()
            for index, row in enumerate(rows)
        )
    ):
        raise ValueError(
            "runtime UI contract: expected "
            f"{COMBAT_DVL_COUNT} sequential translated demon names"
        )
    offsets = bytearray()
    pool = bytearray()
    for index, row in enumerate(rows):
        if len(pool) > 0xFFFF:
            raise ValueError("COMBAT analysis demon-name pool exceeds u16 offsets")
        offsets.extend(struct.pack(">H", len(pool)))
        glyphs = encode_text(
            row["tr"].strip(),
            codes,
            widths,
            COMBAT_NAME_MAX_WIDTH,
            f"COMBAT analysis demon name {index}",
        )
        if len(glyphs) >= 32:
            raise ValueError(f"COMBAT analysis demon name {index} exceeds 31 bytes")
        pool.extend(glyphs)
        pool.append(0)
    return bytes(offsets), bytes(pool)


def load_combat_affinity_strings(
    rows: list[dict],
    combat_source: bytes,
) -> tuple[str, ...]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("runtime UI contract: expected combat affinities")
    translations = {}
    for index, row in enumerate(rows):
        context = f"runtime UI combat affinities: row {index}"
        required = {"source_hex", "jp", "tr", "reviewed", "excluded"}
        if (
            not isinstance(row, dict)
            or not required.issubset(row)
            or set(row) - required - {"en"}
        ):
            raise ValueError(
                f"{context}: expected source_hex, jp, tr, reviewed, excluded, "
                "and optional en"
            )
        try:
            source = bytes.fromhex(row["source_hex"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{context}: invalid source_hex") from error
        if len(source) != COMBAT_AFFINITY_RECORD_SIZE:
            raise ValueError(
                f"{context}: source must be {COMBAT_AFFINITY_RECORD_SIZE} bytes"
            )
        if (
            not isinstance(row["jp"], str)
            or not row["jp"]
            or not isinstance(row["tr"], str)
            or not row["tr"].strip()
            or not isinstance(row["reviewed"], bool)
            or not isinstance(row["excluded"], bool)
            or ("en" in row and not isinstance(row["en"], str))
        ):
            raise ValueError(f"{context}: invalid translation metadata")
        if source in translations:
            raise ValueError(f"{context}: duplicate compact affinity source")
        translations[source] = row["tr"].strip()

    table_offset = COMBAT_AFFINITY_SOURCE - BASE
    raw = combat_source[
        table_offset : table_offset
        + COMBAT_AFFINITY_COUNT * COMBAT_AFFINITY_RECORD_SIZE
    ]
    if len(raw) != COMBAT_AFFINITY_COUNT * COMBAT_AFFINITY_RECORD_SIZE:
        raise ValueError("COMBAT compact affinity source exceeds the overlay")
    used = set()
    strings = []
    for index in range(COMBAT_AFFINITY_COUNT):
        start = index * COMBAT_AFFINITY_RECORD_SIZE
        record = raw[start : start + COMBAT_AFFINITY_RECORD_SIZE]
        try:
            strings.append(translations[record])
        except KeyError as error:
            raise ValueError(
                "runtime UI contract: no translation for compact "
                f"affinity {index} ({record.hex()})"
            ) from error
        used.add(record)
    if used != set(translations):
        raise ValueError("runtime UI contract contains unused compact affinity rows")
    return tuple(strings)


def build_combat_affinity_data(
    codes: dict[str, int],
    widths: bytes,
    rows: list[dict],
    combat_source: bytes,
) -> tuple[bytes, bytes]:
    offsets = bytearray()
    pool = bytearray()
    for index, text in enumerate(load_combat_affinity_strings(rows, combat_source)):
        if len(pool) > 0xFFFF:
            raise ValueError("COMBAT analysis affinity pool exceeds u16 offsets")
        offsets.extend(struct.pack(">H", len(pool)))
        glyphs = encode_text(
            text,
            codes,
            widths,
            COMBAT_AFFINITY_MAX_WIDTH,
            f"COMBAT analysis affinity {index}",
        )
        pool.extend(glyphs)
        pool.append(0)
    return bytes(offsets), bytes(pool)


def load_combat_result_labels(
    rows: list[dict],
) -> dict[str, str]:
    if not isinstance(rows, list):
        raise ValueError("runtime UI contract: expected combat result labels")
    labels = {}
    for index, row in enumerate(rows):
        context = f"runtime UI combat result labels: row {index}"
        required = {"key", "source_hex", "jp", "tr", "reviewed", "excluded"}
        if (
            not isinstance(row, dict)
            or not required.issubset(row)
            or set(row) - required - {"en"}
        ):
            raise ValueError(
                f"{context}: expected key, source_hex, jp, tr, reviewed, excluded, "
                "and optional en"
            )
        key = row["key"]
        if key not in COMBAT_RESULT_LABEL_SOURCES or key in labels:
            raise ValueError(f"{context}: unexpected or duplicate key {key!r}")
        try:
            source = bytes.fromhex(row["source_hex"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{context}: invalid source_hex") from error
        if source != COMBAT_RESULT_LABEL_SOURCES[key]:
            raise ValueError(
                f"{context}: source_hex does not match COMBAT's result label"
            )
        if (
            not isinstance(row["jp"], str)
            or not row["jp"]
            or not isinstance(row["tr"], str)
            or not row["tr"].strip()
            or not isinstance(row["reviewed"], bool)
            or not isinstance(row["excluded"], bool)
            or ("en" in row and not isinstance(row["en"], str))
        ):
            raise ValueError(f"{context}: invalid translation metadata")
        labels[key] = row["tr"].strip()
    if set(labels) != set(COMBAT_RESULT_LABEL_SOURCES):
        missing = sorted(set(COMBAT_RESULT_LABEL_SOURCES) - set(labels))
        raise ValueError(f"runtime UI contract: missing combat result labels {missing}")
    return labels


def build_combat_result_label_data(
    codes: dict[str, int],
    widths: bytes,
    rows: list[dict],
) -> dict[str, bytes]:
    labels = load_combat_result_labels(rows)
    return {
        key: bytes(
            encode_text(
                labels[key],
                codes,
                widths,
                88,
                f"COMBAT result label {key}",
            )
        )
        + b"\0"
        for key in COMBAT_RESULT_LABEL_SOURCES
    }


def build_combat_result_label_drawer(
    address: int,
    life_stones_address: int,
    beads_address: int,
    blitter_address: int,
    widths_address: int,
) -> bytes:
    source = (ASM_ROOT / "result_label_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "LIFE_STONES": life_stones_address,
                "BEADS": beads_address,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STOCK": COMBAT_STOCK_GLYPH,
            },
            context="COMBAT result labels small-font",
        )
    )


def build_combat_result_name_drawer(
    address: int,
    blitter_address: int,
    widths_address: int,
    character_offsets_address: int,
    character_pool_address: int,
) -> bytes:
    source = (ASM_ROOT / "result_name_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "CODENAME": CODENAME_BYTES,
                "OFFSETS": character_offsets_address,
                "POOL": character_pool_address,
                "DEST0": COMBAT_RESULT_NAME_DEST0,
                "DEST1": COMBAT_RESULT_NAME_DEST1,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
            },
            context="COMBAT result character name small-font",
        )
    )


def build_combat_result_item_drawer(
    address: int,
    blitter_address: int,
    widths_address: int,
) -> bytes:
    source = (ASM_ROOT / "result_item_drawer.s").read_text(encoding="utf-8")
    symbols = {
        "ITEM_BEFORE_FIRST": 0x00228BA0,
        "ITEM_BASE": 0x00228C00,
        "WIDTHS": widths_address,
        "PIXEL": blitter_address,
        "MAX_WIDTH": COMBAT_BATTLE_ITEM_MAX_WIDTH,
    }
    symbols.update(
        {
            f"DEST{index}": destination
            for index, destination in enumerate(COMBAT_RESULT_ITEM_DESTINATIONS)
        }
    )
    return bytes(
        assemble_checked(
            source,
            address,
            symbols,
            context="COMBAT result ITEMNAME small-font",
        )
    )


def build_combat_event_item_drawer(
    address: int,
    blitter_address: int,
    widths_address: int,
) -> bytes:
    source = (ASM_ROOT / "combat_event_item_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "ITEM_BASE_POINTER": COMBAT_EVENT_ITEM_BASE_POINTER,
                "ITEM_FULL_NAME_FROM_COMPACT": 0x5A,
                "FRAMEBUFFER_POINTER": COMBAT_EVENT_ITEM_FRAMEBUFFER_POINTER,
                "FRAMEBUFFER_STRIDE": 320,
                "FRAMEBUFFER_BYTE_STRIDE": 160,
                "COLUMN_WIDTH": COMBAT_EVENT_ITEM_COLUMN_WIDTH,
                "ROW_HEIGHT": COMBAT_EVENT_ITEM_ROW_HEIGHT,
                "START_X": COMBAT_EVENT_ITEM_START_X,
                "START_Y": COMBAT_EVENT_ITEM_START_Y,
                "MAX_WIDTH": COMBAT_EVENT_ITEM_MAX_WIDTH,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
            },
            context="COMBAT event-dialogue item grid small-font",
        )
    )


def build_combat_affinity_drawer(
    address: int,
    offsets_address: int,
    pool_address: int,
    blitter_address: int,
    widths_address: int,
) -> bytes:
    source = (ASM_ROOT / "analysis_affinity_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "SOURCE": COMBAT_AFFINITY_SOURCE,
                "SOURCE_SIZE": (COMBAT_AFFINITY_COUNT * COMBAT_AFFINITY_RECORD_SIZE),
                "SOURCE_STRIDE": COMBAT_AFFINITY_RECORD_SIZE,
                "COUNT": COMBAT_AFFINITY_COUNT,
                "OFFSETS": offsets_address,
                "POOL": pool_address,
                "WIDTHS": widths_address,
                "STRIDE": 0x0200,
                "Y_OFFSET": 4 * (0x0200 // 2),
                "MAX_WIDTH": COMBAT_AFFINITY_MAX_WIDTH,
                "PIXEL": blitter_address,
                "STOCK_COUNTED": COMBAT_AFFINITY_STOCK_DRAWER,
            },
            context="COMBAT analysis FONT8 affinity",
        )
    )


def build_combat_analysis_skill_drawer(
    address: int,
    blitter_address: int,
    widths_address: int,
) -> bytes:
    """Draw the analyzer skill page through MAGNAME's relocated full names."""
    source = (ASM_ROOT / "analysis_skill_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "MAGIC_FIRST": 0x0022F7A4,
                "MAGIC_END": 0x00235740,
                "MAGIC_BASE": 0x0022F7A0,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STRIDE": 0x0200,
                "MAX_WIDTH": COMBAT_AFFINITY_MAX_WIDTH,
                "STOCK_COUNTED": COMBAT_COUNTED_DRAWER,
            },
            context="COMBAT analyzer MAGNAME full-name VWF",
        )
    )


def build_combat_analysis_cave(
    blitter_address: int,
    widths_address: int,
    panel_fallback_address: int | None = None,
    *,
    demon_rows: list[dict],
    affinity_rows: list[dict],
    result_label_rows: list[dict],
    character_rows: list[dict],
    combat_source: bytes,
    font8_data: tuple[bytes, dict[str, int]],
) -> tuple[bytes, dict[str, int]]:
    widths8, codes8 = font8_data
    name_offsets, name_pool = build_combat_name_data(codes8, widths8, demon_rows)
    affinity_offsets, affinity_pool = build_combat_affinity_data(
        codes8,
        widths8,
        affinity_rows,
        combat_source,
    )
    result_labels = build_combat_result_label_data(codes8, widths8, result_label_rows)
    payload = bytearray()
    addresses = {}

    def append(name: str, data: bytes, alignment: int = 2) -> int:
        payload.extend(bytes((-(COMBAT_ANALYSIS_CAVE + len(payload))) % alignment))
        address = COMBAT_ANALYSIS_CAVE + len(payload)
        payload.extend(data)
        addresses[name] = address
        return address

    append("name_offsets", name_offsets)
    append("name_pool", name_pool)
    affinity_offsets_address = append("affinity_offsets", affinity_offsets)
    affinity_pool_address = append("affinity_pool", affinity_pool)
    payload.extend(bytes((-(COMBAT_ANALYSIS_CAVE + len(payload))) % 4))
    affinity_drawer_address = COMBAT_ANALYSIS_CAVE + len(payload)
    addresses["affinity_drawer"] = affinity_drawer_address
    payload.extend(
        build_combat_affinity_drawer(
            affinity_drawer_address,
            affinity_offsets_address,
            affinity_pool_address,
            blitter_address,
            widths_address,
        )
    )
    skill_drawer_address = align_up(
        COMBAT_ANALYSIS_CAVE + len(payload),
        4,
    )
    payload.extend(bytes(skill_drawer_address - COMBAT_ANALYSIS_CAVE - len(payload)))
    addresses["skill_drawer"] = skill_drawer_address
    payload.extend(
        build_combat_analysis_skill_drawer(
            skill_drawer_address,
            blitter_address,
            widths_address,
        )
    )
    if panel_fallback_address is not None:
        panel_drawer_address = align_up(
            COMBAT_ANALYSIS_CAVE + len(payload),
            4,
        )
        payload.extend(
            bytes(panel_drawer_address - COMBAT_ANALYSIS_CAVE - len(payload))
        )
        addresses["panel_full_name_drawer"] = panel_drawer_address
        payload.extend(
            build_packed_full_name_drawer(
                panel_drawer_address,
                blitter_address,
                panel_fallback_address,
                widths_address,
                0x0200,
                string_first=True,
            )
        )
    life_stones_address = append(
        "result_life_stones",
        result_labels["life_stones"],
        1,
    )
    beads_address = append(
        "result_beads",
        result_labels["beads"],
        1,
    )
    result_label_drawer_address = align_up(
        COMBAT_ANALYSIS_CAVE + len(payload),
        4,
    )
    payload.extend(
        bytes(result_label_drawer_address - COMBAT_ANALYSIS_CAVE - len(payload))
    )
    addresses["result_label_drawer"] = result_label_drawer_address
    payload.extend(
        build_combat_result_label_drawer(
            result_label_drawer_address,
            life_stones_address,
            beads_address,
            blitter_address,
            widths_address,
        )
    )
    character_offsets, character_pool = build_character_panel_data(
        character_rows,
        (widths8, codes8),
    )
    character_offsets_address = append(
        "character_offsets",
        character_offsets,
    )
    character_pool_address = append(
        "character_pool",
        character_pool,
        1,
    )
    result_name_drawer_address = align_up(
        COMBAT_ANALYSIS_CAVE + len(payload),
        4,
    )
    payload.extend(
        bytes(result_name_drawer_address - COMBAT_ANALYSIS_CAVE - len(payload))
    )
    addresses["result_name_drawer"] = result_name_drawer_address
    payload.extend(
        build_combat_result_name_drawer(
            result_name_drawer_address,
            blitter_address,
            widths_address,
            character_offsets_address,
            character_pool_address,
        )
    )
    result_item_drawer_address = align_up(
        COMBAT_ANALYSIS_CAVE + len(payload),
        4,
    )
    payload.extend(
        bytes(result_item_drawer_address - COMBAT_ANALYSIS_CAVE - len(payload))
    )
    addresses["result_item_drawer"] = result_item_drawer_address
    payload.extend(
        build_combat_result_item_drawer(
            result_item_drawer_address,
            blitter_address,
            widths_address,
        )
    )
    event_item_drawer_address = align_up(
        COMBAT_ANALYSIS_CAVE + len(payload),
        4,
    )
    payload.extend(
        bytes(event_item_drawer_address - COMBAT_ANALYSIS_CAVE - len(payload))
    )
    addresses["event_item_drawer"] = event_item_drawer_address
    payload.extend(
        build_combat_event_item_drawer(
            event_item_drawer_address,
            blitter_address,
            widths_address,
        )
    )
    if COMBAT_ANALYSIS_CAVE + len(payload) > COMBAT_ANALYSIS_CAVE_LIMIT:
        raise ValueError("COMBAT analysis data exceeds the verified zero window")
    return bytes(payload), addresses


def build_combat_surface_renderer(
    address: int,
    font16_document: dict[str, Any],
) -> tuple[bytes, dict[str, int]]:
    """Build one shared subpixel blitter and COMBAT's surface adapters."""
    code_limit, width_offset = font16_width_layout(font16_document)
    blitter = build_surface_blitter_cave(
        address,
        font16_pointer=COMBAT_FONT16_POINTER,
        glyph_pattern_lut=COMBAT_GLYPH_PATTERN_LUT,
        glyph_mask_lut=COMBAT_GLYPH_MASK_LUT,
        draw_shadow=True,
    )
    payload = bytearray(blitter)
    adapters = {}
    for name, max_width in (
        ("escape", COMBAT_SURFACE_MAX_WIDTH),
        ("help_raw", COMBAT_HELP_MAX_WIDTH),
    ):
        adapter_address = align_up(address + len(payload), 4)
        payload.extend(bytes(adapter_address - address - len(payload)))
        payload.extend(
            build_width_returning_surface_cave(
                adapter_address,
                blitter_address=address,
                font16_pointer=COMBAT_FONT16_POINTER,
                width_table_code_limit=code_limit,
                font16_width_table_offset=width_offset,
                max_width=max_width,
            )
        )
        adapters[name] = adapter_address
    help_address = align_up(address + len(payload), 4)
    payload.extend(bytes(help_address - address - len(payload)))
    source = (ASM_ROOT / "battle_help_drawer.s").read_text(encoding="utf-8")
    payload.extend(
        bytes(
            assemble_checked(
                source,
                help_address,
                {
                    "DRAWER": adapters["help_raw"],
                    "PACKED_LIMIT": COMBAT_HELP_PACKED_LIMIT,
                    "SPACE_CODE": COMBAT_HELP_PACKED_SPACE,
                },
                context="COMBAT packed battle help",
            )
        )
    )
    adapters["help"] = help_address
    return bytes(payload), adapters


def build_combat_battle_item_drawer(
    address: int,
    blitter_address: int,
    widths_address: int,
) -> bytes:
    """Follow ITEMNAME/MAGNAME full names without the voiced-kana compositor."""
    source = (ASM_ROOT / "battle_item_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "ITEM_FIRST": 0x00228C04,
                "ITEM_END": 0x0022F7A0,
                "ITEM_BASE": 0x00228C00,
                "MAGIC_FIRST": 0x0022F7A4,
                "MAGIC_END": 0x00235740,
                "MAGIC_BASE": 0x0022F7A0,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STRIDE": COMBAT_BATTLE_ITEM_STRIDE,
                "Y_OFFSET": COMBAT_BATTLE_ITEM_Y_OFFSET,
                "MAX_WIDTH": COMBAT_BATTLE_ITEM_MAX_WIDTH,
                "STOCK": COMBAT_BATTLE_ITEM_STOCK_DRAWER,
            },
            context="COMBAT battle ITEMNAME/MAGNAME small-font",
        )
    )
