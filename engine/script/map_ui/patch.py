"""Localize MAP2D and render its dynamic city and ward name rows."""

import json
import struct
from functools import cache
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.name.fields import FIELD_BY_KIND, NameField
from engine.script.patching import BinaryTarget, DigestPatch, PatchGroup
from engine.script.static_text import load_static_asset
from project_paths import PROJECT_ROOT as TRANSLATION_ROOT
from tools.sh2asm import assemble

BASE = 0x06020000
TARGET = BinaryTarget("MAP2D.BIN", Path("MAP2D.BIN"), BASE)
ORIGINAL_SHA256 = "1e8d00baefdfa282f3a63beb48ca13adec179935594bd5361bf8234c61ed6ecc"

FONT16_BASE = 0x0021A000
WARD_SCRATCH_CODE = 0x0740
CITY_SCRATCH_CODE = 0x0744
FIXED_SCRATCH_CODE = 0x0748
ITEMNAME_BASE = 0x00228C00

CAVE_FILE = 0x0400
CAVE_ADDR = BASE + CAVE_FILE
SCALE_MAP_FILE = 0x0800
SCALE_MAP_ADDR = BASE + SCALE_MAP_FILE
SCALE_MAP_BYTES = 128
PROMPT_CAVE_FILE = 0x1000
PROMPT_CAVE_ADDR = BASE + PROMPT_CAVE_FILE
FIXED_BITMAP_FILE = 0x1200
FIXED_BITMAP_ADDR = BASE + FIXED_BITMAP_FILE
PROMPT_BITMAP_FILE = 0x1600
PROMPT_BITMAP_ADDR = BASE + PROMPT_BITMAP_FILE
PROMPT_CELLS = 14
PROMPT_FIELD_FILE = 0x1E756
PROMPT_FIELD_ADDR = BASE + PROMPT_FIELD_FILE
PROMPT_FIELD_WORDS = PROMPT_CELLS + 1
PROMPT_SCRATCH_FILE = PROMPT_BITMAP_FILE + PROMPT_CELLS * 32
PROMPT_SCRATCH_ADDR = BASE + PROMPT_SCRATCH_FILE

ORIGINAL_FIXED_DRAW = 0x06039534
FIXED_DRAW_POINTER = 0x19518
FONT16_POINTER = 0x0603DAF0
WARD_ROW = 0x0603E684
CITY_ROW = 0x0603E6C0

NAME_FW_CITY = FIELD_BY_KIND[NameField.CITY].runtime_address
NAME_FW_WARD = FIELD_BY_KIND[NameField.WARD].runtime_address

# Target indices are physical 10-byte records in the stock area-name table.
FIXED_TARGETS = (
    (1, "location_rinkai_park"),
    (2, "location_mount_kasagi"),
    (3, "location_yarai"),
    (4, "location_chuo"),
    (5, "location_hibarigaoka"),
)

SATURN_ROOT = TRANSLATION_ROOT
METRICS_PATH = TRANSLATION_ROOT / "font" / "generated" / "font16_metrics.json"
FONT16_PATH = SATURN_ROOT / "rom" / "build" / "FONT16.FON"
ASM_ROOT = Path(__file__).with_name("asm")


def load_font_metrics() -> tuple[bytes, dict[str, int]]:
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
            if len(text) == 1:
                codes.setdefault(text, code)
    return bytes(widths), codes


@cache
def static_asset():
    return load_static_asset(
        Path("static") / "MAP2D.BIN.static.json",
        TARGET.path,
    )


@cache
def runtime_metrics() -> tuple[bytes, dict[str, int]]:
    return load_font_metrics()


def asset_block(name: str, storage: str) -> bytes:
    try:
        block = static_asset().blocks[name]
    except KeyError as error:
        raise ValueError(f"MAP2D.BIN static text is missing block {name!r}") from error
    if block.storage != storage:
        raise ValueError(f"MAP2D.BIN block {name!r} is not {storage}")
    return static_asset().data[block.offset : block.offset + block.size]


def asset_ascii(name: str) -> str:
    data = asset_block(name, "bytes")
    if not data.endswith(b"\0") or b"\0" in data[:-1]:
        raise ValueError(f"MAP2D.BIN block {name!r} is not one ASCII string")
    return data[:-1].decode("ascii")


def require(data: bytes | bytearray, offset: int, expected: bytes, name: str) -> None:
    actual = bytes(data[offset : offset + len(expected)])
    if actual != expected:
        raise ValueError(
            f"MAP2D.BIN {name} mismatch at {offset:#x}: "
            f"expected {expected.hex(' ')}, found {actual.hex(' ')}"
        )


def encode_ascii(text: str) -> tuple[int, ...]:
    output = []
    for character in text:
        try:
            output.append(runtime_metrics()[1][character])
        except KeyError as error:
            raise ValueError(f"unsupported MAP2D character {character!r}") from error
    return tuple(output)


def name_scale_positions(source_width: int, count: int) -> tuple[int, ...]:
    """Reference the MAP2D runtime's overflow-only 64px X mapping."""
    if not 65 <= source_width <= SCALE_MAP_BYTES:
        raise ValueError(f"invalid MAP2D scaled source width {source_width}")
    if not 0 <= count <= SCALE_MAP_BYTES:
        raise ValueError(f"invalid MAP2D scale-map length {count}")
    screen_x = 0
    error = 0
    positions = []
    for _source_x in range(count):
        positions.append(screen_x)
        error += 64
        if error >= source_width:
            error -= source_width
            screen_x += 1
    return tuple(positions)


def render_bitmap_strip(font16: bytes, text: str, cell_count: int) -> bytes:
    """Compose proportional FONT16 glyphs into fixed 16x16 bitmap cells."""
    width = cell_count * 16
    rows = [0] * 16
    x = 0
    for code in encode_ascii(text):
        if code >= len(runtime_metrics()[0]) or not runtime_metrics()[0][code]:
            raise ValueError(f"MAP2D glyph {code} has no proportional width")
        start = code * 32
        cell = font16[start : start + 32]
        if len(cell) != 32:
            raise ValueError(f"{FONT16_PATH}: glyph {code} exceeds the font")
        for row in range(16):
            word = struct.unpack_from(">H", cell, row * 2)[0]
            for column in range(16):
                if not word & (1 << (15 - column)):
                    continue
                destination = x + column
                if destination >= width:
                    raise ValueError(
                        f"MAP2D text exceeds {width}px with visible ink: {text!r}"
                    )
                rows[row] |= 1 << (width - 1 - destination)
        x += runtime_metrics()[0][code]
    if x > width:
        raise ValueError(f"MAP2D text needs {x}px; limit is {width}px: {text!r}")

    output = bytearray()
    for cell_index in range(cell_count):
        shift = (cell_count - cell_index - 1) * 16
        for row in rows:
            output.extend(struct.pack(">H", row >> shift & 0xFFFF))
    return bytes(output)


def build_fixed_bitmaps(font16: bytes) -> bytes:
    return b"".join(
        render_bitmap_strip(font16, asset_ascii(name), 4)
        for _target_index, name in FIXED_TARGETS
    )


def build_prompt_wrapper() -> bytes:
    source = (ASM_ROOT / "prompt_wrapper.s").read_text(encoding="utf-8")
    blob = assemble(
        source,
        PROMPT_CAVE_ADDR,
        symbols={
            "PROMPT_FIELD": PROMPT_FIELD_ADDR,
            "ORIGINAL_DRAW": ORIGINAL_FIXED_DRAW,
            "SCRATCH": PROMPT_SCRATCH_ADDR,
            "FONT_PTR": FONT16_POINTER,
            "BITMAP": PROMPT_BITMAP_ADDR,
        },
    )
    if blob.warnings:
        raise ValueError(f"MAP2D prompt wrapper warnings: {blob.warnings}")
    return bytes(blob)


def build_name_compositor() -> bytes:
    fixed_cell_count = len(FIXED_TARGETS) * 4
    if FIXED_SCRATCH_CODE < CITY_SCRATCH_CODE + 4:
        raise ValueError("MAP2D fixed labels overlap the dynamic city scratch cells")
    fixed_end = FONT16_BASE + (FIXED_SCRATCH_CODE + fixed_cell_count) * 32
    if fixed_end > ITEMNAME_BASE:
        raise ValueError("MAP2D fixed-label scratch exceeds the FONT16/ITEMNAME gap")
    source = (ASM_ROOT / "name_compositor.s").read_text(encoding="utf-8")
    code = assemble(
        source,
        CAVE_ADDR,
        symbols={
            "WARD_CODE": WARD_SCRATCH_CODE,
            "CITY_CODE": CITY_SCRATCH_CODE,
            "CITY_ROW_ADDR": CITY_ROW,
            "FONT_BASE": FONT16_BASE,
            "TERM": 0x8000,
            "WIDTH_LIMIT": len(runtime_metrics()[0]),
            "NAME_WIDTH": 64,
            "SCALE_MAP": SCALE_MAP_ADDR,
            "FIXED_SRC": FIXED_BITMAP_ADDR,
            "FIXED_DST": FONT16_BASE + FIXED_SCRATCH_CODE * 32,
            "FIXED_LONGS": fixed_cell_count * 32 // 4,
        },
    )
    if code.warnings:
        raise ValueError(f"MAP2D name compositor warnings: {code.warnings}")
    if code.labels["widths"] != CAVE_ADDR + len(code):
        raise ValueError("MAP2D name compositor width-table boundary drifted")
    payload = bytearray(code)
    payload.extend(runtime_metrics()[0])
    payload.extend(bytes((-len(payload)) % 4))
    if CAVE_FILE + len(payload) > SCALE_MAP_FILE:
        raise ValueError("MAP2D name compositor overlaps its runtime scale map")
    return bytes(payload)


def build_map(original: bytes) -> bytes:
    if len(original) != 126600:
        raise ValueError("MAP2D.BIN has an unexpected size")
    font16 = FONT16_PATH.read_bytes()
    if len(font16) < 1872 * 32:
        raise ValueError(f"{FONT16_PATH}: FONT16 build is incomplete")
    data = bytearray(original)

    compositor = build_name_compositor()
    require(data, CAVE_FILE, bytes(len(compositor)), "name-compositor cave")
    require(data, SCALE_MAP_FILE, bytes(SCALE_MAP_BYTES), "name scale-map scratch")
    data[CAVE_FILE : CAVE_FILE + len(compositor)] = compositor

    fixed_bitmaps = build_fixed_bitmaps(font16)
    require(data, FIXED_BITMAP_FILE, bytes(len(fixed_bitmaps)), "fixed-label bitmaps")
    data[FIXED_BITMAP_FILE : FIXED_BITMAP_FILE + len(fixed_bitmaps)] = fixed_bitmaps

    prompt_wrapper = build_prompt_wrapper()
    require(data, PROMPT_CAVE_FILE, bytes(len(prompt_wrapper)), "prompt-wrapper cave")
    data[PROMPT_CAVE_FILE : PROMPT_CAVE_FILE + len(prompt_wrapper)] = prompt_wrapper
    prompt_bitmap = render_bitmap_strip(
        font16,
        asset_ascii("talk_prompt"),
        PROMPT_CELLS,
    )
    require(data, PROMPT_BITMAP_FILE, bytes(len(prompt_bitmap)), "prompt bitmap")
    require(data, PROMPT_SCRATCH_FILE, bytes(8), "prompt scratch")
    data[PROMPT_BITMAP_FILE : PROMPT_BITMAP_FILE + len(prompt_bitmap)] = prompt_bitmap

    require(
        data,
        FIXED_DRAW_POINTER,
        ORIGINAL_FIXED_DRAW.to_bytes(4, "big"),
        "fixed-draw pointer",
    )
    struct.pack_into(">I", data, FIXED_DRAW_POINTER, PROMPT_CAVE_ADDR)
    struct.pack_into(
        f">{PROMPT_FIELD_WORDS}H",
        data,
        PROMPT_FIELD_FILE,
        *range(PROMPT_CELLS),
        0x8000,
    )

    for offset, expected, replacement, name in (
        (0x1DB2C, 0x002029D0, NAME_FW_CITY, "city-name pointer"),
        (0x1DB30, 0x002029D8, NAME_FW_WARD, "ward-name pointer"),
        (0x10E5C, 0x060309E0, CAVE_ADDR, "name-copy pointer"),
    ):
        require(data, offset, expected.to_bytes(4, "big"), name)
        struct.pack_into(">I", data, offset, replacement)

    for bitmap_index, (target_index, _name) in enumerate(FIXED_TARGETS):
        code = FIXED_SCRATCH_CODE + bitmap_index * 4
        struct.pack_into(
            ">5H",
            data,
            0x1E684 + target_index * 10,
            code,
            code + 1,
            code + 2,
            code + 3,
            0x8000,
        )

    struct.pack_into(">5H", data, 0x1E6CA, 0x8000, 0, 0, 0, 0)
    require(data, 0x1ADBC, CITY_ROW.to_bytes(4, "big"), "district city-row pointer")
    require(data, 0x1AC28, bytes.fromhex("430b"), "district city draw")
    struct.pack_into(">H", data, 0x1AC28, 0x0009)
    require(data, 0x1AD96, bytes.fromhex("02a8"), "district ward origin")
    struct.pack_into(">H", data, 0x1AD96, 0x0228)

    for offset, expected in (
        (0x10D58, 0x7106),
        (0x10D5C, 0x2191),
        (0x10D62, 0x4A0B),
        (0x10D70, 0x7106),
        (0x10D74, 0x2191),
        (0x10D78, 0x4A0B),
    ):
        require(data, offset, expected.to_bytes(2, "big"), "stock name truncation")
        struct.pack_into(">H", data, offset, 0x0009)

    for offset, name in ((0x1E774, "label_yes"), (0x1E77C, "label_no")):
        block = asset_block(name, "u16be")
        data[offset : offset + len(block)] = block
        require(data, offset + len(block), bytes.fromhex("8000"), f"{name} terminator")

    return bytes(data)


def build_patch() -> PatchGroup:
    source_path = SATURN_ROOT / "rom" / "extracted" / TARGET.path
    return PatchGroup(
        "map_ui",
        TARGET,
        (
            DigestPatch(
                name="map_overlay",
                address=BASE,
                expected_sha256=ORIGINAL_SHA256,
                replacement=build_map(source_path.read_bytes()),
            ),
        ),
    )


def build_patch_groups(_context: EngineBuildContext) -> PatchGroup:
    return build_patch()
