"""Compact title-case Latin names into checked five-bit token words."""

import struct
from collections.abc import Iterable


def pack_title_case_names(
    names: Iterable[tuple[int, str]],
    *,
    record_count: int,
) -> tuple[bytes, bytes]:
    """Pack selected indexed names and return an index bitmap plus word pool."""
    selected = list(names)
    bits = bytearray((record_count + 7) // 8)
    pool = bytearray()
    previous = -1
    for index, name in selected:
        if not 0 <= index < record_count or index <= previous:
            raise ValueError(
                "compact name indices must be unique, ordered, and in range"
            )
        previous = index
        bits[index // 8] |= 1 << (index & 7)
        tokens: list[int] = []
        uppercase = True
        for character in name:
            if character.isalpha() and character.isascii():
                wanted_uppercase = character.isupper()
                if wanted_uppercase != uppercase:
                    tokens.append(30)
                tokens.append(ord(character.lower()) - ord("a") + 1)
                uppercase = False
            elif character == " ":
                tokens.append(27)
                uppercase = True
            elif character == "-":
                tokens.append(28)
                uppercase = True
            elif character == "'":
                tokens.append(29)
                uppercase = True
            elif character == "8":
                tokens.append(31)
                uppercase = False
            else:
                raise ValueError(
                    f"unsupported compact-name character {character!r} in {name!r}"
                )
        while len(tokens) % 3:
            tokens.append(0)
        for offset in range(0, len(tokens), 3):
            first, second, third = tokens[offset : offset + 3]
            final = offset + 3 == len(tokens)
            pool.extend(
                struct.pack(
                    ">H",
                    (0x8000 if final else 0) | (first << 10) | (second << 5) | third,
                )
            )
    return bytes(bits), bytes(pool)
