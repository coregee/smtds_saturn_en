"""Derived EVENT packed-fetch layout without patch registration."""

from functools import cache

from engine.script.event.model import PACKED_FETCH_ADDRESS
from engine.script.event.packed_runtime import build_fetch_cave
from engine.script.text_render.packed_codec import (
    DICTIONARY_RECORD_SIZE,
    DICTIONARY_TOKENS,
)

RETURN_ZERO = 0x0602BB74
RETURN_CODE = 0x0602BB8C


@cache
def event_fetch_cave(dictionary_table: bytes | None = None) -> bytes:
    return build_fetch_cave(
        PACKED_FETCH_ADDRESS,
        RETURN_CODE,
        RETURN_ZERO,
        dictionary_table,
    )


def next_runtime_address() -> int:
    # Only the fixed layout is needed here. Avoid reading the default generated
    # tree while another EngineBuildContext is being assembled.
    placeholder = bytes(DICTIONARY_TOKENS * DICTIONARY_RECORD_SIZE)
    return (PACKED_FETCH_ADDRESS + len(event_fetch_cave(placeholder)) + 3) & ~3
