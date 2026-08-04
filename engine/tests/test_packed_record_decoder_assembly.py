import unittest
from pathlib import Path

SOURCE_PATH = (
    Path(__file__).parents[1]
    / "script"
    / "text_render"
    / "asm"
    / "packed_record_decoder.s"
)
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


class PackedRecordDecoderAssemblyTests(unittest.TestCase):
    def test_second_slot_space_remains_distinct_from_an_absent_token(self) -> None:
        # A zero low byte means no second token. A low byte of 8 is biased
        # token zero (space), so the decoder must not remove the bias until
        # after it has tested whether the byte is present.
        setup = SOURCE[
            SOURCE.index("mov     r8, r9") : SOURCE.index("no_second_token:")
        ]
        second_token = SOURCE[
            SOURCE.index("token_done:") : SOURCE.index("copy_raw_word:")
        ]
        self.assertNotIn("add     #-8, r9", setup)
        self.assertIn("tst     r9, r9", second_token)
        self.assertIn("mov     r9, r8", second_token)
        self.assertIn("add     #-8, r8", second_token)


if __name__ == "__main__":
    unittest.main()
