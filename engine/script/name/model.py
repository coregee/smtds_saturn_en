"""FONT16 encoding helpers for player-entered names."""

import json
from functools import cache
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT
from engine.script.name.fields import (
    CODENAME_BYTES,
    FIELD_BY_KIND,
    FIELD_BY_OPCODE,
    MAX_NAME_LENGTH,
    NAME_FIELDS,
    NAME_FW,
    NAME_FW_FULL,
    ROW_STRIDE,
    ROW_WORDS,
    TERMINATOR,
    NameField,
    NameFieldSpec,
)
from engine.script.text_render.font8_metrics import METRICS_PATH, load_metrics

__all__ = (
    "CODENAME_BYTES",
    "FIELD_BY_KIND",
    "FIELD_BY_OPCODE",
    "MAX_NAME_LENGTH",
    "NAME_FIELDS",
    "NAME_FW",
    "NAME_FW_FULL",
    "ROW_STRIDE",
    "ROW_WORDS",
    "TERMINATOR",
    "NameField",
    "NameFieldSpec",
    "byte_to_advance_table",
    "byte_to_atlas_table",
    "byte_to_font8_table",
    "encode_full_name",
    "encode_runtime_row",
    "load_atlas_metrics",
    "load_font8_codes",
)

FONT16_METRICS_PATH = DEFAULT_CONTEXT.font_generated_root / "font16_metrics.json"


@cache
def load_atlas_metrics(
    path: Path = FONT16_METRICS_PATH,
) -> tuple[dict[str, int], dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 2 or not data.get("complete"):
        raise ValueError(f"{path}: incomplete FONT16 metrics")

    codes: dict[str, int] = {}
    advances: dict[str, int] = {}
    for glyph in data["glyphs"]:
        for text in (glyph["text"], *glyph.get("aliases", ())):
            if len(text) == 1:
                codes.setdefault(text, glyph["code"])
                advances.setdefault(text, glyph["advance"])

    required = set(" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    if not required <= set(codes):
        missing = "".join(sorted(required - set(codes)))
        raise ValueError(f"FONT16 name coverage is missing {missing!r}")
    return codes, advances


@cache
def load_font8_codes(path: Path = METRICS_PATH) -> dict[str, int]:
    return load_metrics(path)[1]


def byte_to_atlas_table(
    codes: dict[str, int] | None = None,
) -> tuple[int, ...]:
    """Map every saved byte safely into the current FONT16 atlas."""
    if codes is None:
        codes, _ = load_atlas_metrics()
    fallback = codes["?"]
    table = [fallback] * 256
    table[0] = codes[" "]
    for byte in range(0x20, 0x7F):
        table[byte] = codes.get(chr(byte), fallback)
    return tuple(table)


def byte_to_advance_table(
    advances: dict[str, int] | None = None,
) -> tuple[int, ...]:
    """Map every saved byte to its proportional display advance."""
    if advances is None:
        _, advances = load_atlas_metrics()
    fallback = advances["?"]
    table = [fallback] * 256
    table[0] = 0
    for byte in range(0x20, 0x7F):
        table[byte] = advances.get(chr(byte), fallback)
    return tuple(table)


def byte_to_font8_table(codes: dict[str, int] | None = None) -> bytes:
    """Map saved ASCII names into the relocated narrow FONT8 alphabet."""
    if codes is None:
        codes = load_font8_codes()
    fallback = codes["?"]
    table = bytearray([fallback] * 256)
    table[0] = 0
    for byte in range(0x20, 0x7F):
        table[byte] = codes.get(chr(byte), fallback)
    return bytes(table)


def encode_runtime_row(
    text: str,
    codes: dict[str, int] | None = None,
) -> tuple[int, ...]:
    """Encode one trimmed eight-character name as FONT16 cells plus 0x8000."""
    text = text.rstrip(" \x00")
    if len(text) > MAX_NAME_LENGTH:
        raise ValueError(f"name exceeds {MAX_NAME_LENGTH} characters: {text!r}")
    if codes is None:
        codes, _ = load_atlas_metrics()
    try:
        encoded = tuple(codes[character] for character in text)
    except KeyError as error:
        raise ValueError(f"unsupported name character {error.args[0]!r}") from error
    return (*encoded, TERMINATOR)


def encode_full_name(
    first: str,
    last: str,
    codes: dict[str, int] | None = None,
) -> tuple[int, ...]:
    if codes is None:
        codes, _ = load_atlas_metrics()
    first_codes = encode_runtime_row(first, codes)[:-1]
    last_codes = encode_runtime_row(last, codes)[:-1]
    words = (*first_codes, codes[" "], *last_codes, TERMINATOR)
    if len(words) > MAX_NAME_LENGTH * 2 + 2:
        raise ValueError("combined name exceeds its runtime row")
    return words
