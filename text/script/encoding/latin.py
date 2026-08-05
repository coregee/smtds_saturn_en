import json
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

from project_paths import FONT_GENERATED_ROOT
from text.script.dialects import DialectSpec
from text.script.encoding.tokens import normalize_english, parse_inline_tokens

DEFAULT_METRICS_PATH = FONT_GENERATED_ROOT / "font16_metrics.json"
FONT12_METRICS_PATH = FONT_GENERATED_ROOT / "font12_metrics.json"
PACKED_TOKEN_BASE = 8
PACKED_CODE_LIMIT = 120
PACKED_SPACE_CODE = 267


@dataclass(frozen=True)
class LatinGlyph:
    text: str
    code: int
    advance: int
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class LatinEncoding:
    font: str
    glyphs: tuple[LatinGlyph, ...]

    @cached_property
    def by_text(self) -> dict[str, LatinGlyph]:
        mapping = {}
        for glyph in self.glyphs:
            for text in (glyph.text, *glyph.aliases):
                mapping.setdefault(text, glyph)
        return mapping

    @cached_property
    def compound_glyphs(self) -> tuple[tuple[str, LatinGlyph], ...]:
        return tuple(
            sorted(
                (
                    (text, glyph)
                    for text, glyph in self.by_text.items()
                    if len(text) > 1
                ),
                key=lambda item: (-len(item[0]), item[1].code),
            )
        )

    def segment_glyphs(self, text: str) -> tuple[LatinGlyph, ...]:
        glyphs = self.by_text
        compounds = self.compound_glyphs
        output = []
        position = 0

        while position < len(text):
            compound = next(
                (
                    (token, glyph)
                    for token, glyph in compounds
                    if text.startswith(token, position)
                ),
                None,
            )
            if compound is not None:
                token, glyph = compound
                output.append(glyph)
                position += len(token)
                continue

            character = text[position]
            try:
                output.append(glyphs[character])
            except KeyError as error:
                raise ValueError(
                    f"unsupported translation character {character!r}"
                ) from error
            position += 1
        return tuple(output)

    def encode_segment(
        self,
        text: str,
        *,
        packed: bool = False,
        pack_codes=None,
    ) -> list[int]:
        codes = [glyph.code for glyph in self.segment_glyphs(text)]
        if pack_codes is not None:
            return pack_codes(codes)
        if not packed:
            return codes
        return pack_direct_codes(codes)

    def measure_segment(self, text: str) -> int:
        return sum(glyph.advance for glyph in self.segment_glyphs(text))

    def encode(
        self,
        text: str,
        dialect: DialectSpec,
        *,
        packed: bool = False,
        pack_codes=None,
        normalized: bool = False,
    ) -> list[int]:
        output = []
        source = text if normalized else normalize_english(text)
        for line_index, line in enumerate(source.split("\n")):
            if line_index:
                output.append(0x8001)
            for part in parse_inline_tokens(line, dialect):
                if isinstance(part, int):
                    output.append(part)
                else:
                    output.extend(
                        self.encode_segment(
                            part,
                            packed=packed,
                            pack_codes=pack_codes,
                        )
                    )
        return output

    def measure(self, text: str, dialect: DialectSpec, insert_width) -> int:
        width = 0
        for part in parse_inline_tokens(text, dialect):
            if isinstance(part, int):
                width += insert_width(part)
            else:
                width += self.measure_segment(part)
        return width


def pack_direct_codes(codes: list[int]) -> list[int]:
    """Pair compact atlas codes, using packed zero for the nonzero space cell."""
    output = []
    direct = []

    def flush() -> None:
        for position in range(0, len(direct), 2):
            first = direct[position] + PACKED_TOKEN_BASE
            second = (
                direct[position + 1] + PACKED_TOKEN_BASE
                if position + 1 < len(direct)
                else 0
            )
            output.append(first << 8 | second)
        direct.clear()

    for code in codes:
        packed_code = 0 if code == PACKED_SPACE_CODE else code
        if 0 <= packed_code < PACKED_CODE_LIMIT:
            direct.append(packed_code)
        else:
            flush()
            output.append(code)
    flush()
    return output


@lru_cache(maxsize=None)
def load_latin_encoding(path: Path = DEFAULT_METRICS_PATH) -> LatinEncoding:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(
            f"missing Latin metrics {path}; repack FONT16.FON first"
        ) from error

    if data.get("version") != 2:
        raise ValueError(f"{path}: unsupported metrics version")
    if not data.get("complete"):
        missing = data.get("missing_codes", ())
        raise ValueError(f"{path}: incomplete metrics; missing codes {missing}")

    table = data["width_table"]
    storage_glyph = table.get("storage_glyph")
    code_limit = table["code_limit"]
    if storage_glyph is not None and (
        not isinstance(storage_glyph, int) or storage_glyph < 0
    ):
        raise ValueError(f"{path}: invalid width-table storage glyph")
    if not isinstance(code_limit, int) or code_limit <= 0:
        raise ValueError(f"{path}: invalid width-table code limit")

    glyphs = tuple(
        LatinGlyph(
            text=row["text"],
            code=row["code"],
            advance=row["advance"],
            aliases=tuple(row.get("aliases", ())),
        )
        for row in data["glyphs"]
    )
    if len({glyph.code for glyph in glyphs}) != len(glyphs):
        raise ValueError(f"{path}: duplicate glyph codes")
    if any(not 0 <= glyph.code < code_limit for glyph in glyphs):
        raise ValueError(f"{path}: glyph code exceeds the width table")
    if any(not 1 <= glyph.advance <= 0xFF for glyph in glyphs):
        raise ValueError(f"{path}: invalid glyph advance")

    encoding = LatinEncoding(
        font=data["font"],
        glyphs=glyphs,
    )
    required = set(" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    if not required <= set(encoding.by_text):
        missing = "".join(sorted(required - set(encoding.by_text)))
        raise ValueError(f"{path}: basic Latin coverage is missing {missing!r}")
    return encoding


@lru_cache(maxsize=1)
def load_font12_encoding() -> LatinEncoding:
    """Load proportional metrics for FONT12-backed EVE messages."""
    return load_latin_encoding(FONT12_METRICS_PATH)
