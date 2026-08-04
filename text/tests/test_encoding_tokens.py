import unittest

from text.script.codec.words import decode_glyph
from text.script.dialects import COMBAT_DIALECT
from text.script.encoding.latin import load_latin_encoding
from text.script.encoding.tokens import parse_inline_tokens
from text.script.layouts.combat import combat_pixel_width


class StockGlyphTokenTests(unittest.TestCase):
    def test_source_maru_symbol_round_trips_its_stock_font16_cell(self) -> None:
        self.assertEqual(decode_glyph(0x0106), "{maru_symbol}")
        self.assertEqual(
            parse_inline_tokens("{maru_symbol}", COMBAT_DIALECT),
            (0x0106,),
        )
        self.assertEqual(
            combat_pixel_width("{maru_symbol}", load_latin_encoding()),
            16,
        )

    def test_source_outline_heart_uses_its_stock_font16_cell(self) -> None:
        source_character = "\u300e"

        self.assertEqual(
            parse_inline_tokens(source_character, COMBAT_DIALECT),
            (0x0105,),
        )
        self.assertEqual(
            combat_pixel_width(source_character, load_latin_encoding()),
            16,
        )


if __name__ == "__main__":
    unittest.main()
