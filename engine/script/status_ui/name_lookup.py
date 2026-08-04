"""Shared eight-byte hash-to-string-pointer lookup records."""

import struct
from collections.abc import Callable, Mapping

NAME_LOOKUP_STRIDE = struct.calcsize(">II")


def build_name_lookup(
    hashes: Mapping[int, str],
    resolve_pointer: Callable[[str], int],
) -> bytes:
    """Encode sorted XOR hashes followed by absolute string pointers."""
    return b"".join(
        struct.pack(">II", key, resolve_pointer(name))
        for key, name in sorted(hashes.items())
    )
