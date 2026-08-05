"""Import-safe loaders for the shared generated FONT12/FONT16 metadata."""

import json
from functools import cache
from pathlib import Path
from typing import Any

from engine.script.context import DEFAULT_CONTEXT

BUILD_ROOT = DEFAULT_CONTEXT.build_root
FONT_GENERATED_ROOT = DEFAULT_CONTEXT.font_generated_root

FONT16_METRICS_PATH = FONT_GENERATED_ROOT / "font16_metrics.json"
FONT12_METRICS_PATH = FONT_GENERATED_ROOT / "font12_metrics.json"
FONT12_PATH = BUILD_ROOT / "FONT12.FON"
FONT16_PATH = BUILD_ROOT / "FONT16.FON"
FONT12_DIALOGUE_SPACE = 267


def load_font16_metrics(
    path: Path = FONT16_METRICS_PATH,
) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 2:
        raise ValueError(f"{path}: expected metrics version 2")
    table = document.get("width_table")
    glyphs = document.get("glyphs")
    if not isinstance(table, dict) or not isinstance(glyphs, list):
        raise ValueError(f"{path}: invalid FONT16 metrics")
    storage_glyph = table.get("storage_glyph")
    code_limit = table.get("code_limit")
    if not isinstance(storage_glyph, int) or storage_glyph < 0:
        raise ValueError(f"{path}: invalid FONT16 width-table storage glyph")
    if not isinstance(code_limit, int) or not 1 <= code_limit <= 0x7FFF:
        raise ValueError(f"{path}: invalid FONT16 width-table limit")
    return document


def load_font12_metrics(
    path: Path = FONT12_METRICS_PATH,
) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 2 or not document.get("complete"):
        raise ValueError(f"{path}: expected complete metrics version 2")
    if not isinstance(document.get("glyphs"), list):
        raise ValueError(f"{path}: invalid FONT12 metrics")
    return document


def font16_width_layout(document: dict[str, Any]) -> tuple[int, int]:
    """Return the runtime code limit and byte offset of the embedded widths."""
    table = document["width_table"]
    return table["code_limit"], table["storage_glyph"] * 32


def build_font12_dialogue_widths(document: dict[str, Any]) -> bytes:
    widths = bytearray(FONT12_DIALOGUE_SPACE + 1)
    for glyph in document["glyphs"]:
        code = glyph.get("code")
        advance = glyph.get("advance")
        if not isinstance(code, int) or not 0 <= code < len(widths):
            raise ValueError("invalid FONT12 glyph code")
        if not isinstance(advance, int) or not 0 <= advance <= 0xFF:
            raise ValueError(f"invalid FONT12 advance for glyph {code}")
        widths[code] = advance
    # Raw FONT12 encodes space as zero. Word-based wrappers can receive the
    # shared FONT16 blank code and normalize it before drawing, so retain the
    # same advance for that code as well.
    widths[FONT12_DIALOGUE_SPACE] = widths[0]
    return bytes(widths)


def find_font12_signature(
    font12: bytes,
    font16: bytes,
    glyph_code: int = 11,
) -> tuple[int, int]:
    """Choose a loaded byte that distinguishes FONT12 from FONT16."""
    record_start = glyph_code * 32
    font12_record = font12[record_start : record_start + 32]
    font16_record = font16[record_start : record_start + 32]
    for offset, (font12_byte, font16_byte) in enumerate(
        zip(font12_record, font16_record)
    ):
        if font12_byte != font16_byte and 0 < font12_byte < 0x80:
            return record_start + offset, font12_byte
    for offset, (font12_byte, font16_byte) in enumerate(zip(font12, font16)):
        if font12_byte != font16_byte and 0 < font12_byte < 0x80:
            return offset, font12_byte
    raise ValueError("FONT12/FONT16 glyph signature is not distinguishable")


@cache
def font16_metrics(path: Path = FONT16_METRICS_PATH) -> dict[str, Any]:
    """Load and cache FONT16 metrics from an explicit generated path."""
    return load_font16_metrics(path)


@cache
def font12_metrics(path: Path = FONT12_METRICS_PATH) -> dict[str, Any]:
    """Load and cache FONT12 metrics from an explicit generated path."""
    return load_font12_metrics(path)


@cache
def font12_dialogue_widths(path: Path = FONT12_METRICS_PATH) -> bytes:
    return build_font12_dialogue_widths(font12_metrics(path))


@cache
def font12_signature(
    font12_path: Path = FONT12_PATH,
    font16_path: Path = FONT16_PATH,
) -> tuple[int, int]:
    return find_font12_signature(
        font12_path.read_bytes(),
        font16_path.read_bytes(),
    )
