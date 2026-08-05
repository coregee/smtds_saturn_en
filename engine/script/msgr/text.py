"""Packed text and proportional rendering for the MSGR.COF overlay."""

import struct

from engine.script.context import EngineBuildContext
from engine.script.event.packed_runtime import build_fetch_cave, build_site_patch
from engine.script.msgr.model import MSGR_TARGET
from engine.script.patching import BytePatch, PatchGroup
from engine.script.text_render.font16_vwf import (
    align_up,
    build_advance_cave,
    build_blitter_cave,
    build_menu_cave,
)
from engine.script.text_render.font_metrics import (
    font12_dialogue_widths,
    font12_signature,
    font16_metrics,
    font16_width_layout,
)
from engine.script.text_render.packed_codec import bound_dictionary_table
from engine.script.text_render.typewriter import (
    build_two_glyph_pacing,
    tail_normalize_patch,
)

CAVE_ADDRESS = 0x06060400
# The high end of the verified zero window is reserved for the dynamic
# character/demon/race insertion adapters in ``engine.script.msgr.inserts``.
CAVE_WINDOW_END = 0x06065000

TYPEWRITER_UPDATE = 0x0606EBE4
TYPEWRITER_GATE_SITE = 0x0606EBFC
TYPEWRITER_UPDATE_POINTER_SITES = (
    0x0606BEAC,
    0x0606BF78,
)
TYPEWRITER_TAIL_SITE = 0x0606EC8C
TYPEWRITER_TAIL_CONTINUE = 0x0606EC9C
FETCH_SITE_1 = 0x0606EC14
FETCH_SITE_2 = 0x0606EC2C
RETURN_ZERO = 0x0606EC20
RETURN_CODE = 0x0606EC38
FETCH_SITE_1_ORIGINAL = bytes.fromhex("61a26215292122288f0c2a12")
FETCH_SITE_2_ORIGINAL = bytes.fromhex("61a26215292122288df72a12")

ADVANCE_POINTER = 0x0606ED48
ORIGINAL_ADVANCE = 0x0606EEB0
BLITTER_POINTER = 0x0606ED68
ORIGINAL_BLITTER = 0x0606ED6C
MENU_ADVANCE_SITE = 0x0606C75A
MENU_BLITTER_POINTER = 0x0606C7A8

TEXT_ADVANCE = 0x06079594
TEXT_CURSOR_X = 0x06079AA8
TEXT_RIGHT_MARGIN = 0x06079AA4
FONT16_POINTER = 0x06075E88
FRAMEBUFFER_POINTER = 0x06079568
TEXT_COLOR = 0x0607A8C4
TEXT_LINE_HEIGHT = 0x06079598
GLYPH_PATTERN_LUT = 0x0606EAA0
GLYPH_MASK_LUT = 0x0606EAC0
FONT_MODE_FLAG = 0x060217FC


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    metrics = font16_metrics(context.font_generated_root / "font16_metrics.json")
    code_limit, width_offset = font16_width_layout(metrics)
    font12_widths = font12_dialogue_widths(
        context.font_generated_root / "font12_metrics.json"
    )
    signature_offset, signature_value = font12_signature(
        context.build_root / "FONT12.FON",
        context.build_root / "FONT16.FON",
    )
    advance = build_advance_cave(
        CAVE_ADDRESS,
        text_advance=TEXT_ADVANCE,
        text_cursor_x=TEXT_CURSOR_X,
        text_right_margin=TEXT_RIGHT_MARGIN,
        font16_pointer=FONT16_POINTER,
        stock_advance=ORIGINAL_ADVANCE,
        width_table_code_limit=code_limit,
        font_mode_flag=FONT_MODE_FLAG,
        font12_signature_offset=signature_offset,
        font12_signature_value=signature_value,
        font16_width_table_offset=width_offset,
        font12_widths=font12_widths,
    )
    fetch_address = align_up(CAVE_ADDRESS + len(advance), 4)
    dictionary_table = bound_dictionary_table(
        context.text_generated_root / "event_codec.json",
        context.text_generated_root / "event_codec_binding.json",
        context.build_root,
    )
    fetch = build_fetch_cave(
        fetch_address,
        RETURN_CODE,
        RETURN_ZERO,
        dictionary_table,
    )
    blitter_address = align_up(fetch_address + len(fetch), 8)
    blitter = build_blitter_cave(
        blitter_address,
        font16_pointer=FONT16_POINTER,
        text_right_margin=TEXT_RIGHT_MARGIN,
        framebuffer_pointer=FRAMEBUFFER_POINTER,
        text_color=TEXT_COLOR,
        text_line_height=TEXT_LINE_HEIGHT,
        glyph_pattern_lut=GLYPH_PATTERN_LUT,
        glyph_mask_lut=GLYPH_MASK_LUT,
    )
    menu_address = align_up(blitter_address + len(blitter), 4)
    menu = build_menu_cave(
        menu_address,
        blitter_address,
        font16_pointer=FONT16_POINTER,
        font12_signature_offset=signature_offset,
        font12_signature_value=signature_value,
        font12_widths=font12_widths,
        font16_glyphs=metrics["glyphs"],
    )
    typewriter_address = align_up(menu_address + len(menu), 4)
    typewriter = build_two_glyph_pacing(
        typewriter_address,
        original_update=TYPEWRITER_UPDATE,
        visible_blitter=blitter_address,
        tail_continue=TYPEWRITER_TAIL_CONTINUE,
    )
    if typewriter_address + len(typewriter.payload) > CAVE_WINDOW_END:
        raise ValueError("MSGR text caves exceed the verified free window")

    return PatchGroup(
        capability="msgr_text",
        target=MSGR_TARGET,
        patches=(
            BytePatch(
                name="dialogue_two_glyph_pacing_cave",
                address=typewriter_address,
                expected=bytes(len(typewriter.payload)),
                replacement=typewriter.payload,
            ),
            *(
                BytePatch(
                    name=f"dialogue_update_pointer_{address:08x}",
                    address=address,
                    expected=struct.pack(">I", TYPEWRITER_UPDATE),
                    replacement=struct.pack(">I", typewriter.update_entry),
                )
                for address in TYPEWRITER_UPDATE_POINTER_SITES
            ),
            tail_normalize_patch(
                "dialogue_two_glyph_tail",
                TYPEWRITER_TAIL_SITE,
                typewriter.tail_entry,
            ),
            BytePatch(
                name="advance_cave",
                address=CAVE_ADDRESS,
                expected=bytes(len(advance)),
                replacement=advance,
            ),
            BytePatch(
                name="packed_fetch_cave",
                address=fetch_address,
                expected=bytes(len(fetch)),
                replacement=fetch,
            ),
            BytePatch(
                name="subpixel_blitter_cave",
                address=blitter_address,
                expected=bytes(len(blitter)),
                replacement=blitter,
            ),
            BytePatch(
                name="menu_glyph_cave",
                address=menu_address,
                expected=bytes(len(menu)),
                replacement=menu,
            ),
            BytePatch(
                name="fetch_site_1",
                address=FETCH_SITE_1,
                expected=FETCH_SITE_1_ORIGINAL,
                replacement=build_site_patch(FETCH_SITE_1, fetch_address),
            ),
            BytePatch(
                name="fetch_site_2",
                address=FETCH_SITE_2,
                expected=FETCH_SITE_2_ORIGINAL,
                replacement=build_site_patch(FETCH_SITE_2, fetch_address),
            ),
            BytePatch(
                name="advance_pointer",
                address=ADVANCE_POINTER,
                expected=struct.pack(">I", ORIGINAL_ADVANCE),
                replacement=struct.pack(">I", CAVE_ADDRESS),
            ),
            BytePatch(
                name="dialogue_blitter_pointer",
                address=BLITTER_POINTER,
                expected=struct.pack(">I", ORIGINAL_BLITTER),
                replacement=struct.pack(">I", typewriter.blitter_entry),
            ),
            BytePatch(
                name="menu_blitter_pointer",
                address=MENU_BLITTER_POINTER,
                expected=struct.pack(">I", ORIGINAL_BLITTER),
                replacement=struct.pack(">I", menu_address),
            ),
            BytePatch(
                name="menu_advance",
                address=MENU_ADVANCE_SITE,
                expected=struct.pack(">H", 0x61B1),
                replacement=struct.pack(">H", 0x6103),
            ),
        ),
    )
