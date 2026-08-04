"""Rebuild atlas-native name rows after LOAD.BIN restores saved WRAM."""

from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.name.model import (
    CODENAME_BYTES,
    NAME_FIELDS,
    NAME_FW,
    NAME_FW_FULL,
    byte_to_atlas_table,
    byte_to_font8_table,
    load_atlas_metrics,
)
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from tools.sh2asm import AsmBlob, assemble

LOAD_BASE = 0x06020000
LOAD_TARGET = BinaryTarget("LOAD.BIN", Path("LOAD.BIN"), LOAD_BASE)

CAVE_OFFSET = 0x40
CAVE_ADDRESS = LOAD_BASE + CAVE_OFFSET
FREE_WINDOW_END = 0x6500
HOOK_ADDRESS = LOAD_BASE + 0x8CFC
ORIGINAL_PREP_NAMES = 0x0602AB5C

SOURCE_PATH = Path(__file__).with_name("load_names.s")


def build_source() -> str:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    stage_addresses = ", ".join(f"{spec.stage_address:#010x}" for spec in NAME_FIELDS)
    atlas_words = ", ".join(str(code) for code in byte_to_atlas_table())
    font8_bytes = ", ".join(str(code) for code in byte_to_font8_table())
    return (
        source
        + "\n.align 4\nstage_ptrs:\n"
        + f"    .long {stage_addresses}\n"
        + ".align 2\nbyte_to_atlas:\n"
        + f"    .word {atlas_words}\n"
        + "byte_to_font8:\n"
        + f"    .byte {font8_bytes}\n"
    )


def build_cave() -> AsmBlob:
    cave = assemble(
        build_source(),
        CAVE_ADDRESS,
        symbols={
            "NAME_FW": NAME_FW,
            "NAME_FW_FULL": NAME_FW_FULL,
            "CODENAME": CODENAME_BYTES,
            "prep_names": ORIGINAL_PREP_NAMES,
            "space_glyph": load_atlas_metrics()[0][" "],
        },
    )
    if cave.warnings:
        details = "\n  ".join(cave.warnings)
        raise ValueError(f"LOAD.BIN name-rebuild warnings:\n  {details}")
    if CAVE_OFFSET + len(cave) > FREE_WINDOW_END:
        raise ValueError("LOAD.BIN name-rebuild cave exceeds the zero window")
    return cave


def build_patch_groups(_context: EngineBuildContext) -> PatchGroup:
    cave = build_cave()
    return PatchGroup(
        capability="name_runtime",
        target=LOAD_TARGET,
        patches=(
            BytePatch(
                name="name_rebuild_cave",
                address=CAVE_ADDRESS,
                expected=bytes(len(cave)),
                replacement=cave,
            ),
            BytePatch(
                name="name_rebuild_hook",
                address=HOOK_ADDRESS,
                expected=ORIGINAL_PREP_NAMES.to_bytes(4, "big"),
                replacement=CAVE_ADDRESS.to_bytes(4, "big"),
            ),
        ),
    )
