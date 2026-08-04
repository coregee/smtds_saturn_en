"""Expand packed COMBAT words before the widened dialogue grid."""

from pathlib import Path

from engine.script.combat.model import (
    COMBAT_DICTIONARY_ADDRESS,
    COMBAT_PENDING_BUFFER,
    COMBAT_PENDING_FLAG,
    COMBAT_PENDING_WORD_CAPACITY,
    COMBAT_TARGET,
)
from engine.script.context import EngineBuildContext
from engine.script.packed_record import (
    build_record_cave,
    validate_indexed_record_capacity,
)
from engine.script.patching import BytePatch, PatchGroup
from engine.script.text_render.packed_codec import (
    DICTIONARY_RECORD_SIZE,
    DICTIONARY_TOKEN_START,
    MAX_EXPANSION,
    PACKED_SPACE_CODE,
    PACKED_TOKEN_BASE,
    PACKED_TOKEN_RANGE,
    bound_dictionary_table,
)
from tools.sh2asm import AsmBlob, assemble

ASM_ROOT = Path(__file__).with_name("asm")

DISPATCH_SITE = 0x06051D1C
DISPATCH_CAVE_POINTER = 0x06051E40
DISPATCH_DEMON_ID_HANDLER = 0x060504F8
DISPATCH_EQUAL_CONTINUATION = 0x06051D2C
DISPATCH_OTHER_CONTINUATION = 0x06051D44
FIRST_SPECIAL_CODE = 0x00008010

CAVE_ADDRESS = 0x06021000
CAVE_LIMIT = 0x06021400
DIALOGUE_MODE = 0x060213FC
DIALOGUE_DISPATCH_POINTER_SITES = (
    # Shared by the pending-word call at 0x060596A8 and the two dialogue
    # source calls at 0x060596E6 and 0x06059754.
    0x060597B8,
)
TERMINATOR_CODE = 0x8000

BTL_HOOK = 0x0604DCB4
BTL_CONTINUATION = 0x0604DCC0
BTL_CAVE = 0x06020C00
BTL_CAVE_LIMIT = 0x06020F00
BTL_SCRATCH = 0x06020F00
BTL_SCRATCH_SIZE = 0x100
BTL_HOOK_ORIGINAL = bytes.fromhex("3c1c61b066a1611c6013301c")
BTL_LOOP_SITE = 0x0604DD7C
BTL_LOOP_STOCK_TARGET = 0x0604DCB6

DISPATCH_ORIGINAL = bytes.fromhex(
    "4f22"  # sts.l PR,@-r15
    "6643"  # mov r4,r6
    "d147"  # mov.l 0x06051e40,r1
    "3610"  # cmp/eq r1,r6
    "8b0e"  # bf 0x06051d44
    "d047"  # mov.l 0x06051e44,r0
)


def build_dispatch_site(site_address: int, cave_address: int) -> bytes:
    code = assemble(
        "mov.l CAVE_POINTER,r0\njmp @r0\nnop\nnop\nnop\nnop",
        site_address,
        symbols={"CAVE_POINTER": DISPATCH_CAVE_POINTER},
    )
    if code.warnings:
        raise ValueError(f"COMBAT packed-dispatch warnings: {code.warnings}")
    if len(code) != len(DISPATCH_ORIGINAL):
        raise ValueError(
            "COMBAT packed-dispatch hook does not fill the original prologue"
        )
    if cave_address != CAVE_ADDRESS:
        raise ValueError(
            "COMBAT packed-dispatch pointer patch only supports the reserved cave"
        )
    return bytes(code)


def assemble_dispatch(cave_address: int) -> AsmBlob:
    """Assemble the shared immediate and dialogue-paced dispatch entries."""
    source = (ASM_ROOT / "packed_dispatch.s").read_text(encoding="utf-8")
    base_symbols = {
        "RAW_HANDLER": cave_address,
        "PACKED_DISPATCH": cave_address,
        "DICTIONARY": COMBAT_DICTIONARY_ADDRESS,
        "SPACE_CODE": PACKED_SPACE_CODE,
        "PENDING_BUFFER": COMBAT_PENDING_BUFFER,
        "PENDING_FLAG": COMBAT_PENDING_FLAG,
        "DIALOGUE_MODE": DIALOGUE_MODE,
        "TERMINATOR": TERMINATOR_CODE,
        "FIRST_SPECIAL": FIRST_SPECIAL_CODE,
        "DEMON_ID_HANDLER": DISPATCH_DEMON_ID_HANDLER,
        "EQUAL_CONTINUATION": DISPATCH_EQUAL_CONTINUATION,
        "OTHER_CONTINUATION": DISPATCH_OTHER_CONTINUATION,
    }
    probe = assemble(source, cave_address, symbols=base_symbols)
    if probe.warnings:
        raise ValueError(f"COMBAT packed cave warnings: {probe.warnings}")
    code = assemble(
        source,
        cave_address,
        symbols={**base_symbols, "RAW_HANDLER": probe.labels["raw_handler"]},
    )
    if code.warnings:
        raise ValueError(f"COMBAT packed cave warnings: {code.warnings}")
    return code


def build_dispatch_cave(
    cave_address: int,
    dictionary_table: bytes | None = None,
) -> bytes:
    """Expand packed words immediately or queue dialogue glyphs by call site."""
    if dictionary_table is None:
        dictionary_table = bound_dictionary_table()
    code = assemble_dispatch(cave_address)
    payload = bytearray(code)
    dictionary_offset = COMBAT_DICTIONARY_ADDRESS - cave_address
    if len(payload) > dictionary_offset:
        raise ValueError("COMBAT packed dispatcher overlaps its dictionary")
    payload.extend(bytes(dictionary_offset - len(payload)))
    payload.extend(dictionary_table)
    mode_offset = DIALOGUE_MODE - cave_address
    if len(payload) > mode_offset:
        raise ValueError("COMBAT packed dictionary overlaps dialogue mode state")
    payload.extend(bytes(mode_offset + 1 - len(payload)))
    if cave_address + len(payload) > CAVE_LIMIT:
        raise ValueError(
            f"COMBAT packed cave exceeds reserved limit {CAVE_LIMIT:#010x}"
        )
    return bytes(payload)


if (
    DICTIONARY_RECORD_SIZE != 8
    or DICTIONARY_TOKEN_START != 63
    or PACKED_TOKEN_BASE != 8
    or PACKED_TOKEN_RANGE != 120
):
    raise ValueError("COMBAT packed dispatcher and EVENT dictionary disagree")
if MAX_EXPANSION * 2 + 1 > COMBAT_PENDING_WORD_CAPACITY:
    raise ValueError("COMBAT packed expansion exceeds the stock pending queue")


def build_btl_hook() -> bytes:
    code = assemble(
        "mov.l =CAVE,r0\njmp @r0\nnop\n.pool",
        BTL_HOOK,
        symbols={"CAVE": BTL_CAVE},
    )
    if code.warnings:
        raise ValueError(f"BTL_SRF packed hook warnings: {code.warnings}")
    if len(code) != len(BTL_HOOK_ORIGINAL):
        raise ValueError("BTL_SRF packed hook does not fill its displaced window")
    return bytes(code)


def build_btl_loop_branch(target: int) -> bytes:
    """Retarget the stock glyph loop without changing its delay slot."""
    code = assemble(
        "bra TARGET\nmov.b r1,@r11",
        BTL_LOOP_SITE,
        symbols={"TARGET": target},
    )
    if code.warnings:
        raise ValueError(f"BTL_SRF loop branch warnings: {code.warnings}")
    return bytes(code[:2])


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    dictionary_table = bound_dictionary_table(
        context.text_generated_root / "event_codec.json",
        context.text_generated_root / "event_codec_binding.json",
        context.build_root,
    )
    dispatch_code = assemble_dispatch(CAVE_ADDRESS)
    dispatch_cave = build_dispatch_cave(CAVE_ADDRESS, dictionary_table)
    wrapper_source = (ASM_ROOT / "btl_record_hook.s").read_text(encoding="utf-8")
    btl_cave_payload = build_record_cave(
        wrapper_source,
        BTL_CAVE,
        BTL_CAVE_LIMIT,
        {
            "SCRATCH": BTL_SCRATCH,
            "CONTINUATION": BTL_CONTINUATION,
        },
        dictionary_table,
    )
    validate_indexed_record_capacity(
        context.build_root / "BTL_SRF.MDT",
        body_offset=0x400,
        capacity_words=BTL_SCRATCH_SIZE // 2,
        dictionary_table=dictionary_table,
    )
    return PatchGroup(
        capability="combat_packed_fetch",
        target=COMBAT_TARGET,
        patches=(
            BytePatch(
                "dispatch_cave",
                CAVE_ADDRESS,
                bytes(len(dispatch_cave)),
                dispatch_cave,
            ),
            BytePatch(
                "dispatch_hook",
                DISPATCH_SITE,
                DISPATCH_ORIGINAL,
                build_dispatch_site(DISPATCH_SITE, CAVE_ADDRESS),
            ),
            BytePatch(
                "dispatch_cave_pointer",
                DISPATCH_CAVE_POINTER,
                FIRST_SPECIAL_CODE.to_bytes(4, "big"),
                CAVE_ADDRESS.to_bytes(4, "big"),
            ),
            *(
                BytePatch(
                    f"dialogue_dispatch_pointer_{index}",
                    address,
                    DISPATCH_SITE.to_bytes(4, "big"),
                    dispatch_code.labels["dialogue_dispatch"].to_bytes(4, "big"),
                )
                for index, address in enumerate(DIALOGUE_DISPATCH_POINTER_SITES)
            ),
            BytePatch(
                "btl_srf_decoder",
                BTL_CAVE,
                bytes(len(btl_cave_payload)),
                btl_cave_payload,
            ),
            BytePatch(
                "btl_srf_scratch",
                BTL_SCRATCH,
                bytes(BTL_SCRATCH_SIZE),
                bytes(BTL_SCRATCH_SIZE),
            ),
            BytePatch(
                "btl_srf_hook",
                BTL_HOOK,
                BTL_HOOK_ORIGINAL,
                build_btl_hook(),
            ),
            BytePatch(
                "btl_srf_loop_reentry",
                BTL_LOOP_SITE,
                build_btl_loop_branch(BTL_LOOP_STOCK_TARGET),
                build_btl_loop_branch(BTL_HOOK),
            ),
        ),
    )
