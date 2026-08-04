import json
import struct
import unittest

from project_paths import TEXT_CORPUS_ROOT
from text.script.corpus_io import translation_pair
from text.script.formats.mirrored_words.extract import decode_words
from text.script.message import encode_translation
from text.script.profiles import RuntimeCapability, TextFont
from text.script.source_models import FixedHelpSource, IndexedBytesSource
from text.script.sources import get_source


def corpus_rows(source_name: str) -> list[dict]:
    source = get_source(source_name)
    return json.loads(
        (TEXT_CORPUS_ROOT / source.corpus_path).read_text(encoding="utf-8")
    )


class CorpusContractTests(unittest.TestCase):
    def test_new_padding_only_sources_start_excluded_from_review(self) -> None:
        self.assertTrue(translation_pair("", None)["excluded"])
        self.assertTrue(translation_pair(" {n} ", None)["excluded"])
        self.assertFalse(translation_pair("Visible", None)["excluded"])

    def test_battle_help_uses_the_installed_packed_renderer(self) -> None:
        source = get_source("btl_help")
        self.assertIsInstance(source, FixedHelpSource)
        self.assertTrue(source.packed)
        self.assertEqual((source.record_count, source.record_words), (19, 22))
        self.assertIn(RuntimeCapability.SMALLFONT_VWF, source.runtime_requirements)

    def test_battle_messages_reclaim_the_unused_pointer_table_tail(self) -> None:
        source = get_source("btl_mes")
        self.assertIsInstance(source, IndexedBytesSource)
        self.assertEqual(source.table_size, 0x800)
        self.assertEqual(source.output_body_offset, 0x400)
        self.assertEqual(source.engine_load_address, 0x002FA000)
        self.assertIn(RuntimeCapability.SMALLFONT_VWF, source.runtime_requirements)

    def test_level_up_text_uses_the_status_runtime_buffer(self) -> None:
        source = get_source("level_up_system")
        self.assertEqual(len(source.fields), 1)
        self.assertEqual(source.fields[0].kind, "learned_magic")
        self.assertEqual(source.fields[0].word_count, 6)
        self.assertEqual(source.fields[0].runtime_word_count, 18)
        self.assertIn(RuntimeCapability.STATUS_UI, source.runtime_requirements)

    def test_combat_affinities_use_literal_mapped_source_glyphs(self) -> None:
        path = TEXT_CORPUS_ROOT / "mirrored_words" / "COMBAT.analysis_affinities.json"
        source_text = path.read_text(encoding="utf-8")
        self.assertNotIn("\\u", source_text)

        for index, row in enumerate(json.loads(source_text)):
            words = struct.unpack(">5H", bytes.fromhex(row["source_hex"]))
            with self.subTest(index=index):
                self.assertEqual(row["jp"], decode_words(words, "skip"))

    def test_maru_glyph_uses_its_named_source_token(self) -> None:
        occurrences_by_path = {}
        for path in TEXT_CORPUS_ROOT.rglob("*.json"):
            rows = json.loads(path.read_text(encoding="utf-8"))
            occurrences = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                japanese = row.get("jp", "")
                self.assertNotIn("\u300f", japanese, path.as_posix())
                occurrences += japanese.count("{maru_symbol}")

            if occurrences:
                occurrences_by_path[path.relative_to(TEXT_CORPUS_ROOT).as_posix()] = (
                    occurrences
                )

        self.assertEqual(
            occurrences_by_path,
            {
                "eve/CLD_F.EVE.json": 152,
                "eve/CYNI.EVE.json": 6,
                "eve/GRL.EVE.json": 18,
                "eve/SLM.EVE.json": 1,
                # These are seven physical, independently translated records;
                # the former deduplicated fragment corpus collapsed two copies.
                "fixed_words/COMBAT.BIN.condition_messages.json": 7,
            },
        )

    def test_dungeon_locations_define_each_translation_once(self) -> None:
        source = get_source("dungeon_locations")
        rows = corpus_rows("dungeon_locations")
        self.assertTrue(source.deduplicate_by_jp)
        self.assertEqual(len(source.records), 144)
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({row["jp"] for row in rows}), len(rows))

    def test_fusion_direct_talk_record_uses_the_raw_reader(self) -> None:
        talk = next(
            location
            for row in corpus_rows("SHOPSMP.EVE")
            for location in row.get("locations", ())
            if location["message"] == 274
        )
        self.assertEqual(talk["reader"], "raw_u16")

    def test_identity_choice_preserves_the_raw_full_name_insert(self) -> None:
        source = get_source("EVFILE_0.EVE")
        row = next(
            row
            for row in corpus_rows("EVFILE_0.EVE")
            if any(location["message"] == 51 for location in row["locations"])
        )
        location = next(
            location for location in row["locations"] if location["message"] == 51
        )

        self.assertEqual(row["tr"], "{first_name} {last_name}")
        self.assertEqual(location["reader"], "raw_u16")
        encoded = encode_translation(
            source,
            (0x8007, 0x8006, 0x8000),
            [{**location, "tr": row["tr"]}],
        )
        self.assertIsNotNone(encoded)
        self.assertEqual(encoded.words, (0x8006, 0x010B, 0x8007, 0x8000))
        self.assertIn(RuntimeCapability.NAME_RUNTIME, encoded.runtime_requirements)

    def test_triad_unfusible_result_uses_literal_font12_words(self) -> None:
        source = get_source("shopsmp")
        row = next(
            row
            for row in corpus_rows("SHOPSMP.EVE")
            if any(location["message"] == 101 for location in row.get("locations", ()))
        )
        location = next(
            location for location in row["locations"] if location["message"] == 101
        )

        self.assertEqual((row["jp"], row["tr"]), ("合体不能", "Cannot fuse"))
        self.assertEqual(location["reader"], "raw_u16")
        self.assertEqual(location["font"], "font12")
        self.assertIn(101, source.forced_raw_messages)
        self.assertEqual(dict(source.font_overrides)[101], TextFont.FONT12)
        encoded = encode_translation(
            source,
            (0x0150, 0x0151, 0x0178, 0x016B, 0x8000),
            [{**location, "tr": row["tr"]}],
        )
        self.assertIsNotNone(encoded)
        self.assertEqual(
            encoded.words,
            (
                0x000D,
                0x0025,
                0x0032,
                0x0032,
                0x0033,
                0x0038,
                0x0000,
                0x002A,
                0x0039,
                0x0037,
                0x0029,
                0x8000,
            ),
        )

    def test_fusion_confirmation_static_records_match_the_runtime_block(self) -> None:
        self.assertEqual(
            {
                row["kind"]: row["tr"]
                for row in corpus_rows("fusion_confirmation_static")
            },
            {
                "confirm_prompt": "Shall I fuse them?",
                "level_too_low": "I'm afraid your level is too low.",
                "duplicate_demon": "You already have this demon.",
                "begin_fusion": "Then let us begin.",
                "label_yes": "Yes",
                "label_no": "No",
            },
        )

    def test_mag_exchange_options_use_raw_records(self) -> None:
        messages = {773, 774, 779}
        options = {
            location["message"]: location.get("reader")
            for row in corpus_rows("SHOPSMP.EVE")
            for location in row.get("locations", ())
            if location["message"] in messages
        }
        self.assertEqual(
            options,
            {
                773: "raw_u16",
                774: "raw_u16",
                779: "raw_u16",
            },
        )


if __name__ == "__main__":
    unittest.main()
