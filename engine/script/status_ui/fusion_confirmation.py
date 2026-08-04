"""Pointer-based storage for EVENT's extended fusion-confirmation lines."""

import struct
from dataclasses import dataclass

from engine.script.event.model import (
    FUSION_CONFIRMATION_OVERFLOW_ADDRESS,
    PACKED_FETCH_ADDRESS,
)
from engine.script.patching import CodePatch
from engine.script.static_text import StaticTextAsset
from engine.script.status_ui.model import BASE

LOOKUP_SITE = 0x060578A2
DESTINATION_LITERAL = 0x06057914
TABLE_LITERAL = 0x06057918
MAIN_FILE = 0x5458E
MAIN_SIZE = 0xA0
# The stock region begins at 0x...8e, but SH-2 mov.l requires a four-byte
# aligned source.  Its two spare bytes are enough to align the pointer table.
POINTER_TABLE_OFFSET = 2
LABEL_YES_FILE = MAIN_FILE + MAIN_SIZE
LABEL_NO_FILE = LABEL_YES_FILE + 8
STORAGE_END_FILE = LABEL_NO_FILE + 8

EXPECTED_WORD_COUNTS = {
    "confirm_prompt": 20,
    "level_too_low": 34,
    "duplicate_demon": 30,
    "begin_fusion": 20,
    "label_yes": 4,
    "label_no": 4,
}


@dataclass(frozen=True)
class FusionConfirmationStorage:
    main: bytes
    level_too_low: bytes
    label_yes: bytes
    label_no: bytes
    pointers: tuple[int, int, int, int]


def _block_data(asset: StaticTextAsset, name: str) -> bytes:
    try:
        block = asset.blocks[name]
    except KeyError as error:
        raise ValueError(f"fusion-confirmation asset is missing {name!r}") from error
    expected_words = EXPECTED_WORD_COUNTS[name]
    if block.storage != "u16be" or block.word_count != expected_words:
        raise ValueError(
            f"fusion-confirmation {name!r} must contain {expected_words} words"
        )
    data = asset.data[block.offset : block.offset + block.size]
    if not int.from_bytes(data[-2:], "big") & 0x8000:
        raise ValueError(f"fusion-confirmation {name!r} has no terminator")
    return data


def build_storage(asset: StaticTextAsset) -> FusionConfirmationStorage:
    """Lay out the stock table as pointers plus three local and one overflow row."""
    if set(asset.blocks) != set(EXPECTED_WORD_COUNTS):
        raise ValueError("fusion-confirmation asset has unexpected blocks")

    confirm = _block_data(asset, "confirm_prompt")
    level = _block_data(asset, "level_too_low")
    duplicate = _block_data(asset, "duplicate_demon")
    begin = _block_data(asset, "begin_fusion")
    label_yes = _block_data(asset, "label_yes")
    label_no = _block_data(asset, "label_no")

    table_address = BASE + MAIN_FILE + POINTER_TABLE_OFFSET
    if table_address % 4:
        raise ValueError("fusion-confirmation pointer table is not longword-aligned")
    confirm_address = table_address + 16
    duplicate_address = confirm_address + len(confirm)
    begin_address = duplicate_address + len(duplicate)
    pointers = (
        confirm_address,
        FUSION_CONFIRMATION_OVERFLOW_ADDRESS,
        duplicate_address,
        begin_address,
    )
    main = bytearray(POINTER_TABLE_OFFSET)
    main.extend(struct.pack(">4I", *pointers))
    main.extend(confirm)
    main.extend(duplicate)
    main.extend(begin)
    if len(main) > MAIN_SIZE:
        raise ValueError(
            f"fusion-confirmation main table exceeds its stock region by "
            f"{len(main) - MAIN_SIZE} bytes"
        )
    main.extend(bytes(MAIN_SIZE - len(main)))

    if FUSION_CONFIRMATION_OVERFLOW_ADDRESS + len(level) != PACKED_FETCH_ADDRESS:
        raise ValueError("fusion-confirmation overflow does not fill its reservation")
    return FusionConfirmationStorage(
        main=bytes(main),
        level_too_low=level,
        label_yes=label_yes,
        label_no=label_no,
        pointers=pointers,
    )


def pointer_lookup_patch() -> CodePatch:
    """Replace the stock 40-byte stride with a four-entry pointer lookup."""
    return CodePatch(
        "fusion_confirmation_pointer_lookup",
        LOOKUP_SITE,
        """
            mov     #40, r1
            mov.l   DESTINATION_LITERAL, r2
            mov.l   r2, @-r15
            mov     #0, r2
            mov     #0, r7
            mulu.w  r1, r8
            mov     #2, r6
            mov     #20, r5
            sts     macl, r4
            mov.l   TABLE_LITERAL, r1
            add     r1, r4
        """,
        f"""
            mov.l   DESTINATION_LITERAL, r2
            mov.l   r2, @-r15
            mov     #0, r2
            mov     #0, r7
            mov     #2, r6
            mov     #20, r5
            mov     r8, r0
            shll2   r0
            mov.l   TABLE_LITERAL, r1
            add     #{POINTER_TABLE_OFFSET}, r1
            mov.l   @(r0,r1), r4
        """,
        symbols={
            "DESTINATION_LITERAL": DESTINATION_LITERAL,
            "TABLE_LITERAL": TABLE_LITERAL,
        },
    )
