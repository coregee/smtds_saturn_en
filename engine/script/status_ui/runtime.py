"""Assembly builders and cave composition for detailed status UI."""

import json
import struct
from collections.abc import Sequence

from engine.script.sh2 import assemble_checked
from engine.script.status_ui.data import (
    ambiguous_magname_fallbacks,
    da3d_compact_status_data,
    event_status_english_data,
    load_font16_metrics,
    load_status_terms,
    status_english_data,
    validate_shiftable_bitmap,
)
from engine.script.status_ui.model import (
    AFFINITY_SELECTOR,
    AFFINITY_SOURCE,
    ASM_ROOT,
    BASE,
    BUILD_ATLAS,
    BUILD_ATLAS_TILE,
    CHARACTER_NAMES_PATH,
    CURRENT_NAME_PTR,
    CURRENT_PARTY_TYPE,
    DA3D_AFFINITY_SELECTOR,
    DA3D_CURRENT_NAME_PTR,
    DA3D_DVL_SOURCE,
    DA3D_FONT8_DRAWER,
    DA3D_FONT8_GLYPH_DRAWER,
    DA3D_FONT16_DRAWER,
    DA3D_RACE_SOURCE,
    DA3D_STATUS_BLOCK_END,
    DA3D_TABLE_FONT8_DRAWER,
    DA3D_TABLE_FONT8_GLYPH_DRAWER,
    DA3D_TABLE_RACE_SOURCE,
    EVENT_AFFINITY_SELECTOR,
    EVENT_AFFINITY_SOURCE,
    EVENT_BAR_CHAR_SOURCE,
    EVENT_BAR_CHAR_SOURCE_END,
    EVENT_BAR_CODENAME,
    EVENT_BAR_DVL_SOURCE,
    EVENT_BAR_DVL_SOURCE_END,
    EVENT_BAR_PARTY_SOURCE_PTR,
    EVENT_BAR_SURFACE_PTR,
    EVENT_CHARACTER_INSERT_END,
    EVENT_CHARACTER_INSERT_STOCK,
    EVENT_CURRENT_DEMON_IDS,
    EVENT_CURRENT_NAME_PTR,
    EVENT_CURRENT_PARTY_TYPE,
    EVENT_DEMON_INSERT_STOCK,
    EVENT_FONT8_GLYPH_DRAWER,
    EVENT_FONT12_DRAWER,
    EVENT_FONT16_DRAWER,
    EVENT_HEALING_CHAR_SOURCE_PTR,
    EVENT_HEALING_DVL_SOURCE_PTR,
    EVENT_HEALING_SURFACE_PTR,
    EVENT_HEALING_SURFACE_WIDTH,
    EVENT_INSERT_ACTIVE,
    EVENT_INSERT_STATE,
    EVENT_INSERT_STREAM_POINTER,
    EVENT_INSERT_STREAM_PUSH,
    EVENT_INSERT_STREAM_STATUS,
    EVENT_RACE_ID_HELPER,
    EVENT_RACE_INSERT_STOCK,
    EVENT_RACE_SOURCE,
    EVENT_RUNTIME_CAVE_LIMIT,
    EVENT_TEXT_FLAGS,
    FONT8_BITMAP,
    FONT8_DRAWER,
    FONT8_GLYPH_DRAWER,
    FONT16_BITMAP,
    FONT16_DRAWER,
    FONT16_PATH,
    ITEM_ICON_DRAWER,
    LEVEL_UP_CHARACTER_SELECTOR,
    LEVEL_UP_FONT16_DRAWER,
    LEVEL_UP_LEARNED_MAGIC_MAX_WORDS,
    LEVEL_UP_LEARNED_SKILL_LIST_PTR,
    LEVEL_UP_NAME_PREPARE,
    LEVEL_UP_NAME_SURFACE,
    LEVEL_UP_RUNTIME_CAVE_FILE,
    LEVEL_UP_RUNTIME_CAVE_LIMIT,
    LEVEL_UP_RUNTIME_DATA_FILE,
    MAGNAME_BASE,
    MAGNAME_END,
    MAGNAME_FIRST_NAME,
    MAGNAME_POINTER_FROM_NAME,
    NORMCOM_RUNTIME_CAVE_LIMIT,
    PANEL_ATLAS_CACHE,
    PLAYER_STATUS_NAME,
    RACE_SOURCE,
    RUNTIME_CAVE_FILE,
    RUNTIME_DATA_FILE,
    STATUS_MASK_PTR,
    STATUS_SOURCE_PTR,
    STATUS_STOCK_ATLAS,
    STATUS_STOCK_MASKS,
)
from engine.script.text_render.font8_blitter import build_surface_pixel_blitter
from engine.script.text_render.font8_metrics import font8_metrics
from text.script.encoding.tokens import normalize_english

LEVEL_UP_SKILL_NAME_MAX_BYTES = 32
LEVEL_UP_SKILL_NAME_MAX_FONT8_PIXELS = 80
LEVEL_UP_SKILL_NAME_MAX_FONT16_PIXELS = 128
LEVEL_UP_SKILL_SCRATCH_BYTES = (LEVEL_UP_SKILL_NAME_MAX_BYTES + 1) * 2


def build_atlas_wrapper(
    address: int,
    original: int,
    atlas: int,
    masks: int,
    dirty: int,
) -> bytes:
    source = (ASM_ROOT / "atlas_wrapper.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "SOURCE_PTR": STATUS_SOURCE_PTR,
                "EN_ATLAS": atlas,
                "STOCK_ATLAS": STATUS_STOCK_ATLAS,
                "MASK_PTR": STATUS_MASK_PTR,
                "EN_MASKS": masks,
                "STOCK_MASKS": STATUS_STOCK_MASKS,
                "ORIGINAL": original,
                "DIRTY": dirty,
            },
            context="status wrapper",
        )
    )


def build_font16_vwf(
    address: int,
    widths_address: int,
    stock_drawer: int = FONT16_DRAWER,
) -> bytes:
    source = (ASM_ROOT / "font16_vwf.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "WIDTHS": widths_address,
                "END_MASK": 0x8000,
                "FONT_BITMAP": FONT16_BITMAP,
                "STOCK": stock_drawer,
            },
            context="status runtime",
        )
    )


def build_skill_vwf(
    address: int,
    widths_address: int,
    stock_drawer: int = FONT8_DRAWER,
    glyph_drawer: int = FONT8_GLYPH_DRAWER,
) -> bytes:
    source = (ASM_ROOT / "skill_vwf.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "MAGIC_FIRST": MAGNAME_FIRST_NAME,
                "MAGIC_END": MAGNAME_END,
                "MAGIC_BASE": MAGNAME_BASE,
                "NAME_POINTER": MAGNAME_POINTER_FROM_NAME,
                "WIDTHS": widths_address,
                "FONT_BITMAP": FONT8_BITMAP,
                "STOCK": stock_drawer,
                "GLYPH": glyph_drawer,
            },
            context="status runtime",
        )
    )


def build_event_status_skill_dispatcher(
    address: int,
    skill_vwf: int,
    ambiguous: tuple[bytes, ...],
) -> bytes:
    """Resolve an eight-byte fusion-status stack copy back to MAGNAME."""
    if len(ambiguous) != 4 or any(len(key) != 8 for key in ambiguous):
        raise ValueError("fusion status skill dispatcher needs four 8-byte keys")
    source = (ASM_ROOT / "event_status_skill_dispatcher.s").read_text(encoding="utf-8")
    symbols = {
        "MAGIC_FIRST": MAGNAME_FIRST_NAME,
        "SKILL_VWF": skill_vwf,
        "STOCK": EVENT_FONT12_DRAWER,
    }
    for index, key in enumerate(ambiguous):
        symbols[f"AMBIG{index}_HI"] = int.from_bytes(key[:4], "big")
        symbols[f"AMBIG{index}_LO"] = int.from_bytes(key[4:], "big")
    return bytes(assemble_checked(source, address, symbols, context="status runtime"))


def build_name_race_dispatcher(
    address: int,
    font16_vwf: int,
    race_table: int,
    name_lookup: int,
    name_count: int,
    *,
    race_source: int = RACE_SOURCE,
    party_type: int = CURRENT_PARTY_TYPE,
    current_name_ptr: int = CURRENT_NAME_PTR,
    stock_drawer: int = FONT16_DRAWER,
    name_vwf: int | None = None,
) -> bytes:
    source = (ASM_ROOT / "name_race_dispatcher.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "RACE_SOURCE": race_source,
                "RACE_TABLE": race_table,
                "PARTY_TYPE": party_type,
                "CURRENT_NAME_PTR": current_name_ptr,
                "PLAYER_NAME": PLAYER_STATUS_NAME,
                "NAME_LOOKUP": name_lookup,
                "NAME_COUNT": name_count,
                "FONT16_VWF": font16_vwf,
                "NAME_VWF": font16_vwf if name_vwf is None else name_vwf,
                "STOCK": stock_drawer,
            },
            context="status runtime",
        )
    )


def build_event_font16_from_font8(
    address: int,
    widths_address: int,
) -> bytes:
    source = (ASM_ROOT / "da3d_font16_from_font8.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "WIDTHS": widths_address,
                "FONT_BITMAP": FONT16_BITMAP,
                "STOCK": EVENT_FONT16_DRAWER,
            },
            context="EVENT FONT8-source FONT16 VWF",
        )
    )


def build_event_dialogue_inserts(
    address: int,
    name_offsets: int,
    name_pool: int,
    race_table: int,
) -> tuple[bytes, dict[str, int]]:
    """Stage translated character, demon, and race terms through EVENT's VM."""
    _races, _affinities, demon_names = load_status_terms("EVENT dialogue inserts")
    characters = json.loads(CHARACTER_NAMES_PATH.read_text(encoding="utf-8"))
    character_names = [row["tr"] for row in characters]
    return build_dialogue_inserts(
        address,
        name_offsets,
        name_pool,
        race_table,
        demon_names=demon_names,
        character_names=character_names,
        current_demon_ids=EVENT_CURRENT_DEMON_IDS,
        race_id_helper=EVENT_RACE_ID_HELPER,
        insert_state=EVENT_INSERT_STATE,
        insert_active=EVENT_INSERT_ACTIVE,
        stream_push=EVENT_INSERT_STREAM_PUSH,
        stream_pointer=EVENT_INSERT_STREAM_POINTER,
        stream_status=EVENT_INSERT_STREAM_STATUS,
        text_flags=EVENT_TEXT_FLAGS,
        stock_demon_insert=EVENT_DEMON_INSERT_STOCK,
        stock_race_insert=EVENT_RACE_INSERT_STOCK,
        insert_buffer=None,
        context="EVENT dialogue inserts",
    )


def build_dialogue_inserts(
    address: int,
    name_offsets: int,
    name_pool: int,
    race_table: int,
    *,
    demon_names: Sequence[str],
    character_names: Sequence[str],
    current_demon_ids: int,
    race_id_helper: int,
    insert_state: int,
    insert_active: int,
    stream_push: int,
    stream_pointer: int,
    stream_status: int,
    text_flags: int,
    stock_demon_insert: int,
    stock_race_insert: int,
    insert_buffer: int | None,
    context: str,
) -> tuple[bytes, dict[str, int]]:
    """Build the shared two-phase VM adapters for full generated terms."""
    if len(demon_names) != 319 or len(character_names) < 3:
        raise ValueError(f"{context} needs 319 demon and at least 3 character names")
    if any(not name or len(name) > 20 for name in (*demon_names, *character_names[:3])):
        raise ValueError(f"{context} name is empty or exceeds 20 glyphs")
    _widths8, codes8 = font8_metrics()
    _widths16, codes16 = load_font16_metrics()

    def expected_code(code: int) -> int | None:
        if code == codes8[" "]:
            return codes16[" "]
        if codes8["0"] <= code < codes8["s"]:
            return code - 63
        if codes8["s"] <= code <= codes8["z"]:
            return code - 150
        if code == codes8["-"]:
            return codes16["-"]
        if code == codes8["'"]:
            return codes16["'"]
        return None

    for character in set("".join((*demon_names, *character_names[:3]))):
        source = codes8.get(character)
        target = codes16.get(character)
        if source is None or target is None or expected_code(source) != target:
            raise ValueError(f"{context} mapper cannot convert {character!r}")

    source = (ASM_ROOT / "event_dialogue_inserts.s").read_text(encoding="utf-8")

    def assemble_at(buffer: int):
        return assemble_checked(
            source,
            address,
            {
                "CURRENT_DEMON_IDS": current_demon_ids,
                "DEMON_COUNT": len(demon_names),
                "NAME_OFFSETS": name_offsets,
                "NAME_POOL": name_pool,
                "RACE_COUNT": 43,
                "RACE_TABLE": race_table,
                "RACE_ID_HELPER": race_id_helper,
                "INSERT_STATE": insert_state,
                "INSERT_ACTIVE": insert_active,
                "STREAM_PUSH": stream_push,
                "STREAM_POINTER": stream_pointer,
                "STREAM_STATUS": stream_status,
                "TEXT_FLAGS": text_flags,
                "STOCK_DEMON_INSERT": stock_demon_insert,
                "STOCK_RACE_INSERT": stock_race_insert,
                "INSERT_BUFFER": buffer,
                "NAME_LIMIT": 20,
                "FONT8_TAIL_FIRST": codes8["s"],
                "FONT8_TAIL_END": codes8["z"] + 1,
                "FONT8_TAIL_DELTA": 150,
                "FONT8_HYPHEN": codes8["-"],
                "FONT8_APOSTROPHE": codes8["'"],
                "FONT16_SPACE": codes16[" "],
                "FONT16_HYPHEN": codes16["-"],
                "FONT16_APOSTROPHE": codes16["'"],
                "TERMINATOR": 0x8000,
                "ACTIVE_STATUS": 0x7FFF,
            },
            context=context,
        )

    probe = assemble_at(insert_buffer or address)
    buffer_address = insert_buffer or ((address + len(probe) + 3) & ~3)
    code = assemble_at(buffer_address)
    if len(code) != len(probe):
        raise ValueError(f"{context} buffer address changed code size")
    payload = bytearray(code)
    if insert_buffer is None:
        payload.extend(bytes(buffer_address - address - len(payload)))
        payload.extend(bytes((20 + 1) * 2))
    labels = dict(code.labels)
    labels["insert_buffer"] = buffer_address
    return bytes(payload), labels


def build_dialogue_character_insert(
    address: int,
    *,
    character_offsets: int,
    name_pool: int,
    insert_state: int,
    insert_buffer: int,
    name_copy: int,
    name_cleanup: int,
    context: str,
) -> tuple[bytes, dict[str, int]]:
    """Build the direct-index character adapter around the shared VM core."""
    source = (ASM_ROOT / "dialogue_character_insert.s").read_text(encoding="utf-8")
    code = assemble_checked(
        source,
        address,
        {
            "INSERT_STATE": insert_state,
            "CHARACTER_COUNT": 3,
            "CHARACTER_OFFSETS": character_offsets,
            "NAME_POOL": name_pool,
            "INSERT_BUFFER": insert_buffer,
            "NAME_LIMIT": 20,
            "NAME_COPY": name_copy,
            "NAME_CLEANUP": name_cleanup,
        },
        context=context,
    )
    return bytes(code), dict(code.labels)


def build_bar_name_drawers(
    address: int,
    widths_address: int,
    name_lookup: int,
    name_count: int,
    name_offsets: int,
    name_pool: int,
    drink_offsets: int,
    drink_pool: int,
    talk_offsets: int,
    talk_pool: int,
    healing_all: int,
    glyph_drawer: int,
):
    source = (ASM_ROOT / "bar_name_drawers.s").read_text(encoding="utf-8")
    return assemble_checked(
        source,
        address,
        {
            "WIDTHS": widths_address,
            "NAME_LOOKUP": name_lookup,
            "NAME_COUNT": name_count,
            "DVL_SOURCE": EVENT_BAR_DVL_SOURCE,
            "DVL_SOURCE_END": EVENT_BAR_DVL_SOURCE_END,
            "CHAR_SOURCE": EVENT_BAR_CHAR_SOURCE,
            "CHAR_SOURCE_END": EVENT_BAR_CHAR_SOURCE_END,
            "PARTY_SOURCE_PTR": EVENT_BAR_PARTY_SOURCE_PTR,
            "PLAYER_CODENAME": EVENT_BAR_CODENAME,
            "DVL_OFFSETS": name_offsets,
            "CHAR_OFFSETS": name_offsets + 319 * 2,
            "NAME_POOL": name_pool,
            "DRINK_OFFSETS": drink_offsets,
            "DRINK_POOL": drink_pool,
            "TALK_OFFSETS": talk_offsets,
            "TALK_POOL": talk_pool,
            "HEALING_ALL": healing_all,
            "HEALING_SURFACE_PTR": EVENT_HEALING_SURFACE_PTR,
            "HEALING_SURFACE_WIDTH": EVENT_HEALING_SURFACE_WIDTH,
            "HEALING_CHAR_SOURCE_PTR": EVENT_HEALING_CHAR_SOURCE_PTR,
            "HEALING_DVL_SOURCE_PTR": EVENT_HEALING_DVL_SOURCE_PTR,
            "SURFACE_PTR": EVENT_BAR_SURFACE_PTR,
            "GLYPH": glyph_drawer,
        },
        context="EVENT bar/shop VWF",
    )


def build_affinity_dispatcher(
    address: int,
    font16_vwf: int,
    affinity_table: int,
    selector: int = AFFINITY_SELECTOR,
    source_address: int = AFFINITY_SOURCE,
    stock_drawer: int = FONT16_DRAWER,
) -> bytes:
    source = (ASM_ROOT / "affinity_dispatcher.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "SELECTOR": selector,
                "SOURCE": source_address,
                "TABLE": affinity_table,
                "FONT16_VWF": font16_vwf,
                "STOCK": stock_drawer,
            },
            context="status runtime",
        )
    )


def build_stock_icon_wrapper(address: int, dirty: int) -> bytes:
    source = (ASM_ROOT / "stock_icon_wrapper.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "DIRTY": dirty,
                "BUILD_ATLAS": BUILD_ATLAS,
                "BUILD_ATLAS_TILE": BUILD_ATLAS_TILE,
                "PANEL_ATLAS_CACHE": PANEL_ATLAS_CACHE,
                "STOCK": ITEM_ICON_DRAWER,
            },
            context="status runtime",
        )
    )


def build_level_up_name_wrapper(
    address: int,
    font16_vwf: int,
    character_table: int,
) -> bytes:
    source = (ASM_ROOT / "level_up_name.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "PLAYER_NAME": PLAYER_STATUS_NAME,
                "CHARACTER_SELECTOR": LEVEL_UP_CHARACTER_SELECTOR,
                "CHARACTER_COUNT": 5,
                "CHARACTER_TABLE": character_table,
                "PREPARE": LEVEL_UP_NAME_PREPARE,
                "SURFACE": LEVEL_UP_NAME_SURFACE,
                "FONT16_VWF": font16_vwf,
            },
            context="level-up status runtime",
        )
    )


def build_level_up_text_copy(
    address: int,
    word_count: int,
    window_size: int,
) -> bytes:
    source = (ASM_ROOT / "level_up_text_copy.s").read_text(encoding="utf-8")
    code = bytes(
        assemble_checked(
            source,
            address,
            {"WORD_COUNT": word_count},
            context="level-up learned-magic copy",
        )
    )
    if len(code) > window_size or (window_size - len(code)) & 1:
        raise ValueError("level-up learned-magic copy does not fill its window")
    return code + bytes.fromhex("0009") * ((window_size - len(code)) // 2)


def level_up_font8_to_font16(code: int) -> int | None:
    if code == 63:
        return 267
    if 63 < code < 118:
        return code - 63
    if 205 <= code < 213:
        return code - 150
    return {
        213: 173,
        214: 175,
        217: 177,
        229: 204,
    }.get(code)


def _normalized_level_up_skill_names(names: Sequence[str]) -> tuple[str, ...]:
    if len(names) != 255:
        raise ValueError("level-up learned-skill runtime needs 255 translated names")
    normalized = tuple(
        normalize_english(name.strip()) if isinstance(name, str) else ""
        for name in names
    )
    if any(not name for name in normalized):
        raise ValueError("level-up learned-skill runtime needs 255 translated names")
    return normalized


def validate_level_up_skill_names(names: Sequence[str]) -> None:
    names = _normalized_level_up_skill_names(names)
    widths8, codes8 = font8_metrics()
    widths16, codes16 = load_font16_metrics()
    for index, name in enumerate(names):
        try:
            encoded = tuple(codes8[character] for character in name)
            expected = tuple(codes16[character] for character in name)
        except KeyError as error:
            raise ValueError(
                f"level-up MAGNAME row {index} uses unsupported character "
                f"{error.args[0]!r}"
            ) from error
        if len(encoded) > LEVEL_UP_SKILL_NAME_MAX_BYTES:
            raise ValueError(
                f"level-up MAGNAME row {index} exceeds "
                f"{LEVEL_UP_SKILL_NAME_MAX_BYTES} bytes"
            )
        if (
            sum(widths8[code] for code in encoded)
            > LEVEL_UP_SKILL_NAME_MAX_FONT8_PIXELS
        ):
            raise ValueError(
                f"level-up MAGNAME row {index} exceeds "
                f"{LEVEL_UP_SKILL_NAME_MAX_FONT8_PIXELS} FONT8 pixels"
            )
        if (
            sum(widths16[code] for code in expected)
            > LEVEL_UP_SKILL_NAME_MAX_FONT16_PIXELS
        ):
            raise ValueError(
                f"level-up MAGNAME row {index} exceeds "
                f"{LEVEL_UP_SKILL_NAME_MAX_FONT16_PIXELS} FONT16 pixels"
            )
        mapped = tuple(level_up_font8_to_font16(code) for code in encoded)
        if None in mapped or mapped != expected:
            raise ValueError(f"level-up MAGNAME row {index} cannot map FONT8 to FONT16")


def validate_level_up_packed_skill_names(
    packed: bytes,
    names: Sequence[str],
) -> None:
    validate_level_up_skill_names(names)
    names = _normalized_level_up_skill_names(names)
    expected_size = MAGNAME_END - MAGNAME_BASE
    if len(packed) != expected_size:
        raise ValueError(
            f"level-up MAGNAME build has {len(packed):#x} bytes; "
            f"expected {expected_size:#x}"
        )
    record_size = expected_size // len(names)
    pointer_offset = 4 + MAGNAME_POINTER_FROM_NAME
    _widths, codes = font8_metrics()
    for index, name in enumerate(names):
        pointer = struct.unpack_from(
            ">H", packed, index * record_size + pointer_offset
        )[0]
        expected = bytes(codes[character] for character in name) + b"\xff"
        if packed[pointer : pointer + len(expected)] != expected:
            raise ValueError(f"level-up MAGNAME row {index} full-name payload is stale")


def build_level_up_learned_dispatcher(
    address: int,
    font16_vwf: int,
    scratch: int,
) -> bytes:
    if scratch & 1:
        raise ValueError("level-up learned-skill scratch must be word-aligned")
    source = (ASM_ROOT / "level_up_learned_dispatcher.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "LEARNED_LIST_POINTER": LEVEL_UP_LEARNED_SKILL_LIST_PTR,
                "MAGIC_BASE": MAGNAME_BASE,
                "NAME_POINTER": MAGNAME_POINTER_FROM_NAME,
                "MAX_NAME_BYTES": LEVEL_UP_SKILL_NAME_MAX_BYTES,
                "SCRATCH": scratch,
                "FONT16_VWF": font16_vwf,
            },
            context="level-up learned-row dispatcher",
        )
    )


def build_level_up_name_runtime(
    learned_magic: tuple[int, ...],
    character_names: tuple[str, ...],
    magic_names: tuple[str, ...],
) -> tuple[bytes, int, int, int, int]:
    if (
        not 1 <= len(learned_magic) <= LEVEL_UP_LEARNED_MAGIC_MAX_WORDS
        or learned_magic[-1] != 0x8000
        or 0x8000 in learned_magic[:-1]
    ):
        raise ValueError("invalid level-up learned-magic runtime text")
    if len(character_names) != 6 or any(not name for name in character_names):
        raise ValueError("level-up status needs six translated character names")
    validate_level_up_skill_names(magic_names)
    widths, codes = load_font16_metrics()
    validate_shiftable_bitmap(
        FONT16_PATH.read_bytes(),
        widths,
        32,
        2,
        "level-up status FONT16",
    )
    cave_address = BASE + LEVEL_UP_RUNTIME_CAVE_FILE
    widths_address = BASE + LEVEL_UP_RUNTIME_DATA_FILE
    font16_vwf = build_font16_vwf(
        cave_address,
        widths_address,
        LEVEL_UP_FONT16_DRAWER,
    )
    wrapper_address = cave_address + len(font16_vwf)
    wrapper_probe = build_level_up_name_wrapper(
        wrapper_address,
        cave_address,
        cave_address,
    )
    code_end = LEVEL_UP_RUNTIME_CAVE_FILE + len(font16_vwf) + len(wrapper_probe)
    learned_magic_address = BASE + LEVEL_UP_RUNTIME_DATA_FILE + len(widths)
    character_table_address = (learned_magic_address + len(learned_magic) * 2 + 3) & ~3
    wrapper = build_level_up_name_wrapper(
        wrapper_address,
        cave_address,
        character_table_address,
    )
    if len(wrapper) != len(wrapper_probe):
        raise ValueError("level-up character table changed wrapper code size")
    if code_end > LEVEL_UP_RUNTIME_DATA_FILE:
        raise ValueError("level-up status code overlaps its width table")

    payload = bytearray()
    payload.extend(font16_vwf)
    payload.extend(wrapper)
    payload.extend(bytes(LEVEL_UP_RUNTIME_DATA_FILE - code_end))
    payload.extend(widths)
    if BASE + LEVEL_UP_RUNTIME_CAVE_FILE + len(payload) != learned_magic_address:
        raise ValueError("level-up learned-magic address drifted")
    payload.extend(struct.pack(f">{len(learned_magic)}H", *learned_magic))
    payload.extend(
        bytes(
            character_table_address - (BASE + LEVEL_UP_RUNTIME_CAVE_FILE + len(payload))
        )
    )
    character_table_offset = len(payload)
    payload.extend(bytes(5 * 4))
    for index, name in enumerate(character_names[1:]):
        pointer = BASE + LEVEL_UP_RUNTIME_CAVE_FILE + len(payload)
        struct.pack_into(">I", payload, character_table_offset + index * 4, pointer)
        try:
            glyphs = tuple(codes[character] for character in name)
        except KeyError as error:
            raise ValueError(
                f"level-up character name {name!r} uses unsupported FONT16 "
                f"character {error.args[0]!r}"
            ) from error
        if sum(widths[glyph] for glyph in glyphs) > 96:
            raise ValueError(f"level-up character name exceeds 96px: {name!r}")
        payload.extend(struct.pack(f">{len(glyphs) + 1}H", *glyphs, 0x8000))
    payload.extend(bytes((-(BASE + LEVEL_UP_RUNTIME_CAVE_FILE + len(payload))) % 4))
    dispatcher_address = BASE + LEVEL_UP_RUNTIME_CAVE_FILE + len(payload)
    dispatcher_probe = build_level_up_learned_dispatcher(
        dispatcher_address,
        cave_address,
        dispatcher_address,
    )
    scratch_address = (dispatcher_address + len(dispatcher_probe) + 1) & ~1
    dispatcher = build_level_up_learned_dispatcher(
        dispatcher_address,
        cave_address,
        scratch_address,
    )
    if len(dispatcher) != len(dispatcher_probe):
        raise ValueError("level-up learned-row scratch changed dispatcher size")
    payload.extend(dispatcher)
    payload.extend(
        bytes(scratch_address - (BASE + LEVEL_UP_RUNTIME_CAVE_FILE + len(payload)))
    )
    payload.extend(bytes(LEVEL_UP_SKILL_SCRATCH_BYTES))
    if LEVEL_UP_RUNTIME_CAVE_FILE + len(payload) > LEVEL_UP_RUNTIME_CAVE_LIMIT:
        raise ValueError(
            "level-up status runtime exceeds its verified cave by "
            f"{LEVEL_UP_RUNTIME_CAVE_FILE + len(payload) - LEVEL_UP_RUNTIME_CAVE_LIMIT:#x} bytes"
        )
    return (
        bytes(payload),
        wrapper_address,
        learned_magic_address,
        character_table_address,
        dispatcher_address,
    )


def build_status_runtime(masks: bytes) -> tuple[bytes, int, int, int, int, int]:
    (
        data,
        widths16,
        widths8,
        race_table,
        affinity_table,
        name_lookup,
        name_count,
    ) = status_english_data()
    data = bytearray(data)
    while (RUNTIME_DATA_FILE + len(data)) & 3:
        data.append(0)
    masks_address = BASE + RUNTIME_DATA_FILE + len(data)
    data.extend(masks)
    dirty_address = BASE + RUNTIME_DATA_FILE + len(data)
    data.append(0)
    payload = bytearray()

    def append(builder, *args) -> int:
        while (RUNTIME_CAVE_FILE + len(payload)) & 3:
            payload.append(0)
        address = BASE + RUNTIME_CAVE_FILE + len(payload)
        payload.extend(builder(address, *args))
        return address

    font16_vwf = append(build_font16_vwf, widths16)
    skill_vwf = append(build_skill_vwf, widths8)
    name_race = append(
        build_name_race_dispatcher,
        font16_vwf,
        race_table,
        name_lookup,
        name_count,
    )
    affinity = append(build_affinity_dispatcher, font16_vwf, affinity_table)
    stock_icon = append(build_stock_icon_wrapper, dirty_address)
    if RUNTIME_CAVE_FILE + len(payload) > RUNTIME_DATA_FILE:
        raise ValueError("status runtime code overlaps its data tables")
    payload.extend(bytes(RUNTIME_DATA_FILE - RUNTIME_CAVE_FILE - len(payload)))
    payload.extend(data)
    if RUNTIME_CAVE_FILE + len(payload) > NORMCOM_RUNTIME_CAVE_LIMIT:
        raise ValueError(
            f"status runtime exceeds cave limit by "
            f"{RUNTIME_CAVE_FILE + len(payload) - NORMCOM_RUNTIME_CAVE_LIMIT:#x} bytes"
        )
    return (
        bytes(payload),
        name_race,
        skill_vwf,
        affinity,
        masks_address,
        stock_icon,
    )


def build_event_status_runtime(
    runtime_cave: int,
) -> tuple[
    bytes,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
]:
    (
        data,
        widths16,
        skill_widths,
        compact_font16_widths,
        race_table,
        affinity_table,
        name_lookup,
        name_count,
        name_offsets,
        name_pool,
        drink_offsets,
        drink_pool,
        talk_offsets,
        talk_pool,
        healing_all,
    ) = event_status_english_data(runtime_cave)
    payload = bytearray(data)

    def append(builder, *args, **kwargs) -> int:
        payload.extend(bytes((-(runtime_cave + len(payload))) % 4))
        address = runtime_cave + len(payload)
        payload.extend(builder(address, *args, **kwargs))
        return address

    font16_vwf = append(build_font16_vwf, widths16, EVENT_FONT16_DRAWER)
    name_font16_vwf = append(
        build_event_font16_from_font8,
        compact_font16_widths,
    )
    skill_vwf = append(
        build_skill_vwf,
        skill_widths,
        EVENT_FONT12_DRAWER,
        EVENT_FONT8_GLYPH_DRAWER,
    )
    status_skill = append(
        build_event_status_skill_dispatcher,
        skill_vwf,
        ambiguous_magname_fallbacks(),
    )
    name_race = append(
        build_name_race_dispatcher,
        font16_vwf,
        race_table,
        name_lookup,
        name_count,
        race_source=EVENT_RACE_SOURCE,
        party_type=EVENT_CURRENT_PARTY_TYPE,
        current_name_ptr=EVENT_CURRENT_NAME_PTR,
        stock_drawer=EVENT_FONT16_DRAWER,
        name_vwf=name_font16_vwf,
    )
    affinity = append(
        build_affinity_dispatcher,
        font16_vwf,
        affinity_table,
        EVENT_AFFINITY_SELECTOR,
        EVENT_AFFINITY_SOURCE,
        EVENT_FONT16_DRAWER,
    )
    payload.extend(bytes((-(runtime_cave + len(payload))) % 4))
    bar_glyph = append(build_surface_pixel_blitter)
    bar_blob = build_bar_name_drawers(
        runtime_cave + len(payload),
        skill_widths,
        name_lookup,
        name_count,
        name_offsets,
        name_pool,
        drink_offsets,
        drink_pool,
        talk_offsets,
        talk_pool,
        healing_all,
        bar_glyph,
    )
    payload.extend(bar_blob)
    payload.extend(bytes((-(runtime_cave + len(payload))) % 4))
    dialogue_blob, dialogue_labels = build_event_dialogue_inserts(
        runtime_cave + len(payload),
        name_offsets,
        name_pool,
        race_table,
    )
    payload.extend(dialogue_blob)
    character_handler, _character_labels = build_dialogue_character_insert(
        EVENT_CHARACTER_INSERT_STOCK,
        character_offsets=name_offsets + 319 * 2,
        name_pool=name_pool,
        insert_state=EVENT_INSERT_STATE,
        insert_buffer=dialogue_labels["insert_buffer"],
        name_copy=dialogue_labels["name_copy"],
        name_cleanup=dialogue_labels["name_cleanup"],
        context="EVENT dialogue character insert",
    )
    character_window = EVENT_CHARACTER_INSERT_END - EVENT_CHARACTER_INSERT_STOCK
    if len(character_handler) > character_window:
        raise ValueError("EVENT dialogue character insert exceeds its stock window")
    character_handler += bytes.fromhex("0009") * (
        (character_window - len(character_handler)) // 2
    )
    if runtime_cave + len(payload) > EVENT_RUNTIME_CAVE_LIMIT:
        raise ValueError(
            "EVENT status/dialogue runtime exceeds the verified cave by "
            f"{runtime_cave + len(payload) - EVENT_RUNTIME_CAVE_LIMIT:#x} bytes"
        )
    return (
        bytes(payload),
        font16_vwf,
        name_race,
        skill_vwf,
        status_skill,
        affinity,
        bar_blob.labels["bar_drink_name_drawer"],
        bar_blob.labels["bar_talk_role_drawer"],
        bar_blob.labels["bar_status_name_glyph"],
        bar_blob.labels["bar_party_name_glyph"],
        bar_blob.labels["healing_all_drawer"],
        bar_blob.labels["healing_name_drawer"],
        character_handler,
        dialogue_labels["dialogue_demon_name_insert"],
        dialogue_labels["dialogue_race_insert"],
    )


def build_da3d_status_runtime(
    runtime_block: int,
) -> tuple[bytes, bytes, int, int, int, int, int, int]:
    """Build separate DA_3D table and detailed-status text consumers."""
    (
        data,
        widths8,
        font16_widths,
        race_pool,
        race_offsets,
        long_name_bits,
        name_pool,
        affinity_word_offsets,
        affinity_word_pool,
        affinity_tokens,
    ) = da3d_compact_status_data(
        runtime_block,
    )
    payload = bytearray(data)

    def append_assembly(
        filename: str,
        symbols: dict[str, int],
        context: str,
    ):
        payload.extend(bytes((-(runtime_block + len(payload))) % 4))
        address = runtime_block + len(payload)
        source = (ASM_ROOT / filename).read_text(encoding="utf-8")
        blob = assemble_checked(source, address, symbols, context=context)
        payload.extend(blob)
        return address, blob

    font8_vwf, _font8_blob = append_assembly(
        "da3d_font8_vwf.s",
        {
            "WIDTHS": DA3D_TABLE_RACE_SOURCE,
            "FONT_BITMAP": FONT8_BITMAP,
            "GLYPH": DA3D_FONT8_GLYPH_DRAWER,
        },
        "DA_3D FONT8 VWF",
    )
    font16_vwf, _font16_blob = append_assembly(
        "da3d_font16_from_font8.s",
        {
            "WIDTHS": font16_widths,
            "FONT_BITMAP": FONT16_BITMAP,
            "STOCK": DA3D_FONT16_DRAWER,
        },
        "DA_3D FONT16 VWF",
    )
    name_decoder, _name_blob = append_assembly(
        "da3d_name_decoder.s",
        {
            "DVL_SOURCE": DA3D_DVL_SOURCE,
            "LONG_NAME_BITS": long_name_bits,
            "NAME_POOL": name_pool,
        },
        "DA_3D demon-name decoder",
    )
    affinity, _affinity_blob = append_assembly(
        "da3d_affinity_dispatcher.s",
        {
            "SELECTOR": DA3D_AFFINITY_SELECTOR,
            "AFFINITY_TOKENS": affinity_tokens,
            "WORD_OFFSETS": affinity_word_offsets,
            "WORD_POOL": affinity_word_pool,
            "FONT16_VWF": font16_vwf,
            "STOCK": DA3D_FONT16_DRAWER,
        },
        "DA_3D affinity dispatcher",
    )

    table_payload = bytearray(widths8)

    def append_table_assembly(
        filename: str,
        symbols: dict[str, int],
        context: str,
    ):
        table_payload.extend(
            bytes((-(DA3D_TABLE_RACE_SOURCE + len(table_payload))) % 4)
        )
        address = DA3D_TABLE_RACE_SOURCE + len(table_payload)
        source = (ASM_ROOT / filename).read_text(encoding="utf-8")
        blob = assemble_checked(source, address, symbols, context=context)
        table_payload.extend(blob)
        return address, blob

    skill_drawer, _skill_blob = append_table_assembly(
        "da3d_skill_dispatcher.s",
        {
            "MAGIC_FIRST": MAGNAME_FIRST_NAME,
            "MAGIC_END": MAGNAME_END,
            "MAGIC_BASE": MAGNAME_BASE,
            "NAME_POINTER": MAGNAME_POINTER_FROM_NAME,
            "FONT8_VWF": font8_vwf,
            "STOCK": DA3D_FONT8_DRAWER,
        },
        "DA_3D skill dispatcher",
    )
    table_font8_vwf, _table_font8_blob = append_table_assembly(
        "da3d_table_font8_vwf.s",
        {
            "WIDTHS": DA3D_TABLE_RACE_SOURCE,
            "GLYPH": DA3D_TABLE_FONT8_GLYPH_DRAWER,
        },
        "DA_3D table FONT8 VWF",
    )
    table_block_size = 43 * 6
    if len(table_payload) > table_block_size:
        raise ValueError(
            "DA_3D table runtime exceeds its redirected race mirror by "
            f"{len(table_payload) - table_block_size:#x} bytes"
        )
    table_payload.extend(bytes(table_block_size - len(table_payload)))

    _dispatch_address, dispatch_blob = append_assembly(
        "da3d_name_race_dispatcher.s",
        {
            "DVL_SOURCE": DA3D_DVL_SOURCE,
            "FONT8_VWF": table_font8_vwf,
            "FONT16_VWF": font16_vwf,
            "NAME_DECODER": name_decoder,
            "TABLE_RACE_SOURCE": DA3D_TABLE_RACE_SOURCE,
            "TABLE_STOCK": DA3D_TABLE_FONT8_DRAWER,
            "CURRENT_NAME_PTR": DA3D_CURRENT_NAME_PTR,
            "DETAIL_RACE_SOURCE": DA3D_RACE_SOURCE,
            "RACE_POOL": race_pool,
            "RACE_OFFSETS": race_offsets,
            "DETAIL_STOCK": DA3D_FONT16_DRAWER,
        },
        "DA_3D table/status dispatchers",
    )
    if runtime_block + len(payload) > DA3D_STATUS_BLOCK_END:
        raise ValueError(
            "DA_3D status runtime exceeds the redirected text mirrors by "
            f"{runtime_block + len(payload) - DA3D_STATUS_BLOCK_END:#x} bytes"
        )
    payload.extend(bytes(DA3D_STATUS_BLOCK_END - runtime_block - len(payload)))
    return (
        bytes(payload),
        bytes(table_payload),
        font8_vwf,
        font16_vwf,
        dispatch_blob.labels["da3d_detailed_dispatcher"],
        skill_drawer,
        affinity,
        dispatch_blob.labels["da3d_table_dispatcher"],
    )
