"""Proportional fusion options and full translated fusion-list names."""

import re
import struct
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.event.model import (
    EVENT_TARGET,
    FUSION_CONFIRMATION_OVERFLOW_ADDRESS,
)
from engine.script.fusion_menu.data import (
    build_font8_code_map as build_font8_code_map,
)
from engine.script.fusion_menu.data import (
    encode_demon_sort_pool,
    encode_pool,
    load_codes,
    load_names,
    load_optional_guide_lines,
    load_optional_help_lines,
    validate_guide_lines,
    validate_help_lines,
)
from engine.script.fusion_menu.data import (
    guide_line_metrics as guide_line_metrics,
)
from engine.script.fusion_menu.data import (
    help_line_metrics as help_line_metrics,
)
from engine.script.fusion_menu.data import (
    load_guide_lines as load_guide_lines,
)
from engine.script.fusion_menu.data import (
    load_help_lines as load_help_lines,
)
from engine.script.fusion_menu.data import (
    load_races as load_races,
)
from engine.script.fusion_menu.model import (
    CHART_CELL_WIDTH,
    FUSION_RACE_LABELS,
    GUIDE_DESCRIPTION_Y,
    GUIDE_GLYPH_LIMIT,
    HELP_GLYPH_LIMIT,
    LIST_ROW_WIDTH,
    PLAYER_NAME_ID,
    PREVIEW_NAME_WIDTH,
    PREVIEW_RACE_WIDTH,
    RACE_WORD_BASE,
    TABLE_FONT8_MODE,
    TABLE_FONT8_Y_OFFSET,
    TABLE_NAME_WIDTH,
    TABLE_RACE_WIDTH,
    measure_font12,
    truncate_font8,
)
from engine.script.generated_asset import RuntimeUiContract, load_runtime_ui
from engine.script.name.fields import FIELD_BY_KIND, NameField
from engine.script.patching import BytePatch, CodePatch, DigestPatch, PatchGroup
from engine.script.sh2 import assemble_checked
from engine.script.text_render.font8_blitter import build_surface_pixel_blitter
from engine.script.text_render.font8_metrics import load_metrics
from engine.script.text_render.font16_vwf import build_surface_blitter_cave
from engine.script.text_render.font_metrics import (
    build_font12_dialogue_widths,
    load_font12_metrics,
)

CAVE_ADDRESS = 0x06021800
NAME_SORT_REGION = 0x060451E0
NAME_SORT_REGION_SIZE = 0x200
NAME_SORT_REGION_SHA256 = (
    "125d4a15c59aabee09003bba2ee91e81e5d5fde47c9c5a5d98f3133ad86b1638"
)
NAME_SORT_POINTER_SITE = 0x060457BC
STOCK_NAME_SORT = 0x060452AC
ROSTER_COUNT = 0x060768A8
ROSTER_IDS_PTR = 0x06068E78
ROSTER_AUX0_PTR = 0x06068E7C
ROSTER_AUX1_PTR = 0x06068E80
ACTOR_LIST_POINTER_SITE = 0x06041488
DEMON_LIST_POINTER_SITE = 0x06041498
PREVIEW_RACE_POINTER_SITE = 0x060419DC
PREVIEW_DEMON_POINTER_SITE = 0x060419E0
RESULT_DEMON_POINTER_SITE = 0x06045EFC
LEVEL_DIGIT_GLYPH_POINTER_SITE = 0x06045DA0
LEVEL_SECOND_DIGIT_ADVANCE_SITE = 0x06045D50
TABLE_RACE_POINTER_SITES = (
    0x0603D59C,
    0x0603D670,
    0x0603D840,
    0x0603DA2C,
    0x0603E330,
    0x0603E524,
    0x0603E774,
    0x0603F720,
    0x0603FA48,
    0x0603FC5C,
    0x06042B00,
    0x06042BCC,
    0x06042D5C,
    0x06042F34,
    0x06043118,
    0x06043B1C,
    0x06045A94,
    0x060460D8,
    0x06046314,
)
TABLE_DEMON_POINTER_SITES = (
    0x0603D5A0,
    0x0603D674,
    0x0603D844,
    0x0603DA30,
    0x0603E334,
    0x0603E528,
    0x0603E778,
    0x0603F724,
    0x0603FA4C,
    0x0603FC60,
    0x06042B04,
    0x06042BD0,
    0x06042D60,
    0x06042F38,
    0x0604311C,
    0x06043B20,
    0x06045A98,
    0x060460DC,
    0x06046318,
)
STOCK_DEMON_DRAWER = 0x0603C50C
STOCK_CHARACTER_DRAWER = 0x0603C5C8
STOCK_RACE_DRAWER = 0x0603C410
STOCK_TABLE_RACE_DRAWER = 0x0603C4C8
STOCK_GLYPH_DRAWER = 0x0603B760
GUIDE_GLYPH_POINTER = 0x0603B9B0
GUIDE_ADVANCE_SITE = 0x0603B91E
GUIDE_TERMINATOR_COUNT_SITE = 0x0603B912
GUIDE_GLYPH_LIMIT_SITE = 0x0603B918
HELP_GLYPH_POINTER = 0x0603BBD8
HELP_ADVANCE_SITE = 0x0603BB06
HELP_TERMINATOR_COUNT_SITE = 0x0603BAFA
HELP_GLYPH_LIMIT_SITE = 0x0603BB00
WRAPPED_WORD_GLYPH_POINTER = 0x0603C4C4
WRAPPED_WORD_ADVANCE_SITE = 0x0603C48E
CHART_RACE_POINTER_SITES = (0x0604442C, 0x0604461C)
FONT12_POINTER = 0x06062598
GLYPH_PATTERN_LUT = 0x0602B9F4
GLYPH_MASK_LUT = 0x0602BA14
TERMINATOR = 0xFF

ASM_ROOT = Path(__file__).with_name("asm")
GUIDE_GLYPH_TOKEN = re.compile(r"\{GLYPH:([0-9a-fA-F]{4})\}")


def align(payload: bytearray, alignment: int) -> None:
    payload.extend(bytes((-len(payload)) % alignment))


def build_drawers(
    address: int,
    symbols: dict[str, int],
) -> tuple[bytes, dict[str, int]]:
    source = (ASM_ROOT / "name_drawers.s").read_text(encoding="utf-8")
    blob = assemble_checked(source, address, symbols, context="fusion-name")
    return bytes(blob), blob.labels


def build_name_sort(demon_offsets_address: int) -> bytes:
    source = (ASM_ROOT / "name_sort.s").read_text(encoding="utf-8")
    blob = assemble_checked(
        source,
        NAME_SORT_REGION,
        {
            "DVL_OFFSETS": demon_offsets_address,
            "ROSTER_COUNT": ROSTER_COUNT,
            "ROSTER_IDS_PTR": ROSTER_IDS_PTR,
            "ROSTER_AUX0_PTR": ROSTER_AUX0_PTR,
            "ROSTER_AUX1_PTR": ROSTER_AUX1_PTR,
        },
        context="fusion English demon-name sort",
    )
    if len(blob) > NAME_SORT_REGION_SIZE:
        raise ValueError(
            "fusion English demon-name sort exceeds the stock helper/sorter region"
        )
    return bytes(blob).ljust(NAME_SORT_REGION_SIZE, b"\0")


def build_patch(
    contract: RuntimeUiContract | None = None,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> PatchGroup:
    contract = contract or load_runtime_ui(context)
    tables = contract.section("status_tables")
    demon_rows = contract.section("demon_names")
    character_rows = contract.section("character_names")
    message_rows = contract.section("fusion_messages")
    if not all(
        isinstance(rows, list)
        for rows in (tables, demon_rows, character_rows, message_rows)
    ):
        raise ValueError(f"{contract.path}: invalid fusion runtime UI sections")
    metrics_path = context.font_generated_root / "font12_metrics.json"
    font12_widths = build_font12_dialogue_widths(load_font12_metrics(metrics_path))
    codes = load_codes(metrics_path)
    races = load_races(tables)
    if len(races) != len(FUSION_RACE_LABELS):
        raise ValueError("fusion race-label count does not match the source table")
    for label in FUSION_RACE_LABELS:
        width = measure_font12(label, codes, font12_widths)
        if width > PREVIEW_RACE_WIDTH:
            raise ValueError(
                f"fusion race label {label!r} exceeds {PREVIEW_RACE_WIDTH}px: {width}px"
            )
    demon_names = load_names(demon_rows, "fusion demon names")
    character_names = load_names(character_rows, "fusion character names")
    font8_widths, font8_codes = load_metrics(
        context.font_generated_root / "font8_metrics.json"
    )
    font8_code_map = build_font8_code_map((*races, *demon_names), codes, font8_codes)
    guide_lines = load_optional_guide_lines(message_rows)
    help_lines = load_optional_help_lines(message_rows)
    if guide_lines is not None:
        validate_guide_lines(
            message_rows,
            codes,
            font8_widths,
            font8_code_map,
            font8_codes[" "],
        )
    if help_lines is not None:
        validate_help_lines(
            message_rows,
            codes,
            font8_widths,
            font8_code_map,
            font8_codes[" "],
        )
    for race in races:
        width = sum(
            font8_widths[font8_codes[character]] + (character != " ")
            for character in race
        )
        if width > TABLE_RACE_WIDTH:
            raise ValueError(
                f"fusion table race {race!r} exceeds "
                f"{TABLE_RACE_WIDTH}px in FONT8: {width}px"
            )
    chart_races_and_widths = tuple(
        truncate_font8(race, font8_codes, font8_widths, CHART_CELL_WIDTH)
        for race in races
    )
    if any(not race for race, _width in chart_races_and_widths):
        raise ValueError("fusion chart truncation produced an empty race label")
    chart_race_widths = bytes(width for _race, width in chart_races_and_widths)
    race_offsets, race_pool = encode_pool(FUSION_RACE_LABELS, codes)
    table_race_offsets, table_race_pool = encode_pool(races, codes)
    demon_offsets, demon_pool = encode_demon_sort_pool(demon_names, codes)
    character_offsets, character_pool = encode_pool(character_names, codes)

    payload = bytearray(font12_widths)
    race_offsets_address = CAVE_ADDRESS + len(payload)
    payload.extend(race_offsets)
    demon_offsets_address = CAVE_ADDRESS + len(payload)
    payload.extend(demon_offsets)
    character_offsets_address = CAVE_ADDRESS + len(payload)
    payload.extend(character_offsets)
    race_pool_address = CAVE_ADDRESS + len(payload)
    payload.extend(race_pool)
    demon_pool_address = CAVE_ADDRESS + len(payload)
    payload.extend(demon_pool)
    character_pool_address = CAVE_ADDRESS + len(payload)
    payload.extend(character_pool)
    align(payload, 2)
    table_race_offsets_address = CAVE_ADDRESS + len(payload)
    payload.extend(table_race_offsets)
    table_race_pool_address = CAVE_ADDRESS + len(payload)
    payload.extend(table_race_pool)
    chart_race_widths_address = CAVE_ADDRESS + len(payload)
    payload.extend(chart_race_widths)
    font8_widths_address = CAVE_ADDRESS + len(payload)
    payload.extend(font8_widths)
    font8_code_map_address = CAVE_ADDRESS + len(payload)
    payload.extend(font8_code_map)
    align(payload, 4)
    surface_blitter_address = CAVE_ADDRESS + len(payload)
    payload.extend(
        build_surface_blitter_cave(
            surface_blitter_address,
            font16_pointer=FONT12_POINTER,
            glyph_pattern_lut=GLYPH_PATTERN_LUT,
            glyph_mask_lut=GLYPH_MASK_LUT,
        )
    )
    align(payload, 4)
    font8_blitter_address = CAVE_ADDRESS + len(payload)
    payload.extend(build_surface_pixel_blitter(font8_blitter_address))
    align(payload, 4)
    drawers_address = CAVE_ADDRESS + len(payload)
    drawers, labels = build_drawers(
        drawers_address,
        {
            "RACE_OFFSETS": race_offsets_address,
            "RACE_POOL": race_pool_address,
            "TABLE_RACE_OFFSETS": table_race_offsets_address,
            "TABLE_RACE_POOL": table_race_pool_address,
            "CHART_RACE_WIDTHS": chart_race_widths_address,
            "RACE_BASE": RACE_WORD_BASE,
            "DVL_OFFSETS": demon_offsets_address,
            "DVL_POOL": demon_pool_address,
            "CHAR_OFFSETS": character_offsets_address,
            "CHAR_POOL": character_pool_address,
            "WIDTHS": CAVE_ADDRESS,
            "FONT8_WIDTHS": font8_widths_address,
            "FONT8_CODE_MAP": font8_code_map_address,
            "FONT8_SPACE": font8_codes[" "],
            "FONT8_GLYPH": font8_blitter_address,
            "PLAYER_CODENAME": FIELD_BY_KIND[NameField.CODENAME].runtime_address,
            "PLAYER_ID": PLAYER_NAME_ID,
            "DVL_COUNT": len(demon_names),
            "CHAR_COUNT": len(character_names),
            "RACE_COUNT": len(FUSION_RACE_LABELS),
            "NAME_MAX_WIDTH": min(LIST_ROW_WIDTH, PREVIEW_NAME_WIDTH, TABLE_NAME_WIDTH),
            "RACE_MAX_WIDTH": PREVIEW_RACE_WIDTH,
            "TABLE_RACE_MAX_WIDTH": TABLE_RACE_WIDTH,
            "CHART_CELL_WIDTH": CHART_CELL_WIDTH,
            "TABLE_FONT8_Y_OFFSET": TABLE_FONT8_Y_OFFSET,
            "GUIDE_DESCRIPTION_Y": GUIDE_DESCRIPTION_Y,
            "TABLE_FONT8_MODE": TABLE_FONT8_MODE,
            "WORD_TERMINATOR": 0x8000,
            "FONT16_SPACE": 267,
            "SURFACE_GLYPH": surface_blitter_address,
            "STOCK_GLYPH": STOCK_GLYPH_DRAWER,
            "DEMON_STOCK": STOCK_DEMON_DRAWER,
            "CHARACTER_STOCK": STOCK_CHARACTER_DRAWER,
            "RACE_STOCK": STOCK_RACE_DRAWER,
            "TABLE_RACE_STOCK": STOCK_TABLE_RACE_DRAWER,
        },
    )
    payload.extend(drawers)
    if CAVE_ADDRESS + len(payload) > FUSION_CONFIRMATION_OVERFLOW_ADDRESS:
        raise ValueError(
            "fusion menu cave overlaps the reserved fusion-confirmation tail"
        )
    name_sort = build_name_sort(demon_offsets_address)

    guide_patches = ()
    if guide_lines is not None:
        guide_patches = (
            BytePatch(
                "fusion_guide_font8_glyph_pointer",
                GUIDE_GLYPH_POINTER,
                struct.pack(">I", STOCK_GLYPH_DRAWER),
                struct.pack(">I", labels["fusion_guide_mixed_glyph"]),
            ),
            BytePatch(
                "fusion_guide_font8_advance",
                GUIDE_ADVANCE_SITE,
                struct.pack(">H", 0x7B0F),
                struct.pack(">H", 0x7B00),
            ),
            CodePatch(
                "fusion_guide_terminator_count",
                GUIDE_TERMINATOR_COUNT_SITE,
                "mov #0x15, r8",
                f"mov #{GUIDE_GLYPH_LIMIT}, r8",
            ),
            CodePatch(
                "fusion_guide_glyph_count_limit",
                GUIDE_GLYPH_LIMIT_SITE,
                "mov #0x14, r0",
                f"mov #{GUIDE_GLYPH_LIMIT - 1}, r0",
            ),
        )

    help_patches = ()
    if help_lines is not None:
        help_patches = (
            BytePatch(
                "fusion_help_font8_glyph_pointer",
                HELP_GLYPH_POINTER,
                struct.pack(">I", STOCK_GLYPH_DRAWER),
                struct.pack(">I", labels["fusion_word_font8_glyph"]),
            ),
            BytePatch(
                "fusion_help_font8_advance",
                HELP_ADVANCE_SITE,
                struct.pack(">H", 0x7B0C),
                struct.pack(">H", 0x3B0C),
            ),
            CodePatch(
                "fusion_help_terminator_count",
                HELP_TERMINATOR_COUNT_SITE,
                "mov #0x15, r8",
                f"mov #{HELP_GLYPH_LIMIT}, r8",
            ),
            CodePatch(
                "fusion_help_glyph_count_limit",
                HELP_GLYPH_LIMIT_SITE,
                "mov #0x14, r13",
                f"mov #{HELP_GLYPH_LIMIT - 1}, r13",
            ),
        )

    return PatchGroup(
        capability="fusion_menu",
        target=EVENT_TARGET,
        patches=(
            BytePatch(
                "fusion_menu_cave", CAVE_ADDRESS, bytes(len(payload)), bytes(payload)
            ),
            DigestPatch(
                "fusion_english_name_sort",
                NAME_SORT_REGION,
                NAME_SORT_REGION_SHA256,
                name_sort,
            ),
            BytePatch(
                "fusion_name_sort_pointer",
                NAME_SORT_POINTER_SITE,
                struct.pack(">I", STOCK_NAME_SORT),
                struct.pack(">I", NAME_SORT_REGION),
            ),
            BytePatch(
                "fusion_actor_list_name_pointer",
                ACTOR_LIST_POINTER_SITE,
                struct.pack(">I", STOCK_CHARACTER_DRAWER),
                struct.pack(">I", labels["fusion_character_name_vwf"]),
            ),
            BytePatch(
                "fusion_demon_list_name_pointer",
                DEMON_LIST_POINTER_SITE,
                struct.pack(">I", STOCK_DEMON_DRAWER),
                struct.pack(">I", labels["fusion_demon_name_vwf"]),
            ),
            BytePatch(
                "fusion_preview_race_pointer",
                PREVIEW_RACE_POINTER_SITE,
                struct.pack(">I", STOCK_RACE_DRAWER),
                struct.pack(">I", labels["fusion_race_vwf"]),
            ),
            BytePatch(
                "fusion_preview_demon_name_pointer",
                PREVIEW_DEMON_POINTER_SITE,
                struct.pack(">I", STOCK_DEMON_DRAWER),
                struct.pack(">I", labels["fusion_demon_preview_vwf"]),
            ),
            BytePatch(
                "fusion_result_demon_name_pointer",
                RESULT_DEMON_POINTER_SITE,
                struct.pack(">I", STOCK_DEMON_DRAWER),
                struct.pack(">I", labels["fusion_table_demon_font8"]),
            ),
            BytePatch(
                "fusion_level_digit_glyph_pointer",
                LEVEL_DIGIT_GLYPH_POINTER_SITE,
                struct.pack(">I", STOCK_GLYPH_DRAWER),
                struct.pack(">I", surface_blitter_address),
            ),
            BytePatch(
                "fusion_level_second_digit_advance",
                LEVEL_SECOND_DIGIT_ADVANCE_SITE,
                struct.pack(">H", 0x790C),
                struct.pack(">H", 0x7906),
            ),
            *guide_patches,
            *help_patches,
            BytePatch(
                "fusion_chart_font8_glyph_pointer",
                WRAPPED_WORD_GLYPH_POINTER,
                struct.pack(">I", STOCK_GLYPH_DRAWER),
                struct.pack(">I", labels["fusion_word_font8_glyph"]),
            ),
            BytePatch(
                "fusion_chart_font8_advance",
                WRAPPED_WORD_ADVANCE_SITE,
                struct.pack(">H", 0x780C),
                struct.pack(">H", 0x380C),
            ),
            *(
                BytePatch(
                    f"fusion_chart_race_drawer_{site:08x}",
                    site,
                    struct.pack(">I", STOCK_RACE_DRAWER),
                    struct.pack(">I", labels["fusion_chart_race_font8"]),
                )
                for site in CHART_RACE_POINTER_SITES
            ),
            *(
                BytePatch(
                    f"fusion_table_race_pointer_{site:08x}",
                    site,
                    struct.pack(">I", STOCK_TABLE_RACE_DRAWER),
                    struct.pack(">I", labels["fusion_table_race_font8"]),
                )
                for site in TABLE_RACE_POINTER_SITES
            ),
            *(
                BytePatch(
                    f"fusion_table_demon_pointer_{site:08x}",
                    site,
                    struct.pack(">I", STOCK_DEMON_DRAWER),
                    struct.pack(">I", labels["fusion_table_demon_font8"]),
                )
                for site in TABLE_DEMON_POINTER_SITES
            ),
        ),
    )


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    return build_patch(load_runtime_ui(context), context)
