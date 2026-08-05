"""Packed proportional text for NORMCOM's 42-word help/description loop."""

import struct
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from engine.script.sh2 import assemble_checked
from engine.script.text_render.font16_vwf import build_blitter_cave
from engine.script.text_render.font_metrics import font16_metrics, font16_width_layout

BASE = 0x06020000
TARGET = BinaryTarget("NORMCOM.BIN", Path("NORMCOM.BIN"), BASE)

FONT16_BASE = 0x0021A000
PATTERN_LUT = 0x0603E9D4
MASK_LUT = 0x0603E9F4

SCRATCH_FILE = 0x0800
SCRATCH_ADDR = BASE + SCRATCH_FILE
BLITTER_FILE = SCRATCH_FILE + 16
BLITTER_ADDR = BASE + BLITTER_FILE

DRAW_POINTER = 0x0602EB90
STOCK_DRAWER = 0x06027B80
CURSOR_INIT = 0x0602EACC
CURSOR_SCALE = 0x0602EAEA
CURSOR_NEWLINE = 0x0602EB28
CURSOR_ADVANCE = 0x0602EB34
ASM_ROOT = Path(__file__).with_name("asm")


def build_callback(
    address: int,
    blitter_address: int,
    width_table: int,
    width_limit: int,
) -> bytes:
    source = (ASM_ROOT / "draw_word.s").read_text(encoding="utf-8")
    return bytes(
        assemble_checked(
            source,
            address,
            {
                "SCRATCH_FB": SCRATCH_ADDR + 8,
                "SCRATCH_STRIDE": SCRATCH_ADDR + 4,
                "BLITTER": blitter_address,
                "WIDTHS": width_table,
                "WIDTH_LIMIT": width_limit,
                "PACKED_SPACE": 267,
            },
            context="NORMCOM help",
        )
    )


def instruction(source: str, address: int, length: int) -> bytes:
    blob = assemble_checked(source, address, {}, context="NORMCOM help")
    if len(blob) != length:
        raise ValueError(f"NORMCOM help patch at {address:#x} has wrong size")
    return bytes(blob)


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    metrics = font16_metrics(context.font_generated_root / "font16_metrics.json")
    width_limit, width_offset = font16_width_layout(metrics)
    width_table = FONT16_BASE + width_offset
    scratch = struct.pack(">IHHIBBH", FONT16_BASE, 0x0200, 0, 0x25E60000, 2, 0, 16)
    blitter = build_blitter_cave(
        BLITTER_ADDR,
        font16_pointer=SCRATCH_ADDR,
        text_right_margin=SCRATCH_ADDR + 4,
        framebuffer_pointer=SCRATCH_ADDR + 8,
        text_color=SCRATCH_ADDR + 12,
        text_line_height=SCRATCH_ADDR + 14,
        glyph_pattern_lut=PATTERN_LUT,
        glyph_mask_lut=MASK_LUT,
    )
    callback_file = (BLITTER_FILE + len(blitter) + 3) & ~3
    callback_address = BASE + callback_file
    callback = build_callback(
        callback_address,
        BLITTER_ADDR,
        width_table,
        width_limit,
    )
    return PatchGroup(
        capability="normcom_help",
        target=TARGET,
        patches=(
            BytePatch("scratch", SCRATCH_ADDR, bytes(len(scratch)), scratch),
            BytePatch("subpixel_blitter", BLITTER_ADDR, bytes(len(blitter)), blitter),
            BytePatch(
                "word_callback", callback_address, bytes(len(callback)), callback
            ),
            BytePatch(
                "draw_pointer",
                DRAW_POINTER,
                struct.pack(">I", STOCK_DRAWER),
                struct.pack(">I", callback_address),
            ),
            BytePatch(
                "cursor_init",
                CURSOR_INIT,
                bytes.fromhex("e901"),
                instruction("mov #18,r9", CURSOR_INIT, 2),
            ),
            BytePatch(
                "cursor_scale",
                CURSOR_SCALE,
                bytes.fromhex("e110"),
                instruction("mov #1,r1", CURSOR_SCALE, 2),
            ),
            BytePatch(
                "cursor_newline",
                CURSOR_NEWLINE,
                bytes.fromhex("0929"),
                instruction("mov #18,r9", CURSOR_NEWLINE, 2),
            ),
            BytePatch(
                "cursor_advance",
                CURSOR_ADVANCE,
                bytes.fromhex("61937101691c"),
                instruction("add r0,r9\nextu.w r9,r9\nnop", CURSOR_ADVANCE, 6),
            ),
        ),
    )
