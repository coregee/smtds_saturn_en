"""Assemble the English NAME.BIN entry controller after its generated data."""

import struct
from dataclasses import dataclass
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.name.data import (
    DATA_END,
    DATA_START,
    NAME_BASE,
    ORIGINAL_DATA_SHA256,
    NameDataLayout,
    build_data_layout,
    build_template_patches,
)
from engine.script.name.model import (
    CODENAME_BYTES,
    FIELD_BY_KIND,
    NAME_FW,
    NAME_FW_FULL,
    NameField,
    load_atlas_metrics,
)
from engine.script.patching import BinaryTarget, BytePatch, DigestPatch, PatchGroup
from tools.sh2asm import AsmBlob, assemble

SOURCE_PATH = Path(__file__).with_name("entry.s")
NAME_TARGET = BinaryTarget("NAME.BIN", Path("NAME.BIN"), NAME_BASE)

ORIGINAL_TEMPLATES = {
    0x20B78: bytes.fromhex(
        "003f0053004e005705430361005800b4000000000750075107520000"
        "075407550756000000008000"
    ),
    0x20C18: bytes.fromhex(
        "0048006800da00000040004000da004b004400b4000000000023000f"
        "001d00000018001900008000"
    ),
    0x20CB8: (
        bytes.fromhex("003f0053004e0057032c0276005800b4")
        + bytes(22)
        + bytes.fromhex("8000")
    ),
}


@dataclass(frozen=True)
class EntryBuild:
    layout: NameDataLayout
    cave_offset: int
    cave: AsmBlob

    @property
    def cave_address(self) -> int:
        return NAME_BASE + self.cave_offset

    @property
    def end_offset(self) -> int:
        return self.cave_offset + len(self.cave)


def symbols(layout: NameDataLayout) -> dict[str, int]:
    block = layout.block
    return {
        "g_type": 0x06045E8A,
        "g_state": 0x06045E8C,
        "g_tab": 0x06045E8E,
        "g_occ": 0x06045E90,
        "g_pos": 0x06045EE8,
        "g_col": 0x06045EEE,
        "g_row": 0x06045EF0,
        "g_scroll": 0x06045EF2,
        "g_pad_edge": 0x06045E94,
        "g_pad_rep": 0x06045E96,
        "fn_sound": 0x0602EDBC,
        "fn_btnA": 0x0602ECD0,
        "fn_btnB": 0x0602ECC0,
        "fn_btnX": 0x0602ECB2,
        "fn_exitgrid": 0x06030E84,
        "fn_rowclear": 0x0602EE1C,
        "fn_pen": 0x0602EE80,
        "fn_color": 0x0602EE94,
        "fn_drawstr": 0x0602EFB8,
        "fn_rowflush": 0x0602F6AC,
        "fn_newline": 0x0602EE60,
        "fn_gridrow": 0x0602F05C,
        "fn_clearall": 0x0602EDD0,
        "fn_fullflush": 0x0602F628,
        "fn_upload": 0x0602F1C4,
        "fn_setbit": 0x06032AD4,
        "fn_blit": 0x0602F510,
        "fn_clearrow": 0x0602F0E4,
        "fn_clear07": 0x0602F0C8,
        "ascii_to_atlas": block("ascii_to_atlas").address,
        "ascii_to_width": block("ascii_to_width").address,
        "ascii_to_charmap": block("ascii_to_charmap").address,
        "OCC_INFO": block("occupation_info").address,
        "TAB_INFO": block("tab_info").address,
        "OCC_PROMPT": layout.label_addresses["label_occupation"],
        "J_TEXT_JSR": 0x06033144,
        "J_TEXT_SKIP": 0x0603314A,
        "J_OCC": 0x060332AE,
        "J_CONFIRM": 0x060332EA,
        "J_T12": 0x0603336A,
        "J_IDLE": 0x0603341E,
        "TMPL8": 0x06040B78,
        "prompt_pointers": block("prompt_pointers").address,
        "default_city_ward": block("default_city_ward").address,
        "grid_bases": block("grid_bases").address,
        "stage_ptrs": block("stage_pointers").address,
        "NAME_FW": NAME_FW,
        "NAME_FW_FULL": NAME_FW_FULL,
        "CODENAME": CODENAME_BYTES,
        "DEF_CITY": FIELD_BY_KIND[NameField.CITY].stage_address,
        "space_glyph": load_atlas_metrics()[0][" "],
    }


def build_entry() -> EntryBuild:
    layout = build_data_layout()
    cave_offset = (layout.next_free + 3) & ~3
    source = SOURCE_PATH.read_text(encoding="utf-8")
    cave = assemble(source, NAME_BASE + cave_offset, symbols(layout))
    if cave.warnings:
        details = "\n  ".join(cave.warnings)
        raise ValueError(f"NAME.BIN assembly warnings:\n  {details}")
    if cave_offset + len(cave) > DATA_END:
        raise ValueError(
            f"NAME.BIN controller ends at {cave_offset + len(cave):#x}, "
            f"beyond {DATA_END:#x}"
        )
    return EntryBuild(layout, cave_offset, cave)


def build_retired_region(entry: EntryBuild) -> bytes:
    region = bytearray(DATA_END - DATA_START)
    for block in entry.layout.blocks:
        start = block.offset - DATA_START
        region[start : start + len(block.data)] = block.data
    cave_start = entry.cave_offset - DATA_START
    region[cave_start : cave_start + len(entry.cave)] = entry.cave
    return bytes(region)


def word32(value: int) -> tuple[int, int]:
    return ((value >> 16) & 0xFFFF, value & 0xFFFF)


def controller_patches(labels: dict[str, int]) -> tuple[BytePatch, ...]:
    records = {
        0x130FC: ((0x8801, 0x8F32, 0x8802), (0xD141, 0x412B, 0x0009)),
        0x13204: (word32(0x0603203C), word32(labels["router"])),
        0x13054: (word32(0x06030850), word32(labels["init_shim"])),
        0x13078: (word32(0x0602F6AC), word32(labels["initial_row_flush"])),
        0x13478: (word32(0x06032B1C), word32(labels["commit"])),
        0x112B4: (word32(0x06030ED4), word32(labels["end_handler"])),
        0x128FC: (word32(0x06030ED4), word32(labels["end_handler"])),
        0x13488: (word32(0x06030780), word32(labels["tab_draw"])),
        0x12800: ((0x480B, 0xE401), (0xA013, 0x0009)),
        0x12AD0: (word32(0x0603049C), word32(labels["occ_cursor"])),
        0x12936: ((0x6013,), (0xE005,)),
        0x12938: ((0x8804,), (0x3106,)),
        0x12948: ((0x8802,), (0x0018,)),
        0x1295A: ((0x7617,), (0x7627,)),
        0x1295E: ((0xCB09,), (0x7019,)),
        0x1297E: ((0x8804,), (0x8806,)),
        0x129A6: ((0xCB08,), (0x7018,)),
        0x12A44: ((0x8804,), (0x8806,)),
    }
    return tuple(
        BytePatch(
            name=f"controller_{offset:05x}",
            address=NAME_BASE + offset,
            expected=struct.pack(f">{len(expected)}H", *expected),
            replacement=struct.pack(f">{len(replacement)}H", *replacement),
        )
        for offset, (expected, replacement) in records.items()
    )


def build_patch_groups(_context: EngineBuildContext) -> PatchGroup:
    entry = build_entry()
    template_patches = build_template_patches()
    return PatchGroup(
        capability="name_runtime",
        target=NAME_TARGET,
        patches=(
            DigestPatch(
                name="retired_tables_and_controller",
                address=NAME_BASE + DATA_START,
                expected_sha256=ORIGINAL_DATA_SHA256,
                replacement=build_retired_region(entry),
            ),
            *(
                BytePatch(
                    name=f"template_{offset:05x}",
                    address=NAME_BASE + offset,
                    expected=ORIGINAL_TEMPLATES[offset],
                    replacement=replacement,
                )
                for offset, replacement in template_patches.items()
            ),
            *controller_patches(entry.cave.labels),
        ),
    )
