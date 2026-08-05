"""Compose fixed-word text assets into binaries also owned by engine patches."""

import hashlib
import json
import struct
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.fixed_text_fields.end_roll import (
    build_patch_group as build_end_roll_patch,
)
from engine.script.fixed_text_fields.generated import ASSETS, load_group
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from engine.script.static_text import StaticTextAsset, load_static_asset
from engine.script.text_render.font8_metrics import font8_metrics
from engine.script.text_render.font16_vwf import align_up
from engine.script.text_render.font_metrics import (
    FONT16_PATH,
    font16_metrics,
    font16_width_layout,
)
from engine.script.text_render.precomposed import (
    PrecomposedStrip,
    precompose_font16_strip,
)
from project_paths import EXTRACTED_ROOT, TEXT_GENERATED_ROOT
from tools.sh2asm import assemble

MAZE_BASE = 0x06020000
MAZE_TARGET = BinaryTarget("MAZE.BIN", Path("MAZE.BIN"), MAZE_BASE)
MAZE_MESSAGE_CAVE = 0x06022C00
MAZE_MESSAGE_CAVE_LIMIT = 0x06023800
MAZE_CHOICE_ASSET = Path("static") / "MAZE.BIN.speech_choices.json"
MAZE_CHOICE_YES = 0x060450D0
MAZE_CHOICE_NO = 0x060450D6
MAZE_CHOICE_DRAW = 0x06040AAC
MAZE_CHOICE_DRAW_POINTERS = (
    0x060330F8,
    0x0603C680,
    0x0603C884,
    0x0603C9A0,
    0x06040D40,
)
MAZE_CHOICE_SCRATCH_CODE = 0x0756
MAZE_CHOICE_CELLS = 3
MAZE_CHOICE_FIELDS = (
    ("label_yes", MAZE_CHOICE_YES, (0x0023, 0x000F, 0x001D)),
    ("label_no", MAZE_CHOICE_NO, (0x0018, 0x0019, 0x0000)),
)
MAZE_MESSAGE_DISPLAY = 0x06040BC4
MAZE_MESSAGE_DISPLAY_POINTERS = (
    0x06032F90,
    0x06033510,
    0x060342FC,
    0x060343CC,
    0x0603463C,
    0x0603479C,
    0x06034948,
    0x06034AAC,
    0x06034E48,
    0x06035968,
    0x06035B28,
    0x0603C540,
)
FONT16_BASE = 0x0021A000
MAZE_SCRATCH_CODE = 0x0748
MAZE_PROMPT_CODE = 0x00C5
MAZE_CURRENCY_YEN_CODE = 0x00C0
MAZE_CURRENCY_MAG_CODE = 0x00C1
ITEMNAME_BASE = 0x00228C00
ITEMNAME_FULL_NAME_OFFSET = 0x5E
ITEMNAME_MAX_BYTES = 32
MAZE_MESSAGE_NATIVE_BUFFER = 0x060451C0
MAZE_MESSAGE_BUFFER_POINTERS = (
    0x060342EC,
    0x060343BC,
    0x06034628,
    0x06034788,
)
PACKED_SPACE_CODE = 267
MAZE_MESSAGE_PACKED_WORDS = 18
MAZE_MESSAGE_CELLS = 14
MAZE_MESSAGE_BUFFER_WORDS = 64
MAZE_ITEM_FOUND_HOOKS = (
    (0x060341C0, 0x06034210),
    (0x06034284, 0x060342D4),
)
MAZE_ITEM_FULL_HOOK = (0x06034332, 0x0603439A)
ASM_ROOT = Path(__file__).with_name("asm")


def load_maze_choice_asset(
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path = EXTRACTED_ROOT,
) -> StaticTextAsset:
    return load_static_asset(
        MAZE_CHOICE_ASSET,
        MAZE_TARGET.path,
        generated_root,
        extracted_root,
    )


def maze_choice_block(asset: StaticTextAsset, name: str) -> bytes:
    try:
        block = asset.blocks[name]
    except KeyError as error:
        raise ValueError(f"MAZE speech choices are missing block {name!r}") from error
    if block.storage != "u16be" or block.word_count != MAZE_CHOICE_CELLS:
        raise ValueError(f"MAZE speech choice {name!r} has an invalid span")
    return asset.data[block.offset : block.offset + block.size]


def maze_choice_words(asset: StaticTextAsset, name: str) -> tuple[int, ...]:
    data = maze_choice_block(asset, name)
    return struct.unpack(f">{MAZE_CHOICE_CELLS}H", data)


def font16_advances() -> bytes:
    metrics = font16_metrics()
    code_limit, _width_offset = font16_width_layout(metrics)
    widths = bytearray(code_limit)
    for glyph in metrics["glyphs"]:
        code = glyph["code"]
        advance = glyph["advance"]
        if not 0 <= code < code_limit or not 1 <= advance <= 0xFF:
            raise ValueError(f"invalid FONT16 metrics for glyph {code}")
        widths[code] = advance
    return bytes(widths)


def build_maze_choice_strips(
    font16: bytes,
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path = EXTRACTED_ROOT,
) -> tuple[PrecomposedStrip, ...]:
    asset = load_maze_choice_asset(generated_root, extracted_root)
    widths = font16_advances()
    strips = []
    for name, _address, _expected in MAZE_CHOICE_FIELDS:
        physical_words = maze_choice_words(asset, name)
        visible_words = physical_words
        while visible_words and visible_words[-1] == 0:
            visible_words = visible_words[:-1]
        if not visible_words or 0 in visible_words:
            raise ValueError(f"MAZE speech choice {name!r} has embedded padding")
        strips.append(
            precompose_font16_strip(
                font16,
                visible_words,
                widths,
                MAZE_CHOICE_CELLS,
                context=f"MAZE {name}",
            )
        )
    return tuple(strips)


def build_maze_choice_runtime(
    address: int,
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path = EXTRACTED_ROOT,
    font16_path: Path = FONT16_PATH,
) -> tuple[bytes, dict[str, int]]:
    scratch_end = FONT16_BASE + (MAZE_CHOICE_SCRATCH_CODE + MAZE_CHOICE_CELLS) * 32
    message_scratch_end = FONT16_BASE + (MAZE_SCRATCH_CODE + MAZE_MESSAGE_CELLS) * 32
    if FONT16_BASE + MAZE_CHOICE_SCRATCH_CODE * 32 < message_scratch_end:
        raise ValueError("MAZE speech-choice scratch overlaps message scratch")
    if scratch_end > ITEMNAME_BASE:
        raise ValueError("MAZE speech-choice scratch overlaps ITEMNAME")

    yes_strip, no_strip = build_maze_choice_strips(
        font16_path.read_bytes(),
        generated_root,
        extracted_root,
    )
    source = (ASM_ROOT / "maze_choice_vwf.s").read_text(encoding="utf-8")
    base_symbols = {
        "YES_FIELD": MAZE_CHOICE_YES,
        "NO_FIELD": MAZE_CHOICE_NO,
        "ORIGINAL_DRAW": MAZE_CHOICE_DRAW,
        "FONT_DST": FONT16_BASE + MAZE_CHOICE_SCRATCH_CODE * 32,
        "BITMAP_LONGS": MAZE_CHOICE_CELLS * 32 // 4,
        "YES_BITMAP": address,
        "NO_BITMAP": address,
        "ROW": address,
    }
    probe = assemble(source, address, symbols=base_symbols)
    if probe.warnings:
        raise ValueError(f"MAZE speech-choice wrapper warnings: {probe.warnings}")

    yes_bitmap_address = align_up(address + len(probe), 4)
    no_bitmap_address = yes_bitmap_address + len(yes_strip.bitmap)
    row_address = align_up(no_bitmap_address + len(no_strip.bitmap), 2)
    wrapper = assemble(
        source,
        address,
        symbols={
            **base_symbols,
            "YES_BITMAP": yes_bitmap_address,
            "NO_BITMAP": no_bitmap_address,
            "ROW": row_address,
        },
    )
    if wrapper.warnings:
        raise ValueError(
            f"MAZE speech-choice final wrapper warnings: {wrapper.warnings}"
        )
    row = struct.pack(
        f">{MAZE_CHOICE_CELLS}H",
        *range(
            MAZE_CHOICE_SCRATCH_CODE,
            MAZE_CHOICE_SCRATCH_CODE + MAZE_CHOICE_CELLS,
        ),
    )
    payload = bytearray(wrapper)
    for part_address, part in (
        (yes_bitmap_address, yes_strip.bitmap),
        (no_bitmap_address, no_strip.bitmap),
        (row_address, row),
    ):
        payload.extend(bytes(part_address - address - len(payload)))
        payload.extend(part)
    return bytes(payload), {
        "choice_draw": address,
        "choice_yes_bitmap": yes_bitmap_address,
        "choice_no_bitmap": no_bitmap_address,
        "choice_row": row_address,
    }


def load_maze_runtime_fields(
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path = EXTRACTED_ROOT,
) -> tuple[tuple[str, int, tuple[int, ...]], ...]:
    relative = Path("fixed_words") / "MAZE.BIN.messages.json"
    path = generated_root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1 or document.get("source") != "MAZE.BIN":
        raise ValueError(f"{path}: invalid MAZE runtime asset")
    original = (extracted_root / "MAZE.BIN").read_bytes()
    if hashlib.sha256(original).hexdigest() != document.get("source_sha256"):
        raise ValueError(f"{path}: extracted MAZE.BIN hash changed")
    rows = document.get("runtime_fields")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: missing MAZE runtime fields")
    fields = []
    names = set()
    offsets = set()
    for index, row in enumerate(rows):
        context = f"{path}: runtime field {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        name = row.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"{context}: invalid or duplicate name")
        try:
            offset = int(row["file_offset"], 16)
            count = row["word_count"]
            data = bytes.fromhex(row["words_hex"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{context}: invalid encoded words") from error
        if (
            offset in offsets
            or not isinstance(count, int)
            or not 1 <= count <= MAZE_MESSAGE_PACKED_WORDS
            or len(data) != count * 2
        ):
            raise ValueError(f"{context}: invalid runtime span")
        words = struct.unpack(f">{count}H", data)
        names.add(name)
        offsets.add(offset)
        fields.append((name, offset, words))
    return tuple(fields)


def build_maze_item_code_map() -> bytes:
    metrics16 = font16_metrics()
    codes16 = {}
    for row in metrics16["glyphs"]:
        for text in (row["text"], *row.get("aliases", ())):
            if len(text) == 1:
                codes16.setdefault(text, row["code"])

    _widths8, codes8 = font8_metrics()
    output = bytearray(512)
    for text, code8 in codes8.items():
        if len(text) != 1 or text not in codes16:
            continue
        code16 = codes16[text]
        struct.pack_into(">H", output, code8 * 2, code16)
    return bytes(output)


def encode_maze_literal(text: str) -> tuple[int, ...]:
    metrics16 = font16_metrics()
    codes = {}
    for row in metrics16["glyphs"]:
        for glyph_text in (row["text"], *row.get("aliases", ())):
            if len(glyph_text) == 1:
                codes.setdefault(glyph_text, row["code"])

    words = []
    for character in text:
        try:
            code = codes[character]
        except KeyError as error:
            raise ValueError(
                f"unsupported MAZE message character {character!r}"
            ) from error
        words.append(code)
    return tuple(words)


def decode_maze_packed_words(words: tuple[int, ...]) -> tuple[int, ...]:
    decoded = []
    for word in words:
        high = word >> 8
        if high >= 8:
            first = high - 8
            decoded.append(PACKED_SPACE_CODE if first == 0 else first)
            low = word & 0xFF
            if low:
                second = low - 8
                decoded.append(PACKED_SPACE_CODE if second == 0 else second)
        else:
            decoded.append(word)
    return tuple(decoded)


def maze_message_width(words: tuple[int, ...]) -> int:
    advances = {row["code"]: row["advance"] for row in font16_metrics()["glyphs"]}
    return sum(advances.get(code, 16) for code in words)


def maze_composed_width(words: tuple[int, ...]) -> int:
    if words and words[0] == MAZE_PROMPT_CODE:
        return 16 + maze_message_width(words[1:])
    return maze_message_width(words)


def build_item_hook(start: int, end: int, target: int) -> bytes:
    source = (ASM_ROOT / "item_hook.s").read_text(encoding="utf-8")
    code = bytes(assemble(source, start, symbols={"TARGET": target}))
    size = end - start
    if len(code) > size or (size - len(code)) & 1:
        raise ValueError(f"MAZE item hook at {start:#x} does not fit")
    return code + bytes.fromhex("0009") * ((size - len(code)) // 2)


def build_maze_message_runtime(
    cave_address: int,
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path = EXTRACTED_ROOT,
    font16_path: Path = FONT16_PATH,
) -> tuple[bytes, dict[str, int]]:
    packed_fields = load_maze_runtime_fields(generated_root, extracted_root)
    runtime_fields = tuple(
        (name, offset, decode_maze_packed_words(words))
        for name, offset, words in packed_fields
        if 0xFFF0 not in words
    )
    for name, _offset, words in runtime_fields:
        width = maze_composed_width(words)
        if width > MAZE_MESSAGE_CELLS * 16:
            raise ValueError(
                f"MAZE message {name!r} is {width} pixels wide; "
                f"maximum is {MAZE_MESSAGE_CELLS * 16}"
            )
    metrics = font16_metrics()
    code_limit, width_offset = font16_width_layout(metrics)
    compositor_address = cave_address
    compositor_source = (ASM_ROOT / "maze_message_compositor.s").read_text(
        encoding="utf-8"
    )
    compositor_symbols = {
        "FONT_BASE": FONT16_BASE,
        "WIDTHS": FONT16_BASE + width_offset,
        "WIDTH_LIMIT": code_limit,
        "SCRATCH_CODE": MAZE_SCRATCH_CODE,
        "SCRATCH_LONGS": MAZE_MESSAGE_CELLS * 8,
        "CELL_COUNT": MAZE_MESSAGE_CELLS,
        "MAX_GLYPHS": MAZE_MESSAGE_BUFFER_WORDS,
        "PROMPT_CODE": MAZE_PROMPT_CODE,
        "CURRENCY_YEN_CODE": MAZE_CURRENCY_YEN_CODE,
        "CURRENCY_MAG_CODE": MAZE_CURRENCY_MAG_CODE,
        "CURRENCY_PREFIX": cave_address,
        "ROW": cave_address,
    }
    compositor_probe = assemble(
        compositor_source,
        compositor_address,
        symbols=compositor_symbols,
    )
    if compositor_probe.warnings:
        raise ValueError(
            f"MAZE message compositor warnings: {compositor_probe.warnings}"
        )

    display_address = align_up(
        compositor_address + len(compositor_probe),
        4,
    )
    display_source = (ASM_ROOT / "maze_message_display.s").read_text(encoding="utf-8")
    display_symbols = {
        "ORIGINAL": MAZE_MESSAGE_DISPLAY,
        "MAPPING_TABLE": display_address,
        "MAPPING_COUNT": len(runtime_fields),
        "COMPOSITOR": compositor_address,
        "BUFFER": display_address,
        "ROW": display_address,
    }
    display_probe = assemble(
        display_source,
        display_address,
        symbols=display_symbols,
    )
    if display_probe.warnings:
        raise ValueError(f"MAZE message display warnings: {display_probe.warnings}")

    item_address = align_up(display_address + len(display_probe), 4)
    item_source = (ASM_ROOT / "maze_item_names.s").read_text(encoding="utf-8")
    item_symbols = {
        "BUFFER": item_address,
        "ITEM_BASE": ITEMNAME_BASE,
        "ITEM_FULL_NAME_OFFSET": ITEMNAME_FULL_NAME_OFFSET,
        "ITEM_NAME_LIMIT": min(
            ITEMNAME_MAX_BYTES,
            MAZE_MESSAGE_BUFFER_WORDS - 8,
        ),
        "BUFFER_WORDS": MAZE_MESSAGE_BUFFER_WORDS,
        "TOKEN_MAP": item_address,
        "FOUND_PREFIX": item_address,
        "FOUND_WORDS": 6,
        "FULL_SUFFIX": item_address,
        "FULL_WORDS": 8,
    }
    item_probe = assemble(item_source, item_address, symbols=item_symbols)
    if item_probe.warnings:
        raise ValueError(f"MAZE item-name warnings: {item_probe.warnings}")

    token_map = build_maze_item_code_map()
    token_map_address = align_up(item_address + len(item_probe), 4)
    found_words = encode_maze_literal("Found ")
    full_words = encode_maze_literal(" is full")
    if len(found_words) != 6 or len(full_words) != 8:
        raise ValueError("MAZE item-message phrase encoding changed")
    found_prefix = struct.pack(">6H", *found_words)
    full_suffix = struct.pack(">8H", *full_words)
    found_prefix_address = token_map_address + len(token_map)
    full_suffix_address = found_prefix_address + len(found_prefix)
    currency_prefix_words = encode_maze_literal("Obtained ")
    if len(currency_prefix_words) != 9:
        raise ValueError("MAZE currency-message prefix encoding changed")
    currency_prefix = struct.pack(">9H", *currency_prefix_words)
    currency_prefix_address = full_suffix_address + len(full_suffix)
    mapping_table_address = align_up(
        currency_prefix_address + len(currency_prefix),
        4,
    )
    runtime_strings_address = mapping_table_address + len(runtime_fields) * 8
    runtime_rows = []
    cursor = runtime_strings_address
    for name, offset, words in runtime_fields:
        data = struct.pack(f">{len(words) + 1}H", *words, 0)
        runtime_rows.append((name, offset, cursor, data))
        cursor = align_up(cursor + len(data), 2)
    buffer_address = align_up(cursor, 4)
    row_address = buffer_address + MAZE_MESSAGE_BUFFER_WORDS * 2
    mapping_table = b"".join(
        struct.pack(">II", MAZE_BASE + offset, address)
        for _name, offset, address, _data in runtime_rows
    )

    compositor = assemble(
        compositor_source,
        compositor_address,
        symbols={
            **compositor_symbols,
            "CURRENCY_PREFIX": currency_prefix_address,
            "ROW": row_address,
        },
    )
    display = assemble(
        display_source,
        display_address,
        symbols={
            **display_symbols,
            "MAPPING_TABLE": mapping_table_address,
            "BUFFER": buffer_address,
            "ROW": row_address,
        },
    )
    item = assemble(
        item_source,
        item_address,
        symbols={
            **item_symbols,
            "BUFFER": buffer_address,
            "TOKEN_MAP": token_map_address,
            "FOUND_PREFIX": found_prefix_address,
            "FULL_SUFFIX": full_suffix_address,
        },
    )
    if compositor.warnings or display.warnings or item.warnings:
        raise ValueError(
            "MAZE message final assembly warnings: "
            f"{compositor.warnings + display.warnings + item.warnings}"
        )

    payload = bytearray()
    for address, part in (
        (compositor_address, compositor),
        (display_address, display),
        (item_address, item),
        (token_map_address, token_map),
        (found_prefix_address, found_prefix),
        (full_suffix_address, full_suffix),
        (currency_prefix_address, currency_prefix),
        (mapping_table_address, mapping_table),
        *((address, data) for _name, _offset, address, data in runtime_rows),
    ):
        payload.extend(bytes(address - cave_address - len(payload)))
        payload.extend(part)
    payload.extend(bytes(buffer_address - cave_address - len(payload)))
    payload.extend(bytes(MAZE_MESSAGE_BUFFER_WORDS * 2))
    payload.extend(bytes(MAZE_MESSAGE_CELLS * 2))
    choice_address = align_up(cave_address + len(payload), 4)
    choice_runtime, choice_labels = build_maze_choice_runtime(
        choice_address,
        generated_root,
        extracted_root,
        font16_path,
    )
    payload.extend(bytes(choice_address - cave_address - len(payload)))
    payload.extend(choice_runtime)
    if cave_address + len(payload) > MAZE_MESSAGE_CAVE_LIMIT:
        raise ValueError(
            "MAZE fixed-cell message runtime exceeds its verified free window"
        )
    return bytes(payload), {
        "compositor": compositor_address,
        "display": display_address,
        "found_item": item.labels["maze_found_item"],
        "full_item": item.labels["maze_full_item"],
        "currency_prefix": currency_prefix_address,
        "token_map": token_map_address,
        "buffer": buffer_address,
        "row": row_address,
        "mapping_table": mapping_table_address,
        "code_limit": code_limit,
        **choice_labels,
    }


def build_maze_patch(
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path = EXTRACTED_ROOT,
    font16_path: Path = FONT16_PATH,
) -> PatchGroup:
    runtime, labels = build_maze_message_runtime(
        MAZE_MESSAGE_CAVE,
        generated_root,
        extracted_root,
        font16_path,
    )
    original = (extracted_root / MAZE_TARGET.path).read_bytes()
    choice_asset = load_maze_choice_asset(generated_root, extracted_root)

    def original_span(start: int, end: int) -> bytes:
        return original[start - MAZE_BASE : end - MAZE_BASE]

    return PatchGroup(
        "fixed_text_fields",
        MAZE_TARGET,
        (
            BytePatch(
                "maze_message_fixed_cell_cave",
                MAZE_MESSAGE_CAVE,
                bytes(len(runtime)),
                runtime,
            ),
            *(
                BytePatch(
                    f"maze_speech_choice_draw_pointer_{address:08x}",
                    address,
                    struct.pack(">I", MAZE_CHOICE_DRAW),
                    struct.pack(">I", labels["choice_draw"]),
                )
                for address in MAZE_CHOICE_DRAW_POINTERS
            ),
            *(
                BytePatch(
                    f"maze_speech_choice_{name}",
                    address,
                    struct.pack(f">{len(expected)}H", *expected),
                    maze_choice_block(choice_asset, name),
                )
                for name, address, expected in MAZE_CHOICE_FIELDS
            ),
            *(
                BytePatch(
                    f"maze_message_display_pointer_{address:08x}",
                    address,
                    struct.pack(">I", MAZE_MESSAGE_DISPLAY),
                    struct.pack(">I", labels["display"]),
                )
                for address in MAZE_MESSAGE_DISPLAY_POINTERS
            ),
            *(
                BytePatch(
                    f"maze_message_buffer_pointer_{address:08x}",
                    address,
                    struct.pack(">I", MAZE_MESSAGE_NATIVE_BUFFER),
                    struct.pack(">I", labels["buffer"]),
                )
                for address in MAZE_MESSAGE_BUFFER_POINTERS
            ),
            *(
                BytePatch(
                    f"maze_item_found_hook_{start:08x}",
                    start,
                    original_span(start, end),
                    build_item_hook(start, end, labels["found_item"]),
                )
                for start, end in MAZE_ITEM_FOUND_HOOKS
            ),
            BytePatch(
                "maze_item_full_hook",
                MAZE_ITEM_FULL_HOOK[0],
                original_span(*MAZE_ITEM_FULL_HOOK),
                build_item_hook(*MAZE_ITEM_FULL_HOOK, labels["full_item"]),
            ),
        ),
    )


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    groups = tuple(
        group
        for relative in ASSETS
        if (
            group := load_group(
                relative,
                context.text_generated_root,
                context.extracted_root,
            )
        )
        is not None
    )
    return (
        *groups,
        build_maze_patch(
            context.text_generated_root,
            context.extracted_root,
            context.build_root / "FONT16.FON",
        ),
        build_end_roll_patch(context),
    )
