import json
import unittest
from pathlib import Path

from project_paths import TEXT_CORPUS_ROOT
from text.script.dialects import get_dialect
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.fixed_words.repack import encode_fixed_text
from text.script.sources import get_source

SOURCE_PATH = (
    Path(__file__).parents[1] / "script" / "combat" / "asm" / "packed_dispatch.s"
)
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


class CombatPackedDispatchTests(unittest.TestCase):
    def test_low_byte_presence_is_checked_before_removing_the_bias(self) -> None:
        setup = SOURCE[
            SOURCE.index("mov     r8, r12") : SOURCE.index("no_second_token:")
        ]
        second_token = SOURCE[
            SOURCE.index("token_done:") : SOURCE.index("packed_done:")
        ]
        self.assertIn("extu.b  r12, r12", setup)
        self.assertIn("tst     r12, r12", setup)
        self.assertNotIn("add     #-8, r12", setup)
        self.assertIn("tst     r12, r12", second_token)
        self.assertIn("mov     r12, r11", second_token)
        self.assertIn("add     #-8, r11", second_token)

    def test_cyni_refusal_packs_all_four_authored_spaces(self) -> None:
        source = get_source("combat_condition_messages")
        rows = json.loads(
            (TEXT_CORPUS_ROOT / source.corpus_path).read_text(encoding="utf-8")
        )
        translation = next(
            row["tr"] for row in rows if row["kind"] == "talk_blocked_cyni"
        )
        self.assertEqual(translation, "I don't talk to fools.")

        words = encode_fixed_text(
            translation,
            packed=source.packed,
            zero_mode="space",
            latin=load_latin_encoding(),
            dialect=get_dialect(source.dialect),
        )
        space_slots = [
            (index, slot)
            for index, word in enumerate(words)
            for slot, byte in (("high", word >> 8), ("low", word & 0xFF))
            if byte == 0x08
        ]

        # Packed token zero is a space only after the +8 bias. The apostrophe
        # and period are raw words, so the tokens before them legitimately have
        # absent low slots; the four authored spaces must still be biased 0x08.
        self.assertEqual(
            space_slots,
            [(0, "low"), (4, "low"), (7, "high"), (8, "low")],
        )


if __name__ == "__main__":
    unittest.main()
