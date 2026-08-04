"""Pure shared FONT16/FONT12 VWF cave builders."""

import struct


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


def encode_branches(items: list[int | tuple]) -> list[int]:
    """Resolve the short branch labels used by the two fixed caves."""
    labels = {}
    position = 0
    for item in items:
        if isinstance(item, tuple) and item[0] == "label":
            labels[item[1]] = position
        else:
            position += 2

    words = []
    position = 0
    for item in items:
        if isinstance(item, tuple) and item[0] == "label":
            continue
        if isinstance(item, tuple):
            operation, target = item
            displacement = (labels[target] - (position + 4)) // 2
            short_opcode = {
                "bt": 0x8900,
                "bf": 0x8B00,
                "bts": 0x8D00,
                "bfs": 0x8F00,
            }.get(operation)
            if short_opcode is not None:
                if not -128 <= displacement <= 127:
                    raise ValueError(f"{operation} to {target} is out of range")
                words.append(short_opcode | (displacement & 0xFF))
            else:
                if operation != "bra" or not -2048 <= displacement <= 2047:
                    raise ValueError(f"{operation} to {target} is out of range")
                words.append(0xA000 | (displacement & 0xFFF))
        else:
            words.append(item)
        position += 2
    return words


def resolve_literals(
    items: list[int | tuple],
    cave_address: int,
    literal_order: tuple[str, ...],
) -> tuple[list[int | tuple], int]:
    """Replace PC-relative literal markers and return their pool offset."""
    instruction_count = sum(
        1 for item in items if not (isinstance(item, tuple) and item[0] == "label")
    )
    if instruction_count % 2:
        items.append(0x0009)
        instruction_count += 1

    literal_offset = instruction_count * 2
    position = 0
    for index, item in enumerate(items):
        if isinstance(item, tuple) and item[0] == "label":
            continue
        if isinstance(item, tuple) and item[0] == "literal":
            _marker, name, register = item
            literal_address = (
                cave_address + literal_offset + literal_order.index(name) * 4
            )
            pc_base = (cave_address + position + 4) & ~3
            displacement = (literal_address - pc_base) // 4
            if not 0 <= displacement <= 0xFF:
                raise ValueError(f"literal {name} is out of range")
            items[index] = 0xD000 | (register << 8) | displacement
        position += 2
    return items, literal_offset


def build_advance_cave(
    cave_address: int,
    *,
    text_advance: int,
    text_cursor_x: int,
    text_right_margin: int,
    font16_pointer: int,
    stock_advance: int,
    width_table_code_limit: int,
    font_mode_flag: int,
    font12_signature_offset: int,
    font12_signature_value: int,
    font16_width_table_offset: int,
    font12_widths: bytes,
) -> bytes:
    """Advance Latin by its width, call stock wrapping, then restore globals."""
    code: list[int | tuple] = [
        0x4F22,  # sts.l pr,@-r15
        0x2F56,  # mov.l r5,@-r15
        ("literal", "scratch", 2),  # r2 = private scratch words
        ("literal", "advance", 1),
        0x6011,  # r0 = pristine advance
        0x2201,  # save pristine advance
        ("literal", "margin", 1),
        0x6011,  # r0 = pristine right margin
        0x8121,  # save pristine margin
        0x634D,  # r3 = unsigned glyph code
        ("literal", "code_limit", 1),
        0x3312,  # cmp/hs r1,r3
        ("bt", "japanese"),
        ("literal", "font_mode", 1),
        0x6011,
        0x8801,
        ("bt", "font12"),
        ("literal", "font16", 1),
        0x6112,  # r1 = FONT16 buffer
        ("literal", "font_signature_offset", 5),
        0x315C,
        0x6010,  # inspect a known FONT12 glyph byte
        0x600C,
        0x8800 | font12_signature_value,
        ("bt", "font12"),
        0x6033,
        ("literal", "font16", 1),
        0x6112,
        ("literal", "width_offset", 5),
        0x315C,
        0x6033,
        0x001C,  # r0 = width_table[index]
        0x630C,  # r3 = configured glyph width
        0x2338,  # zero means use stock behaviour
        ("bt", "japanese"),
        ("bra", "width_ready"),
        0x0009,
        ("label", "font12"),
        0x634D,
        ("literal", "font12_limit", 1),
        0x3312,
        ("bt", "japanese"),
        ("literal", "font12_widths", 1),
        0x6033,
        0x001C,
        0x630C,
        0x2338,
        ("bt", "japanese"),
        ("label", "width_ready"),
        0x8521,  # r0 = pristine margin
        0x3038,  # margin -= current width
        0x7001,  # retain one pixel at right edge
        ("bra", "set_margin"),
        0x0009,
        ("label", "japanese"),
        0x8520,  # Japanese uses pristine advance
        0x6303,
        0x8521,  # Japanese uses pristine margin
        ("label", "set_margin"),
        ("literal", "margin", 1),
        0x2101,  # install temporary margin
        ("literal", "cursor_x", 1),
        0x6011,
        0x4011,  # cmp/pz cursor_x
        ("bts", "advance_ready"),
        0x8522,  # delay: previous glyph width
        0x6011,  # new line starts at -advance
        0x600B,  # negate to land at zero
        ("label", "advance_ready"),
        ("literal", "advance", 1),
        0x2101,  # install temporary advance
        0x6033,
        0x8122,  # remember current width for next glyph
        ("literal", "stock_advance", 1),
        0x410B,  # jsr stock text_advance_and_wrap
        0x0009,
        ("literal", "cursor_x", 1),
        0x6011,
        0x2008,  # wrapped/new line if X == 0
        ("bf", "cursor_ready"),
        0xE004,
        0x2101,  # four-pixel dialogue inset
        ("label", "cursor_ready"),
        ("literal", "scratch", 2),
        ("literal", "advance", 1),
        0x8520,
        0x2101,  # restore pristine advance
        ("literal", "margin", 1),
        0x8521,
        0x2101,  # restore pristine margin
        0x65F6,
        0x4F26,
        0x000B,
        0x0009,
    ]
    order = (
        "scratch",
        "advance",
        "margin",
        "code_limit",
        "font_mode",
        "font16",
        "font_signature_offset",
        "width_offset",
        "font12_limit",
        "font12_widths",
        "cursor_x",
        "stock_advance",
    )
    code, literal_offset = resolve_literals(code, cave_address, order)
    words = encode_branches(code)
    blob = struct.pack(f">{len(words)}H", *words)
    if len(blob) != literal_offset:
        raise ValueError("advance cave literal pool is misaligned")

    scratch_address = cave_address + literal_offset + len(order) * 4
    font12_widths_address = align_up(scratch_address + 6, 4)
    literals = {
        "scratch": scratch_address,
        "advance": text_advance,
        "margin": text_right_margin,
        "code_limit": width_table_code_limit,
        "font_mode": font_mode_flag,
        "font16": font16_pointer,
        "font_signature_offset": font12_signature_offset,
        "width_offset": font16_width_table_offset,
        "font12_limit": len(font12_widths),
        "font12_widths": font12_widths_address,
        "cursor_x": text_cursor_x,
        "stock_advance": stock_advance,
    }
    blob += b"".join(struct.pack(">I", literals[name]) for name in order)
    blob += struct.pack(">3H", 16, 0, 16)
    blob += b"\x00" * ((4 - len(blob) % 4) % 4)
    if cave_address + len(blob) != font12_widths_address:
        raise ValueError("FONT12 advance table address drifted")
    blob += font12_widths
    return blob


def build_blitter_cave(
    cave_address: int,
    *,
    font16_pointer: int,
    text_right_margin: int,
    framebuffer_pointer: int,
    text_color: int,
    text_line_height: int,
    glyph_pattern_lut: int,
    glyph_mask_lut: int,
) -> bytes:
    """Merge a 16-pixel glyph at an arbitrary pixel-aligned X coordinate."""
    code: list[int | tuple] = [
        0x2F86,
        0x2F96,
        0x2FA6,
        0x2FB6,
        0x2FC6,
        0x2FD6,
        0x2FE6,
        ("literal", "font16", 1),
        0x6812,  # r8 = FONT16 buffer
        0x644D,
        0x4408,
        0x4408,
        0x4400,  # glyph code * 32
        0x384C,  # r8 = glyph bitmap
        ("literal", "margin", 1),
        0x6911,
        0x699D,  # r9 = framebuffer stride
        ("literal", "framebuffer", 1),
        0x6A12,  # r10 = framebuffer base
        ("literal", "color", 1),
        0x6B10,
        0x6BBC,  # r11 = text color
        ("literal", "line_height", 1),
        0x6C11,
        0x6CCD,
        0x7CFF,  # r12 = line height - 1
        0x655D,
        0x666D,
        0xED00,  # r13 = row
        ("label", "row_loop"),
        0x6163,
        0x31DC,
        0x611D,
        0x219E,
        0x021A,  # (y + row) * stride
        0x6353,
        0x332C,  # pixel index = x + row offset
        0x6184,
        0x611C,
        0x4118,
        0x6284,
        0x622C,
        0x212B,  # r1 = 16-bit glyph row
        0x6033,
        0xC903,
        0xE704,
        0x3708,  # shift = 4 - (pixel & 3)
        ("label", "shift_main"),
        0x4100,
        0x4710,
        ("bf", "shift_main"),
        0x6233,
        0x4209,
        0x322C,
        0x32AC,
        0xE705,  # five destination words
        ("label", "column_main"),
        0x6013,
        0x4019,
        0x4019,
        0xC90F,
        0x2008,
        ("bts", "next_main"),
        0x300C,
        ("literal", "pattern_lut", 4),
        0x044D,
        0x2B4E,
        ("literal", "mask_lut", 14),
        0x0EED,
        0x6021,
        0x20E9,
        0x0E1A,
        0x30EC,
        0x2201,
        ("label", "next_main"),
        0x4108,
        0x4108,
        0x7202,
        0x4710,
        ("bf", "column_main"),
        0x3DC0,  # skip shadow on final row
        ("bt", "no_shadow"),
        0x6233,
        0x329C,
        0x7201,  # shadow at down-right pixel
        0x6183,
        0x71FE,
        0x6E14,
        0x6EEC,
        0x4E18,
        0x6110,
        0x611C,
        0x2E1B,
        0x6023,
        0xC903,
        0xE704,
        0x3708,
        ("label", "shift_shadow"),
        0x4E00,
        0x4710,
        ("bf", "shift_shadow"),
        0x6123,
        0x4109,
        0x311C,
        0x31AC,
        0xE705,
        ("label", "column_shadow"),
        0x60E3,
        0x4019,
        0x4019,
        0xC90F,
        0x2008,
        ("bts", "next_shadow"),
        0x300C,
        ("literal", "pattern_lut", 4),
        0x044D,
        0x6011,
        0x304C,
        0x2101,
        ("label", "next_shadow"),
        0x4E08,
        0x4E08,
        0x7102,
        0x4710,
        ("bf", "column_shadow"),
        ("label", "no_shadow"),
        0x7D01,
        0xE110,
        0x3D10,
        ("bf", "row_loop"),
        0x6EF6,
        0x6DF6,
        0x6CF6,
        0x6BF6,
        0x6AF6,
        0x69F6,
        0x000B,
        0x68F6,
    ]
    order = (
        "font16",
        "margin",
        "framebuffer",
        "color",
        "line_height",
        "pattern_lut",
        "mask_lut",
    )
    code, literal_offset = resolve_literals(code, cave_address, order)
    words = encode_branches(code)
    blob = struct.pack(f">{len(words)}H", *words)
    if len(blob) != literal_offset:
        raise ValueError("blitter cave literal pool is misaligned")

    literals = {
        "font16": font16_pointer,
        "margin": text_right_margin,
        "framebuffer": framebuffer_pointer,
        "color": text_color,
        "line_height": text_line_height,
        "pattern_lut": glyph_pattern_lut,
        "mask_lut": glyph_mask_lut,
    }
    return blob + b"".join(struct.pack(">I", literals[name]) for name in order)


def build_surface_blitter_cave(
    cave_address: int,
    *,
    font16_pointer: int,
    glyph_pattern_lut: int,
    glyph_mask_lut: int,
    draw_shadow: bool = False,
    stacked_shadow_color: bool = False,
) -> bytes:
    """Merge a glyph at an arbitrary pixel X using the stock surface ABI.

    The stock surface drawer receives ``base, stride, x, y`` in r4-r7 and
    ``glyph, color`` on the stack.  Unlike the stock implementation, this
    uses the EVENT text VM's four-pixel-word shift-and-merge algorithm, so
    proportional advances are not rounded to the destination word boundary.
    Most surface consumers draw only the foreground.  Consumers whose stock
    contract includes a down-right color-1 shadow can request the EVENT
    blitter's matching shadow pass with ``draw_shadow=True``.  Those callers
    normally use the EVENT VM's fixed palette-index-1 shadow.  Surface ABIs
    that provide a third stacked ``shadow_color`` argument can instead set
    ``stacked_shadow_color=True``.
    """
    if stacked_shadow_color and not draw_shadow:
        raise ValueError("stacked shadow color requires draw_shadow")
    code: list[int | tuple] = [
        0x2F86,
        0x2F96,
        0x2FA6,
        0x2FB6,
        0x2FC6,
        0x2FD6,
        0x2FE6,
        0x6A43,  # r10 = framebuffer base
        0x6953,  # r9 = framebuffer stride in pixels
        0x6563,  # r5 = x
        0x6673,  # r6 = y
        ("literal", "font16", 1),
        0x6812,  # r8 = FONT16/FONT12 buffer
        0x51F7,  # r1 = stacked glyph code
        0x641D,
        0x4408,
        0x4408,
        0x4400,  # glyph code * 32
        0x384C,  # r8 = glyph bitmap
        0x5BF8,  # r11 = stacked color
        0x6BBC,
        *(
            [0x5CF9, 0x6CCC]  # r12 = stacked shadow color
            if stacked_shadow_color
            else []
        ),
        0xED00,  # r13 = row
        ("label", "row_loop"),
        0x6163,
        0x31DC,
        0x611D,
        0x219E,
        0x021A,  # (y + row) * stride
        0x6353,
        0x332C,  # pixel index = x + row offset
        0x6184,
        0x611C,
        0x4118,
        0x6284,
        0x622C,
        0x212B,  # r1 = 16-bit glyph row
        0x6033,
        0xC903,
        0xE704,
        0x3708,  # shift = 4 - (pixel & 3)
        ("label", "shift_main"),
        0x4100,
        0x4710,
        ("bf", "shift_main"),
        0x6233,
        0x4209,
        0x322C,
        0x32AC,
        0xE705,  # five destination words
        ("label", "column_main"),
        0x6013,
        0x4019,
        0x4019,
        0xC90F,
        0x2008,
        ("bts", "next_main"),
        0x300C,
        ("literal", "pattern_lut", 4),
        0x044D,
        0x2B4E,
        ("literal", "mask_lut", 14),
        0x0EED,
        0x6021,
        0x20E9,
        0x0E1A,
        0x30EC,
        0x2201,
        ("label", "next_main"),
        0x4108,
        0x4108,
        0x7202,
        0x4710,
        ("bf", "column_main"),
    ]
    if draw_shadow:
        code.extend(
            [
                0xE10F,
                0x3D10,  # skip shadow below final row
                ("bt", "no_shadow"),
                0x6233,
                0x329C,
                0x7201,  # shadow at down-right pixel
                0x6183,
                0x71FE,
                0x6E14,
                0x6EEC,
                0x4E18,
                0x6110,
                0x611C,
                0x2E1B,
                0x6023,
                0xC903,
                0xE704,
                0x3708,
                ("label", "shift_shadow"),
                0x4E00,
                0x4710,
                ("bf", "shift_shadow"),
                0x6123,
                0x4109,
                0x311C,
                0x31AC,
                0xE705,
                ("label", "column_shadow"),
                0x60E3,
                0x4019,
                0x4019,
                0xC90F,
                0x2008,
                ("bts", "next_shadow"),
                0x300C,
                ("literal", "pattern_lut", 4),
                0x044D,
                0x6011,
                0x304C,
                0x2101,
                ("label", "next_shadow"),
                0x4E08,
                0x4E08,
                0x7102,
                0x4710,
                ("bf", "column_shadow"),
                ("label", "no_shadow"),
            ]
        )
        if stacked_shadow_color:
            shadow_pattern = code.index(0x044D, code.index(("label", "column_shadow")))
            code[shadow_pattern + 1 : shadow_pattern + 1] = [
                0x2C4E,  # scale mask by stacked shadow color
                0x041A,
            ]
    code.extend(
        [
            0x7D01,
            0xE110,
            0x3D10,
            ("bf", "row_loop"),
            0x6EF6,
            0x6DF6,
            0x6CF6,
            0x6BF6,
            0x6AF6,
            0x69F6,
            0x000B,
            0x68F6,
        ]
    )
    order = ("font16", "pattern_lut", "mask_lut")
    code, literal_offset = resolve_literals(code, cave_address, order)
    words = encode_branches(code)
    blob = struct.pack(f">{len(words)}H", *words)
    if len(blob) != literal_offset:
        raise ValueError("surface blitter cave literal pool is misaligned")

    literals = {
        "font16": font16_pointer,
        "pattern_lut": glyph_pattern_lut,
        "mask_lut": glyph_mask_lut,
    }
    return blob + b"".join(struct.pack(">I", literals[name]) for name in order)


def build_width_returning_surface_cave(
    cave_address: int,
    *,
    blitter_address: int,
    font16_pointer: int,
    width_table_code_limit: int,
    font16_width_table_offset: int,
    max_width: int,
) -> bytes:
    """Adapt a stock FONT16 surface call to the shared subpixel blitter.

    The incoming ABI is ``base, stride, x, glyph`` in r4-r7 with ``color`` on
    the stack.  The adapter supplies ``y=0`` and stacked ``glyph, color`` to
    :func:`build_surface_blitter_cave`, clips at ``max_width``, and returns the
    configured glyph advance in r0.
    """
    code: list[int | tuple] = [
        0x60F2,  # capture stacked color
        0x2F86,
        0x2F96,
        0x2FA6,
        0x2FB6,
        0x4F22,
        0x6803,  # r8 = color
        0x6963,  # r9 = x
        0x6A73,  # r10 = glyph
        0x60A3,
        ("literal", "code_limit", 1),
        0x3012,
        ("bt", "fixed_width"),
        ("literal", "font16", 1),
        0x6112,
        ("literal", "width_offset", 2),
        0x312C,
        0x0B1C,
        0x6BBC,
        0x2BB8,
        ("bf", "width_ready"),
        ("label", "fixed_width"),
        0xEB10,
        ("label", "width_ready"),
        0x6093,
        0x30BC,
        ("literal", "max_width", 1),
        0x3016,
        ("bt", "done"),
        0x2F86,  # stack color
        0x2FA6,  # stack glyph
        0xE700,  # y = 0
        ("literal", "blitter", 0),
        0x400B,
        0x0009,
        0x7F08,
        ("label", "done"),
        0x60B3,  # return width
        0x4F26,
        0x6BF6,
        0x6AF6,
        0x69F6,
        0x000B,
        0x68F6,
    ]
    order = (
        "code_limit",
        "font16",
        "width_offset",
        "max_width",
        "blitter",
    )
    code, literal_offset = resolve_literals(code, cave_address, order)
    words = encode_branches(code)
    blob = struct.pack(f">{len(words)}H", *words)
    if len(blob) != literal_offset:
        raise ValueError("surface adapter literal pool is misaligned")

    literals = {
        "code_limit": width_table_code_limit,
        "font16": font16_pointer,
        "width_offset": font16_width_table_offset,
        "max_width": max_width,
        "blitter": blitter_address,
    }
    return blob + b"".join(struct.pack(">I", literals[name]) for name in order)


def compact_width_tables(
    glyphs: list[dict],
) -> tuple[bytes, int, bytes]:
    """Split sparse atlas widths around their largest unused code gap."""
    glyphs = sorted(glyphs, key=lambda glyph: glyph["code"])
    if not glyphs:
        raise ValueError("FONT16 menu widths are empty")

    gaps = [
        (right["code"] - left["code"] - 1, index)
        for index, (left, right) in enumerate(zip(glyphs, glyphs[1:]), 1)
    ]
    gap_size, split = max(gaps)
    if gap_size <= 0:
        raise ValueError("FONT16 menu widths need a gap for compact storage")

    low_glyphs = glyphs[:split]
    high_glyphs = glyphs[split:]
    low_table = bytearray(low_glyphs[-1]["code"] + 1)
    high_start = high_glyphs[0]["code"]
    high_table = bytearray(high_glyphs[-1]["code"] - high_start + 1)
    for glyph in low_glyphs:
        low_table[glyph["code"]] = glyph["advance"]
    for glyph in high_glyphs:
        high_table[glyph["code"] - high_start] = glyph["advance"]
    if len(low_table) > 0x7F or len(high_table) > 0x7F:
        raise ValueError("compact FONT16 width ranges exceed SH-2 immediates")
    return bytes(low_table), high_start, bytes(high_table)


def build_menu_cave(
    cave_address: int,
    blitter_address: int,
    *,
    font16_pointer: int,
    font12_signature_offset: int,
    font12_signature_value: int,
    font12_widths: bytes,
    font16_glyphs: list[dict],
) -> bytes:
    """Draw a raw FONT16/FONT12 glyph and return its configured advance."""
    low_table, high_start, high_table = compact_width_tables(font16_glyphs)
    code: list[int | tuple] = [
        0x4F22,  # save return address
        0x2F46,  # save glyph code
        ("literal", "blitter", 1),
        0x410B,  # draw through the subpixel blitter
        0x0009,
        0x63F6,  # restore glyph code into r3
        ("literal", "font16", 1),
        0x6112,
        ("literal", "font_signature_offset", 2),
        0x312C,
        0x6010,
        0x600C,
        0x8800 | font12_signature_value,
        ("bf", "font16_lookup"),
        0x633D,
        ("literal", "font12_limit", 1),
        0x3312,
        ("bt", "stock"),
        ("literal", "font12_table", 1),
        0x6033,
        0x001C,
        0x600C,
        0x2008,
        ("bf", "return"),
        ("bra", "stock"),
        0x0009,
        ("label", "font16_lookup"),
        0x633D,
        0xE100 | len(low_table),  # codes below this use the low table
        0x3312,
        ("bf", "low"),
        ("literal", "high_start", 1),
        0x3312,
        ("bf", "stock"),
        0x6033,
        0x3018,  # high-table index = code - high_start
        0xE100 | len(high_table),
        0x3012,
        ("bt", "stock"),
        ("literal", "high_table", 1),
        ("bra", "lookup"),
        0x0009,
        ("label", "low"),
        0x6033,
        ("literal", "low_table", 1),
        ("label", "lookup"),
        0x001C,
        0x600C,
        0x2008,
        ("bf", "return"),
        ("label", "stock"),
        0xE010,  # unmapped glyphs remain 16px
        ("label", "return"),
        0x4F26,
        0x000B,
        0x0009,
    ]
    order = (
        "blitter",
        "font16",
        "font_signature_offset",
        "font12_limit",
        "font12_table",
        "high_start",
        "high_table",
        "low_table",
    )
    code, literal_offset = resolve_literals(code, cave_address, order)
    words = encode_branches(code)
    blob = struct.pack(f">{len(words)}H", *words)
    if len(blob) != literal_offset:
        raise ValueError("menu cave literal pool is misaligned")

    table_address = cave_address + literal_offset + len(order) * 4
    font12_table_address = table_address + len(high_table) + len(low_table)
    literals = {
        "blitter": blitter_address,
        "font16": font16_pointer,
        "font_signature_offset": font12_signature_offset,
        "font12_limit": len(font12_widths),
        "font12_table": font12_table_address,
        "high_start": high_start,
        "high_table": table_address,
        "low_table": table_address + len(high_table),
    }
    blob += b"".join(struct.pack(">I", literals[name]) for name in order)
    blob += high_table + low_table + font12_widths
    blob += bytes((-len(blob)) % 4)
    return blob
