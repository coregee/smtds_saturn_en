"""Install the shared proportional FONT8 renderer in its three consumers."""

import struct

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.generated_asset import RuntimeUiContract, load_runtime_ui
from engine.script.patching import BytePatch, PatchGroup
from engine.script.smallfont.combat import (
    COMBAT_AFFINITY_POINTER_SITE,
    COMBAT_AFFINITY_STOCK_DRAWER,
    COMBAT_ANALYSIS_CAVE,
    COMBAT_ANALYSIS_CAVE_LIMIT,
    COMBAT_ANALYSIS_SKILL_POINTER_SITE,
    COMBAT_BATTLE_ITEM_POINTER_SITES,
    COMBAT_BATTLE_ITEM_STOCK_DRAWER,
    COMBAT_BTL_MES_BODY_BASE_SITES,
    COMBAT_COUNTED_DRAWER,
    COMBAT_COUNTED_POINTER_SITES,
    COMBAT_EVENT_ITEM_POINTER,
    COMBAT_EVENT_ITEM_STOCK_DRAWER,
    COMBAT_HELP_ADVANCE_SITE,
    COMBAT_HELP_BASE_X_SCALE_SITE,
    COMBAT_HELP_CURSOR_START_SITE,
    COMBAT_HELP_CURSOR_WIDTH_SITE,
    COMBAT_HELP_DRAW_X_SITE,
    COMBAT_HELP_DRAWER_POINTER,
    COMBAT_HELP_NEWLINE_X_SITE,
    COMBAT_HELP_START_X,
    COMBAT_RESULT_CHARACTER_NAME_POINTER,
    COMBAT_RESULT_ITEM_POINTER,
    COMBAT_RESULT_ITEM_STOCK_DRAWER,
    COMBAT_RESULT_LABEL_GLYPH_POINTER,
    COMBAT_RESULT_NAME_POINTER,
    COMBAT_RESULT_NAME_STOCK_DRAWER,
    COMBAT_SMALLFONT_CAVE_LIMIT,
    COMBAT_STOCK_GLYPH,
    COMBAT_SURFACE_ADVANCE_SITE,
    COMBAT_SURFACE_DRAWER_POINTER,
    COMBAT_SURFACE_STOCK_DRAWER,
    build_combat_analysis_cave,
    build_combat_battle_item_drawer,
    build_combat_counted_drawer,
    build_combat_race_pool,
    build_combat_surface_renderer,
)
from engine.script.smallfont.model import (
    BASE,
    NORMCOM_PANEL_CAVE_LIMIT,
    NORMCOM_PANEL_CAVE_OFFSET,
    OVERLAYS,
    OverlaySpec,
)
from engine.script.smallfont.renderer import (
    build_character_panel_data,
    build_character_panel_drawer,
    build_combat_panel_drawer,
    build_drawer,
    build_normcom_demon_panel_data,
    build_normcom_panel_drawer,
    build_packed_full_name_drawer,
)
from engine.script.text_render.font8_blitter import build_pixel_blitter
from engine.script.text_render.font8_metrics import font8_metrics, load_metrics
from text.script.source_models import IndexedBytesSource
from text.script.sources import get_source


def _append_character_panel(
    payload: bytearray,
    payload_address: int,
    *,
    character_rows: list[dict],
    font8_data: tuple[bytes, dict[str, int]],
    blitter_address: int,
    fallback_address: int,
    widths_address: int,
) -> int:
    offsets, pool = build_character_panel_data(character_rows, font8_data)
    offsets_address = payload_address + len(payload)
    payload.extend(offsets)
    pool_address = payload_address + len(payload)
    payload.extend(pool)
    while (payload_address + len(payload)) & 3:
        payload.append(0)
    drawer_address = payload_address + len(payload)
    payload.extend(
        build_character_panel_drawer(
            drawer_address,
            blitter_address,
            fallback_address,
            widths_address,
            offsets_address,
            pool_address,
        )
    )
    return drawer_address


def _append_combat_panel(
    payload: bytearray,
    payload_address: int,
    *,
    blitter_address: int,
    fallback_address: int,
    widths_address: int,
    character_offsets_address: int,
    character_pool_address: int,
    demon_offsets_address: int,
    demon_pool_address: int,
) -> int:
    while (payload_address + len(payload)) & 3:
        payload.append(0)
    drawer_address = payload_address + len(payload)
    payload.extend(
        build_combat_panel_drawer(
            drawer_address,
            blitter_address,
            fallback_address,
            widths_address,
            character_offsets_address,
            character_pool_address,
            demon_offsets_address,
            demon_pool_address,
        )
    )
    return drawer_address


def _append_normcom_panel(
    payload: bytearray,
    payload_address: int,
    *,
    character_rows: list[dict],
    demon_rows: list[dict],
    built_names: bytes,
    font8_data: tuple[bytes, dict[str, int]],
    blitter_address: int,
    fallback_address: int,
    widths_address: int,
) -> int:
    character_offsets, character_pool = build_character_panel_data(
        character_rows, font8_data
    )
    long_name_bits, name_pool, high_name_pool = build_normcom_demon_panel_data(
        demon_rows, built_names, font8_data
    )

    def append(data: bytes, alignment: int = 1) -> int:
        while (payload_address + len(payload)) % alignment:
            payload.append(0)
        address = payload_address + len(payload)
        payload.extend(data)
        return address

    character_offsets_address = append(character_offsets, 2)
    character_pool_address = append(character_pool)
    long_name_bits_address = append(long_name_bits)
    name_pool_address = append(name_pool, 2)
    high_name_pool_address = append(high_name_pool, 2)
    while (payload_address + len(payload)) & 3:
        payload.append(0)
    drawer_address = payload_address + len(payload)
    payload.extend(
        build_normcom_panel_drawer(
            drawer_address,
            blitter_address,
            fallback_address,
            widths_address,
            character_offsets_address,
            character_pool_address,
            long_name_bits_address,
            name_pool_address,
            high_name_pool_address,
        )
    )
    return drawer_address


def build_group(
    overlay: OverlaySpec,
    contract: RuntimeUiContract | None = None,
    context: EngineBuildContext | None = None,
) -> PatchGroup:
    font8_data = (
        font8_metrics()
        if context is None
        else load_metrics(context.font_generated_root / "font8_metrics.json")
    )
    widths, codes = font8_data
    cave_address = BASE + overlay.cave_offset
    blitter = build_pixel_blitter(cave_address)
    payload = bytearray(blitter)
    drawer_addresses = {}
    counted_drawer_address = None
    surface_drawer_address = None
    battle_item_drawer_address = None
    analysis_payload = None
    analysis_addresses = None
    panel_fallback_address = None
    panel_cave_patch = None

    while (overlay.cave_offset + len(payload)) & 3:
        payload.append(0)
    widths_address = BASE + overlay.cave_offset + len(payload)
    payload.extend(widths)

    for drawer in overlay.drawers:
        while (overlay.cave_offset + len(payload)) & 3:
            payload.append(0)
        fallback_address = BASE + overlay.cave_offset + len(payload)
        payload.extend(
            build_drawer(
                fallback_address,
                cave_address,
                overlay,
                drawer,
                widths_address,
            )
        )
        if drawer.packed_full_names:
            while (overlay.cave_offset + len(payload)) & 3:
                payload.append(0)
            drawer_address = BASE + overlay.cave_offset + len(payload)
            payload.extend(
                build_packed_full_name_drawer(
                    drawer_address,
                    cave_address,
                    fallback_address,
                    widths_address,
                    drawer.stride,
                    string_first=drawer.string_first,
                )
            )
        else:
            drawer_address = fallback_address
        drawer_addresses[drawer.name] = drawer_address
        if drawer.name == "panel":
            panel_fallback_address = fallback_address

    context = context or DEFAULT_CONTEXT
    contract = contract or load_runtime_ui(context)
    character_rows = contract.section("character_names")
    if not isinstance(character_rows, list):
        raise ValueError(f"{contract.path}: invalid character_names section")

    if overlay.target.name == "NORMCOM.BIN":
        panel_payload = bytearray()
        panel_cave = BASE + NORMCOM_PANEL_CAVE_OFFSET
        if panel_fallback_address is None:
            raise ValueError("NORMCOM character panel fallback is missing")
        demon_rows = contract.section("demon_names")
        if not isinstance(demon_rows, list):
            raise ValueError(f"{contract.path}: invalid demon_names section")
        panel_address = _append_normcom_panel(
            panel_payload,
            panel_cave,
            character_rows=character_rows,
            demon_rows=demon_rows,
            built_names=(context.build_root / "DVLNAME.DAT").read_bytes(),
            font8_data=font8_data,
            blitter_address=cave_address,
            fallback_address=panel_fallback_address,
            widths_address=widths_address,
        )
        if NORMCOM_PANEL_CAVE_OFFSET + len(panel_payload) > NORMCOM_PANEL_CAVE_LIMIT:
            raise ValueError("NORMCOM character panel exceeds its reserved cave")
        panel_cave_patch = BytePatch(
            "character_panel_cave",
            panel_cave,
            bytes(len(panel_payload)),
            bytes(panel_payload),
        )
        drawer_addresses["panel"] = panel_address

    if overlay.target.name == "COMBAT.BIN":
        demon_rows = contract.section("demon_names")
        affinity_rows = contract.section("combat_affinities")
        result_label_rows = contract.section("combat_result_labels")
        race_rows = contract.section("status_tables")
        if not all(
            isinstance(rows, list)
            for rows in (demon_rows, affinity_rows, result_label_rows, race_rows)
        ):
            raise ValueError(f"{contract.path}: invalid COMBAT runtime UI sections")
        combat_source = (context.extracted_root / "COMBAT.BIN").read_bytes()
        built_analysis_payload, analysis_addresses = build_combat_analysis_cave(
            cave_address,
            widths_address,
            drawer_addresses["panel"],
            demon_rows=demon_rows,
            affinity_rows=affinity_rows,
            result_label_rows=result_label_rows,
            character_rows=character_rows,
            combat_source=combat_source,
            font8_data=font8_data,
        )
        analysis_payload = bytearray(built_analysis_payload)
        panel_address = _append_combat_panel(
            analysis_payload,
            COMBAT_ANALYSIS_CAVE,
            blitter_address=cave_address,
            fallback_address=analysis_addresses["panel_full_name_drawer"],
            widths_address=widths_address,
            character_offsets_address=analysis_addresses["character_offsets"],
            character_pool_address=analysis_addresses["character_pool"],
            demon_offsets_address=analysis_addresses["name_offsets"],
            demon_pool_address=analysis_addresses["name_pool"],
        )
        if COMBAT_ANALYSIS_CAVE + len(analysis_payload) > COMBAT_ANALYSIS_CAVE_LIMIT:
            raise ValueError("COMBAT character panel exceeds the verified zero window")
        analysis_addresses["character_panel_drawer"] = panel_address
        drawer_addresses["panel"] = panel_address
        while (overlay.cave_offset + len(payload)) & 3:
            payload.append(0)
        race_pool_address = BASE + overlay.cave_offset + len(payload)
        payload.extend(build_combat_race_pool(codes, race_rows))
        while (overlay.cave_offset + len(payload)) & 3:
            payload.append(0)
        counted_drawer_address = BASE + overlay.cave_offset + len(payload)
        payload.extend(
            build_combat_counted_drawer(
                counted_drawer_address,
                cave_address,
                widths_address,
                race_pool_address,
                analysis_addresses["name_offsets"],
                analysis_addresses["name_pool"],
            )
        )
        while (overlay.cave_offset + len(payload)) & 3:
            payload.append(0)
        surface_renderer_address = BASE + overlay.cave_offset + len(payload)
        surface_renderer, surface_drawers = build_combat_surface_renderer(
            surface_renderer_address
        )
        surface_drawer_address = surface_drawers["escape"]
        help_drawer_address = surface_drawers["help"]
        payload.extend(surface_renderer)
        while (overlay.cave_offset + len(payload)) & 3:
            payload.append(0)
        battle_item_drawer_address = BASE + overlay.cave_offset + len(payload)
        payload.extend(
            build_combat_battle_item_drawer(
                battle_item_drawer_address,
                cave_address,
                widths_address,
            )
        )
    elif overlay.target.name == "MAZE.BIN":
        if panel_fallback_address is None:
            raise ValueError("MAZE character panel fallback is missing")
        drawer_addresses["panel"] = _append_character_panel(
            payload,
            cave_address,
            character_rows=character_rows,
            font8_data=font8_data,
            blitter_address=cave_address,
            fallback_address=panel_fallback_address,
            widths_address=widths_address,
        )
    cave_limit = {
        "NORMCOM.BIN": 0x0800,
        "COMBAT.BIN": COMBAT_SMALLFONT_CAVE_LIMIT,
    }.get(overlay.target.name, 0x6500)
    if overlay.cave_offset + len(payload) > cave_limit:
        raise ValueError(
            f"{overlay.target.name}: small-font cave exceeds {cave_limit:#x}"
        )

    patches = [
        BytePatch(
            "renderer_cave",
            cave_address,
            bytes(len(payload)),
            bytes(payload),
        ),
    ]
    if panel_cave_patch is not None:
        patches.append(panel_cave_patch)
    for drawer in overlay.drawers:
        replacement = struct.pack(">I", drawer_addresses[drawer.name])
        expected = struct.pack(">I", drawer.stock_drawer)
        for site in drawer.pointer_sites:
            patches.append(
                BytePatch(
                    f"{drawer.name}_pointer_{site:08x}",
                    site,
                    expected,
                    replacement,
                )
            )
    if counted_drawer_address is not None:
        replacement = struct.pack(">I", counted_drawer_address)
        expected = struct.pack(">I", COMBAT_COUNTED_DRAWER)
        for site in COMBAT_COUNTED_POINTER_SITES:
            patches.append(
                BytePatch(
                    f"analysis_counted_pointer_{site:08x}",
                    site,
                    expected,
                    replacement,
                )
            )
    if analysis_payload is not None and analysis_addresses is not None:
        patches.append(
            BytePatch(
                "analysis_english_cave",
                COMBAT_ANALYSIS_CAVE,
                bytes(len(analysis_payload)),
                bytes(analysis_payload),
            )
        )
        patches.append(
            BytePatch(
                "analysis_affinity_pointer",
                COMBAT_AFFINITY_POINTER_SITE,
                struct.pack(">I", COMBAT_AFFINITY_STOCK_DRAWER),
                struct.pack(">I", analysis_addresses["affinity_drawer"]),
            )
        )
        patches.append(
            BytePatch(
                "analysis_skill_pointer",
                COMBAT_ANALYSIS_SKILL_POINTER_SITE,
                struct.pack(">I", COMBAT_COUNTED_DRAWER),
                struct.pack(">I", analysis_addresses["skill_drawer"]),
            )
        )
        patches.extend(
            (
                BytePatch(
                    "result_label_glyph_pointer",
                    COMBAT_RESULT_LABEL_GLYPH_POINTER,
                    struct.pack(">I", COMBAT_STOCK_GLYPH),
                    struct.pack(
                        ">I",
                        analysis_addresses["result_label_drawer"],
                    ),
                ),
                BytePatch(
                    "result_codename_pointer",
                    COMBAT_RESULT_NAME_POINTER,
                    struct.pack(">I", COMBAT_RESULT_NAME_STOCK_DRAWER),
                    struct.pack(
                        ">I",
                        analysis_addresses["result_name_drawer"],
                    ),
                ),
                BytePatch(
                    "result_character_name_pointer",
                    COMBAT_RESULT_CHARACTER_NAME_POINTER,
                    struct.pack(">I", COMBAT_RESULT_NAME_STOCK_DRAWER),
                    struct.pack(
                        ">I",
                        analysis_addresses["result_name_drawer"],
                    ),
                ),
                BytePatch(
                    "result_item_pointer",
                    COMBAT_RESULT_ITEM_POINTER,
                    struct.pack(">I", COMBAT_RESULT_ITEM_STOCK_DRAWER),
                    struct.pack(
                        ">I",
                        analysis_addresses["result_item_drawer"],
                    ),
                ),
                BytePatch(
                    "event_dialogue_item_grid_pointer",
                    COMBAT_EVENT_ITEM_POINTER,
                    struct.pack(">I", COMBAT_EVENT_ITEM_STOCK_DRAWER),
                    struct.pack(
                        ">I",
                        analysis_addresses["event_item_drawer"],
                    ),
                ),
            )
        )
    if surface_drawer_address is not None:
        patches.extend(
            (
                BytePatch(
                    "battle_surface_drawer_pointer",
                    COMBAT_SURFACE_DRAWER_POINTER,
                    struct.pack(">I", COMBAT_SURFACE_STOCK_DRAWER),
                    struct.pack(">I", surface_drawer_address),
                ),
                BytePatch(
                    "battle_surface_pixel_advance",
                    COMBAT_SURFACE_ADVANCE_SITE,
                    struct.pack(">H", 0x7101),
                    struct.pack(">H", 0x310C),
                ),
                BytePatch(
                    "battle_help_drawer_pointer",
                    COMBAT_HELP_DRAWER_POINTER,
                    struct.pack(">I", COMBAT_SURFACE_STOCK_DRAWER),
                    struct.pack(">I", help_drawer_address),
                ),
                BytePatch(
                    "battle_help_cursor_start",
                    COMBAT_HELP_CURSOR_START_SITE,
                    struct.pack(">H", 0xE901),
                    struct.pack(">H", 0xE900 | COMBAT_HELP_START_X),
                ),
                BytePatch(
                    "battle_help_remove_fixed_x_scale",
                    COMBAT_HELP_BASE_X_SCALE_SITE,
                    struct.pack(">H", 0xE110),
                    struct.pack(">H", 0xE100),
                ),
                BytePatch(
                    "battle_help_newline_cursor",
                    COMBAT_HELP_NEWLINE_X_SITE,
                    struct.pack(">H", 0x0929),
                    struct.pack(">H", 0xE900 | COMBAT_HELP_START_X),
                ),
                BytePatch(
                    "battle_help_pixel_x",
                    COMBAT_HELP_DRAW_X_SITE,
                    struct.pack(">H", 0xE600),
                    struct.pack(">H", 0x6693),
                ),
                BytePatch(
                    "battle_help_pixel_advance",
                    COMBAT_HELP_ADVANCE_SITE,
                    struct.pack(">H", 0x7101),
                    struct.pack(">H", 0x310C),
                ),
                BytePatch(
                    "battle_help_wide_cursor",
                    COMBAT_HELP_CURSOR_WIDTH_SITE,
                    struct.pack(">H", 0x691C),
                    struct.pack(">H", 0x691D),
                ),
            )
        )
    if battle_item_drawer_address is not None:
        replacement = struct.pack(">I", battle_item_drawer_address)
        expected = struct.pack(">I", COMBAT_BATTLE_ITEM_STOCK_DRAWER)
        patches.extend(
            BytePatch(
                f"battle_item_name_pointer_{address:08x}",
                address,
                expected,
                replacement,
            )
            for address in COMBAT_BATTLE_ITEM_POINTER_SITES
        )
    if overlay.target.name == "COMBAT.BIN":
        btl_mes = get_source("btl_mes")
        if not isinstance(btl_mes, IndexedBytesSource):
            raise TypeError("btl_mes must be an indexed-byte source")
        if btl_mes.engine_load_address is None:
            raise ValueError("btl_mes is missing its engine load address")
        stock_body = btl_mes.engine_load_address + btl_mes.table_size
        output_body = btl_mes.engine_load_address + btl_mes.output_body_offset
        patches.extend(
            BytePatch(
                f"btl_mes_body_base_{address:08x}",
                address,
                struct.pack(">I", stock_body),
                struct.pack(">I", output_body),
            )
            for address in COMBAT_BTL_MES_BODY_BASE_SITES
        )
    return PatchGroup("smallfont_vwf", overlay.target, tuple(patches))


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    contract = load_runtime_ui(context)
    return tuple(build_group(overlay, contract, context) for overlay in OVERLAYS)
