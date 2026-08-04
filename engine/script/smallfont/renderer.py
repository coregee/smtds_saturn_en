"""Shared FONT8 drawer builders used by each small-font target."""

import struct
from collections.abc import Sequence
from pathlib import Path

from engine.script.sh2 import assemble_checked
from engine.script.smallfont.model import DrawerSpec, OverlaySpec
from engine.script.text_render.compact_names import pack_title_case_names

ASM_ROOT = Path(__file__).with_name("asm")


def build_character_panel_data(
    rows: Sequence[object],
    font8_data: tuple[bytes, dict[str, int]],
) -> tuple[bytes, bytes]:
    """Encode the six generated CHARNAME rows for NORMCOM party panels."""
    widths, codes = font8_data
    if len(rows) != 6:
        raise ValueError("NORMCOM character panel needs six character-name rows")
    offsets = bytearray()
    pool = bytearray()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("record") != index:
            raise ValueError(f"NORMCOM character panel row {index} is invalid")
        text = row.get("tr")
        if not isinstance(text, str) or not text:
            raise ValueError(f"NORMCOM character panel row {index} is untranslated")
        try:
            encoded = bytes(codes[character] for character in text)
        except KeyError as error:
            raise ValueError(
                f"NORMCOM character panel name {text!r} uses unsupported "
                f"FONT8 character {error.args[0]!r}"
            ) from error
        pixel_width = sum(widths[code] for code in encoded)
        if pixel_width > 80:
            raise ValueError(
                f"NORMCOM character panel name exceeds 80px ({pixel_width}px): {text!r}"
            )
        offsets.extend(struct.pack(">H", len(pool)))
        pool.extend(encoded)
        pool.append(0)
    return bytes(offsets), bytes(pool)


def build_normcom_demon_panel_data(
    rows: Sequence[object],
    built_names: bytes,
    font8_data: tuple[bytes, dict[str, int]],
) -> tuple[bytes, bytes, bytes]:
    """Pack long DVLNAME rows into low/high record pages."""
    widths, codes = font8_data
    if len(rows) != 319 or len(built_names) != 319 * 8:
        raise ValueError("NORMCOM COMP panel needs 319 built demon-name rows")
    packed: list[tuple[int, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("record") != index:
            raise ValueError(f"NORMCOM COMP panel row {index} is invalid")
        text = row.get("tr")
        if not isinstance(text, str) or not text:
            raise ValueError(f"NORMCOM COMP panel row {index} is untranslated")
        try:
            encoded = bytes(codes[character] for character in text)
        except KeyError as error:
            raise ValueError(
                f"NORMCOM COMP panel name {text!r} uses unsupported "
                f"FONT8 character {error.args[0]!r}"
            ) from error
        record = built_names[index * 8 : (index + 1) * 8]
        direct = len(encoded) <= 8 and sum(widths[code] for code in encoded) <= 64
        if direct:
            if record != encoded.ljust(8, b"\0"):
                raise ValueError(
                    f"NORMCOM COMP panel direct name {index} is stale in DVLNAME.DAT"
                )
        else:
            packed.append((index, text))
    low_bits, low_pool = pack_title_case_names(
        ((index, text) for index, text in packed if index < 0x100),
        record_count=0x100,
    )
    high_bits, high_pool = pack_title_case_names(
        ((index - 0x100, text) for index, text in packed if index >= 0x100),
        record_count=len(rows) - 0x100,
    )
    return low_bits + high_bits, low_pool, high_pool


def build_drawer(
    address: int,
    blitter_address: int,
    overlay: OverlaySpec,
    drawer: DrawerSpec,
    widths_address: int,
) -> bytes:
    setup = (
        "        mov r4,r8\n        mov r5,r9"
        if drawer.string_first
        else "        mov r5,r8\n        mov r4,r9"
    )
    template = (ASM_ROOT / "drawer.s").read_text(encoding="utf-8")
    source = template % {"setup": setup}
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "PIXEL": blitter_address,
                "ORIGINAL": overlay.stock_wrapper,
                "STRIDE": drawer.stride,
                "WIDTHS": widths_address,
            },
            context="small-font",
        )
    )


def build_packed_full_name_drawer(
    address: int,
    blitter_address: int,
    fallback_address: int,
    widths_address: int,
    stride: int,
    *,
    string_first: bool = False,
) -> bytes:
    template = (ASM_ROOT / "packed_full_name_drawer.s").read_text(encoding="utf-8")
    if string_first:
        setup = "    mov     r4, r0\n    mov     r5, r4\n    mov     r0, r5"
        fallback_setup = "    mov     r4, r0\n    mov     r5, r4\n    mov     r0, r5"
    else:
        setup = ""
        fallback_setup = ""
    source = template % {
        "setup": setup,
        "fallback_setup": fallback_setup,
    }
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "ITEM_FIRST": 0x00228C04,
                "ITEM_END": 0x0022F7A0,
                "ITEM_BASE": 0x00228C00,
                "MAGIC_FIRST": 0x0022F7A4,
                "MAGIC_END": 0x00235740,
                "MAGIC_BASE": 0x0022F7A0,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STRIDE": stride,
                "Y_OFFSET": 4 * (stride // 2),
                "FALLBACK": fallback_address,
            },
            context="small-font",
        )
    )


def build_character_panel_drawer(
    address: int,
    blitter_address: int,
    fallback_address: int,
    widths_address: int,
    offsets_address: int,
    pool_address: int,
) -> bytes:
    """Resolve fixed non-player CHARNAME records to full English strings."""
    source = (ASM_ROOT / "character_panel_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "CHAR_BASE": 0x0023FFD0,
                "CHAR_FIRST": 0x0023FFD8,
                "CHAR_END": 0x00240000,
                "OFFSETS": offsets_address,
                "POOL": pool_address,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STRIDE": 0x0200,
                "FALLBACK": fallback_address,
            },
            context="character party panel",
        )
    )


def build_combat_panel_drawer(
    address: int,
    blitter_address: int,
    fallback_address: int,
    widths_address: int,
    character_offsets_address: int,
    character_pool_address: int,
    demon_offsets_address: int,
    demon_pool_address: int,
) -> bytes:
    """Resolve direct COMBAT character and demon panel records."""
    source = (ASM_ROOT / "combat_panel_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "DVL_BASE": 0x0023F5D0,
                "DVL_END": 0x0023FFD0,
                "DVL_OFFSETS": demon_offsets_address,
                "DVL_POOL": demon_pool_address,
                "CHAR_BASE": 0x0023FFD0,
                "CHAR_FIRST": 0x0023FFD8,
                "CHAR_END": 0x00240000,
                "CHAR_OFFSETS": character_offsets_address,
                "CHAR_POOL": character_pool_address,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STRIDE": 0x0200,
                "FALLBACK": fallback_address,
            },
            context="COMBAT party panel",
        )
    )


def build_normcom_panel_drawer(
    address: int,
    blitter_address: int,
    fallback_address: int,
    widths_address: int,
    character_offsets_address: int,
    character_pool_address: int,
    long_name_bits_address: int,
    name_pool_address: int,
    high_name_pool_address: int,
) -> bytes:
    """Resolve complete character and demon names on the NORMCOM COMP panel."""
    source = (ASM_ROOT / "normcom_panel_drawer.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "DVL_BASE": 0x0023F5D0,
                "DVL_END": 0x0023FFD0,
                "CHAR_BASE": 0x0023FFD0,
                "CHAR_FIRST": 0x0023FFD8,
                "CHAR_END": 0x00240000,
                "CHAR_OFFSETS": character_offsets_address,
                "CHAR_POOL": character_pool_address,
                "LONG_NAME_BITS": long_name_bits_address,
                "NAME_POOL": name_pool_address,
                "HIGH_NAME_POOL": high_name_pool_address,
                "WIDTHS": widths_address,
                "PIXEL": blitter_address,
                "STRIDE": 0x0200,
                "FALLBACK": fallback_address,
            },
            context="NORMCOM COMP name panel",
        )
    )
