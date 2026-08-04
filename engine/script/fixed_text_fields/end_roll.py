"""Relocate END_ROLL credit names into proportional, complete bitmap rows."""

import struct
from dataclasses import dataclass
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.fixed_text_fields.generated import (
    RuntimeWordField,
    load_runtime_fields,
)
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from engine.script.text_render.font_metrics import load_font16_metrics
from tools.sh2asm import assemble

BASE = 0x06020000
TARGET = BinaryTarget("END_ROLL.BIN", Path("END_ROLL.BIN"), BASE)
ASSET = Path("fixed_words/END_ROLL.BIN.names.json")
SOURCE = Path("END_ROLL.BIN")
FONT16_NAME = "FONT16.FON"
METRICS_NAME = "font16_metrics.json"

MAIN_COUNT = 28
TEST_COUNT = 12
FIELD_COUNT = MAIN_COUNT + TEST_COUNT
MAIN_CELLS = 6
TEST_CELLS = 7
MAX_NAME_WORDS = 18

# 0x060247d0..0x0602484f is a live 128-byte save/restore buffer. The following
# window is independently all-zero in the source and has no absolute readers.
SOURCE_ZERO_START = 0x0602472B
LIVE_BUFFER = 0x060247D0
LIVE_BUFFER_SIZE = 0x80
CAVE = 0x06025000
CAVE_LIMIT = 0x0602AD50
RENDERER = CAVE
TEST_MAIN_WRAPPER = 0x06025100
TEST_EXTRA_WRAPPER = 0x06025140
OFFSET_TABLE = 0x06025180
BITMAP_POOL = OFFSET_TABLE + FIELD_COUNT * 2

MAIN_HOOK = (0x0602CF5E, 0x0602CF90)
MAIN_CONTINUATION = MAIN_HOOK[1]
MAIN_VDP_LITERAL = 0x0602D018
MAIN_RENDERER_LITERAL = 0x0602D01C
TEST_MAIN_TRAMPOLINE = (0x0602D1B0, 0x0602D1BC)
TEST_EXTRA_TRAMPOLINE = (0x0602D210, 0x0602D21C)

MAIN_VDP_BITMAP = 0x25E02000
TEST_VDP_BITMAP = 0x25E00000
MAIN_SOURCE_TABLE = 0x06039FA8
TEST_MAIN_SOURCE_TABLE = 0x06040304
TEST_EXTRA_SOURCE_TABLE = 0x060403AC
STOCK_MAIN_DRAWER = 0x0602CDCC
STOCK_TEST_DRAWER = 0x0602D020

ASM_ROOT = Path(__file__).with_name("asm")


@dataclass(frozen=True)
class EndRollRuntime:
    payload: bytes
    labels: dict[str, int]
    widths: tuple[int, ...]
    compressed_fields: tuple[str, ...]


def expected_field_names() -> tuple[str, ...]:
    return tuple(f"main_staff_{index:02d}" for index in range(MAIN_COUNT)) + tuple(
        f"test_staff_{index:02d}" for index in range(TEST_COUNT)
    )


def load_advances(path: Path) -> dict[int, int]:
    document = load_font16_metrics(path)
    if not document.get("complete"):
        raise ValueError(f"{path}: incomplete FONT16 metrics")
    advances = {}
    for glyph in document["glyphs"]:
        code = glyph.get("code")
        advance = glyph.get("advance")
        if (
            not isinstance(code, int)
            or code < 0
            or not isinstance(advance, int)
            or not 1 <= advance <= 16
            or code in advances
        ):
            raise ValueError(f"{path}: invalid or duplicate FONT16 glyph metric")
        advances[code] = advance
    return advances


def render_name_tiles(
    font16: bytes,
    words: tuple[int, ...],
    advances: dict[int, int],
    cell_count: int,
) -> tuple[bytes, int, bool]:
    """Render one proportional row as sequential Saturn 8x8 tile masks."""
    if not words:
        raise ValueError("END_ROLL name cannot be empty")
    if cell_count not in (MAIN_CELLS, TEST_CELLS):
        raise ValueError(f"unsupported END_ROLL row width: {cell_count} cells")

    glyphs = []
    source_width = 0
    for code in words:
        try:
            advance = advances[code]
        except KeyError as error:
            raise ValueError(f"END_ROLL glyph {code:#06x} has no width") from error
        start = code * 32
        glyph = font16[start : start + 32]
        if len(glyph) != 32:
            raise ValueError(f"END_ROLL glyph {code:#06x} exceeds FONT16")
        glyphs.append((code, glyph, advance, source_width))
        source_width += advance

    destination_width = cell_count * 16
    compressed = source_width > destination_width
    rows = [0] * 16
    for code, glyph, advance, glyph_x in glyphs:
        for row in range(16):
            word = struct.unpack_from(">H", glyph, row * 2)[0]
            for column in range(16):
                if not word & (1 << (15 - column)):
                    continue
                if column >= advance:
                    raise ValueError(
                        f"END_ROLL glyph {code:#06x} has ink beyond its "
                        f"{advance}px advance"
                    )
                source_x = glyph_x + column
                destination_x = (
                    source_x * destination_width // source_width
                    if compressed
                    else source_x
                )
                if destination_x >= destination_width:
                    raise ValueError("END_ROLL name bitmap exceeds its surface")
                rows[row] |= 1 << (destination_width - destination_x - 1)

    output = bytearray()
    for cell in range(cell_count):
        left_shift = destination_width - cell * 16 - 8
        right_shift = left_shift - 8
        for row_start, shift in (
            (0, left_shift),
            (0, right_shift),
            (8, left_shift),
            (8, right_shift),
        ):
            output.extend(
                (rows[row] >> shift) & 0xFF for row in range(row_start, row_start + 8)
            )
    expected_size = cell_count * 32
    if len(output) != expected_size:
        raise AssertionError(
            f"END_ROLL tile layout is {len(output)} bytes; expected {expected_size}"
        )
    return bytes(output), source_width, compressed


def build_bitmap_pool(
    fields: tuple[RuntimeWordField, ...],
    font16: bytes,
    advances: dict[int, int],
) -> tuple[bytes, bytes, tuple[int, ...], tuple[str, ...]]:
    expected_names = expected_field_names()
    actual_names = tuple(field.name for field in fields)
    if actual_names != expected_names:
        raise ValueError(
            "END_ROLL runtime fields are missing, duplicated, or out of source order"
        )

    offsets = []
    bitmaps = bytearray()
    widths = []
    compressed_fields = []
    for index, field in enumerate(fields):
        offsets.append(len(bitmaps))
        cells = MAIN_CELLS if index < MAIN_COUNT else TEST_CELLS
        bitmap, width, compressed = render_name_tiles(
            font16,
            field.words,
            advances,
            cells,
        )
        bitmaps.extend(bitmap)
        widths.append(width)
        if compressed:
            compressed_fields.append(field.name)

    if offsets and offsets[-1] > 0xFFFF:
        raise ValueError("END_ROLL bitmap offsets exceed the 16-bit table")
    return (
        struct.pack(f">{len(offsets)}H", *offsets),
        bytes(bitmaps),
        tuple(widths),
        tuple(compressed_fields),
    )


def _assemble(path: Path, address: int, symbols: dict[str, int]) -> bytes:
    blob = assemble(path.read_text(encoding="utf-8"), address, symbols=symbols)
    if blob.warnings:
        raise ValueError(f"{path.name}: assembler warnings: {blob.warnings}")
    return bytes(blob)


def build_runtime(
    fields: tuple[RuntimeWordField, ...],
    font16: bytes,
    advances: dict[int, int],
) -> EndRollRuntime:
    offsets, bitmaps, widths, compressed_fields = build_bitmap_pool(
        fields,
        font16,
        advances,
    )
    if len(offsets) != FIELD_COUNT * 2:
        raise AssertionError("END_ROLL offset-table size changed")

    renderer = _assemble(
        ASM_ROOT / "end_roll_renderer.s",
        RENDERER,
        {"OFFSETS": OFFSET_TABLE, "BITMAPS": BITMAP_POOL},
    )
    wrapper_source = ASM_ROOT / "end_roll_test_wrapper.s"
    test_main = _assemble(
        wrapper_source,
        TEST_MAIN_WRAPPER,
        {
            "INDEX_BASE": MAIN_COUNT,
            "RENDERER": RENDERER,
            "VDP_BITMAP": TEST_VDP_BITMAP,
        },
    )
    test_extra = _assemble(
        wrapper_source,
        TEST_EXTRA_WRAPPER,
        {
            "INDEX_BASE": MAIN_COUNT + 10,
            "RENDERER": RENDERER,
            "VDP_BITMAP": TEST_VDP_BITMAP,
        },
    )

    if RENDERER + len(renderer) > TEST_MAIN_WRAPPER:
        raise ValueError("END_ROLL renderer exceeds its reserved code slot")
    if TEST_MAIN_WRAPPER + len(test_main) > TEST_EXTRA_WRAPPER:
        raise ValueError("END_ROLL first test wrapper exceeds its slot")
    if TEST_EXTRA_WRAPPER + len(test_extra) > OFFSET_TABLE:
        raise ValueError("END_ROLL second test wrapper exceeds its slot")

    payload = bytearray()
    for address, part in (
        (RENDERER, renderer),
        (TEST_MAIN_WRAPPER, test_main),
        (TEST_EXTRA_WRAPPER, test_extra),
        (OFFSET_TABLE, offsets),
        (BITMAP_POOL, bitmaps),
    ):
        if address < CAVE + len(payload):
            raise ValueError("END_ROLL runtime sections overlap")
        payload.extend(bytes(address - CAVE - len(payload)))
        payload.extend(part)
    if CAVE + len(payload) > CAVE_LIMIT:
        raise ValueError("END_ROLL runtime exceeds its verified zero window")
    return EndRollRuntime(
        payload=bytes(payload),
        labels={
            "renderer": RENDERER,
            "test_main_wrapper": TEST_MAIN_WRAPPER,
            "test_extra_wrapper": TEST_EXTRA_WRAPPER,
            "offset_table": OFFSET_TABLE,
            "bitmap_pool": BITMAP_POOL,
            "end": CAVE + len(payload),
        },
        widths=widths,
        compressed_fields=compressed_fields,
    )


def _fit_hook(code: bytes, size: int, name: str) -> bytes:
    if len(code) > size or (size - len(code)) & 1:
        raise ValueError(f"END_ROLL {name} does not fit its {size}-byte hook")
    return code + bytes.fromhex("0009") * ((size - len(code)) // 2)


def build_main_hook() -> bytes:
    source = (ASM_ROOT / "end_roll_main_hook.s").read_text(encoding="utf-8")
    blob = assemble(
        source,
        MAIN_HOOK[0],
        symbols={
            "CONTINUATION": MAIN_CONTINUATION,
            "RENDERER_LITERAL": MAIN_RENDERER_LITERAL,
            "VDP_LITERAL": MAIN_VDP_LITERAL,
        },
    )
    if blob.warnings:
        raise ValueError(f"END_ROLL main hook warnings: {blob.warnings}")
    return _fit_hook(bytes(blob), MAIN_HOOK[1] - MAIN_HOOK[0], "main hook")


def build_trampoline(address: int, wrapper: int, size: int) -> bytes:
    source = (ASM_ROOT / "end_roll_trampoline.s").read_text(encoding="utf-8")
    blob = assemble(source, address, symbols={"WRAPPER": wrapper})
    if blob.warnings:
        raise ValueError(f"END_ROLL trampoline warnings: {blob.warnings}")
    return _fit_hook(bytes(blob), size, "test trampoline")


def build_patch_group(context: EngineBuildContext) -> PatchGroup:
    load_address, fields = load_runtime_fields(
        ASSET,
        context.text_generated_root,
        context.extracted_root,
        expected_source=SOURCE,
        max_words=MAX_NAME_WORDS,
    )
    if load_address != BASE:
        raise ValueError(
            f"END_ROLL generated load address is {load_address:#010x}; "
            f"expected {BASE:#010x}"
        )

    font16 = (context.build_root / FONT16_NAME).read_bytes()
    advances = load_advances(context.font_generated_root / METRICS_NAME)
    runtime = build_runtime(fields, font16, advances)
    original = (context.extracted_root / SOURCE).read_bytes()

    def span(start: int, end: int) -> bytes:
        return original[start - BASE : end - BASE]

    cave_original = span(CAVE, CAVE + len(runtime.payload))
    if cave_original != bytes(len(runtime.payload)):
        first = next(index for index, value in enumerate(cave_original) if value != 0)
        raise ValueError(
            f"END_ROLL verified cave is no longer zero at {CAVE + first:#010x}"
        )

    return PatchGroup(
        "fixed_text_fields",
        TARGET,
        (
            BytePatch(
                "end_roll_name_runtime",
                CAVE,
                cave_original,
                runtime.payload,
            ),
            BytePatch(
                "end_roll_main_name_hook",
                MAIN_HOOK[0],
                span(*MAIN_HOOK),
                build_main_hook(),
            ),
            BytePatch(
                "end_roll_main_vdp_literal",
                MAIN_VDP_LITERAL,
                struct.pack(">I", MAIN_SOURCE_TABLE),
                struct.pack(">I", MAIN_VDP_BITMAP),
            ),
            BytePatch(
                "end_roll_main_renderer_literal",
                MAIN_RENDERER_LITERAL,
                struct.pack(">I", STOCK_MAIN_DRAWER),
                struct.pack(">I", RENDERER),
            ),
            BytePatch(
                "end_roll_test_main_trampoline",
                TEST_MAIN_TRAMPOLINE[0],
                span(*TEST_MAIN_TRAMPOLINE),
                build_trampoline(
                    TEST_MAIN_TRAMPOLINE[0],
                    TEST_MAIN_WRAPPER,
                    TEST_MAIN_TRAMPOLINE[1] - TEST_MAIN_TRAMPOLINE[0],
                ),
            ),
            BytePatch(
                "end_roll_test_extra_trampoline",
                TEST_EXTRA_TRAMPOLINE[0],
                span(*TEST_EXTRA_TRAMPOLINE),
                build_trampoline(
                    TEST_EXTRA_TRAMPOLINE[0],
                    TEST_EXTRA_WRAPPER,
                    TEST_EXTRA_TRAMPOLINE[1] - TEST_EXTRA_TRAMPOLINE[0],
                ),
            ),
        ),
    )
