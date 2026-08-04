"""Register detailed status-interface patches across their copied overlays."""

import hashlib
import struct
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.event.model import FUSION_CONFIRMATION_OVERFLOW_ADDRESS
from engine.script.event.packed_layout import next_runtime_address
from engine.script.fixed_text_fields.generated import load_runtime_fields
from engine.script.generated_asset import load_runtime_ui
from engine.script.patching import BinaryTarget, BytePatch, DigestPatch, PatchGroup
from engine.script.static_text import load_static_asset
from engine.script.status_ui.assets import (
    direct_color_assets,
    direct_color_row,
    read_font8,
    read_original,
    status_atlas_tile,
    status_mask,
)
from engine.script.status_ui.data import derived_rows, status_labels
from engine.script.status_ui.fusion_confirmation import (
    LABEL_NO_FILE,
    LABEL_YES_FILE,
    MAIN_FILE,
    MAIN_SIZE,
)
from engine.script.status_ui.fusion_confirmation import (
    build_storage as build_fusion_confirmation_storage,
)
from engine.script.status_ui.fusion_confirmation import (
    pointer_lookup_patch as fusion_confirmation_pointer_lookup_patch,
)
from engine.script.status_ui.model import (
    AFFINITY_DRAWER_PTR,
    ATLAS_FILE,
    BASE,
    BUILD_ATLAS,
    BUILD_PANEL,
    COUNTS_FILE,
    DA3D_AFFINITY_DRAWER_PTR,
    DA3D_FONT8_DRAWER,
    DA3D_FONT16_DRAWER,
    DA3D_GENERIC_ACCURACY_FILE,
    DA3D_GENERIC_ATTACK_FILE,
    DA3D_LOYALTY_LABEL_FILE,
    DA3D_NAME_RACE_DRAWER_PTR,
    DA3D_NODE_BITMAP_FILE,
    DA3D_ROW_BITMAP_FILE,
    DA3D_SHA256,
    DA3D_SKILL_DRAWER_PTR,
    DA3D_STATUS_BLOCK,
    DA3D_STATUS_BLOCK_END_FILE,
    DA3D_STATUS_BLOCK_FILE,
    DA3D_TABLE_DRAWER_PTR,
    DA3D_TABLE_FONT8_DRAWER,
    DA3D_TABLE_HIGHLIGHT_DRAWER_PTR,
    DA3D_TABLE_RACE_SOURCE,
    DA3D_TABLE_RACE_SOURCE_FILE,
    DA3D_TARGET,
    DETAIL_ATLAS_PTR,
    DETAIL_PANEL_PTR,
    EVENT_AFFINITY_DRAWER_PTR,
    EVENT_BAR_DRINK_DRAWER_PTR,
    EVENT_BAR_DRINK_STOCK_DRAWER,
    EVENT_BAR_LABEL_ALIAS_REPLACEMENT,
    EVENT_BAR_LABEL_ALIAS_SOURCE,
    EVENT_BAR_LABEL_ALIASES,
    EVENT_BAR_PARTY_GLYPH_PTR,
    EVENT_BAR_STATUS_GLYPH_PTR,
    EVENT_BAR_STOCK_GLYPH,
    EVENT_BAR_TALK_ROLE_DRAWER_PTR,
    EVENT_BAR_TALK_ROLE_STOCK_DRAWER,
    EVENT_CHARACTER_INSERT_END,
    EVENT_CHARACTER_INSERT_STOCK,
    EVENT_DEMON_INSERT_PTR,
    EVENT_DEMON_INSERT_STOCK,
    EVENT_FONT12_DRAWER,
    EVENT_FONT16_DRAWER,
    EVENT_FUSION_CONFIRMATION_DRAWER_PTR,
    EVENT_GENERIC_ACCURACY_FILE,
    EVENT_GENERIC_ATTACK_FILE,
    EVENT_HEALING_ALL_DRAWER_PTRS,
    EVENT_HEALING_ALL_STOCK_DRAWER,
    EVENT_HEALING_NAME_DRAWER_PTRS,
    EVENT_HEALING_NAME_STOCK_DRAWER,
    EVENT_LOYALTY_LABEL_FILE,
    EVENT_NAME_RACE_DRAWER_PTR,
    EVENT_NODE_BITMAP_FILE,
    EVENT_RACE_INSERT_PTR,
    EVENT_RACE_INSERT_STOCK,
    EVENT_ROW_BITMAP_FILE,
    EVENT_SHA256,
    EVENT_SKILL_DRAWER_PTR,
    EVENT_STATUS_SKILL_DRAWER_PTR,
    EVENT_TARGET,
    FONT8_DRAWER,
    FONT12_SOURCE_PTR_FILE,
    FONT16_DRAWER,
    GENERIC_ACCURACY_FILE,
    GENERIC_ATTACK_FILE,
    ITEM_ICON_DRAWER,
    ITEM_ICON_DRAWER_PTRS,
    LEVEL_UP_GENERIC_ACCURACY_FILE,
    LEVEL_UP_GENERIC_ATTACK_FILE,
    LEVEL_UP_LEARNED_MAGIC_COPY_END_FILE,
    LEVEL_UP_LEARNED_MAGIC_COPY_FILE,
    LEVEL_UP_LEARNED_MAGIC_FIELD_FILE,
    LEVEL_UP_LEARNED_MAGIC_MAX_WORDS,
    LEVEL_UP_LEARNED_MAGIC_POINTER,
    LEVEL_UP_NAME_DRAWER_PTR,
    LEVEL_UP_NODE_BITMAP_FILE,
    LEVEL_UP_ROW_BITMAP_FILE,
    LEVEL_UP_RUNTIME_CAVE_FILE,
    LEVEL_UP_SHA256,
    LEVEL_UP_STOCK_NAME_DRAWER,
    LEVEL_UP_TARGET,
    LOYALTY_LABEL_FILE,
    NAME_RACE_DRAWER_PTR,
    NODE_BITMAP_FILE,
    NORMCOM_SHA256,
    NORMCOM_TARGET,
    PAUSE_PANEL_PTR,
    PERSONALITY_LABELS,
    PERSONALITY_STRIDE,
    ROW_BITMAP_FILE,
    ROWS_FILE,
    RUNTIME_CAVE_FILE,
    SKILL_DRAWER_PTR,
    STATUS_MASK_PTR,
    STATUS_STOCK_ATLAS,
    STATUS_STOCK_MASKS,
    WRAPPER_FILE,
    X_POSITIONS_FILE,
)
from engine.script.status_ui.runtime import (
    build_atlas_wrapper,
    build_da3d_status_runtime,
    build_event_status_runtime,
    build_level_up_name_runtime,
    build_level_up_text_copy,
    build_status_runtime,
)

LEVEL_UP_TEXT_ASSET = Path("fixed_words/LEVEL_UP.BIN.json")


def digest_patch(
    target: BinaryTarget,
    name: str,
    offset: int,
    original: bytes,
    replacement: bytes,
) -> DigestPatch:
    source = original[offset : offset + len(replacement)]
    if len(source) != len(replacement):
        raise ValueError(f"{target.name} {name} exceeds the file")
    return DigestPatch(
        name,
        target.load_address + offset,
        hashlib.sha256(source).hexdigest(),
        replacement,
    )


def build_normcom_patch() -> PatchGroup:
    original = read_original(NORMCOM_TARGET, NORMCOM_SHA256)
    font8 = read_font8()

    labels = status_labels()
    rows_config = derived_rows(labels)
    chunks = []
    for row in rows_config:
        for chunk in row:
            if chunk not in chunks:
                chunks.append(chunk)
    if len(chunks) > 9:
        raise ValueError("status atlas has room for at most nine derived chunks")
    chunks.extend([""] * (9 - len(chunks)))
    atlas_labels = (*labels.base, *chunks, *("" for _ in range(6)))
    if len(atlas_labels) != 21:
        raise ValueError("status atlas must contain 21 tiles")

    atlas = b"".join(status_atlas_tile(text, font8) for text in atlas_labels)
    masks = b"".join(
        status_mask(atlas[index * 0x48 : (index + 1) * 0x48]) for index in range(21)
    )
    chunk_ids = {chunk: 6 + index for index, chunk in enumerate(chunks) if chunk}
    rows = bytearray()
    counts = bytearray()
    x_positions = bytearray()
    for row in rows_config:
        ids = [chunk_ids[chunk] for chunk in row]
        rows.extend(struct.pack(">4H", *(ids + [0] * (4 - len(ids)))))
        counts.extend(struct.pack(">H", len(ids)))
        x_positions.extend(struct.pack(">H", 12 if len(ids) == 2 else 18))

    node_data, row_data = direct_color_assets(
        original,
        NODE_BITMAP_FILE,
        font8,
        labels.base,
        rows_config,
    )
    (
        runtime,
        name_race_drawer,
        skill_drawer,
        affinity_drawer,
        masks_address,
        stock_icon_drawer,
    ) = build_status_runtime(masks)
    dirty_address = masks_address + len(masks)

    atlas_address = BASE + ATLAS_FILE
    panel_wrapper = build_atlas_wrapper(
        BASE + WRAPPER_FILE,
        BUILD_PANEL,
        atlas_address,
        masks_address,
        dirty_address,
    )
    second_offset = (WRAPPER_FILE + len(panel_wrapper) + 3) & ~3
    atlas_wrapper = build_atlas_wrapper(
        BASE + second_offset,
        BUILD_ATLAS,
        atlas_address,
        masks_address,
        dirty_address,
    )
    wrapper_end = second_offset + len(atlas_wrapper)
    if wrapper_end > ATLAS_FILE:
        raise ValueError("status wrappers overlap the English atlas")
    wrapper_payload = bytearray(wrapper_end - WRAPPER_FILE)
    wrapper_payload[: len(panel_wrapper)] = panel_wrapper
    start = second_offset - WRAPPER_FILE
    wrapper_payload[start : start + len(atlas_wrapper)] = atlas_wrapper

    def require_u32(offset: int, expected: int, name: str) -> None:
        actual = struct.unpack_from(">I", original, offset)[0]
        if actual != expected:
            raise ValueError(
                f"NORMCOM.BIN {name} at {offset:#x}: "
                f"expected {expected:#010x}, found {actual:#010x}"
            )

    require_u32(FONT12_SOURCE_PTR_FILE, STATUS_STOCK_ATLAS, "FONT12 source")
    require_u32(
        STATUS_MASK_PTR - BASE,
        STATUS_STOCK_MASKS,
        "FONT12 mask source",
    )
    require_u32(PAUSE_PANEL_PTR - BASE, BUILD_PANEL, "pause status builder")

    patches = [
        BytePatch(
            "wrapper_cave",
            BASE + WRAPPER_FILE,
            bytes(len(wrapper_payload)),
            bytes(wrapper_payload),
        ),
        BytePatch("font12_atlas", atlas_address, bytes(len(atlas)), atlas),
        digest_patch(NORMCOM_TARGET, "derived_rows", ROWS_FILE, original, bytes(rows)),
        digest_patch(
            NORMCOM_TARGET, "derived_counts", COUNTS_FILE, original, bytes(counts)
        ),
        digest_patch(
            NORMCOM_TARGET,
            "derived_x_positions",
            X_POSITIONS_FILE,
            original,
            bytes(x_positions),
        ),
        digest_patch(
            NORMCOM_TARGET,
            "parameter_nodes",
            NODE_BITMAP_FILE,
            original,
            node_data,
        ),
        digest_patch(
            NORMCOM_TARGET,
            "parameter_rows",
            ROW_BITMAP_FILE,
            original,
            row_data,
        ),
        digest_patch(
            NORMCOM_TARGET,
            "generic_attack_label",
            GENERIC_ATTACK_FILE,
            original,
            direct_color_row("Attack", font8),
        ),
        digest_patch(
            NORMCOM_TARGET,
            "generic_accuracy_label",
            GENERIC_ACCURACY_FILE,
            original,
            direct_color_row("Accuracy", font8),
        ),
        *(
            digest_patch(
                NORMCOM_TARGET,
                f"personality_label_{index}",
                LOYALTY_LABEL_FILE + index * PERSONALITY_STRIDE,
                original,
                direct_color_row(label, font8, 40),
            )
            for index, label in enumerate(PERSONALITY_LABELS)
        ),
        BytePatch(
            "english_status_runtime",
            BASE + RUNTIME_CAVE_FILE,
            bytes(len(runtime)),
            runtime,
        ),
        BytePatch(
            "name_race_drawer",
            NAME_RACE_DRAWER_PTR,
            struct.pack(">I", FONT16_DRAWER),
            struct.pack(">I", name_race_drawer),
        ),
        BytePatch(
            "skill_name_drawer",
            SKILL_DRAWER_PTR,
            struct.pack(">I", FONT8_DRAWER),
            struct.pack(">I", skill_drawer),
        ),
        BytePatch(
            "affinity_drawer",
            AFFINITY_DRAWER_PTR,
            struct.pack(">I", FONT16_DRAWER),
            struct.pack(">I", affinity_drawer),
        ),
        BytePatch(
            "detail_panel_builder",
            DETAIL_PANEL_PTR,
            struct.pack(">I", BUILD_PANEL),
            struct.pack(">I", BASE + WRAPPER_FILE),
        ),
        BytePatch(
            "detail_atlas_builder",
            DETAIL_ATLAS_PTR,
            struct.pack(">I", BUILD_ATLAS),
            struct.pack(">I", BASE + second_offset),
        ),
        *(
            BytePatch(
                f"restore_item_icon_atlas_{site:08x}",
                site,
                struct.pack(">I", ITEM_ICON_DRAWER),
                struct.pack(">I", stock_icon_drawer),
            )
            for site in ITEM_ICON_DRAWER_PTRS
        ),
    ]
    return PatchGroup("status_ui", NORMCOM_TARGET, tuple(patches))


def build_event_patch() -> PatchGroup:
    event_runtime_cave = next_runtime_address()
    fusion_confirmation_asset = load_static_asset(
        Path("static") / "EVENT.fusion_confirmation.json",
        Path("EVENT.BIN"),
    )
    fusion_confirmation = build_fusion_confirmation_storage(fusion_confirmation_asset)
    original = read_original(EVENT_TARGET, EVENT_SHA256)
    font8 = read_font8()
    labels = status_labels()
    rows_config = derived_rows(labels)
    node_data, row_data = direct_color_assets(
        original,
        EVENT_NODE_BITMAP_FILE,
        font8,
        labels.base,
        rows_config,
    )
    (
        runtime,
        font16_vwf,
        name_race_drawer,
        skill_drawer,
        status_skill_drawer,
        affinity_drawer,
        bar_drink_drawer,
        bar_talk_role_drawer,
        bar_status_glyph,
        bar_party_glyph,
        healing_all_drawer,
        healing_name_drawer,
        dialogue_character_name_insert,
        dialogue_demon_name_insert,
        dialogue_race_insert,
    ) = build_event_status_runtime(event_runtime_cave)
    return PatchGroup(
        "status_ui",
        EVENT_TARGET,
        (
            digest_patch(
                EVENT_TARGET,
                "fusion_parameter_nodes",
                EVENT_NODE_BITMAP_FILE,
                original,
                node_data,
            ),
            digest_patch(
                EVENT_TARGET,
                "fusion_parameter_rows",
                EVENT_ROW_BITMAP_FILE,
                original,
                row_data,
            ),
            digest_patch(
                EVENT_TARGET,
                "fusion_generic_attack_label",
                EVENT_GENERIC_ATTACK_FILE,
                original,
                direct_color_row("Attack", font8),
            ),
            digest_patch(
                EVENT_TARGET,
                "fusion_generic_accuracy_label",
                EVENT_GENERIC_ACCURACY_FILE,
                original,
                direct_color_row("Accuracy", font8),
            ),
            *(
                digest_patch(
                    EVENT_TARGET,
                    f"fusion_personality_label_{index}",
                    EVENT_LOYALTY_LABEL_FILE + index * PERSONALITY_STRIDE,
                    original,
                    direct_color_row(label, font8, 40),
                )
                for index, label in enumerate(PERSONALITY_LABELS)
            ),
            BytePatch(
                "fusion_status_runtime",
                event_runtime_cave,
                bytes(len(runtime)),
                runtime,
            ),
            fusion_confirmation_pointer_lookup_patch(),
            BytePatch(
                "fusion_confirmation_main_storage",
                BASE + MAIN_FILE,
                original[MAIN_FILE : MAIN_FILE + MAIN_SIZE],
                fusion_confirmation.main,
            ),
            BytePatch(
                "fusion_confirmation_level_too_low",
                FUSION_CONFIRMATION_OVERFLOW_ADDRESS,
                bytes(len(fusion_confirmation.level_too_low)),
                fusion_confirmation.level_too_low,
            ),
            BytePatch(
                "fusion_confirmation_label_yes",
                BASE + LABEL_YES_FILE,
                original[
                    LABEL_YES_FILE : LABEL_YES_FILE + len(fusion_confirmation.label_yes)
                ],
                fusion_confirmation.label_yes,
            ),
            BytePatch(
                "fusion_confirmation_label_no",
                BASE + LABEL_NO_FILE,
                original[
                    LABEL_NO_FILE : LABEL_NO_FILE + len(fusion_confirmation.label_no)
                ],
                fusion_confirmation.label_no,
            ),
            BytePatch(
                "fusion_confirmation_vwf_drawer",
                EVENT_FUSION_CONFIRMATION_DRAWER_PTR,
                struct.pack(">I", EVENT_FONT16_DRAWER),
                struct.pack(">I", font16_vwf),
            ),
            BytePatch(
                "fusion_name_race_drawer",
                EVENT_NAME_RACE_DRAWER_PTR,
                struct.pack(">I", EVENT_FONT16_DRAWER),
                struct.pack(">I", name_race_drawer),
            ),
            BytePatch(
                "fusion_skill_name_drawer",
                EVENT_SKILL_DRAWER_PTR,
                struct.pack(">I", EVENT_FONT12_DRAWER),
                struct.pack(">I", skill_drawer),
            ),
            BytePatch(
                "fusion_status_skill_drawer",
                EVENT_STATUS_SKILL_DRAWER_PTR,
                struct.pack(">I", EVENT_FONT12_DRAWER),
                struct.pack(">I", status_skill_drawer),
            ),
            BytePatch(
                "fusion_affinity_drawer",
                EVENT_AFFINITY_DRAWER_PTR,
                struct.pack(">I", EVENT_FONT16_DRAWER),
                struct.pack(">I", affinity_drawer),
            ),
            BytePatch(
                "event_dialogue_character_name_insert",
                EVENT_CHARACTER_INSERT_STOCK,
                original[
                    EVENT_CHARACTER_INSERT_STOCK - BASE : EVENT_CHARACTER_INSERT_END
                    - BASE
                ],
                dialogue_character_name_insert,
            ),
            BytePatch(
                "event_dialogue_demon_name_insert",
                EVENT_DEMON_INSERT_PTR,
                struct.pack(">I", EVENT_DEMON_INSERT_STOCK),
                struct.pack(">I", dialogue_demon_name_insert),
            ),
            BytePatch(
                "event_dialogue_race_insert",
                EVENT_RACE_INSERT_PTR,
                struct.pack(">I", EVENT_RACE_INSERT_STOCK),
                struct.pack(">I", dialogue_race_insert),
            ),
            BytePatch(
                "bar_review_status_aliases",
                EVENT_BAR_LABEL_ALIASES,
                EVENT_BAR_LABEL_ALIAS_SOURCE,
                EVENT_BAR_LABEL_ALIAS_REPLACEMENT,
            ),
            BytePatch(
                "bar_drink_name_drawer",
                EVENT_BAR_DRINK_DRAWER_PTR,
                struct.pack(">I", EVENT_BAR_DRINK_STOCK_DRAWER),
                struct.pack(">I", bar_drink_drawer),
            ),
            BytePatch(
                "bar_talk_role_drawer",
                EVENT_BAR_TALK_ROLE_DRAWER_PTR,
                struct.pack(">I", EVENT_BAR_TALK_ROLE_STOCK_DRAWER),
                struct.pack(">I", bar_talk_role_drawer),
            ),
            BytePatch(
                "bar_status_name_glyph",
                EVENT_BAR_STATUS_GLYPH_PTR,
                struct.pack(">I", EVENT_BAR_STOCK_GLYPH),
                struct.pack(">I", bar_status_glyph),
            ),
            BytePatch(
                "bar_party_name_glyph",
                EVENT_BAR_PARTY_GLYPH_PTR,
                struct.pack(">I", EVENT_BAR_STOCK_GLYPH),
                struct.pack(">I", bar_party_glyph),
            ),
            *(
                BytePatch(
                    f"healing_all_drawer_{index}",
                    site,
                    struct.pack(">I", EVENT_HEALING_ALL_STOCK_DRAWER),
                    struct.pack(">I", healing_all_drawer),
                )
                for index, site in enumerate(EVENT_HEALING_ALL_DRAWER_PTRS)
            ),
            *(
                BytePatch(
                    f"healing_name_drawer_{index}",
                    site,
                    struct.pack(">I", EVENT_HEALING_NAME_STOCK_DRAWER),
                    struct.pack(">I", healing_name_drawer),
                )
                for index, site in enumerate(EVENT_HEALING_NAME_DRAWER_PTRS)
            ),
        ),
    )


def build_da3d_patch() -> PatchGroup:
    original = read_original(DA3D_TARGET, DA3D_SHA256)
    font8 = read_font8()
    labels = status_labels()
    rows_config = derived_rows(labels)
    node_data, row_data = direct_color_assets(
        original,
        DA3D_NODE_BITMAP_FILE,
        font8,
        labels.base,
        rows_config,
    )
    (
        runtime,
        table_runtime,
        _font8_vwf,
        _font16_vwf,
        name_race_drawer,
        skill_drawer,
        affinity_drawer,
        table_drawer,
    ) = build_da3d_status_runtime(DA3D_STATUS_BLOCK)
    return PatchGroup(
        "status_ui",
        DA3D_TARGET,
        (
            BytePatch(
                "demon_analyzer_runtime",
                DA3D_STATUS_BLOCK,
                original[DA3D_STATUS_BLOCK_FILE:DA3D_STATUS_BLOCK_END_FILE],
                runtime,
            ),
            BytePatch(
                "demon_analyzer_table_runtime",
                DA3D_TABLE_RACE_SOURCE,
                original[
                    DA3D_TABLE_RACE_SOURCE_FILE : DA3D_TABLE_RACE_SOURCE_FILE
                    + len(table_runtime)
                ],
                table_runtime,
            ),
            BytePatch(
                "demon_analyzer_name_race_drawer",
                DA3D_NAME_RACE_DRAWER_PTR,
                struct.pack(">I", DA3D_FONT16_DRAWER),
                struct.pack(">I", name_race_drawer),
            ),
            BytePatch(
                "demon_analyzer_skill_drawer",
                DA3D_SKILL_DRAWER_PTR,
                struct.pack(">I", DA3D_FONT8_DRAWER),
                struct.pack(">I", skill_drawer),
            ),
            BytePatch(
                "demon_analyzer_affinity_drawer",
                DA3D_AFFINITY_DRAWER_PTR,
                struct.pack(">I", DA3D_FONT16_DRAWER),
                struct.pack(">I", affinity_drawer),
            ),
            BytePatch(
                "demon_analyzer_table_drawer",
                DA3D_TABLE_DRAWER_PTR,
                struct.pack(">I", DA3D_TABLE_FONT8_DRAWER),
                struct.pack(">I", table_drawer),
            ),
            BytePatch(
                "demon_analyzer_table_highlight_drawer",
                DA3D_TABLE_HIGHLIGHT_DRAWER_PTR,
                struct.pack(">I", DA3D_TABLE_FONT8_DRAWER),
                struct.pack(">I", table_drawer),
            ),
            digest_patch(
                DA3D_TARGET,
                "demon_analyzer_parameter_nodes",
                DA3D_NODE_BITMAP_FILE,
                original,
                node_data,
            ),
            digest_patch(
                DA3D_TARGET,
                "demon_analyzer_parameter_rows",
                DA3D_ROW_BITMAP_FILE,
                original,
                row_data,
            ),
            digest_patch(
                DA3D_TARGET,
                "demon_analyzer_generic_attack_label",
                DA3D_GENERIC_ATTACK_FILE,
                original,
                direct_color_row("Attack", font8),
            ),
            digest_patch(
                DA3D_TARGET,
                "demon_analyzer_generic_accuracy_label",
                DA3D_GENERIC_ACCURACY_FILE,
                original,
                direct_color_row("Accuracy", font8),
            ),
            digest_patch(
                DA3D_TARGET,
                "demon_analyzer_loyalty_label",
                DA3D_LOYALTY_LABEL_FILE,
                original,
                direct_color_row(PERSONALITY_LABELS[0], font8, 40),
            ),
        ),
    )


def build_level_up_patch(context: EngineBuildContext) -> PatchGroup:
    original = read_original(LEVEL_UP_TARGET, LEVEL_UP_SHA256)
    font8 = read_font8()
    labels = status_labels()
    rows_config = derived_rows(labels)
    node_data, row_data = direct_color_assets(
        original,
        LEVEL_UP_NODE_BITMAP_FILE,
        font8,
        labels.base,
        rows_config,
    )
    load_address, runtime_fields = load_runtime_fields(
        LEVEL_UP_TEXT_ASSET,
        context.text_generated_root,
        context.extracted_root,
        expected_source=LEVEL_UP_TARGET.path,
        max_words=LEVEL_UP_LEARNED_MAGIC_MAX_WORDS,
    )
    if load_address != LEVEL_UP_TARGET.load_address or len(runtime_fields) != 1:
        raise ValueError("invalid LEVEL_UP runtime-field layout")
    learned_magic = runtime_fields[0]
    if (
        learned_magic.name != "learned_magic"
        or learned_magic.file_offset != LEVEL_UP_LEARNED_MAGIC_FIELD_FILE
    ):
        raise ValueError("LEVEL_UP learned-magic runtime field is missing")
    character_rows = load_runtime_ui(context).section("character_names")
    if not isinstance(character_rows, list) or len(character_rows) != 6:
        raise ValueError("LEVEL_UP needs six generated character-name rows")
    character_names = []
    for index, row in enumerate(character_rows):
        if not isinstance(row, dict) or row.get("record") != index:
            raise ValueError(f"LEVEL_UP character-name row {index} is invalid")
        text = row.get("tr")
        if not isinstance(text, str) or not text:
            raise ValueError(f"LEVEL_UP character-name row {index} is untranslated")
        character_names.append(text)
    (
        name_runtime,
        name_drawer,
        learned_magic_address,
        _character_table_address,
    ) = build_level_up_name_runtime(learned_magic.words, tuple(character_names))
    copy_address = BASE + LEVEL_UP_LEARNED_MAGIC_COPY_FILE
    copy_window = (
        LEVEL_UP_LEARNED_MAGIC_COPY_END_FILE - LEVEL_UP_LEARNED_MAGIC_COPY_FILE
    )
    text_copy = build_level_up_text_copy(
        copy_address,
        len(learned_magic.words),
        copy_window,
    )
    return PatchGroup(
        "status_ui",
        LEVEL_UP_TARGET,
        (
            BytePatch(
                "level_up_name_runtime",
                BASE + LEVEL_UP_RUNTIME_CAVE_FILE,
                bytes(len(name_runtime)),
                name_runtime,
            ),
            BytePatch(
                "level_up_name_drawer",
                LEVEL_UP_NAME_DRAWER_PTR,
                struct.pack(">I", LEVEL_UP_STOCK_NAME_DRAWER),
                struct.pack(">I", name_drawer),
            ),
            BytePatch(
                "level_up_learned_magic_pointer",
                LEVEL_UP_LEARNED_MAGIC_POINTER,
                struct.pack(">I", BASE + LEVEL_UP_LEARNED_MAGIC_FIELD_FILE),
                struct.pack(">I", learned_magic_address),
            ),
            digest_patch(
                LEVEL_UP_TARGET,
                "level_up_learned_magic_copy",
                LEVEL_UP_LEARNED_MAGIC_COPY_FILE,
                original,
                text_copy,
            ),
            digest_patch(
                LEVEL_UP_TARGET,
                "level_up_parameter_nodes",
                LEVEL_UP_NODE_BITMAP_FILE,
                original,
                node_data,
            ),
            digest_patch(
                LEVEL_UP_TARGET,
                "level_up_parameter_rows",
                LEVEL_UP_ROW_BITMAP_FILE,
                original,
                row_data,
            ),
            digest_patch(
                LEVEL_UP_TARGET,
                "level_up_generic_attack_label",
                LEVEL_UP_GENERIC_ATTACK_FILE,
                original,
                direct_color_row("Attack", font8),
            ),
            digest_patch(
                LEVEL_UP_TARGET,
                "level_up_generic_accuracy_label",
                LEVEL_UP_GENERIC_ACCURACY_FILE,
                original,
                direct_color_row("Accuracy", font8),
            ),
        ),
    )


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    load_runtime_ui(context)
    return (
        build_normcom_patch(),
        build_event_patch(),
        build_da3d_patch(),
        build_level_up_patch(context),
    )
