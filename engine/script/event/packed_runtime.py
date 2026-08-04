"""Pure stateful packed-text fetch builders shared by EVENT and MSGR."""

import struct
from pathlib import Path

from engine.script.text_render.packed_codec import bound_dictionary_table
from tools.sh2asm import assemble

ASM_ROOT = Path(__file__).with_name("asm")


def build_fetch_cave(
    cave_address: int,
    return_code: int,
    return_zero: int,
) -> bytes:
    """Expand two packed tokens, including corpus-trained dictionary entries."""
    if cave_address % 4:
        raise ValueError("packed fetch cave must be four-byte aligned")
    dictionary_table = bound_dictionary_table()
    source = (ASM_ROOT / "packed_fetch.s").read_text(encoding="utf-8")
    probe = assemble(
        source,
        cave_address,
        symbols={
            "RETURN_CODE": return_code,
            "RETURN_ZERO": return_zero,
            "DICTIONARY": cave_address,
            "STATE": cave_address,
        },
    )
    if probe.warnings:
        raise ValueError(f"packed fetch assembly warnings: {probe.warnings}")
    dictionary_address = (cave_address + len(probe) + 3) & ~3
    state_address = (dictionary_address + len(dictionary_table) + 3) & ~3
    code = assemble(
        source,
        cave_address,
        symbols={
            "RETURN_CODE": return_code,
            "RETURN_ZERO": return_zero,
            "DICTIONARY": dictionary_address,
            "STATE": state_address,
        },
    )
    if code.warnings:
        raise ValueError(f"packed fetch assembly warnings: {code.warnings}")
    payload = bytearray(code)
    payload.extend(bytes(dictionary_address - cave_address - len(payload)))
    payload.extend(dictionary_table)
    payload.extend(bytes(state_address - cave_address - len(payload)))
    payload.extend(bytes(16))
    return bytes(payload)


def build_site_patch(site_address: int, cave_address: int) -> bytes:
    literal_address = site_address + 8
    pc_base = (site_address + 4) & ~3
    if literal_address % 4 or literal_address - pc_base != 4:
        raise ValueError(f"fetch site {site_address:#x} cannot hold its literal")
    return struct.pack(">4H", 0xD301, 0x432B, 0x0009, 0x0009) + struct.pack(
        ">I", cave_address
    )
