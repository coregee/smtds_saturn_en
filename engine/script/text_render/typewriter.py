"""Two-visible-glyph pacing for the cloned EVENT/MSGR text VMs."""

import struct
from dataclasses import dataclass
from pathlib import Path

from engine.script.patching import BytePatch
from engine.script.text_render.font16_vwf import align_up
from tools.sh2asm import assemble

ASM_PATH = Path(__file__).with_name("asm") / "two_glyph_pacing.s"

# Ghidra's SH-2 disassembly shows that this is the stock phase-normalization
# block at the end of both cloned VMs.  The hook replaces the first six
# instructions, then resumes at the untouched loop test.
TAIL_NORMALIZE_ORIGINAL = bytes.fromhex("62819315612d31b08b029113")


@dataclass(frozen=True)
class TwoGlyphPacing:
    """One VM's wrappers, tail handler, and embedded visible-count byte."""

    payload: bytes
    update_entry: int
    blitter_entry: int
    tail_entry: int


def build_two_glyph_pacing(
    address: int,
    *,
    original_update: int,
    visible_blitter: int,
    tail_continue: int,
) -> TwoGlyphPacing:
    """Count actual blits and allow one extra visible glyph per VM update."""
    source = ASM_PATH.read_text(encoding="utf-8")
    probe = assemble(
        source,
        address,
        symbols={
            "ORIGINAL_UPDATE": original_update,
            "VISIBLE_BLITTER": visible_blitter,
            "VISIBLE_COUNT": address,
            "TAIL_CONTINUE": tail_continue,
        },
    )
    if probe.warnings:
        raise ValueError(f"two-glyph pacing probe warnings: {probe.warnings}")

    visible_count = align_up(address + len(probe), 4)
    code = assemble(
        source,
        address,
        symbols={
            "ORIGINAL_UPDATE": original_update,
            "VISIBLE_BLITTER": visible_blitter,
            "VISIBLE_COUNT": visible_count,
            "TAIL_CONTINUE": tail_continue,
        },
    )
    if code.warnings:
        raise ValueError(f"two-glyph pacing warnings: {code.warnings}")
    if len(code) != len(probe):
        raise ValueError("two-glyph pacing size changed after placing its state")

    payload = bytearray(code)
    payload.extend(bytes(visible_count - address - len(payload)))
    payload.append(0)
    return TwoGlyphPacing(
        payload=bytes(payload),
        update_entry=code.labels["two_glyph_update"],
        blitter_entry=code.labels["two_glyph_blit"],
        tail_entry=code.labels["two_glyph_tail"],
    )


def build_absolute_jump(site_address: int, target_address: int) -> bytes:
    """Build the reviewed 12-byte SH-2 absolute jump used by the tail hook."""
    literal_address = site_address + 8
    pc_base = (site_address + 4) & ~3
    if literal_address % 4 or literal_address - pc_base != 4:
        raise ValueError(f"jump site {site_address:#x} cannot hold its literal")
    return struct.pack(">4H", 0xD301, 0x432B, 0x0009, 0x0009) + struct.pack(
        ">I", target_address
    )


def tail_normalize_patch(
    name: str,
    address: int,
    target_address: int,
) -> BytePatch:
    """Run the visible budget after stock input and page-boundary handling."""
    return BytePatch(
        name=name,
        address=address,
        expected=TAIL_NORMALIZE_ORIGINAL,
        replacement=build_absolute_jump(address, target_address),
    )
