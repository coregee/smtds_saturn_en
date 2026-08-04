import json
import unittest

from project_paths import TEXT_CORPUS_ROOT
from text.script.dialects import COMBAT_DIALECT
from text.script.encoding.event_codec import EventDictionary
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.eve.extract import extract_bank
from text.script.formats.eve.readers import MenuGroup, find_menu_groups
from text.script.formats.eve.repack import group_corpus_pages, load_validated_corpus
from text.script.layouts.combat import (
    COMBAT_CHOICE_OPTION_LAYOUT,
    RUNTIME_STATIC_HINT_BASE,
    RUNTIME_STATIC_HINT_LIMIT,
    combat_pixel_width,
)
from text.script.message import encode_translation
from text.script.source_models import EveSource
from text.script.sources import get_source


class KemoChoiceAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = get_source("kemo")
        if not isinstance(source, EveSource):
            raise TypeError("kemo must be an EVE source")
        cls.source = source
        cls.rows = json.loads(
            (TEXT_CORPUS_ROOT / source.corpus_path).read_text(encoding="utf-8")
        )
        cls.pages = group_corpus_pages(load_validated_corpus(source, TEXT_CORPUS_ROOT))
        cls.bank = extract_bank(source)

    def test_demon_ethics_prompt_uses_the_complete_affirmative_answer(self) -> None:
        answer = next(
            row
            for row in self.rows
            if {location["message"] for location in row["locations"]} == {176, 209}
        )
        self.assertEqual(answer["tr"], "I think so.")
        self.assertEqual(
            combat_pixel_width(
                answer["tr"],
                load_latin_encoding(),
                COMBAT_CHOICE_OPTION_LAYOUT,
            ),
            53,
        )
        self.assertLessEqual(53, COMBAT_CHOICE_OPTION_LAYOUT.width)

    def test_both_physical_messages_pack_the_complete_answer(self) -> None:
        latin = load_latin_encoding()
        expected = latin.encode("I think so.", COMBAT_DIALECT, normalized=True)
        dictionary = EventDictionary(())
        expected_words = (
            0x1B08,
            0x076B,
            0x4034,
            0x353A,
            0x3708,
            0x0760,
            0x3F3B,
            0x00B0,
            0x8000,
        )
        for message in (176, 209):
            encoded = encode_translation(
                self.source,
                self.bank.messages[message].words,
                self.pages[message],
                event_dictionary=dictionary,
            )
            self.assertIsNotNone(encoded)
            assert encoded is not None
            visible = [
                word
                for word in dictionary.decode_words(encoded.words)
                if word < 0x8000
                and not RUNTIME_STATIC_HINT_BASE <= word < RUNTIME_STATIC_HINT_LIMIT
            ]
            with self.subTest(message=message):
                self.assertEqual(encoded.words, expected_words)
                self.assertEqual(visible, expected)

    def test_stock_scripts_bind_the_shared_answer_to_both_choice_menus(self) -> None:
        groups = find_menu_groups(self.source.input_path.read_bytes(), self.source)
        relevant = tuple(group for group in groups if group.script_index in {189, 219})
        self.assertEqual(
            relevant,
            (
                MenuGroup(
                    script_index=189,
                    word_offset=5,
                    prompt_message=175,
                    lead_messages=(174,),
                    option_messages=(176, 177),
                ),
                MenuGroup(
                    script_index=219,
                    word_offset=5,
                    prompt_message=208,
                    lead_messages=(207,),
                    option_messages=(209, 210),
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
