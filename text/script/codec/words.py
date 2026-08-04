from collections.abc import Iterable

from text.script.codec.atlas import FONT12_GLYPHS, FONT16_GLYPHS
from text.script.dialects import TextDialect, get_dialect
from text.script.profiles import TextFont


def decode_glyph(word: int, font: TextFont = TextFont.FONT16) -> str:
    if font is TextFont.FONT12:
        return FONT12_GLYPHS.get(word, f"{{{word:03x}}}")
    if word == 0:
        return ""
    if word <= 0xFF:
        return FONT12_GLYPHS.get(word, f"{{{word:02x}}}")
    return FONT16_GLYPHS.get(word, f"{{{word:03x}}}")


def decode_words(
    words: Iterable[int],
    dialect: TextDialect,
    font: TextFont = TextFont.FONT16,
) -> str:
    dialect_spec = get_dialect(dialect)
    decoded = []
    for word in words:
        if word & 0x8000:
            decoded.append(dialect_spec.decode_control(word))
        else:
            decoded.append(decode_glyph(word, font))
    return "".join(decoded).strip()
