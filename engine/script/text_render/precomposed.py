"""Build fixed-cell bitmap strips from proportional FONT16 glyphs."""

import struct
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PrecomposedStrip:
    codes: tuple[int, ...]
    width: int
    cells: int
    bitmap: bytes


def precompose_font16_strip(
    font16: bytes,
    codes: Sequence[int],
    widths: Sequence[int],
    cell_count: int,
    *,
    context: str,
) -> PrecomposedStrip:
    """Compose proportional glyphs into ``cell_count`` 16x16 records."""
    if (
        not isinstance(cell_count, int)
        or isinstance(cell_count, bool)
        or cell_count < 1
    ):
        raise ValueError(f"{context}: cell count must be positive")

    encoded = tuple(codes)
    pixel_limit = cell_count * 16
    rows = [0] * 16
    cursor = 0
    for code in encoded:
        if (
            not isinstance(code, int)
            or isinstance(code, bool)
            or code < 0
            or code >= len(widths)
            or not widths[code]
        ):
            raise ValueError(f"{context}: glyph {code!r} has no proportional width")
        start = code * 32
        glyph = font16[start : start + 32]
        if len(glyph) != 32:
            raise ValueError(f"{context}: glyph {code} exceeds FONT16")
        for row_index in range(16):
            word = struct.unpack_from(">H", glyph, row_index * 2)[0]
            for column in range(16):
                if not word & (1 << (15 - column)):
                    continue
                destination = cursor + column
                if destination >= pixel_limit:
                    raise ValueError(
                        f"{context}: visible ink exceeds {pixel_limit} pixels"
                    )
                rows[row_index] |= 1 << (pixel_limit - 1 - destination)
        cursor += widths[code]

    if cursor > pixel_limit:
        raise ValueError(
            f"{context}: text needs {cursor} pixels; limit is {pixel_limit}"
        )

    bitmap = bytearray()
    for cell_index in range(cell_count):
        shift = (cell_count - cell_index - 1) * 16
        for row in rows:
            bitmap.extend(struct.pack(">H", row >> shift & 0xFFFF))
    return PrecomposedStrip(encoded, cursor, cell_count, bytes(bitmap))
