import unittest

from text.script.encoding.latin import load_latin_encoding
from text.script.formats.eve.model import EveMessage
from text.script.formats.eve.pages import split_pages
from text.script.layouts.combat import (
    COMBAT_DIALOGUE_LAYOUT,
    RUNTIME_SOFT_WRAP_CODE,
    combat_pixel_width,
    wrap_combat_lines,
)
from text.script.message import encode_translation
from text.script.sources import get_source


class CombatLayoutTests(unittest.TestCase):
    def test_unmapped_raw_glyph_uses_the_runtime_fixed_advance(self) -> None:
        encoding = load_latin_encoding()
        self.assertEqual(
            combat_pixel_width("A{GLYPH:010d}", encoding),
            encoding.measure_segment("A") + 16,
        )

    def test_message_encoder_preserves_exact_stock_combat_boundaries(self) -> None:
        encoded = encode_translation(
            get_source("cld_f"),
            (0x0041, 0x8002, 0x0042, 0x8003, 0x8000),
            [
                {"message": 0, "page": 0, "tr": "First page."},
                {"message": 0, "page": 1, "tr": "Second page."},
            ],
        )

        self.assertIsNotNone(encoded)
        message = EveMessage(
            index=0,
            start_word=0,
            end_word=len(encoded.words),
            file_offset=0,
            words=encoded.words,
        )
        self.assertEqual(
            tuple(page.boundary_codes for page in split_pages(message)),
            ((0x8002,), (0x8003, 0x8000)),
        )

    def test_combat_overflow_remains_runtime_paginated(self) -> None:
        text = " ".join(["WWWWWWWW"] * 20)
        encoding = load_latin_encoding()
        wrapped_lines = wrap_combat_lines(text, encoding)
        encoded = encode_translation(
            get_source("cld_f"),
            (0x0041, 0x8000),
            [{"message": 0, "page": 0, "tr": text}],
        )

        self.assertGreater(
            len(wrapped_lines),
            COMBAT_DIALOGUE_LAYOUT.lines_per_page,
        )
        self.assertIsNotNone(encoded)
        self.assertEqual(
            encoded.words.count(RUNTIME_SOFT_WRAP_CODE),
            len(wrapped_lines) - 1,
        )
        self.assertNotIn(0x8002, encoded.words)


if __name__ == "__main__":
    unittest.main()
