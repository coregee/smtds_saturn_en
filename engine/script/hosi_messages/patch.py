"""Relocate HOSI's horoscope text without replacing its stock renderer."""

import struct
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.fixed_text_fields.generated import (
    RuntimeWordField,
    load_runtime_fields,
)
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup

HOSI_BASE = 0x06020000
HOSI_SOURCE = Path("HOSI.BIN")
HOSI_TARGET = BinaryTarget("HOSI.BIN", HOSI_SOURCE, HOSI_BASE)
HOSI_ASSET = Path("fixed_words/HOSI.BIN.json")

# The extracted overlay is zero from file 0x0000 through 0x64ff.  Keep the
# first 0x400 bytes reserved like the other overlay runtimes and bound this
# source-owned pool to the following 0x400-byte window.
HOSI_POOL_ADDRESS = 0x06020400
HOSI_POOL_LIMIT = 0x06020800

HOSI_TERMINATOR = 0x8000
HOSI_NEWLINE = 0x8001
HOSI_SPACE = 0x010B
HOSI_LINE_CELLS = 20
HOSI_MAX_LINES = 3
HOSI_MAX_WORDS = 64

# The stock dispatcher reveals one additional source word per tick and gives
# each message twenty ticks.  Scaling its r5 count by four reaches every
# wrapped English record while retaining a progressive reveal.
HOSI_REVEAL_SCALE_SITE = 0x0602D880
HOSI_REVEAL_SCALE_EXPECTED = bytes.fromhex("0009")  # nop (JSR delay slot)
HOSI_REVEAL_SCALE_REPLACEMENT = bytes.fromhex("4508")  # shll2 r5

# (field name, original file offset, pointer-literal address).  Each literal is
# the sole stored pointer for its source record; horoscope_02 has two code
# references to the same literal.
HOSI_FIELDS = (
    ("horoscope_00", 0x10F62, 0x0602D7F8),
    ("horoscope_01", 0x10F8C, 0x0602D7FC),
    ("horoscope_02", 0x10FB6, 0x0602D800),
    ("horoscope_03", 0x10FE0, 0x0602D804),
    ("horoscope_04", 0x1100A, 0x0602D808),
    ("horoscope_05", 0x11034, 0x0602D80C),
    ("horoscope_06", 0x1105E, 0x0602D8AC),
    ("horoscope_07", 0x11088, 0x0602D8B0),
)


def layout_horoscope_words(words: tuple[int, ...]) -> tuple[int, ...]:
    """Insert stock newlines at word boundaries without changing text glyphs."""
    if (
        not words
        or words[-1] != HOSI_TERMINATOR
        or HOSI_TERMINATOR in words[:-1]
        or HOSI_NEWLINE in words
    ):
        raise ValueError("HOSI runtime text must have one final terminator")

    remaining = list(words[:-1])
    lines = []
    while len(remaining) > HOSI_LINE_CELLS:
        boundaries = [
            index
            for index, word in enumerate(remaining[: HOSI_LINE_CELLS + 1])
            if word == HOSI_SPACE and index > 0
        ]
        if not boundaries:
            raise ValueError("HOSI runtime text has a word wider than 20 cells")
        boundary = boundaries[-1]
        lines.append(tuple(remaining[:boundary]))
        remaining = remaining[boundary + 1 :]
    if not remaining:
        raise ValueError("HOSI runtime text cannot end with a space")
    lines.append(tuple(remaining))

    if len(lines) > HOSI_MAX_LINES or any(
        not line or len(line) > HOSI_LINE_CELLS for line in lines
    ):
        raise ValueError("HOSI runtime text exceeds its three 20-cell rows")

    reconstructed_words = []
    laid_out_words = []
    for index, line in enumerate(lines):
        if index:
            reconstructed_words.append(HOSI_SPACE)
            laid_out_words.append(HOSI_NEWLINE)
        reconstructed_words.extend(line)
        laid_out_words.extend(line)

    reconstructed = tuple(reconstructed_words)
    if reconstructed != words[:-1]:
        raise ValueError("HOSI layout controls changed the source text")

    laid_out = (*laid_out_words, HOSI_TERMINATOR)
    if len(laid_out) > HOSI_MAX_WORDS:
        raise ValueError("HOSI runtime text exceeds its reveal limit")
    return laid_out


def build_hosi_pool(
    fields: tuple[RuntimeWordField, ...],
) -> tuple[bytes, dict[str, int], dict[str, tuple[int, ...]]]:
    """Build the relocated message pool and return each record address/layout."""
    expected = {name: offset for name, offset, _literal in HOSI_FIELDS}
    by_name = {field.name: field for field in fields}
    if len(by_name) != len(fields) or set(by_name) != set(expected):
        raise ValueError("HOSI runtime asset does not define the eight messages")

    payload = bytearray()
    addresses = {}
    layouts = {}
    for name, offset, _literal in HOSI_FIELDS:
        field = by_name[name]
        if field.file_offset != offset:
            raise ValueError(f"HOSI runtime field {name!r} moved in the source")
        laid_out = layout_horoscope_words(field.words)
        addresses[name] = HOSI_POOL_ADDRESS + len(payload)
        layouts[name] = laid_out
        payload.extend(struct.pack(f">{len(laid_out)}H", *laid_out))

    if HOSI_POOL_ADDRESS + len(payload) > HOSI_POOL_LIMIT:
        raise ValueError("HOSI runtime text exceeds its verified zero window")
    return bytes(payload), addresses, layouts


def build_hosi_group(
    load_address: int,
    fields: tuple[RuntimeWordField, ...],
) -> PatchGroup:
    """Compose the source-bound pool, pointer literals, and reveal scaling."""
    if load_address != HOSI_BASE:
        raise ValueError(f"HOSI runtime asset has wrong load address {load_address:#x}")
    payload, addresses, _layouts = build_hosi_pool(fields)
    patches = [
        BytePatch(
            "hosi_message_pool",
            HOSI_POOL_ADDRESS,
            bytes(len(payload)),
            payload,
        )
    ]
    for name, offset, literal in HOSI_FIELDS:
        patches.append(
            BytePatch(
                f"{name}_pointer",
                literal,
                struct.pack(">I", HOSI_BASE + offset),
                struct.pack(">I", addresses[name]),
            )
        )
    patches.append(
        BytePatch(
            "hosi_reveal_scale",
            HOSI_REVEAL_SCALE_SITE,
            HOSI_REVEAL_SCALE_EXPECTED,
            HOSI_REVEAL_SCALE_REPLACEMENT,
        )
    )
    return PatchGroup("hosi_messages", HOSI_TARGET, tuple(patches))


def build_patch_groups(
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> PatchGroup:
    load_address, fields = load_runtime_fields(
        HOSI_ASSET,
        context.text_generated_root,
        context.extracted_root,
        expected_source=HOSI_SOURCE,
        max_words=HOSI_MAX_WORDS,
    )
    return build_hosi_group(load_address, fields)
