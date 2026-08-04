"""Generated fusion text loading, encoding, and layout validation."""

import json
import re
import struct
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT
from engine.script.demon_sort import encode_sorted_pool
from engine.script.fusion_menu.model import (
    GUIDE_FIRST_MESSAGE,
    GUIDE_GLYPH_LIMIT,
    GUIDE_LAST_MESSAGE,
    GUIDE_LINE_WIDTH,
    GUIDE_ROW_HEIGHT,
    GUIDE_STOCK_ROWS,
    HELP_FIRST_MESSAGE,
    HELP_GLYPH_LIMIT,
    HELP_LAST_MESSAGE,
    HELP_LINE_WIDTH,
)
from engine.script.generated_asset import load_runtime_ui

TERMINATOR = 0xFF
GUIDE_GLYPH_TOKEN = re.compile(r"\{GLYPH:([0-9a-fA-F]{4})\}")


def runtime_rows(name: str) -> list[dict]:
    rows = load_runtime_ui(DEFAULT_CONTEXT).section(name)
    if not isinstance(rows, list):
        raise ValueError(f"runtime UI section {name!r} must be an array")
    return rows


def load_codes(metrics_path: Path) -> dict[str, int]:
    document = json.loads(metrics_path.read_text(encoding="utf-8"))
    if document.get("version") != 2 or not document.get("complete"):
        raise ValueError(f"{metrics_path}: incomplete FONT12 metrics")
    codes = {}
    for glyph in document["glyphs"]:
        for text in (glyph["text"], *glyph.get("aliases", ())):
            if len(text) == 1:
                codes.setdefault(text, glyph["code"])
    return codes


def load_names(rows: list[dict], context: str) -> tuple[str, ...]:
    if [row.get("record") for row in rows] != list(range(len(rows))):
        raise ValueError(f"{context}: records are not contiguous")
    names = tuple(row.get("tr", "").strip() for row in rows)
    if not all(names):
        raise ValueError(f"{context}: every fusion name needs translated text")
    return names


def load_races(rows: list[dict] | None = None) -> tuple[str, ...]:
    rows = rows or runtime_rows("status_tables")
    races = tuple(row.get("tr", "").strip() for row in rows if row["table"] == "races")
    if len(races) != 43 or not all(races):
        raise ValueError("runtime UI contract: expected 43 translated races")
    # Fusion's compact race bank uses Time in its final slot. The general
    # NORMCOM race table uses Human there, so this screen-local value must not
    # be inferred from the general-purpose table.
    return (*races[:-1], "Time")


def encode_pool(names: tuple[str, ...], codes: dict[str, int]) -> tuple[bytes, bytes]:
    offsets = []
    pool = bytearray()
    for name in names:
        offsets.append(len(pool))
        try:
            encoded = bytes(codes[character] for character in name)
        except KeyError as error:
            raise ValueError(
                f"unsupported FONT12 character {error.args[0]!r} in {name!r}"
            ) from error
        pool.extend(encoded)
        pool.append(TERMINATOR)
    if len(pool) > 0xFFFF:
        raise ValueError("fusion name pool exceeds 16-bit offsets")
    return struct.pack(f">{len(offsets)}H", *offsets), bytes(pool)


def encode_demon_sort_pool(
    names: tuple[str, ...],
    codes: dict[str, int],
) -> tuple[bytes, bytes]:
    """Pack demon names so their u16 offsets are English collation ranks."""
    return encode_sorted_pool(names, codes)


def build_font8_code_map(
    names: tuple[str, ...],
    font12_codes: dict[str, int],
    font8_codes: dict[str, int],
) -> bytes:
    """Translate the shared FONT12 name pool into the table's FONT8 cells."""
    code_map = bytearray([0xFF] * 256)
    requested = set("".join(names))
    for character in set(font12_codes) & set(font8_codes):
        code12 = font12_codes.get(character)
        code8 = font8_codes.get(character)
        if code12 is None or not 0 <= code12 < len(code_map):
            raise ValueError(f"fusion FONT12 pool has no byte code for {character!r}")
        if code8 is None or not 0 <= code8 < 256:
            raise ValueError(f"fusion FONT8 table has no byte code for {character!r}")
        existing = code_map[code12]
        if existing not in (0xFF, code8):
            raise ValueError(
                "fusion FONT12 byte maps to multiple FONT8 cells: "
                f"{code12:#x} -> {existing:#x}/{code8:#x}"
            )
        code_map[code12] = code8
    missing = sorted(
        character
        for character in requested
        if font12_codes.get(character) is None
        or code_map[font12_codes[character]] == 0xFF
    )
    if missing:
        raise ValueError(
            f"fusion FONT8 table cannot map characters {''.join(missing)!r}"
        )
    return bytes(code_map)


def load_optional_lines(
    rows: list[dict],
    first_message: int,
    last_message: int,
    label: str,
) -> tuple[str, ...] | None:
    by_message = {}
    for row in rows:
        for location in row.get("locations", ()):
            message = location["message"]
            if first_message <= message <= last_message:
                if message in by_message:
                    raise ValueError(
                        f"runtime UI contract: duplicate {label} message {message}"
                    )
                by_message[message] = row.get("tr", "").strip()
    expected = set(range(first_message, last_message + 1))
    if set(by_message) != expected:
        missing = sorted(expected - set(by_message))
        raise ValueError(
            f"runtime UI contract: incomplete {label} lines; missing {missing}"
        )
    lines = tuple(by_message[message] for message in sorted(by_message))
    if not any(lines):
        return None
    if not all(lines):
        missing = [message for message in sorted(by_message) if not by_message[message]]
        raise ValueError(
            f"runtime UI contract: partially translated {label} lines; "
            f"missing translations {missing}"
        )
    return lines


def load_optional_guide_lines(
    rows: list[dict] | None = None,
) -> tuple[str, ...] | None:
    rows = rows or runtime_rows("fusion_messages")
    return load_optional_lines(
        rows,
        GUIDE_FIRST_MESSAGE,
        GUIDE_LAST_MESSAGE,
        "Guide",
    )


def load_guide_lines(rows: list[dict] | None = None) -> tuple[str, ...]:
    lines = load_optional_guide_lines(rows)
    if lines is None:
        raise ValueError("runtime UI contract: Guide lines have no translations")
    return lines


def load_optional_help_lines(
    rows: list[dict] | None = None,
) -> tuple[str, ...] | None:
    rows = rows or runtime_rows("fusion_messages")
    return load_optional_lines(
        rows,
        HELP_FIRST_MESSAGE,
        HELP_LAST_MESSAGE,
        "Help",
    )


def load_help_lines(rows: list[dict] | None = None) -> tuple[str, ...]:
    lines = load_optional_help_lines(rows)
    if lines is None:
        raise ValueError("runtime UI contract: Help lines have no translations")
    return lines


def guide_line_metrics(
    text: str,
    row_index: int,
    font12_codes: dict[str, int],
    font8_widths: bytes,
    font8_code_map: bytes,
    font8_space: int,
) -> tuple[int, int]:
    """Measure the direct words consumed by the Guide's mixed glyph callback."""
    normalized = " ".join(text.split())
    normalized = re.sub(r"([.!?])([A-Za-z{])", r"\1 \2", normalized)
    glyphs: list[int] = []
    position = 0
    while position < len(normalized):
        token = GUIDE_GLYPH_TOKEN.match(normalized, position)
        if token is not None:
            glyphs.append(int(token.group(1), 16))
            position = token.end()
            continue
        character = normalized[position]
        if character in "{}":
            raise ValueError(f"unknown Guide token in {text!r}")
        try:
            glyphs.append(font12_codes[character])
        except KeyError as error:
            raise ValueError(
                f"unsupported FONT12 character {character!r} in Guide line {text!r}"
            ) from error
        position += 1

    width = 0
    for glyph_index, glyph in enumerate(glyphs):
        if row_index < GUIDE_STOCK_ROWS and glyph_index == 0:
            width += GUIDE_ROW_HEIGHT
            continue
        code8 = font8_code_map[glyph] if glyph < len(font8_code_map) else 0xFF
        if code8 == 0xFF:
            width += 12
        else:
            width += font8_widths[code8] + (code8 != font8_space)
    return len(glyphs), width


def validate_guide_lines(
    rows: list[dict],
    font12_codes: dict[str, int],
    font8_widths: bytes,
    font8_code_map: bytes,
    font8_space: int,
) -> None:
    for row_index, text in enumerate(load_guide_lines(rows)):
        glyphs, width = guide_line_metrics(
            text,
            row_index,
            font12_codes,
            font8_widths,
            font8_code_map,
            font8_space,
        )
        if glyphs > GUIDE_GLYPH_LIMIT:
            raise ValueError(
                f"fusion Guide line {text!r} exceeds "
                f"{GUIDE_GLYPH_LIMIT} glyphs: {glyphs}"
            )
        if width > GUIDE_LINE_WIDTH:
            raise ValueError(
                f"fusion Guide line {text!r} exceeds {GUIDE_LINE_WIDTH}px: {width}px"
            )


def help_line_metrics(
    text: str,
    font12_codes: dict[str, int],
    font8_widths: bytes,
    font8_code_map: bytes,
    font8_space: int,
) -> tuple[int, int]:
    """Measure a direct Help line using the shared FONT8 callback contract."""
    width = 0
    for character in text:
        try:
            glyph = font12_codes[character]
        except KeyError as error:
            raise ValueError(
                f"unsupported FONT12 character {character!r} in Help line {text!r}"
            ) from error
        code8 = font8_code_map[glyph] if glyph < len(font8_code_map) else 0xFF
        if code8 == 0xFF:
            raise ValueError(
                f"unmapped FONT8 character {character!r} in Help line {text!r}"
            )
        width += font8_widths[code8] + (code8 != font8_space)
    return len(text), width


def validate_help_lines(
    rows: list[dict],
    font12_codes: dict[str, int],
    font8_widths: bytes,
    font8_code_map: bytes,
    font8_space: int,
) -> None:
    for text in load_help_lines(rows):
        glyphs, width = help_line_metrics(
            text,
            font12_codes,
            font8_widths,
            font8_code_map,
            font8_space,
        )
        if glyphs > HELP_GLYPH_LIMIT:
            raise ValueError(
                f"fusion Help line {text!r} exceeds {HELP_GLYPH_LIMIT} glyphs: {glyphs}"
            )
        if width > HELP_LINE_WIDTH:
            raise ValueError(
                f"fusion Help line {text!r} exceeds {HELP_LINE_WIDTH}px: {width}px"
            )
