"""Pixel-bounded FONT16 rendering for COMBAT event dialogue and choices."""

import struct
from dataclasses import dataclass
from pathlib import Path

from engine.script.combat.model import (
    COMBAT_PENDING_BUFFER,
    COMBAT_PENDING_FLAG,
    COMBAT_PENDING_WORD_CAPACITY,
    COMBAT_TARGET,
)
from engine.script.context import EngineBuildContext
from engine.script.generated_asset import load_runtime_ui
from engine.script.name.fields import FIELD_BY_KIND, NameField
from engine.script.name.model import encode_full_name
from engine.script.patching import BytePatch, CodePatch, PatchGroup
from engine.script.text_render.font16_vwf import align_up, build_surface_blitter_cave
from engine.script.text_render.font_metrics import (
    font16_metrics,
    font16_width_layout,
    load_font16_metrics,
)
from text.script.layouts.combat import (
    COMBAT_CHOICE_OPTION_LAYOUT,
    COMBAT_DIALOGUE_LAYOUT,
    RUNTIME_MEASURE_END_CODE,
    RUNTIME_MEASURE_START_CODE,
    RUNTIME_SOFT_WRAP_CODE,
    RUNTIME_STATIC_HINT_BASE,
    RUNTIME_STATIC_HINT_LIMIT,
)
from tools.sh2asm import AsmBlob, assemble

ASM_ROOT = Path(__file__).with_name("asm")
CAVE_ADDRESS = 0x06021400
CAVE_LIMIT = 0x06021C00
INSERT_DATA_ADDRESS = 0x06024000
INSERT_DATA_LIMIT = 0x06026000
SURFACE_RENDERER_POINTER = 0x060598E8
ORIGINAL_SURFACE_RENDERER = 0x06051A08
ORIGINAL_SURFACE_CLEAR = 0x060515B4
STORE_HOOK = 0x06051EE6
STORE_RETURN = 0x06051F6A
STORE_HOOK_ORIGINAL = bytes.fromhex("d2266120631c33768f13e113")
ORIGINAL_POSITION = 0x06051568

FONT16_POINTER = 0x060721E0
FRAMEBUFFER_POINTER = 0x060721DC
FRAMEBUFFER_STRIDE = 320
GLYPH_PATTERN_LUT = 0x0606F124
GLYPH_MASK_LUT = 0x0606F144
RIGHT_MARGIN = COMBAT_DIALOGUE_LAYOUT.width

GRID_ROWS = COMBAT_DIALOGUE_LAYOUT.lines_per_page
GRID_ADDRESS = 0x06026000
CURSOR_X = 0x06074099
CURSOR_Y = 0x0607409A
CURRENT_COLOR = 0x0607409B

COMPACT_INSERT_POINTER = 0x06051E4C
FULLWORD_INSERT_POINTER = 0x06051E8C
ORIGINAL_COMPACT_INSERT = 0x06051AE0
ORIGINAL_FULLWORD_INSERT = 0x06051A94
DVL_BASE_POINTER = 0x06072220
DVL_SOURCE_SIZE = 319 * 8
RACE_SOURCE = 0x060743C0
RACE_COUNT = 43
RACE_SOURCE_END = RACE_SOURCE + RACE_COUNT * 8
ITEM_BASE_POINTER = 0x0607221C
ITEM_ID0 = 0x0607C0D4
ITEM_ID1 = 0x0607C0D8
ITEM_BUFFER0 = 0x0607C08C
ITEM_BUFFER1 = 0x0607C0A4
ITEM_COUNT = 287
ITEM_ID_LIMIT = ITEM_COUNT + 1
ITEM_RECORD_SIZE = 0x60
ITEM_FULL_NAME_OFFSET = 0x5E
ITEM_FLAG_MASK = 0x60000000
PENDING_BUFFER = COMBAT_PENDING_BUFFER
PENDING_FLAG = COMBAT_PENDING_FLAG
PENDING_WORD_CAPACITY = COMBAT_PENDING_WORD_CAPACITY
SOURCE_POINTER = 0x06073FD8
FULLWORD_INSERT_LIMIT = PENDING_WORD_CAPACITY - 1
ITEM_NAME_LIMIT = PENDING_WORD_CAPACITY - 2
ITEM_COLOR_RESET = 0x8020

TYPEWRITER_DELAY_BRANCH = 0x06059646
TYPEWRITER_DELAY_BRANCH_ORIGINAL = bytes.fromhex("8917")
TYPEWRITER_FRAME_ENTRY_HOOK = 0x06059640
TYPEWRITER_MODE_ENTRY_POINTER = 0x06059668
TYPEWRITER_MODE_PENDING_BRANCH = 0x06059680
TYPEWRITER_MODE_PENDING_BRANCH_ORIGINAL = bytes.fromhex("a053")
TYPEWRITER_SOURCE_CONTINUE_BRANCH = 0x060596FA
TYPEWRITER_SOURCE_REFETCH = 0x060596DC
TYPEWRITER_PENDING_SELECTOR = 0x06059678
TYPEWRITER_VISIBLE_RETURN_HOOK = 0x06059720
TYPEWRITER_FRAME_RETURN = 0x06059874
TYPEWRITER_WHOLE_DRAIN = 0x0605972A
TYPEWRITER_DRAIN_ORIGINAL = bytes.fromhex(
    "d9216191d821611d318089076413341cd120341cd124410b00092981"
)
TYPEWRITER_DRAIN_POINTER = 0x060597D0
TYPEWRITER_RESET_HELPER = 0x06059580
TYPEWRITER_RESET_HELPER_LIMIT = 0x0605958C
TYPEWRITER_RESET_HELPER_ORIGINAL = bytes.fromhex("06050450060728ec060504e4")
TYPEWRITER_VISIBLE_HELPER = 0x06059594
TYPEWRITER_VISIBLE_HELPER_LIMIT = 0x0605959C
TYPEWRITER_VISIBLE_HELPER_ORIGINAL = bytes.fromhex("060504a006073f9e")
TYPEWRITER_DRAIN_FUNCTION = 0x06051FA0
TYPEWRITER_LITERAL_RELOCATIONS = (
    # The first three literal slots become the reset helper.
    ("input_reader_0", 0x06059436, "r11", 0x06059580, 0x0605966C),
    ("input_reader_1", 0x060594C2, "r0", 0x06059580, 0x0605966C),
    ("input_reader_2", 0x06059540, "r0", 0x06059580, 0x0605966C),
    ("input_mask_0", 0x06059442, "r0", 0x06059584, 0x0605965C),
    ("input_mask_1", 0x0605947A, "r0", 0x06059584, 0x0605965C),
    ("input_mask_2", 0x060594CC, "r0", 0x06059584, 0x0605965C),
    ("input_mask_3", 0x06059502, "r0", 0x06059584, 0x0605965C),
    ("input_mask_4", 0x0605954A, "r0", 0x06059584, 0x0605965C),
    ("input_ack_0", 0x0605945E, "r1", 0x06059588, 0x06059660),
    ("input_ack_1", 0x0605949A, "r1", 0x06059588, 0x06059660),
    ("input_ack_2", 0x060594E8, "r1", 0x06059588, 0x06059660),
    ("input_ack_3", 0x06059522, "r1", 0x06059588, 0x06059660),
    ("input_ack_4", 0x06059566, "r1", 0x06059588, 0x06059660),
    # These two slots become the visible-glyph helper.
    ("alternate_reader_0", 0x06059470, "r0", 0x06059594, 0x06059658),
    ("alternate_reader_1", 0x060594F8, "r0", 0x06059594, 0x06059658),
    ("dialogue_state_0", 0x060594B6, "r11", 0x06059598, 0x060597C8),
    ("dialogue_state_1", 0x0605952E, "r11", 0x06059598, 0x060597C8),
)

CHOICE_ANCHOR_CODE = 0x00007FFF
ZERO_SEPARATOR_CODE = 0x07FF
SOFT_WRAP_CODE = RUNTIME_SOFT_WRAP_CODE
MEASURE_START_CODE = RUNTIME_MEASURE_START_CODE
MEASURE_END_CODE = RUNTIME_MEASURE_END_CODE
STATIC_HINT_BASE = RUNTIME_STATIC_HINT_BASE
STATIC_HINT_LIMIT = RUNTIME_STATIC_HINT_LIMIT
SPACE_CODE = 267
CHOICE_RIGHT_X = COMBAT_CHOICE_OPTION_LAYOUT.width
FONT16_GLYPH_COUNT = 1872

MEASURE_MODE = 0x06021A00
MEASURE_WIDTH = 0x06021A02
SURFACE_VALID = 0x06021A04

EXTERNAL_SURFACE_CLEAR_POINTER_SITES = (
    0x06053A20,
    0x06053FE4,
)

CODENAME_POINTER = 0x06074518
ORIGINAL_CODENAME = 0x002029C0
CODENAME_LIMIT_SITE = 0x06051DDC
STOCK_KYOUJI_POINTER = 0x06051E94
ORIGINAL_STOCK_KYOUJI = 0x0607451C
POSITION_POINTER_SITES = (
    0x0605285C,
    0x06052A64,
    0x06052C70,
    0x06053784,
)
CLEAR_POINTER_SITES = (
    0x06052840,
    0x06052954,
    0x06052B3C,
    0x060547C0,
    0x06054C68,
    0x06054E88,
    0x06057F54,
    0x060589C8,
    0x06058D14,
    0x0605958C,
    0x06059664,
    0x060598E4,
)
PARTIAL_CLEAR_POINTER_SITES = (
    0x06052854,
    0x06052A5C,
    0x06052C68,
    0x0605377C,
    0x06054558,
)
ORIGINAL_PARTIAL_CLEAR = 0x06051518


@dataclass(frozen=True)
class CombatVwfLayout:
    metrics: dict
    code_limit: int
    width_offset: int
    grid_columns: int
    grid_row_bytes: int
    color_row_bytes: int
    total_cells: int
    colors_address: int
    buffer_size: int
    choice_anchor_column: int
    choice_anchor_byte_offset: int


def load_layout(metrics_path: Path | None = None) -> CombatVwfLayout:
    metrics = (
        font16_metrics() if metrics_path is None else load_font16_metrics(metrics_path)
    )
    code_limit, width_offset = font16_width_layout(metrics)
    minimum_advance = min(
        glyph["advance"] for glyph in metrics["glyphs"] if glyph["advance"] > 0
    )
    # This is backing capacity, not a render limit. The renderer stops on the
    # accumulated pixel advance. Rounding up leaves room for the choice anchor
    # while holding every sequence which can fit within the right margin.
    grid_columns = (RIGHT_MARGIN + minimum_advance - 1) // minimum_advance
    total_cells = grid_columns * GRID_ROWS
    anchor_column = grid_columns // 2
    return CombatVwfLayout(
        metrics=metrics,
        code_limit=code_limit,
        width_offset=width_offset,
        grid_columns=grid_columns,
        grid_row_bytes=grid_columns * 2,
        color_row_bytes=grid_columns,
        total_cells=total_cells,
        colors_address=GRID_ADDRESS + total_cells * 2,
        buffer_size=total_cells * 3,
        choice_anchor_column=anchor_column,
        choice_anchor_byte_offset=anchor_column * 2,
    )


def font16_codes(metrics: dict) -> dict[str, int]:
    codes = {}
    for row in metrics.get("glyphs", ()):
        code = row.get("code")
        for text in (row.get("text"), *row.get("aliases", ())):
            if isinstance(text, str) and len(text) == 1:
                codes.setdefault(text, code)
    return codes


def load_insert_terms(
    name_rows: list[dict],
    race_rows: list[dict],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    names = tuple(
        row.get("tr", "").strip()
        for index, row in enumerate(name_rows)
        if row.get("record") == index
    )
    races = tuple(
        row.get("tr", "").strip() for row in race_rows if row.get("table") == "races"
    )
    if len(names) != DVL_SOURCE_SIZE // 8 or not all(names):
        raise ValueError("COMBAT dialogue needs 319 translated demon names")
    if len(races) != RACE_COUNT or not all(races):
        raise ValueError("COMBAT dialogue needs 43 translated races")
    return names, races


def build_insert_data(
    address: int,
    metrics: dict,
    name_rows: list[dict],
    race_rows: list[dict],
) -> tuple[bytes, dict[str, int]]:
    """Build full English dynamic-name pools and their dispatcher adapters."""
    names, races = load_insert_terms(name_rows, race_rows)
    codes16 = font16_codes(metrics)

    data = bytearray()
    name_offsets_offset = len(data)
    data.extend(bytes(len(names) * 2))
    race_offsets_offset = len(data)
    data.extend(bytes(len(races) * 2))
    font8_map_offset = len(data)
    data.extend(bytes(256 * 2))
    if len(data) & 1:
        data.append(0)
    string_pool_offset = len(data)
    interned = {}

    def encode(text: str, context: str) -> int:
        cached = interned.get(text)
        if cached is not None:
            return cached
        offset = len(data) - string_pool_offset
        if offset > 0xFFFF:
            raise ValueError("COMBAT dialogue insert pool exceeds u16 offsets")
        try:
            glyphs = [codes16[character] for character in text]
        except KeyError as error:
            raise ValueError(
                f"unsupported {context} FONT16 character {error.args[0]!r} in {text!r}"
            ) from error
        if len(glyphs) > FULLWORD_INSERT_LIMIT:
            raise ValueError(
                f"{context} exceeds COMBAT's {FULLWORD_INSERT_LIMIT}-glyph "
                f"pending-buffer limit: {text!r}"
            )
        data.extend(struct.pack(f">{len(glyphs) + 1}H", *glyphs, 0x8000))
        interned[text] = offset
        return offset

    for index, text in enumerate(names):
        struct.pack_into(
            ">H",
            data,
            name_offsets_offset + index * 2,
            encode(text, f"COMBAT demon name {index}"),
        )
    for index, text in enumerate(races):
        struct.pack_into(
            ">H",
            data,
            race_offsets_offset + index * 2,
            encode(text, f"COMBAT race {index}"),
        )

    # ITEMNAME's complete strings are FONT8 bytes.  Convert every mapped
    # single-character atlas cell to the corresponding FONT16 dialogue code.
    from engine.script.text_render.font8_metrics import font8_metrics

    _, codes8_by_text = font8_metrics()
    for text, code8 in codes8_by_text.items():
        if len(text) != 1 or text not in codes16:
            continue
        struct.pack_into(
            ">H",
            data,
            font8_map_offset + code8 * 2,
            codes16[text],
        )

    while (address + len(data)) & 3:
        data.append(0)
    code_address = address + len(data)
    source = (ASM_ROOT / "english_inserts.s").read_text(encoding="utf-8")
    code = assemble(
        source,
        code_address,
        symbols={
            "DVL_BASE_POINTER": DVL_BASE_POINTER,
            "DVL_SOURCE_SIZE": DVL_SOURCE_SIZE,
            "NAME_OFFSETS": address + name_offsets_offset,
            "RACE_OFFSETS": address + race_offsets_offset,
            "STRING_POOL": address + string_pool_offset,
            "FONT8_TO_FONT16": address + font8_map_offset,
            "COMPACT_COPY": ORIGINAL_COMPACT_INSERT,
            "FULLWORD_COPY": ORIGINAL_FULLWORD_INSERT,
            "RACE_SOURCE": RACE_SOURCE,
            "RACE_SOURCE_END": RACE_SOURCE_END,
            "ITEM_BUFFER0": ITEM_BUFFER0,
            "ITEM_BUFFER1": ITEM_BUFFER1,
            "ITEM_ID0": ITEM_ID0,
            "ITEM_ID1": ITEM_ID1,
            "ITEM_FLAG_MASK": ITEM_FLAG_MASK,
            "ITEM_ID_LIMIT": ITEM_ID_LIMIT,
            "ITEM_RECORD_SIZE": ITEM_RECORD_SIZE,
            "ITEM_BASE_POINTER": ITEM_BASE_POINTER,
            "ITEM_FULL_NAME_OFFSET": ITEM_FULL_NAME_OFFSET,
            "ITEM_NAME_LIMIT": ITEM_NAME_LIMIT,
            "PENDING_BUFFER": PENDING_BUFFER,
            "PENDING_FLAG": PENDING_FLAG,
            "COLOR_RESET": ITEM_COLOR_RESET,
            "TERMINATOR": 0x8000,
        },
    )
    if code.warnings:
        raise ValueError(f"COMBAT English insert warnings: {code.warnings}")
    data.extend(code)
    labels = {
        **code.labels,
        "name_offsets": address + name_offsets_offset,
        "race_offsets": address + race_offsets_offset,
        "font8_to_font16": address + font8_map_offset,
        "string_pool": address + string_pool_offset,
        "code": code_address,
    }
    return bytes(data), labels


def build_dialogue_vwf(
    cave_address: int,
    *,
    font16_pointer: int,
    framebuffer_pointer: int,
    framebuffer_stride: int,
    glyph_pattern_lut: int,
    glyph_mask_lut: int,
    code_limit: int,
    width_offset: int,
    layout: CombatVwfLayout,
) -> tuple[bytes, dict[str, int], int, int]:
    """Build the shared VM blitter and widened COMBAT dialogue consumer."""
    if not FONT16_GLYPH_COUNT <= STATIC_HINT_BASE < STATIC_HINT_LIMIT:
        raise ValueError(
            "COMBAT width hints must be above FONT16 and below packed words"
        )
    surface_address = cave_address
    surface = build_surface_blitter_cave(
        surface_address,
        font16_pointer=font16_pointer,
        glyph_pattern_lut=glyph_pattern_lut,
        glyph_mask_lut=glyph_mask_lut,
        draw_shadow=True,
        stacked_shadow_color=True,
    )
    code_address = align_up(surface_address + len(surface), 4)
    source = (ASM_ROOT / "dialogue_vwf.s").read_text(encoding="utf-8")
    code = assemble(
        source,
        code_address,
        symbols={
            "ORIGINAL_SURFACE_CLEAR": ORIGINAL_SURFACE_CLEAR,
            "FONT16_POINTER": font16_pointer,
            "FRAMEBUFFER_POINTER": framebuffer_pointer,
            "FRAMEBUFFER_STRIDE": framebuffer_stride,
            "SURFACE_BLITTER": surface_address,
            "CODE_LIMIT": code_limit,
            "WIDTH_OFFSET": width_offset,
            "GRID": GRID_ADDRESS,
            "COLORS": layout.colors_address,
            "GRID_COLUMNS": layout.grid_columns,
            "GRID_ROW_BYTES": layout.grid_row_bytes,
            "COLOR_ROW_BYTES": layout.color_row_bytes,
            "TOTAL_CELLS": layout.total_cells,
            "OPTION_CELLS": layout.grid_columns * (GRID_ROWS - 1),
            "CURSOR_X": CURSOR_X,
            "CURSOR_Y": CURSOR_Y,
            "CURRENT_COLOR": CURRENT_COLOR,
            "STORE_RETURN": STORE_RETURN,
            "RIGHT_MARGIN": RIGHT_MARGIN,
            "ANCHOR_CODE": CHOICE_ANCHOR_CODE,
            "ZERO_SEPARATOR_CODE": ZERO_SEPARATOR_CODE,
            "SOFT_WRAP_CODE": SOFT_WRAP_CODE,
            "STATIC_HINT_BASE": STATIC_HINT_BASE,
            "STATIC_HINT_LIMIT": STATIC_HINT_LIMIT,
            "MEASURE_START_CODE": MEASURE_START_CODE,
            "MEASURE_END_CODE": MEASURE_END_CODE,
            "SPACE_CODE": SPACE_CODE,
            "MEASURE_MODE": MEASURE_MODE,
            "MEASURE_WIDTH": MEASURE_WIDTH,
            "SURFACE_VALID": SURFACE_VALID,
            "PENDING_BUFFER": PENDING_BUFFER,
            "PENDING_FLAG": PENDING_FLAG,
            "PENDING_WORD_CAPACITY": PENDING_WORD_CAPACITY,
            "SOURCE_POINTER": SOURCE_POINTER,
            "CHOICE_RIGHT_X": CHOICE_RIGHT_X,
            "ANCHOR_COLUMN": layout.choice_anchor_column,
            "ANCHOR_BYTE_OFFSET": layout.choice_anchor_byte_offset,
        },
    )
    if code.warnings:
        raise ValueError(f"COMBAT dialogue VWF warnings: {code.warnings}")
    payload = bytearray(surface)
    payload.extend(bytes(code_address - cave_address - len(payload)))
    payload.extend(code)
    stock_kyouji_address = cave_address + len(payload)
    stock_kyouji = encode_full_name("Kyouji", "Kuzunoha")
    payload.extend(struct.pack(f">{len(stock_kyouji)}H", *stock_kyouji))
    if cave_address + len(payload) > MEASURE_MODE:
        raise ValueError("COMBAT dialogue code overlaps its width-hint state")
    return bytes(payload), code.labels, stock_kyouji_address, surface_address


def build_store_hook(site_address: int, store_address: int) -> bytes:
    """Build the misaligned storage-tail jump with an explicit literal.

    ``STORE_HOOK`` is 2 mod 4.  Letting the assembler place a ``.pool`` for
    ``mov.l =STORE`` pads relative to the blob instead of the runtime address,
    making the load consume the padding and half of the pointer.  The literal
    belongs immediately after the three instructions at the next aligned
    address.
    """
    literal_address = site_address + 6
    if literal_address & 3:
        raise ValueError("COMBAT widened-grid hook literal is not aligned")
    pc_base = (site_address & ~3) + 4
    displacement = (literal_address - pc_base) // 4
    if not 0 <= displacement <= 0xFF:
        raise ValueError("COMBAT widened-grid hook literal is out of range")
    code = struct.pack(
        ">HHHIH",
        0xD000 | displacement,  # mov.l @(disp,pc),r0
        0x402B,  # jmp @r0
        0x0009,  # nop
        store_address,
        0x0009,  # fill the displaced 12-byte window
    )
    if len(code) != len(STORE_HOOK_ORIGINAL):
        raise ValueError("COMBAT widened-grid hook does not fill its window")
    return code


def assemble_typewriter_pacing() -> tuple[AsmBlob, AsmBlob]:
    """Assemble the reset and visible helpers into relocated literal slots."""
    reset_source = (ASM_ROOT / "typewriter_reset.s").read_text(encoding="utf-8")
    reset = assemble(
        reset_source,
        TYPEWRITER_RESET_HELPER,
        symbols={
            "TYPEWRITER_MODE_POINTER": TYPEWRITER_MODE_ENTRY_POINTER,
        },
    )
    visible_source = (ASM_ROOT / "typewriter_visible.s").read_text(encoding="utf-8")
    visible = assemble(
        visible_source,
        TYPEWRITER_VISIBLE_HELPER,
        symbols={
            "TYPEWRITER_PENDING_SELECTOR": TYPEWRITER_PENDING_SELECTOR,
            "TYPEWRITER_FRAME_RETURN": TYPEWRITER_FRAME_RETURN,
        },
    )
    warnings = (*reset.warnings, *visible.warnings)
    if warnings:
        raise ValueError(f"COMBAT typewriter pacing warnings: {warnings}")
    if TYPEWRITER_RESET_HELPER + len(reset) != TYPEWRITER_RESET_HELPER_LIMIT:
        raise ValueError(
            "COMBAT typewriter reset does not fill its relocated literal slots"
        )
    if TYPEWRITER_VISIBLE_HELPER + len(visible) != TYPEWRITER_VISIBLE_HELPER_LIMIT:
        raise ValueError(
            "COMBAT typewriter visible helper does not fill its relocated literal slots"
        )
    return reset, visible


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    contract = load_runtime_ui(context)
    name_rows = contract.section("demon_names")
    race_rows = contract.section("status_tables")
    if not isinstance(name_rows, list) or not isinstance(race_rows, list):
        raise ValueError(f"{contract.path}: invalid combat name/race sections")
    layout = load_layout(context.font_generated_root / "font16_metrics.json")
    dialogue_vwf, labels, stock_kyouji_address, _ = build_dialogue_vwf(
        CAVE_ADDRESS,
        font16_pointer=FONT16_POINTER,
        framebuffer_pointer=FRAMEBUFFER_POINTER,
        framebuffer_stride=FRAMEBUFFER_STRIDE,
        glyph_pattern_lut=GLYPH_PATTERN_LUT,
        glyph_mask_lut=GLYPH_MASK_LUT,
        code_limit=layout.code_limit,
        width_offset=layout.width_offset,
        layout=layout,
    )
    if CAVE_ADDRESS + len(dialogue_vwf) > CAVE_LIMIT:
        raise ValueError("COMBAT dialogue VWF exceeds the verified free window")

    insert_data, insert_labels = build_insert_data(
        INSERT_DATA_ADDRESS,
        layout.metrics,
        name_rows,
        race_rows,
    )
    if INSERT_DATA_ADDRESS + len(insert_data) > INSERT_DATA_LIMIT:
        raise ValueError("COMBAT English insert data exceeds its reserved window")

    renderer_address = labels["combat_render"]
    store_address = labels["combat_store"]
    clear_address = labels["combat_clear"]
    partial_clear_address = labels["combat_clear_options"]
    choice_position = labels["combat_choice_position"]
    external_surface_clear = labels["combat_external_surface_clear"]
    typewriter_reset, typewriter_visible = assemble_typewriter_pacing()

    return PatchGroup(
        capability="combat_vwf",
        target=COMBAT_TARGET,
        patches=(
            BytePatch(
                "dialogue_vwf_cave",
                CAVE_ADDRESS,
                bytes(len(dialogue_vwf)),
                dialogue_vwf,
            ),
            BytePatch(
                "expanded_dialogue_buffer",
                GRID_ADDRESS,
                bytes(layout.buffer_size),
                bytes(layout.buffer_size),
            ),
            BytePatch(
                "english_insert_data",
                INSERT_DATA_ADDRESS,
                bytes(len(insert_data)),
                insert_data,
            ),
            BytePatch(
                "compact_name_insert_pointer",
                COMPACT_INSERT_POINTER,
                struct.pack(">I", ORIGINAL_COMPACT_INSERT),
                struct.pack(
                    ">I",
                    insert_labels["combat_compact_name_insert"],
                ),
            ),
            BytePatch(
                "fullword_insert_pointer",
                FULLWORD_INSERT_POINTER,
                struct.pack(">I", ORIGINAL_FULLWORD_INSERT),
                struct.pack(
                    ">I",
                    insert_labels["combat_fullword_insert"],
                ),
            ),
            BytePatch(
                "dialogue_renderer_pointer",
                SURFACE_RENDERER_POINTER,
                struct.pack(">I", ORIGINAL_SURFACE_RENDERER),
                struct.pack(">I", renderer_address),
            ),
            BytePatch(
                "dialogue_store_hook",
                STORE_HOOK,
                STORE_HOOK_ORIGINAL,
                build_store_hook(STORE_HOOK, store_address),
            ),
            *(
                BytePatch(
                    f"dialogue_external_surface_clear_{address:08x}",
                    address,
                    struct.pack(">I", ORIGINAL_SURFACE_CLEAR),
                    struct.pack(">I", external_surface_clear),
                )
                for address in EXTERNAL_SURFACE_CLEAR_POINTER_SITES
            ),
            *(
                CodePatch(
                    f"dialogue_typewriter_relocate_{name}",
                    address,
                    f"mov.l TYPEWRITER_OLD_LITERAL,{register}",
                    f"mov.l TYPEWRITER_NEW_LITERAL,{register}",
                    symbols={
                        "TYPEWRITER_OLD_LITERAL": original_literal,
                        "TYPEWRITER_NEW_LITERAL": replacement_literal,
                    },
                )
                for (
                    name,
                    address,
                    register,
                    original_literal,
                    replacement_literal,
                ) in TYPEWRITER_LITERAL_RELOCATIONS
            ),
            CodePatch(
                "dialogue_typewriter_reset_budget",
                TYPEWRITER_FRAME_ENTRY_HOOK,
                "mov.l TYPEWRITER_MODE_ENTRY_POINTER,r1\nmov.b @r1,r1",
                "bsr TYPEWRITER_RESET\nnop",
                symbols={
                    "TYPEWRITER_MODE_ENTRY_POINTER": TYPEWRITER_MODE_ENTRY_POINTER,
                    "TYPEWRITER_RESET": typewriter_reset.labels["typewriter_reset"],
                },
            ),
            CodePatch(
                "dialogue_typewriter_continue_through_pending_selector",
                TYPEWRITER_SOURCE_CONTINUE_BRANCH,
                "bt/s TYPEWRITER_SOURCE_REFETCH",
                "bt/s TYPEWRITER_PENDING_SELECTOR",
                symbols={
                    "TYPEWRITER_SOURCE_REFETCH": TYPEWRITER_SOURCE_REFETCH,
                    "TYPEWRITER_PENDING_SELECTOR": TYPEWRITER_PENDING_SELECTOR,
                },
                allow_trailing_delay_slot=True,
            ),
            CodePatch(
                "dialogue_typewriter_continue_after_first_visible_glyph",
                TYPEWRITER_VISIBLE_RETURN_HOOK,
                "bra TYPEWRITER_FRAME_RETURN\nor r0,r0",
                "bra TYPEWRITER_VISIBLE\nnop",
                symbols={
                    "TYPEWRITER_FRAME_RETURN": TYPEWRITER_FRAME_RETURN,
                    "TYPEWRITER_VISIBLE": typewriter_visible.labels[
                        "typewriter_visible"
                    ],
                },
            ),
            BytePatch(
                "dialogue_typewriter_reset_helper",
                TYPEWRITER_RESET_HELPER,
                TYPEWRITER_RESET_HELPER_ORIGINAL,
                bytes(typewriter_reset),
            ),
            BytePatch(
                "dialogue_typewriter_visible_helper",
                TYPEWRITER_VISIBLE_HELPER,
                TYPEWRITER_VISIBLE_HELPER_ORIGINAL,
                bytes(typewriter_visible),
            ),
            *(
                BytePatch(
                    f"dialogue_clear_pointer_{address:08x}",
                    address,
                    struct.pack(">I", 0x06051478),
                    struct.pack(">I", clear_address),
                )
                for address in CLEAR_POINTER_SITES
            ),
            *(
                BytePatch(
                    f"dialogue_partial_clear_pointer_{address:08x}",
                    address,
                    struct.pack(">I", ORIGINAL_PARTIAL_CLEAR),
                    struct.pack(">I", partial_clear_address),
                )
                for address in PARTIAL_CLEAR_POINTER_SITES
            ),
            *(
                BytePatch(
                    f"choice_position_pointer_{address:08x}",
                    address,
                    struct.pack(">I", ORIGINAL_POSITION),
                    struct.pack(">I", choice_position),
                )
                for address in POSITION_POINTER_SITES
            ),
            BytePatch(
                "combat_codename_pointer",
                CODENAME_POINTER,
                struct.pack(">I", ORIGINAL_CODENAME),
                struct.pack(
                    ">I",
                    FIELD_BY_KIND[NameField.CODENAME].runtime_address,
                ),
            ),
            CodePatch(
                "combat_codename_capacity",
                CODENAME_LIMIT_SITE,
                "add #0xc,r2",
                "add #0x10,r2",
            ),
            BytePatch(
                "combat_stock_kyouji_pointer",
                STOCK_KYOUJI_POINTER,
                struct.pack(">I", ORIGINAL_STOCK_KYOUJI),
                struct.pack(">I", stock_kyouji_address),
            ),
        ),
    )
