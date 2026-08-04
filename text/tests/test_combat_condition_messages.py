import json
import struct
import unittest
from pathlib import Path

from project_paths import TEXT_CORPUS_ROOT, TEXT_LAYOUT_ROOT
from text.script.dialects import TextDialect, get_dialect
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.fixed_words.repack import (
    encode_fixed_text,
    repack_fixed_words,
)
from text.script.layouts.combat import COMBAT_DIALOGUE_LAYOUT, combat_pixel_width
from text.script.source_catalog.records import (
    COMBAT_CONDITION_BLOCKS,
    COMBAT_DIALOGUE_VOICES,
)
from text.script.source_models import FixedWordsSource
from text.script.sources import get_source

EXPECTED_BLOCKS = (
    ("charmed", 0x5455C),
    ("happy", 0x5481C),
    ("confused", 0x54ADC),
    ("enraged", 0x54D9C),
    ("talk_blocked", 0x5505C),
    ("ally_veto", 0x5531C),
    ("full_moon", 0x555DC),
)
EXPECTED_VOICES = (
    "tlk_bst",
    "kemo",
    "tlk_kofu",
    "nbl_m",
    "tlk_hirk",
    "tlk_yngm",
    "grl",
    "tlk_boy",
    "cld_f",
    "tlk_lady",
    "tlk_crzy",
    "jijy",
    "cyni",
    "tlk_west",
    "slm",
    "fallback",
)
EXPECTED_OUTLINE_HEART_KINDS = frozenset(
    {
        "charmed_grl",
        "charmed_tlk_lady",
        "charmed_jijy",
    }
)
EXPECTED_MARU_KINDS = frozenset(
    {
        "charmed_kemo",
        "happy_kemo",
        "happy_cld_f",
        "confused_cld_f",
        "confused_slm",
        "enraged_cld_f",
        "ally_veto_cld_f",
    }
)
RECORD_WORDS = 22
RECORD_BYTES = RECORD_WORDS * 2
CONDITION_START = 0x5455C
CONDITION_END = 0x558C8


class CombatConditionMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = get_source("combat_condition_messages")
        cls.corpus_path = TEXT_CORPUS_ROOT / cls.source.corpus_path
        cls.rows = json.loads(cls.corpus_path.read_text(encoding="utf-8"))
        cls.rows_by_kind = {row["kind"]: row for row in cls.rows}

    def test_catalog_owns_exact_condition_matrix(self) -> None:
        self.assertIsInstance(self.source, FixedWordsSource)
        self.assertEqual(COMBAT_CONDITION_BLOCKS, EXPECTED_BLOCKS)
        self.assertEqual(COMBAT_DIALOGUE_VOICES, EXPECTED_VOICES)
        self.assertEqual(self.source.path, Path("COMBAT.BIN"))
        self.assertTrue(self.source.packed)
        self.assertEqual(self.source.dialect, TextDialect.COMBAT)

        expected_fields = [
            (
                f"{condition}_{voice}",
                base + voice_index * RECORD_BYTES,
                RECORD_WORDS,
                0x8000,
                "space",
            )
            for condition, base in EXPECTED_BLOCKS
            for voice_index, voice in enumerate(EXPECTED_VOICES)
        ]
        expected_fields.append(
            ("comp_signal_happy", 0x5589C, RECORD_WORDS, 0x8000, "space")
        )
        actual_fields = [
            (
                field.kind,
                field.file_offset,
                field.word_count,
                field.terminator,
                field.zero_mode,
            )
            for field in self.source.fields
        ]

        self.assertEqual(len(EXPECTED_BLOCKS), 7)
        self.assertEqual(len(EXPECTED_VOICES), 16)
        self.assertEqual(len(actual_fields), 7 * 16 + 1)
        self.assertEqual(actual_fields, expected_fields)
        self.assertEqual(self.source.fields[0].file_offset, CONDITION_START)
        self.assertEqual(
            self.source.fields[-1].file_offset + RECORD_BYTES,
            CONDITION_END,
        )

    def test_corpus_is_complete_translated_and_reviewed(self) -> None:
        self.assertEqual(len(self.rows), 113)
        self.assertEqual(
            [row["kind"] for row in self.rows],
            [field.kind for field in self.source.fields],
        )
        for row, field in zip(self.rows, self.source.fields, strict=True):
            with self.subTest(kind=field.kind):
                self.assertEqual(row["file_offset"], f"0x{field.file_offset:x}")
                self.assertEqual(row["word_count"], RECORD_WORDS)
                self.assertTrue(row["tr"].strip())
                self.assertIs(row["reviewed"], True)
                self.assertIs(row["excluded"], False)

    def test_repack_is_complete_contiguous_and_terminated(self) -> None:
        result = repack_fixed_words(self.source, TEXT_CORPUS_ROOT)
        self.assertEqual(
            (
                result.records,
                result.requested_translations,
                result.translated_records,
                result.capacity_fallbacks,
            ),
            (113, 113, 113, 0),
        )

        latin = load_latin_encoding()
        dialect = get_dialect(self.source.dialect)
        for field in self.source.fields:
            translation = self.rows_by_kind[field.kind]["tr"].strip()
            encoded = encode_fixed_text(
                translation,
                packed=self.source.packed,
                zero_mode=field.zero_mode,
                latin=latin,
                dialect=dialect,
            )
            output_words = struct.unpack_from(
                f">{field.word_count}H",
                result.data,
                field.file_offset,
            )

            with self.subTest(kind=field.kind):
                self.assertNotIn(0, encoded)
                self.assertEqual(output_words.count(0x8000), 1)
                terminator = output_words.index(0x8000)
                self.assertEqual(output_words[:terminator], encoded)
                self.assertTrue(
                    all(word == 0 for word in output_words[terminator + 1 :])
                )

    def test_every_condition_message_fits_one_runtime_row(self) -> None:
        latin = load_latin_encoding()
        for row in self.rows:
            width = combat_pixel_width(row["tr"], latin)
            with self.subTest(kind=row["kind"]):
                self.assertLessEqual(width, COMBAT_DIALOGUE_LAYOUT.width)

    def test_required_line_and_stock_emphasis_glyphs_are_preserved(self) -> None:
        self.assertEqual(
            self.rows_by_kind["talk_blocked_cyni"]["tr"],
            "I don't talk to fools.",
        )
        self.assertEqual(
            self.rows_by_kind["comp_signal_happy"]["tr"],
            'COMP SIGNAL{GLYPH:010d}> "HAPPY"',
        )

        for glyph, expected_kinds in (
            ("\u300e", EXPECTED_OUTLINE_HEART_KINDS),
            ("{maru_symbol}", EXPECTED_MARU_KINDS),
        ):
            with self.subTest(glyph=glyph, side="stock"):
                self.assertEqual(
                    frozenset(row["kind"] for row in self.rows if glyph in row["jp"]),
                    expected_kinds,
                )
            with self.subTest(glyph=glyph, side="translation"):
                self.assertEqual(
                    frozenset(row["kind"] for row in self.rows if glyph in row["tr"]),
                    expected_kinds,
                )

    def test_debug_layout_no_longer_owns_condition_message_range(self) -> None:
        layout_path = (
            TEXT_LAYOUT_ROOT / "deduplicated_words" / "COMBAT.BIN.debug_text.json"
        )
        rows = json.loads(layout_path.read_text(encoding="utf-8"))
        overlaps = []
        for row in rows:
            for location in row["locations"]:
                start = int(location["file_offset"], 16)
                end = start + location["word_count"] * 2
                if int(location["boundary_word"], 16) != 0x8000:
                    end += 2
                if start < CONDITION_END and CONDITION_START < end:
                    overlaps.append((row["index"], start, end))

        self.assertEqual(overlaps, [])


if __name__ == "__main__":
    unittest.main()
