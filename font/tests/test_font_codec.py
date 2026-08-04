import unittest

from PIL import Image

from font.script.util.font_codec import (
    FontSpec,
    decode_glyph,
    encode_glyph,
    glyph_count,
    parse_decimal_index,
)


class FontCodecTests(unittest.TestCase):
    def test_packed_glyph_round_trip_preserves_quantized_pixels(self) -> None:
        spec = FontSpec(
            "TEST.FON", width=4, height=2, bpp=2, row_stride=1, glyph_stride=2
        )
        original = bytearray((0b00011011, 0b11100100))
        glyph = decode_glyph(original, spec, 0)
        rebuilt = bytearray(2)
        encode_glyph(rebuilt, spec, 0, glyph)
        self.assertEqual(rebuilt, original)

    def test_encoder_rejects_wrong_glyph_dimensions(self) -> None:
        spec = FontSpec(
            "TEST.FON", width=4, height=2, bpp=2, row_stride=1, glyph_stride=2
        )
        with self.assertRaisesRegex(ValueError, "expected 4x2"):
            encode_glyph(bytearray(2), spec, 0, Image.new("L", (3, 2)))

    def test_config_indices_and_font_lengths_are_strict(self) -> None:
        self.assertEqual(parse_decimal_index("12", "test"), 12)
        for value in (True, "0x10", -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_decimal_index(value, "test")
        with self.assertRaisesRegex(ValueError, "after its last complete glyph"):
            glyph_count(b"\0\0\0", FontSpec("TEST.FON", 4, 2, 2, 1, 2))


if __name__ == "__main__":
    unittest.main()
