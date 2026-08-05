"""Localize the two-page CONFIG overlay and its private action atlas."""

import json
import struct
from functools import cache
from pathlib import Path

from engine.script.config_menu.model import (
    ACTION_ADVANCE_SITE_FILE,
    ACTION_ATLAS_ADDR,
    ACTION_ATLAS_FILE,
    ACTION_ATLAS_POINTER,
    ACTION_BLOCKS,
    ACTION_CAPACITY,
    ACTION_GLYPH,
    ACTION_GLYPH_POOL_FILE,
    ACTION_VWF_ADDR,
    ACTION_VWF_FILE,
    ACTIVE_CACHE_ADDR,
    ACTIVE_CACHE_FILE,
    ACTIVE_RENDER_ADDR,
    ACTIVE_RENDER_FILE,
    ACTIVE_RENDER_POINTERS,
    ADVANCE_SITE_FILE,
    ASSIST_BLOCKS,
    BASE,
    CAVE_ADDR,
    CAVE_FILE,
    COMPOUND_CODES,
    COMPOUND_GLYPH_ADDR,
    COMPOUND_GLYPH_FILE,
    COMPOUND_TEXT,
    FOOTER_BLOCKS,
    GLYPH_POOL_FILE,
    ITEM_SORT_POINTER,
    ITEM_SORT_TABLE_ADDR,
    ITEM_SORT_TABLE_FILE,
    LABEL_BLOCKS,
    LABEL_CELLS,
    LABEL_RECORDS,
    LABEL_STRIDE_SITES,
    LABEL_TABLE_ADDR,
    LABEL_TABLE_FILE,
    LABEL_TABLE_POINTERS,
    MAGIC_SORT_TABLE_ADDR,
    MAGIC_SORT_TABLE_FILE,
    MODE_COUNT_SITES,
    ORIGINAL_SHA256,
    PAGE2_BLOCKS,
    ROW_RENDER_POINTERS,
    SORT_RECORD_CELLS,
    STOCK_ACTION_ATLAS_ADDR,
    STOCK_GLYPH,
    STOCK_LABEL_TABLE_FILE,
    TARGET,
)
from engine.script.config_menu.sort_order import (
    MAGIC_SORT_BLOCKS,
    MAGIC_SORT_ORDERS,
    SORT_COMPOUNDS,
)
from engine.script.context import EngineBuildContext
from engine.script.patching import DigestPatch, PatchGroup
from engine.script.static_text import load_static_asset
from project_paths import BUILD_ROOT, EXTRACTED_ROOT, FONT_GENERATED_ROOT
from tools.sh2asm import assemble

METRICS_PATH = FONT_GENERATED_ROOT / "font16_metrics.json"
FONT16_PATH = BUILD_ROOT / "FONT16.FON"
ASM_ROOT = Path(__file__).with_name("asm")


def load_widths() -> tuple[bytes, dict[str, int]]:
    document = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    if document.get("version") != 2 or not document.get("complete"):
        raise ValueError(f"{METRICS_PATH}: incomplete FONT16 metrics")
    code_limit = document["width_table"]["code_limit"]
    if not isinstance(code_limit, int) or not 1 <= code_limit <= 0x7FFF:
        raise ValueError(f"{METRICS_PATH}: invalid width-table limit")
    widths = bytearray(code_limit)
    codes = {}
    for row in document["glyphs"]:
        code = row["code"]
        advance = row["advance"]
        if not 0 <= code < code_limit or not 1 <= advance <= 0xFF:
            raise ValueError(f"{METRICS_PATH}: invalid glyph metrics")
        widths[code] = advance
        for text in (row["text"], *row.get("aliases", ())):
            codes.setdefault(text, code)
    return bytes(widths), codes


@cache
def static_asset():
    return load_static_asset(
        Path("static") / "CFG_SET.BIN.static.json",
        TARGET.path,
    )


@cache
def runtime_metrics() -> tuple[bytes, dict[str, int]]:
    return load_widths()


def asset_block(name: str, storage: str) -> bytes:
    try:
        block = static_asset().blocks[name]
    except KeyError as error:
        raise ValueError(
            f"CFG_SET.BIN static text is missing block {name!r}"
        ) from error
    if block.storage != storage:
        raise ValueError(f"CFG_SET.BIN block {name!r} is not {storage}")
    return static_asset().data[block.offset : block.offset + block.size]


def asset_words(name: str) -> tuple[int, ...]:
    data = asset_block(name, "u16be")
    return struct.unpack(f">{len(data) // 2}H", data)


def sort_record(name: str) -> bytes:
    data = asset_block(name, "u16be")
    if len(data) != SORT_RECORD_CELLS * 2:
        raise ValueError(
            f"CFG_SET.BIN block {name!r} is not a {SORT_RECORD_CELLS}-cell record"
        )
    words = struct.unpack(f">{SORT_RECORD_CELLS}H", data)
    used = []
    for word in words:
        if word == 0xFFFF:
            break
        used.append(word)
    output = []
    position = 0
    while position < len(used):
        compound = next(
            (
                text
                for text in SORT_COMPOUNDS
                if tuple(runtime_metrics()[1][character] for character in text)
                == tuple(used[position : position + len(text)])
            ),
            None,
        )
        if compound is None:
            output.append(used[position])
            position += 1
        else:
            output.append(COMPOUND_CODES[compound])
            position += len(compound)
    if len(output) > 5:
        raise ValueError(
            f"CFG_SET.BIN block {name!r} needs {len(output)} popup cells; maximum is 5"
        )
    return struct.pack(
        f">{SORT_RECORD_CELLS}H",
        *(output + [0xFFFF] * (SORT_RECORD_CELLS - len(output))),
    )


def asset_ascii(name: str) -> str:
    data = asset_block(name, "bytes")
    if not data.endswith(b"\0") or b"\0" in data[:-1]:
        raise ValueError(f"CFG_SET.BIN block {name!r} is not one ASCII string")
    return data[:-1].decode("ascii")


def require(data: bytes | bytearray, offset: int, expected: bytes, name: str) -> None:
    actual = bytes(data[offset : offset + len(expected)])
    if actual != expected:
        raise ValueError(
            f"CFG_SET.BIN {name} mismatch at {offset:#x}: "
            f"expected {expected.hex(' ')}, found {actual.hex(' ')}"
        )


def instruction(source: str, offset: int) -> bytes:
    blob = assemble(source, BASE + offset)
    if len(blob) != 2 or blob.warnings:
        raise ValueError(f"CFG_SET.BIN instruction at {offset:#x} is unsafe")
    return bytes(blob)


def used_word_count(words: tuple[int, ...], name: str) -> int:
    for index in range(len(words) - 1, -1, -1):
        if words[index] != 0:
            return index + 1
    raise ValueError(f"CFG_SET.BIN block {name!r} is empty")


def expanded_label_offset(stock_offset: int) -> int:
    index, remainder = divmod(stock_offset - STOCK_LABEL_TABLE_FILE, 16)
    if remainder or not 0 <= index < LABEL_RECORDS:
        raise ValueError(f"invalid stock CONFIG label offset {stock_offset:#x}")
    return LABEL_TABLE_FILE + index * LABEL_CELLS * 2


def encode_ascii(text: str, *, compounds: bool = False) -> tuple[int, ...]:
    output = []
    position = 0
    while position < len(text):
        compound = (
            next(
                (value for value in COMPOUND_CODES if text.startswith(value, position)),
                None,
            )
            if compounds
            else None
        )
        if compound is not None:
            output.append(COMPOUND_CODES[compound])
            position += len(compound)
            continue
        character = text[position]
        try:
            output.append(runtime_metrics()[1][character])
        except KeyError as error:
            raise ValueError(f"unsupported CONFIG character {character!r}") from error
        position += 1
    return tuple(output)


def render_action_chunk(font16: bytes, codes: tuple[int, ...]) -> tuple[bytes, int]:
    rows = [0] * 12
    x = 0
    for code in codes:
        start = code * 32
        cell = font16[start : start + 32]
        if (
            len(cell) != 32
            or code >= len(runtime_metrics()[0])
            or not runtime_metrics()[0][code]
        ):
            raise ValueError(f"CONFIG action glyph {code} has no FONT16 metrics")
        for row in range(12):
            word = struct.unpack_from(">H", cell, (row + 2) * 2)[0]
            if x and word & ((1 << x) - 1):
                raise ValueError("CONFIG action chunk clips its right edge")
            rows[row] |= word >> x
        x += runtime_metrics()[0][code]
    if x > 16 or any(row & 0x000F for row in rows):
        raise ValueError("CONFIG action chunk does not fit its 12px atlas cell")
    data = b"".join(struct.pack(">H", row) for row in rows) + bytes(8)
    return data, x


def render_compound_glyph(font16: bytes, text: str) -> bytes:
    rows = [0] * 16
    x = 0
    for character in text:
        code = runtime_metrics()[1][character]
        start = code * 32
        cell = font16[start : start + 32]
        if (
            len(cell) != 32
            or code >= len(runtime_metrics()[0])
            or not runtime_metrics()[0][code]
        ):
            raise ValueError(
                f"CONFIG compound character {character!r} has no FONT16 metrics"
            )
        for row in range(16):
            word = struct.unpack_from(">H", cell, row * 2)[0]
            if x and word & ((1 << x) - 1):
                raise ValueError(f"CONFIG compound {text!r} clips its right edge")
            rows[row] |= word >> x
        x += runtime_metrics()[0][code]
    if x > 16:
        raise ValueError(f"CONFIG compound {text!r} is {x}px wide; maximum is 16px")
    return b"".join(struct.pack(">H", row) for row in rows)


def build_compound_glyph_runtime(font16: bytes) -> bytes:
    source = (ASM_ROOT / "compound_glyph.s").read_text(encoding="utf-8")
    base_symbols = {
        "CGLYPH_BASE": min(COMPOUND_CODES.values()),
        "BIT_MASK": 0x00008000,
        "FRAMEBUFFER": 0x25C00000,
    }
    probe = assemble(
        source,
        COMPOUND_GLYPH_ADDR,
        symbols={**base_symbols, "BITMAPS": COMPOUND_GLYPH_ADDR + 0x200},
    )
    if probe.warnings:
        raise ValueError(f"CONFIG compound-glyph warnings: {probe.warnings}")
    bitmaps_address = (COMPOUND_GLYPH_ADDR + len(probe) + 3) & ~3
    code = assemble(
        source,
        COMPOUND_GLYPH_ADDR,
        symbols={**base_symbols, "BITMAPS": bitmaps_address},
    )
    if code.warnings:
        raise ValueError(f"CONFIG compound-glyph warnings: {code.warnings}")
    payload = bytearray(code)
    payload.extend(bytes((-len(payload)) % 4))
    if COMPOUND_GLYPH_ADDR + len(payload) != bitmaps_address:
        raise ValueError("CONFIG compound bitmap address drifted")
    for text in COMPOUND_TEXT:
        payload.extend(render_compound_glyph(font16, text))
    payload.extend(bytes((-len(payload)) % 4))
    return bytes(payload)


def build_action_atlas(
    font16: bytes,
) -> tuple[bytes, bytes, dict[str, tuple[int, ...]]]:
    unique: list[tuple[int, ...]] = []
    encoded = {}
    for _offset, name in ACTION_BLOCKS:
        codes = encode_ascii(asset_ascii(name))
        chunks = []
        position = 0
        while position < len(codes):
            chunk = None
            for end in range(len(codes), position, -1):
                candidate = codes[position:end]
                try:
                    render_action_chunk(font16, candidate)
                except ValueError:
                    continue
                chunk = candidate
                break
            if chunk is None:
                raise ValueError(f"CFG_SET.BIN {name} cannot fit the action atlas")
            chunks.append(chunk)
            position += len(chunk)
        if len(chunks) > 8:
            raise ValueError(f"CFG_SET.BIN {name} needs more than eight action cells")
        encoded[name] = tuple(chunks)
        for chunk in chunks:
            if chunk not in unique:
                unique.append(chunk)

    if len(unique) > ACTION_CAPACITY:
        raise ValueError("CFG_SET.BIN action atlas exceeds 30 glyphs")
    indices = {chunk: index + 1 for index, chunk in enumerate(unique)}
    atlas = bytearray((ACTION_CAPACITY + 1) * 32)
    widths = bytearray(ACTION_CAPACITY)
    for chunk, index in indices.items():
        cell, width = render_action_chunk(font16, chunk)
        atlas[index * 32 : (index + 1) * 32] = cell
        widths[index - 1] = width
    records = {
        name: tuple(indices[chunk] for chunk in chunks)
        for name, chunks in encoded.items()
    }
    return bytes(atlas), bytes(widths), records


def compound_widths() -> bytes:
    values = []
    for text in COMPOUND_CODES:
        values.append(
            sum(
                runtime_metrics()[0][runtime_metrics()[1][character]]
                for character in text
            )
        )
    return bytes(values)


def build_vwf_wrapper(action_widths: bytes) -> bytes:
    source = (ASM_ROOT / "glyph_vwf.s").read_text(encoding="utf-8")
    base_symbols = {
        "L_BLIT": STOCK_GLYPH,
        "L_COMPOUND_BLIT": COMPOUND_GLYPH_ADDR,
        "CGLYPH_BASE": min(COMPOUND_CODES.values()),
        "CGLYPH_END": max(COMPOUND_CODES.values()) + 1,
        "WIDTH_LIMIT": len(runtime_metrics()[0]),
        "PADDING": 0xFFFF,
    }
    probe = assemble(
        source,
        CAVE_ADDR,
        symbols={
            **base_symbols,
            "WIDTHS": CAVE_ADDR + 0x100,
            "COMPOUND_WIDTHS": CAVE_ADDR + 0x200,
        },
    )
    if probe.warnings:
        raise ValueError(f"CONFIG VWF wrapper warnings: {probe.warnings}")
    widths_address = CAVE_ADDR + len(probe)
    action_widths_address = (widths_address + len(runtime_metrics()[0]) + 3) & ~3
    compound_widths_address = (action_widths_address + len(action_widths) + 3) & ~3
    code = assemble(
        source,
        CAVE_ADDR,
        symbols={
            **base_symbols,
            "WIDTHS": widths_address,
            "COMPOUND_WIDTHS": compound_widths_address,
        },
    )
    if code.warnings:
        raise ValueError(f"CONFIG VWF wrapper warnings: {code.warnings}")
    payload = bytearray(code)
    payload.extend(runtime_metrics()[0])
    payload.extend(bytes((-len(payload)) % 4))
    if CAVE_ADDR + len(payload) != action_widths_address:
        raise ValueError("CONFIG action-width table address drifted")
    payload.extend(action_widths)
    payload.extend(bytes((-len(payload)) % 4))
    if CAVE_ADDR + len(payload) != compound_widths_address:
        raise ValueError("CONFIG compound-width table address drifted")
    payload.extend(compound_widths())
    payload.extend(bytes((-len(payload)) % 4))
    return bytes(payload)


def build_active_row_renderer() -> bytes:
    source = (ASM_ROOT / "active_row_renderer.s").read_text(encoding="utf-8")
    blob = assemble(
        source,
        ACTIVE_RENDER_ADDR,
        symbols={
            "L_SELECTION": 0x06029DE4,
            "L_BRIGHT": 0x06029DF8,
            "L_COUNTS": 0x06029E02,
            "L_LABELS": LABEL_TABLE_ADDR,
            "L_CONTEXT": 0x060625C0,
            "L_DRAW": 0x06027E74,
            "L_NUMERIC": 0x06026AC8,
            "L_CACHE": ACTIVE_CACHE_ADDR,
        },
    )
    if blob.warnings:
        raise ValueError(f"CONFIG active-row renderer warnings: {blob.warnings}")
    return bytes(blob)


def build_action_vwf(action_widths: bytes) -> bytes:
    source = (ASM_ROOT / "action_vwf.s").read_text(encoding="utf-8")
    base_symbols = {
        "L_BLIT": ACTION_GLYPH,
        "ACTION_END": ACTION_CAPACITY + 1,
    }
    probe = assemble(
        source,
        ACTION_VWF_ADDR,
        symbols={
            **base_symbols,
            "ACTION_WIDTHS": ACTION_VWF_ADDR + 0x100,
        },
    )
    if probe.warnings:
        raise ValueError(f"CONFIG action VWF warnings: {probe.warnings}")
    widths_address = ACTION_VWF_ADDR + len(probe)
    code = assemble(
        source,
        ACTION_VWF_ADDR,
        symbols={
            **base_symbols,
            "ACTION_WIDTHS": widths_address,
        },
    )
    if code.warnings:
        raise ValueError(f"CONFIG action VWF warnings: {code.warnings}")
    payload = bytearray(code)
    payload.extend(action_widths)
    payload.extend(bytes((-len(payload)) % 4))
    return bytes(payload)


def build_config(original: bytes) -> bytes:
    if len(original) != 273560:
        raise ValueError("CFG_SET.BIN has an unexpected size")
    font16 = FONT16_PATH.read_bytes()
    if len(font16) < 1872 * 32:
        raise ValueError(f"{FONT16_PATH}: FONT16 build is incomplete")
    action_atlas, action_widths, action_records = build_action_atlas(font16)
    compound_runtime = build_compound_glyph_runtime(font16)
    data = bytearray(original)

    cave = build_vwf_wrapper(action_widths)
    if CAVE_FILE + len(cave) > COMPOUND_GLYPH_FILE:
        raise ValueError("CONFIG VWF wrapper exceeds its zero window")
    require(data, CAVE_FILE, bytes(len(cave)), "VWF cave")
    data[CAVE_FILE : CAVE_FILE + len(cave)] = cave

    require(
        data,
        COMPOUND_GLYPH_FILE,
        bytes(len(compound_runtime)),
        "compound-glyph cave",
    )
    data[COMPOUND_GLYPH_FILE : COMPOUND_GLYPH_FILE + len(compound_runtime)] = (
        compound_runtime
    )

    table_size = LABEL_RECORDS * LABEL_CELLS * 2
    require(data, LABEL_TABLE_FILE, bytes(table_size), "expanded label table")
    for index in range(LABEL_RECORDS):
        source = STOCK_LABEL_TABLE_FILE + index * 16
        target = LABEL_TABLE_FILE + index * LABEL_CELLS * 2
        data[target : target + 16] = data[source : source + 16]
    for stock_offset, name in LABEL_BLOCKS:
        words = asset_words(name)
        if len(words) != LABEL_CELLS:
            raise ValueError(f"CFG_SET.BIN label {name!r} is not 16 cells")
        target = expanded_label_offset(stock_offset)
        data[target : target + LABEL_CELLS * 2] = struct.pack(">16H", *words)
        length_offset = 0x9E04 + LABEL_BLOCKS.index((stock_offset, name)) * 2
        struct.pack_into(">H", data, length_offset, used_word_count(words, name))

    for offset in LABEL_STRIDE_SITES:
        require(data, offset, bytes.fromhex("e110"), "label stride")
        data[offset : offset + 2] = instruction("mov #0x20,r1", offset)
    for offset in LABEL_TABLE_POINTERS:
        require(
            data,
            offset,
            (BASE + STOCK_LABEL_TABLE_FILE).to_bytes(4, "big"),
            "label table pointer",
        )
        struct.pack_into(">I", data, offset, LABEL_TABLE_ADDR)
    require(
        data,
        ITEM_SORT_POINTER,
        (BASE + 0x9E9A).to_bytes(4, "big"),
        "item-sort pointer",
    )
    struct.pack_into(
        ">I",
        data,
        ITEM_SORT_POINTER,
        BASE + expanded_label_offset(0x9E9A),
    )

    active = build_active_row_renderer()
    noop_address = (ACTIVE_RENDER_ADDR + len(active) + 3) & ~3
    noop_offset = noop_address - BASE
    noop = bytes(assemble("rts\nnop", noop_address))
    require(
        data,
        ACTIVE_RENDER_FILE,
        bytes(noop_offset + len(noop) - ACTIVE_RENDER_FILE),
        "active-row cave",
    )
    require(data, ACTIVE_CACHE_FILE, bytes(4), "active-row cache")
    data[ACTIVE_RENDER_FILE : ACTIVE_RENDER_FILE + len(active)] = active
    data[ACTIVE_CACHE_FILE : ACTIVE_CACHE_FILE + 4] = b"\xff" * 4
    data[noop_offset : noop_offset + len(noop)] = noop
    for offset in ROW_RENDER_POINTERS:
        require(data, offset, (0x06026BEC).to_bytes(4, "big"), "row renderer pointer")
        struct.pack_into(">I", data, offset, ACTIVE_RENDER_ADDR)
    for offset in ACTIVE_RENDER_POINTERS:
        require(
            data, offset, (0x06026CD4).to_bytes(4, "big"), "active renderer pointer"
        )
        struct.pack_into(">I", data, offset, noop_address)

    action_vwf = build_action_vwf(action_widths)
    require(data, ACTION_VWF_FILE, bytes(len(action_vwf)), "action VWF cave")
    data[ACTION_VWF_FILE : ACTION_VWF_FILE + len(action_vwf)] = action_vwf
    require(
        data,
        ACTION_GLYPH_POOL_FILE,
        ACTION_GLYPH.to_bytes(4, "big"),
        "action glyph pointer",
    )
    struct.pack_into(">I", data, ACTION_GLYPH_POOL_FILE, ACTION_VWF_ADDR)
    require(data, ACTION_ADVANCE_SITE_FILE, bytes.fromhex("710c"), "action advance")
    data[ACTION_ADVANCE_SITE_FILE : ACTION_ADVANCE_SITE_FILE + 2] = instruction(
        "add r0,r1", ACTION_ADVANCE_SITE_FILE
    )
    require(data, GLYPH_POOL_FILE, STOCK_GLYPH.to_bytes(4, "big"), "glyph pointer")
    struct.pack_into(">I", data, GLYPH_POOL_FILE, CAVE_ADDR)
    require(data, ADVANCE_SITE_FILE, bytes.fromhex("7110"), "glyph advance")
    data[ADVANCE_SITE_FILE : ADVANCE_SITE_FILE + 2] = instruction(
        "add r0,r1", ADVANCE_SITE_FILE
    )

    for offset, name in PAGE2_BLOCKS:
        block = asset_block(name, "u16be")
        data[offset : offset + len(block)] = block

    magic_sort_table = b"".join(sort_record(name) for name in MAGIC_SORT_BLOCKS)
    item_sort_table = b"".join(sort_record(name) for name in ASSIST_BLOCKS)
    require(
        data,
        MAGIC_SORT_TABLE_FILE,
        bytes(len(magic_sort_table) + len(item_sort_table)),
        "expanded sort tables",
    )
    data[MAGIC_SORT_TABLE_FILE : MAGIC_SORT_TABLE_FILE + len(magic_sort_table)] = (
        magic_sort_table
    )
    data[ITEM_SORT_TABLE_FILE : ITEM_SORT_TABLE_FILE + len(item_sort_table)] = (
        item_sort_table
    )

    for offset, expected, source in (
        (0x69F8, bytes.fromhex("e10a"), "mov #0x20,r1"),
        (0x6A7E, bytes.fromhex("e10a"), "mov #0x20,r1"),
    ):
        require(data, offset, expected, "sort record geometry")
        data[offset : offset + 2] = instruction(source, offset)
    for offset, expected, replacement, name in (
        (0x6A3C, BASE + 0x9FA0, MAGIC_SORT_TABLE_ADDR, "magic-sort table"),
        (0x6AC4, BASE + 0x9FC8, ITEM_SORT_TABLE_ADDR, "item-sort table"),
    ):
        require(data, offset, expected.to_bytes(4, "big"), f"{name} pointer")
        struct.pack_into(">I", data, offset, replacement)
    for offset in MODE_COUNT_SITES:
        require(data, offset, bytes.fromhex("e504"), "mode cell count")
        data[offset : offset + 2] = instruction("mov #6,r5", offset)
    magic_sort_orders = tuple(value for order in MAGIC_SORT_ORDERS for value in order)
    require(
        data,
        0x9FE6,
        struct.pack(">12H", *magic_sort_orders),
        "magic-sort preset order",
    )

    require(data, ACTION_ATLAS_FILE, bytes(len(action_atlas)), "action atlas cave")
    data[ACTION_ATLAS_FILE : ACTION_ATLAS_FILE + len(action_atlas)] = action_atlas
    require(
        data,
        ACTION_ATLAS_POINTER,
        STOCK_ACTION_ATLAS_ADDR.to_bytes(4, "big"),
        "action atlas pointer",
    )
    struct.pack_into(">I", data, ACTION_ATLAS_POINTER, ACTION_ATLAS_ADDR)
    for offset, name in ACTION_BLOCKS:
        values = action_records[name]
        struct.pack_into(">8H", data, offset, *(values + (0,) * (8 - len(values))))
    for offset, name in FOOTER_BLOCKS:
        values = encode_ascii(asset_ascii(name), compounds=True)
        if len(values) > 9:
            raise ValueError(f"CFG_SET.BIN {name} exceeds nine footer cells")
        struct.pack_into(">9H", data, offset, *(values + (0,) * (9 - len(values))))

    return bytes(data)


def build_patch() -> PatchGroup:
    source_path = EXTRACTED_ROOT / TARGET.path
    replacement = build_config(source_path.read_bytes())
    return PatchGroup(
        "config_ui",
        TARGET,
        (
            DigestPatch(
                name="config_overlay",
                address=BASE,
                expected_sha256=ORIGINAL_SHA256,
                replacement=replacement,
            ),
        ),
    )


def build_patch_groups(_context: EngineBuildContext) -> PatchGroup:
    return build_patch()
