"""Derived EVENT packed-fetch layout without patch registration."""

from functools import cache

from engine.script.event.model import PACKED_FETCH_ADDRESS
from engine.script.event.packed_runtime import build_fetch_cave

RETURN_ZERO = 0x0602BB74
RETURN_CODE = 0x0602BB8C


@cache
def event_fetch_cave() -> bytes:
    return build_fetch_cave(
        PACKED_FETCH_ADDRESS,
        RETURN_CODE,
        RETURN_ZERO,
    )


def next_runtime_address() -> int:
    return (PACKED_FETCH_ADDRESS + len(event_fetch_cave()) + 3) & ~3
