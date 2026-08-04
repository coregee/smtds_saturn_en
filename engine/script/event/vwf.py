import struct
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.event.model import EVENT_TARGET
from engine.script.patching import BytePatch, PatchGroup
from engine.script.text_render.font16_vwf import (
    align_up,
    build_advance_cave,
    build_blitter_cave,
    build_menu_cave,
    build_surface_blitter_cave,
)
from engine.script.text_render.font_metrics import (
    font12_dialogue_widths,
    font12_signature,
    font16_metrics,
    font16_width_layout,
)
from engine.script.text_render.typewriter import (
    TwoGlyphPacing,
    build_two_glyph_pacing,
    tail_normalize_patch,
)
from tools.sh2asm import assemble

TYPEWRITER_UPDATE = 0x0602BB38
TYPEWRITER_GATE_SITE = 0x0602BB50
TYPEWRITER_UPDATE_POINTER_SITES = (
    0x0603043C,
    0x06030494,
    0x06030508,
    0x06033820,
    0x06033874,
    0x060338FC,
    0x06036668,
    0x06039780,
    0x060397EC,
)
TYPEWRITER_TAIL_SITE = 0x0602BBE0
TYPEWRITER_TAIL_CONTINUE = 0x0602BBF0
ADVANCE_POINTER = 0x0602BC9C
ORIGINAL_ADVANCE = 0x0602BE04
BLITTER_POINTER = 0x0602BCBC
ORIGINAL_BLITTER = 0x0602BCC0
MENU_ADVANCE_SITE = 0x06030CD2
MENU_BLITTER_POINTER = 0x06030D20
RAW_MENU_ADVANCE_SITE = 0x0602F022
RAW_MENU_BLITTER_POINTER = 0x0602F03C
WORD_MENU_ADVANCE_SITE = 0x0603BE20
WORD_MENU_BLITTER_POINTER = 0x0603BE54
STOCK_WORD_MENU_BLITTER = 0x0603B760
STOCK_FONT_LOADER = 0x0602B91A
FONT_LOADER_POINTER_SITES = (
    0x0602EB08,
    0x0602EC94,
    0x0602F2F4,
    0x06032D48,
    0x06041770,
    0x06042124,
    0x0604286C,
    0x06046AE0,
    0x06046DE4,
    0x06048794,
    0x06049604,
    0x0604A010,
)
FONT12_NAME_TAG = 0x31322E46  # "12.F" from "FONT12.FON"
FONT_MODE_FLAG = 0x060217FC
ZERO_SPACE_ADVANCE = 0x060217FE
ZERO_SPACE_POINTER_SITE = 0x0602BC2C

VWF_CAVE_ADDRESS = 0x06021000
CAVE_WINDOW_END = 0x06021800
TEXT_ADVANCE = 0x06076754
TEXT_CURSOR_X = 0x06076E20
TEXT_RIGHT_MARGIN = 0x06076E24
FONT16_POINTER = 0x06062598

ASM_ROOT = Path(__file__).with_name("asm")

FRAMEBUFFER_POINTER = 0x06067C90
TEXT_COLOR = 0x060BFC98
TEXT_LINE_HEIGHT = 0x0607675C
GLYPH_PATTERN_LUT = 0x0602B9F4
GLYPH_MASK_LUT = 0x0602BA14


def build_word_menu_code(
    cave_address: int,
    blitter_address: int,
    widths_address: int,
) -> bytes:
    """Assemble a FONT12 word-glyph wrapper for one surface contract."""
    source = (ASM_ROOT / "font12_word_glyph_vwf.s").read_text(encoding="utf-8")
    code = assemble(
        source,
        cave_address,
        symbols={
            "SURFACE_BLITTER": blitter_address,
            "WIDTHS": widths_address,
        },
    )
    if code.warnings:
        raise ValueError(f"FONT12 word-menu assembly warnings: {code.warnings}")
    return bytes(code)


def build_word_menu_cave(
    cave_address: int,
    blitter_address: int,
    font12_widths: bytes,
) -> tuple[bytes, int]:
    """Build a word-glyph wrapper followed by its shared width table."""
    probe = build_word_menu_code(cave_address, blitter_address, cave_address)
    width_address = align_up(cave_address + len(probe), 4)
    code = build_word_menu_code(cave_address, blitter_address, width_address)
    payload = bytearray(code)
    payload.extend(bytes((-len(payload)) % 4))
    if cave_address + len(payload) != width_address:
        raise ValueError("FONT12 word-menu width table address drifted")
    payload.extend(font12_widths)
    return bytes(payload), width_address


def build_font_loader_cave(cave_address: int, font12_widths: bytes) -> bytes:
    """Track the loaded font and the VM zero-cell space advance."""
    source = (ASM_ROOT / "tracked_font_loader.s").read_text(encoding="utf-8")
    code = assemble(
        source,
        cave_address,
        symbols={
            "FONT12_TAG": FONT12_NAME_TAG,
            "FONT_MODE": FONT_MODE_FLAG,
            "FONT12_SPACE": font12_widths[0],
            "SPACE_ADVANCE": ZERO_SPACE_ADVANCE,
            "STOCK_LOADER": STOCK_FONT_LOADER,
        },
    )
    if code.warnings:
        raise ValueError(f"tracked font-loader assembly warnings: {code.warnings}")
    return bytes(code)


@dataclass(frozen=True)
class EventVwfArtifacts:
    advance: bytes
    blitter_address: int
    blitter: bytes
    menu_address: int
    menu: bytes
    surface_address: int
    surface: bytes
    word_menu_address: int
    word_menu: bytes
    font_loader_address: int
    font_loader: bytes
    typewriter_address: int
    typewriter: TwoGlyphPacing


@cache
def build_artifacts() -> EventVwfArtifacts:
    metrics = font16_metrics()
    code_limit, width_offset = font16_width_layout(metrics)
    font12_widths = font12_dialogue_widths()
    signature_offset, signature_value = font12_signature()
    advance = build_advance_cave(
        VWF_CAVE_ADDRESS,
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
    blitter_address = align_up(VWF_CAVE_ADDRESS + len(advance), 8)
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
    surface_address = align_up(menu_address + len(menu), 4)
    surface = build_surface_blitter_cave(
        surface_address,
        font16_pointer=FONT16_POINTER,
        glyph_pattern_lut=GLYPH_PATTERN_LUT,
        glyph_mask_lut=GLYPH_MASK_LUT,
    )
    word_menu_address = align_up(surface_address + len(surface), 4)
    word_menu, _ = build_word_menu_cave(
        word_menu_address,
        surface_address,
        font12_widths,
    )
    font_loader_address = align_up(word_menu_address + len(word_menu), 4)
    font_loader = build_font_loader_cave(font_loader_address, font12_widths)
    typewriter_address = align_up(font_loader_address + len(font_loader), 4)
    typewriter = build_two_glyph_pacing(
        typewriter_address,
        original_update=TYPEWRITER_UPDATE,
        visible_blitter=blitter_address,
        tail_continue=TYPEWRITER_TAIL_CONTINUE,
    )
    if len(blitter) != 288:
        raise ValueError(f"unexpected blitter cave size: {len(blitter)}")
    if typewriter_address + len(typewriter.payload) > FONT_MODE_FLAG:
        raise ValueError("EVENT VWF caves exceed the verified free window")
    return EventVwfArtifacts(
        advance,
        blitter_address,
        blitter,
        menu_address,
        menu,
        surface_address,
        surface,
        word_menu_address,
        word_menu,
        font_loader_address,
        font_loader,
        typewriter_address,
        typewriter,
    )


def _build_patch_group() -> PatchGroup:
    artifacts = build_artifacts()
    return PatchGroup(
        capability="event_vwf",
        target=EVENT_TARGET,
        patches=(
            BytePatch(
                name="dialogue_two_glyph_pacing_cave",
                address=artifacts.typewriter_address,
                expected=bytes(len(artifacts.typewriter.payload)),
                replacement=artifacts.typewriter.payload,
            ),
            *(
                BytePatch(
                    name=f"dialogue_update_pointer_{address:08x}",
                    address=address,
                    expected=struct.pack(">I", TYPEWRITER_UPDATE),
                    replacement=struct.pack(
                        ">I",
                        artifacts.typewriter.update_entry,
                    ),
                )
                for address in TYPEWRITER_UPDATE_POINTER_SITES
            ),
            tail_normalize_patch(
                "dialogue_two_glyph_tail",
                TYPEWRITER_TAIL_SITE,
                artifacts.typewriter.tail_entry,
            ),
            BytePatch(
                name="advance_cave",
                address=VWF_CAVE_ADDRESS,
                expected=b"\x00" * len(artifacts.advance),
                replacement=artifacts.advance,
            ),
            BytePatch(
                name="advance_pointer",
                address=ADVANCE_POINTER,
                expected=struct.pack(">I", ORIGINAL_ADVANCE),
                replacement=struct.pack(">I", VWF_CAVE_ADDRESS),
            ),
            BytePatch(
                name="subpixel_blitter_cave",
                address=artifacts.blitter_address,
                expected=b"\x00" * len(artifacts.blitter),
                replacement=artifacts.blitter,
            ),
            BytePatch(
                name="dialogue_blitter_pointer",
                address=BLITTER_POINTER,
                expected=struct.pack(">I", ORIGINAL_BLITTER),
                replacement=struct.pack(
                    ">I",
                    artifacts.typewriter.blitter_entry,
                ),
            ),
            BytePatch(
                name="menu_glyph_cave",
                address=artifacts.menu_address,
                expected=b"\x00" * len(artifacts.menu),
                replacement=artifacts.menu,
            ),
            BytePatch(
                name="menu_blitter_pointer",
                address=MENU_BLITTER_POINTER,
                expected=struct.pack(">I", ORIGINAL_BLITTER),
                replacement=struct.pack(">I", artifacts.menu_address),
            ),
            BytePatch(
                name="menu_advance",
                address=MENU_ADVANCE_SITE,
                expected=struct.pack(">H", 0x61B1),
                replacement=struct.pack(">H", 0x6103),
            ),
            BytePatch(
                name="raw_menu_blitter_pointer",
                address=RAW_MENU_BLITTER_POINTER,
                expected=struct.pack(">I", ORIGINAL_BLITTER),
                replacement=struct.pack(">I", artifacts.menu_address),
            ),
            BytePatch(
                name="raw_menu_advance",
                address=RAW_MENU_ADVANCE_SITE,
                expected=struct.pack(">H", 0x7910),
                replacement=struct.pack(">H", 0x390C),
            ),
            BytePatch(
                name="surface_subpixel_blitter_cave",
                address=artifacts.surface_address,
                expected=b"\x00" * len(artifacts.surface),
                replacement=artifacts.surface,
            ),
            BytePatch(
                name="font12_word_menu_cave",
                address=artifacts.word_menu_address,
                expected=b"\x00" * len(artifacts.word_menu),
                replacement=artifacts.word_menu,
            ),
            BytePatch(
                name="font12_word_menu_blitter_pointer",
                address=WORD_MENU_BLITTER_POINTER,
                expected=struct.pack(">I", STOCK_WORD_MENU_BLITTER),
                replacement=struct.pack(">I", artifacts.word_menu_address),
            ),
            BytePatch(
                name="font12_word_menu_advance",
                address=WORD_MENU_ADVANCE_SITE,
                expected=struct.pack(">H", 0x790C),
                replacement=struct.pack(">H", 0x390C),
            ),
            BytePatch(
                name="tracked_font_loader_cave",
                address=artifacts.font_loader_address,
                expected=b"\x00" * len(artifacts.font_loader),
                replacement=artifacts.font_loader,
            ),
            BytePatch(
                name="zero_cell_space_advance",
                address=ZERO_SPACE_ADVANCE,
                expected=b"\x00\x00",
                replacement=struct.pack(">H", 16),
            ),
            BytePatch(
                name="zero_cell_space_pointer",
                address=ZERO_SPACE_POINTER_SITE,
                expected=struct.pack(">I", TEXT_ADVANCE),
                replacement=struct.pack(">I", ZERO_SPACE_ADVANCE),
            ),
            *(
                BytePatch(
                    name=f"tracked_font_loader_pointer_{address:08x}",
                    address=address,
                    expected=struct.pack(">I", STOCK_FONT_LOADER),
                    replacement=struct.pack(">I", artifacts.font_loader_address),
                )
                for address in FONT_LOADER_POINTER_SITES
            ),
        ),
    )


def build_patch_groups(_context: EngineBuildContext) -> PatchGroup:
    return _build_patch_group()
