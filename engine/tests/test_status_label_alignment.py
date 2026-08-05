import struct
import unittest
from unittest.mock import patch

from engine.script.status_ui.assets import direct_color_row, font8_pixels, read_font8
from engine.script.status_ui.data import derived_rows, status_labels
from engine.script.status_ui.model import PERSONALITY_LABELS


class StatusLabelAlignmentTests(unittest.TestCase):
    def test_static_status_rows_start_two_pixels_lower(self) -> None:
        with patch(
            "engine.script.status_ui.assets.font8_pixels",
            return_value=([(0, 0)], 1),
        ):
            row = direct_color_row("x", b"")

        pixels = struct.unpack(f">{len(row) // 2}H", row)
        self.assertTrue(all(value == 0 for value in pixels[: 4 * 48]))
        self.assertEqual(pixels[4 * 48 + 1], 0xFFFF)
        self.assertEqual(pixels[5 * 48 + 2], 0x8000)

    def test_every_shifted_static_term_and_shadow_fits_its_row(self) -> None:
        font8 = read_font8()
        labels = status_labels()
        texts = [" ".join(row) for row in derived_rows(labels)]
        texts.extend(("Attack", "Accuracy", *PERSONALITY_LABELS))

        for text in texts:
            with self.subTest(text=text):
                pixels, _advance = font8_pixels(text, font8)
                self.assertTrue(pixels)
                self.assertLess(4 + max(y for _x, y in pixels) + 1, 12)


if __name__ == "__main__":
    unittest.main()
