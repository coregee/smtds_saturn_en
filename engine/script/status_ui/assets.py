"""Pure bitmap rendering and verified asset reads for detailed status UI."""

import hashlib
import struct

from engine.script.patching import BinaryTarget
from engine.script.status_ui.model import FONT8_PATH, STOCK_FONT16_PATH
from engine.script.text_render.font8_metrics import font8_metrics
from project_paths import EXTRACTED_ROOT


def glyph_code(character: str) -> int:
    widths, codes = font8_metrics()
    try:
        code = codes[character]
    except KeyError as error:
        raise ValueError(f"unsupported status-label character {character!r}") from error
    if not widths[code]:
        raise ValueError(f"status-label glyph {code} has no width")
    return code


def status_atlas_tile(text: str, font: bytes) -> bytes:
    """Create one 12x12 4bpp tile using compressed FONT8 letter slots."""
    if len(text) > 3:
        raise ValueError(f"status atlas chunk exceeds three characters: {text!r}")
    pixels = [[0] * 12 for _ in range(12)]
    slot_width = 6 if len(text) <= 2 else 4
    for slot, character in enumerate(text):
        code = glyph_code(character)
        cell = font[code * 8 : (code + 1) * 8]
        if len(cell) != 8:
            raise ValueError(f"{FONT8_PATH}: glyph {code} exceeds the font")
        ink_columns = [x for row in cell for x in range(8) if row & (0x80 >> x)]
        if not ink_columns:
            continue
        left, right = min(ink_columns), max(ink_columns)
        source_width = right - left + 1
        target_width = min(slot_width - 1, source_width)
        x_origin = slot * slot_width + (slot_width - target_width) // 2
        for y, bits in enumerate(cell):
            for target_x in range(target_width):
                source_x = (
                    left
                    if target_width == 1
                    else (
                        left + round(target_x * (source_width - 1) / (target_width - 1))
                    )
                )
                if bits & (0x80 >> source_x):
                    pixels[y + 2][x_origin + target_x] = 2
    packed = bytearray()
    for row in pixels:
        for x in range(0, 12, 2):
            packed.append(row[x] << 4 | row[x + 1])
    return bytes(packed)


def status_mask(tile: bytes) -> bytes:
    if len(tile) != 0x48:
        raise ValueError("status atlas tile must be 0x48 bytes")
    rows = [0] * 16
    for y in range(12):
        for x in range(12):
            value = tile[y * 6 + x // 2]
            value = value >> 4 if x % 2 == 0 else value & 0x0F
            if value:
                rows[y + 2] |= 0x8000 >> (x + 2)
    return struct.pack(">16H", *rows)


def font8_pixels(text: str, font: bytes) -> tuple[list[tuple[int, int]], int]:
    widths, _ = font8_metrics()
    pixels = []
    x = 0
    for character in text:
        code = glyph_code(character)
        cell = font[code * 8 : (code + 1) * 8]
        for y, bits in enumerate(cell):
            for glyph_x in range(8):
                if bits & (0x80 >> glyph_x):
                    pixels.append((x + glyph_x, y))
        x += widths[code]
    return pixels, x


def direct_color_row(text: str, font: bytes, width: int = 48) -> bytes:
    height = 12
    pixels, advance = font8_pixels(text, font)
    if advance > width - 2:
        raise ValueError(f"status row exceeds {width - 2}px: {text!r}")
    image = [[0x0000] * width for _ in range(height)]
    # These pre-rendered labels sit beside values and above the independently
    # drawn spell list.  FONT8's visible seven rows fit exactly at y=4 with the
    # one-pixel shadow, aligning the labels without moving the spell-name path.
    x_origin, y_origin = 1, 4
    for x, y in pixels:
        if x_origin + x + 1 < width and y_origin + y + 1 < height:
            image[y_origin + y + 1][x_origin + x + 1] = 0x8000
    for x, y in pixels:
        if x_origin + x < width and y_origin + y < height:
            image[y_origin + y][x_origin + x] = 0xFFFF
    return b"".join(struct.pack(">H", value) for row in image for value in row)


def node_background(original: bytes, node_offset: int) -> list[int]:
    size = 16 * 16 * 2
    cell = original[node_offset : node_offset + size]
    image = [
        int.from_bytes(cell[position : position + 2], "big")
        for position in range(0, len(cell), 2)
    ]
    stock_font16 = STOCK_FONT16_PATH.read_bytes()
    glyph = stock_font16[0x143 * 32 : 0x144 * 32]
    if len(glyph) != 32:
        raise ValueError(f"{STOCK_FONT16_PATH}: missing status-node mask glyph")
    ink = set()
    for y in range(16):
        bits = int.from_bytes(glyph[y * 2 : y * 2 + 2], "big")
        for x in range(16):
            if bits & (0x8000 >> x):
                ink.add((x, y))
    mask = {
        (x + dx, y + dy)
        for x, y in ink
        for dx in range(-2, 3)
        for dy in range(-2, 3)
        if 1 < x + dx < 14 and 1 < y + dy < 14
    }
    known = {
        (x, y): image[y * 16 + x]
        for y in range(16)
        for x in range(16)
        if (x, y) not in mask
    }

    def components(value: int) -> tuple[int, int, int]:
        return value >> 10 & 31, value >> 5 & 31, value & 31

    while len(known) < 16 * 16:
        added = {}
        for y in range(16):
            for x in range(16):
                if (x, y) in known:
                    continue
                values = [
                    known[position]
                    for position in (
                        (x - 1, y),
                        (x + 1, y),
                        (x, y - 1),
                        (x, y + 1),
                    )
                    if position in known
                ]
                if values:
                    colors = [components(value) for value in values]
                    red, green, blue = (
                        round(sum(color[channel] for color in colors) / len(colors))
                        for channel in range(3)
                    )
                    added[x, y] = 0x8000 | red << 10 | green << 5 | blue
        if not added:
            raise ValueError("could not reconstruct the status-node background")
        known.update(added)
    return [known[x, y] for y in range(16) for x in range(16)]


def direct_color_node(text: str, font: bytes, background: list[int]) -> bytes:
    image = background.copy()
    tile = status_atlas_tile(text, font)
    for y in range(12):
        for x in range(12):
            value = tile[y * 6 + x // 2]
            value = value >> 4 if x % 2 == 0 else value & 0x0F
            if value:
                image[(y + 2) * 16 + x + 2] = 0xFFFF
    return b"".join(struct.pack(">H", value) for value in image)


def direct_color_assets(
    original: bytes,
    node_offset: int,
    font8: bytes,
    base_labels: tuple[str, ...],
    derived_rows: tuple[tuple[str, ...], ...],
) -> tuple[bytes, bytes]:
    background = node_background(original, node_offset)
    node_data = b"".join(
        direct_color_node(label, font8, background) for label in base_labels
    )
    row_data = b"".join(direct_color_row(" ".join(row), font8) for row in derived_rows)
    return node_data, row_data


def read_original(target: BinaryTarget, expected_sha256: str) -> bytes:
    source_path = EXTRACTED_ROOT / target.path
    original = source_path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if digest != expected_sha256:
        raise ValueError(
            f"{target.name}: expected SHA-256 {expected_sha256}, found {digest}"
        )
    return original


def read_font8() -> bytes:
    font8 = FONT8_PATH.read_bytes()
    if len(font8) != 256 * 8:
        raise ValueError(f"{FONT8_PATH}: expected a 256-cell FONT8 build")
    return font8
