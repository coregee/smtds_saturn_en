"""Build a bounded raw-u16 scratch copy from a dictionary-packed word record."""

import struct
from pathlib import Path

from engine.script.text_render.packed_codec import (
    DICTIONARY_TOKEN_START,
    PACKED_SPACE_CODE,
    PACKED_TOKEN_BASE,
    PACKED_TOKEN_RANGE,
    bound_dictionary_table,
)
from tools.sh2asm import assemble

DECODER_SOURCE_PATH = (
    Path(__file__).with_name("text_render") / "asm" / "packed_record_decoder.s"
)


def build_record_cave(
    wrapper_source: str,
    cave_address: int,
    cave_limit: int,
    symbols: dict[str, int],
    dictionary_table: bytes | None = None,
) -> bytes:
    if dictionary_table is None:
        dictionary_table = bound_dictionary_table()
    source = wrapper_source + DECODER_SOURCE_PATH.read_text(encoding="utf-8")
    base_symbols = {
        **symbols,
        "DICTIONARY": cave_address,
        "SPACE_CODE": PACKED_SPACE_CODE,
        "TERMINATOR": 0x00008000,
    }
    probe = assemble(source, cave_address, symbols=base_symbols)
    if probe.warnings:
        raise ValueError(f"packed-record cave warnings: {probe.warnings}")
    dictionary_address = (cave_address + len(probe) + 3) & ~3
    code = assemble(
        source,
        cave_address,
        symbols={**base_symbols, "DICTIONARY": dictionary_address},
    )
    if code.warnings:
        raise ValueError(f"packed-record cave warnings: {code.warnings}")
    payload = bytearray(code)
    payload.extend(bytes(dictionary_address - cave_address - len(payload)))
    payload.extend(dictionary_table)
    if cave_address + len(payload) > cave_limit:
        raise ValueError(
            f"packed-record cave exceeds reserved limit {cave_limit:#010x}"
        )
    return bytes(payload)


def validate_indexed_record_capacity(
    path: Path,
    body_offset: int,
    capacity_words: int,
    dictionary_table: bytes | None = None,
) -> int:
    """Return the longest decoded record and reject scratch-buffer overflow."""
    if dictionary_table is None:
        dictionary_table = bound_dictionary_table()
    data = path.read_bytes()
    pointers = []
    for offset in range(0, body_offset, 2):
        pointer = struct.unpack_from(">H", data, offset)[0]
        if pointer == 0xFFFF:
            break
        pointers.append(pointer)
    if not pointers or pointers[0] != 0:
        raise ValueError(f"{path}: invalid indexed-word pointer table")

    def token_words(token: int) -> int:
        if token < DICTIONARY_TOKEN_START:
            return 1
        offset = (token - DICTIONARY_TOKEN_START) * 8
        length = dictionary_table[offset]
        if not 2 <= length <= 7:
            raise ValueError(f"{path}: invalid dictionary token {token}")
        return length

    longest = 0
    body_words = (len(data) - body_offset) // 2
    for index, start in enumerate(pointers):
        stop = pointers[index + 1] if index + 1 < len(pointers) else body_words
        decoded = 0
        terminated = False
        for position in range(start, stop):
            word = struct.unpack_from(
                ">H",
                data,
                body_offset + position * 2,
            )[0]
            if word == 0x8000:
                decoded += 1
                terminated = True
                break
            first = (word >> 8) - PACKED_TOKEN_BASE
            if 0 <= first < PACKED_TOKEN_RANGE:
                decoded += token_words(first)
                second_byte = word & 0xFF
                if second_byte:
                    second = second_byte - PACKED_TOKEN_BASE
                    if not 0 <= second < PACKED_TOKEN_RANGE:
                        raise ValueError(
                            f"{path}: invalid packed token byte {second_byte:#x}"
                        )
                    decoded += token_words(second)
            else:
                decoded += 1
        if not terminated:
            raise ValueError(f"{path}: record {index} has no terminator")
        if decoded > capacity_words:
            raise ValueError(
                f"{path}: record {index} decodes to {decoded}/"
                f"{capacity_words} scratch words"
            )
        longest = max(longest, decoded)
    return longest


if DICTIONARY_TOKEN_START != 63 or PACKED_TOKEN_BASE != 8 or PACKED_TOKEN_RANGE != 120:
    raise ValueError("packed-record decoder and EVENT dictionary disagree")
