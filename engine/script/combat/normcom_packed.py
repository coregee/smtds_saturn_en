"""Dictionary-packed BUTU_SRF record decoder in NORMCOM."""

from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.packed_record import (
    build_record_cave,
    validate_indexed_record_capacity,
)
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from engine.script.text_render.packed_codec import bound_dictionary_table
from tools.sh2asm import assemble

BASE = 0x06020000
TARGET = BinaryTarget("NORMCOM.BIN", Path("NORMCOM.BIN"), BASE)
ASM_ROOT = Path(__file__).with_name("asm")

HOOK = 0x0602F7E8
CONTINUATION = 0x0602F7F4
CAVE = 0x06020A00
SCRATCH = 0x06020D00
CAVE_LIMIT = SCRATCH
SCRATCH_SIZE = 0x100

HOOK_ORIGINAL = bytes.fromhex("301c91620217e8009c60d139")


def build_hook() -> bytes:
    code = assemble(
        "mov.l =CAVE,r3\njmp @r3\nnop\n.pool",
        HOOK,
        symbols={"CAVE": CAVE},
    )
    if code.warnings:
        raise ValueError(f"BUTU_SRF packed hook warnings: {code.warnings}")
    if len(code) != len(HOOK_ORIGINAL):
        raise ValueError("BUTU_SRF packed hook does not fill its displaced window")
    return bytes(code)


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    dictionary_table = bound_dictionary_table(
        context.text_generated_root / "event_codec.json",
        context.text_generated_root / "event_codec_binding.json",
        context.build_root,
    )
    wrapper_source = (ASM_ROOT / "butu_record_hook.s").read_text(encoding="utf-8")
    cave_payload = build_record_cave(
        wrapper_source,
        CAVE,
        CAVE_LIMIT,
        {
            "SCRATCH": SCRATCH,
            "ROW_STRIDE": 0x2000,
            "LINE_WIDTH": 0x00B0,
            "HELPER": 0x0603DB90,
            "CONTINUATION": CONTINUATION,
        },
        dictionary_table,
    )
    validate_indexed_record_capacity(
        context.build_root / "BUTU_SRF.MDT",
        body_offset=0x400,
        capacity_words=SCRATCH_SIZE // 2,
        dictionary_table=dictionary_table,
    )
    return PatchGroup(
        capability="combat_packed_fetch",
        target=TARGET,
        patches=(
            BytePatch(
                "butu_srf_decoder",
                CAVE,
                bytes(len(cave_payload)),
                cave_payload,
            ),
            BytePatch(
                "butu_srf_scratch",
                SCRATCH,
                bytes(SCRATCH_SIZE),
                bytes(SCRATCH_SIZE),
            ),
            BytePatch(
                "butu_srf_hook",
                HOOK,
                HOOK_ORIGINAL,
                build_hook(),
            ),
        ),
    )
