import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from text.script.formats.eve.extract import extract_corpus
from text.script.formats.eve.model import EveBank
from text.script.formats.eve.readers import (
    SCRIPT_BODY_OFFSET,
    SCRIPT_TABLE_OFFSET,
    MenuGroup,
    find_menu_groups,
    find_raw_u16_messages,
)
from text.script.profiles import COMBAT_DIALOGUE, EVENT_DIALOGUE
from text.script.source_models import EveSource


class EveBankTests(unittest.TestCase):
    TABLE_OFFSET = 0x04
    BODY_OFFSET = 0x10

    @classmethod
    def source_data(cls) -> bytes:
        data = bytearray(0x30)
        data[: cls.TABLE_OFFSET] = b"HEAD"
        struct.pack_into(">3H", data, cls.TABLE_OFFSET, 0, 2, 0xFFFF)
        struct.pack_into(
            ">5H",
            data,
            cls.BODY_OFFSET,
            0x0041,
            0x8000,
            0x0042,
            0x8003,
            0x8000,
        )
        return bytes(data)

    def test_each_pointer_starts_a_message_and_final_terminator_ends_body(
        self,
    ) -> None:
        source_data = self.source_data()
        bank = EveBank.parse(source_data, self.TABLE_OFFSET, self.BODY_OFFSET)

        self.assertEqual(bank.pointers, (0, 2))
        self.assertEqual(
            [message.words for message in bank.messages],
            [(0x0041, 0x8000), (0x0042, 0x8003, 0x8000)],
        )
        self.assertEqual(bank.body_size_bytes, 10)
        self.assertEqual(
            bank.body_bytes(),
            source_data[self.BODY_OFFSET : self.BODY_OFFSET + 10],
        )

    def test_identity_rebuild_preserves_final_message_and_zero_padding(self) -> None:
        source_data = self.source_data()
        bank = EveBank.parse(source_data, self.TABLE_OFFSET, self.BODY_OFFSET)

        rebuilt = bank.rebuild(
            source_data,
            [message.words for message in bank.messages],
        )

        self.assertEqual(rebuilt, source_data)

    def test_rebuild_writes_only_message_start_pointers(self) -> None:
        source_data = self.source_data()
        bank = EveBank.parse(source_data, self.TABLE_OFFSET, self.BODY_OFFSET)

        rebuilt = bank.rebuild(
            source_data,
            [
                (0x0041, 0x0042, 0x8000),
                (0x0043, 0x8003, 0x8000),
            ],
        )

        self.assertEqual(
            struct.unpack_from(">3H", rebuilt, self.TABLE_OFFSET),
            (0, 3, 0xFFFF),
        )
        reparsed = EveBank.parse(rebuilt, self.TABLE_OFFSET, self.BODY_OFFSET)
        self.assertEqual(len(reparsed.messages), 2)
        self.assertEqual(reparsed.body_size_bytes, 12)
        self.assertFalse(any(rebuilt[self.BODY_OFFSET + 12 :]))

    def test_final_message_requires_a_terminator(self) -> None:
        data = bytearray(0x20)
        struct.pack_into(">2H", data, self.TABLE_OFFSET, 0, 0xFFFF)
        struct.pack_into(">H", data, self.BODY_OFFSET, 0x0041)

        with self.assertRaisesRegex(ValueError, "final message has no 0x8000"):
            EveBank.parse(bytes(data), self.TABLE_OFFSET, self.BODY_OFFSET)


class EveScriptReaderTests(unittest.TestCase):
    TEXT_TABLE_OFFSET = 0x840

    @classmethod
    def source(cls) -> EveSource:
        return EveSource(
            name="fixture",
            path=Path("FIXTURE.EVE"),
            default_profile=EVENT_DIALOGUE,
            table_offset=cls.TEXT_TABLE_OFFSET,
            body_offset=0x880,
            corpus_path=Path("eve/FIXTURE.EVE.json"),
            detect_menu_readers=True,
        )

    @classmethod
    def combat_source(cls) -> EveSource:
        return EveSource(
            name="combat_fixture",
            path=Path("COMBDATA/FIXTURE.EVE"),
            default_profile=COMBAT_DIALOGUE,
            table_offset=cls.TEXT_TABLE_OFFSET,
            body_offset=0x880,
            corpus_path=Path("eve/FIXTURE.EVE.json"),
        )

    @staticmethod
    def script_data(pointers: tuple[int, ...]) -> bytearray:
        data = bytearray(0x900)
        struct.pack_into(
            f">{len(pointers) + 1}H",
            data,
            SCRIPT_TABLE_OFFSET,
            *pointers,
            0xFFFF,
        )
        return data

    @classmethod
    def add_message_bank(cls, data: bytearray, count: int) -> None:
        struct.pack_into(
            f">{count + 1}H",
            data,
            cls.TEXT_TABLE_OFFSET,
            *range(count),
            0xFFFF,
        )
        struct.pack_into(f">{count}H", data, 0x880, *([0x8000] * count))

    def test_final_script_block_is_scanned(self) -> None:
        data = self.script_data((0, 2))
        struct.pack_into(">4H", data, SCRIPT_BODY_OFFSET + 4, 3, 1, 7, 0)

        self.assertEqual(find_raw_u16_messages(bytes(data), self.source()), {7})

    def test_menu_can_target_final_script_index(self) -> None:
        data = self.script_data((0, 4))
        struct.pack_into(">4H", data, SCRIPT_BODY_OFFSET, 3, 1, 9, 1)

        self.assertEqual(find_raw_u16_messages(bytes(data), self.source()), {9})

    def test_menu_groups_retain_prompt_and_option_order(self) -> None:
        data = self.script_data((0, 10))
        struct.pack_into(
            ">10H",
            data,
            SCRIPT_BODY_OFFSET,
            1,
            5,
            3,
            3,
            7,
            0,
            8,
            1,
            9,
            0,
        )

        self.assertEqual(
            find_menu_groups(bytes(data), self.source()),
            (
                MenuGroup(
                    script_index=0,
                    word_offset=2,
                    prompt_message=5,
                    lead_messages=(),
                    option_messages=(7, 8, 9),
                ),
            ),
        )

    def test_menu_group_at_script_start_has_no_prompt(self) -> None:
        data = self.script_data((0, 4))
        struct.pack_into(">4H", data, SCRIPT_BODY_OFFSET, 3, 1, 9, 1)

        self.assertEqual(
            find_menu_groups(bytes(data), self.source())[0].prompt_message, None
        )

    def test_combat_menu_separates_lead_from_displayed_prompt(self) -> None:
        data = self.script_data((0, 11))
        self.add_message_bank(data, 10)
        struct.pack_into(
            ">11H",
            data,
            SCRIPT_BODY_OFFSET,
            0,
            6,
            1,
            0,
            7,
            0x10,
            8,
            9,
            0x11,
            0,
            1,
        )

        self.assertEqual(
            find_menu_groups(bytes(data), self.combat_source()),
            (
                MenuGroup(
                    script_index=0,
                    word_offset=5,
                    prompt_message=7,
                    lead_messages=(6,),
                    option_messages=(8, 9),
                ),
            ),
        )

    def test_combat_menu_supports_two_three_and_four_options(self) -> None:
        for option_count, opcode in ((2, 0x10), (3, 0x12), (4, 0x14)):
            with self.subTest(option_count=option_count):
                labels = tuple(range(7, 7 + option_count))
                words = (0, 5, opcode, *labels, opcode + 1, *([1] * option_count))
                data = self.script_data((0, len(words)))
                self.add_message_bank(data, 16)
                struct.pack_into(
                    f">{len(words)}H",
                    data,
                    SCRIPT_BODY_OFFSET,
                    *words,
                )

                group = find_menu_groups(bytes(data), self.combat_source())[0]
                self.assertEqual(group.prompt_message, 5)
                self.assertEqual(group.lead_messages, ())
                self.assertEqual(group.option_messages, labels)

    def test_combat_menu_rejects_an_out_of_range_target(self) -> None:
        words = (0x10, 7, 8, 0x11, 0, 2)
        data = self.script_data((0, len(words)))
        self.add_message_bank(data, 10)
        struct.pack_into(
            f">{len(words)}H",
            data,
            SCRIPT_BODY_OFFSET,
            *words,
        )

        self.assertEqual(find_menu_groups(bytes(data), self.combat_source()), ())


class EveCorpusStateTests(unittest.TestCase):
    TABLE_OFFSET = 0x04
    BODY_OFFSET = 0x10

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.extracted_root = self.root / "extracted"
        self.corpus_root = self.root / "corpus"
        self.extracted_root.mkdir()
        (self.corpus_root / "eve").mkdir(parents=True)
        self.source = EveSource(
            name="fixture",
            path=Path("FIXTURE.EVE"),
            default_profile=EVENT_DIALOGUE,
            table_offset=self.TABLE_OFFSET,
            body_offset=self.BODY_OFFSET,
            corpus_path=Path("eve/FIXTURE.EVE.json"),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_source(self, first_word: int) -> None:
        data = bytearray(0x20)
        data[: self.TABLE_OFFSET] = b"HEAD"
        struct.pack_into(">2H", data, self.TABLE_OFFSET, 0, 0xFFFF)
        struct.pack_into(">2H", data, self.BODY_OFFSET, first_word, 0x8000)
        (self.extracted_root / self.source.path).write_bytes(data)

    def test_extract_preserves_state_only_while_page_grounding_matches(self) -> None:
        self.write_source(0x0041)
        with patch("text.script.source_models.EXTRACTED_PATH", self.extracted_root):
            rows = extract_corpus(self.source, self.corpus_root)

        self.assertEqual(len(rows), 1)
        rows[0].update(
            {
                "en": "English reference",
                "tr": "Target translation",
                "reviewed": True,
                "excluded": True,
            }
        )
        corpus_path = self.corpus_root / self.source.corpus_path
        corpus_path.write_text(json.dumps(rows), encoding="utf-8")

        with patch("text.script.source_models.EXTRACTED_PATH", self.extracted_root):
            unchanged = extract_corpus(self.source, self.corpus_root)

        self.assertEqual(unchanged[0]["en"], "English reference")
        self.assertEqual(unchanged[0]["tr"], "Target translation")
        self.assertTrue(unchanged[0]["reviewed"])
        self.assertTrue(unchanged[0]["excluded"])

        self.write_source(0x0042)
        with patch("text.script.source_models.EXTRACTED_PATH", self.extracted_root):
            regrounded = extract_corpus(self.source, self.corpus_root)

        self.assertEqual(regrounded[0]["tr"], "")
        self.assertFalse(regrounded[0]["reviewed"])
        self.assertFalse(regrounded[0]["excluded"])
        self.assertNotIn("en", regrounded[0])


if __name__ == "__main__":
    unittest.main()
