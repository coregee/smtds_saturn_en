import unittest
from unittest.mock import patch

from text.editor import capacity
from text.editor.capacity import analyze_capacity


def checks_by_name(result: dict) -> dict[str, dict]:
    return {check["name"]: check for check in result["checks"]}


class EditorCapacityTests(unittest.TestCase):
    def test_fixed_bytes_reports_native_runtime_and_strict_fallbacks(self) -> None:
        fits = analyze_capacity("fixed_bytes/CHARNAME.DAT.json", [0], "A")
        runtime = analyze_capacity(
            "fixed_bytes/CHARNAME.DAT.json",
            [0],
            "X" * 20,
        )
        fallback = analyze_capacity(
            "fixed_bytes/DVLNAME.DAT.json",
            [255],
            "X" * 20,
        )

        self.assertEqual(fits["outcome"], "fits")
        self.assertEqual(
            set(checks_by_name(fits)),
            {"encoded_bytes", "rendered_width"},
        )
        self.assertEqual(runtime["outcome"], "runtime")
        self.assertTrue(runtime["runtime_requirements"])
        self.assertEqual(fallback["outcome"], "fallback")
        self.assertTrue(all(result["exact"] for result in (fits, runtime, fallback)))

    def test_fixed_help_includes_word_line_and_indentation_limits(self) -> None:
        fits = analyze_capacity("fixed_help/BTL_HELP.DAT.json", [0], "Fight")
        overflow = analyze_capacity(
            "fixed_help/BTL_HELP.DAT.json",
            [0],
            "X" * 50,
        )

        self.assertEqual(fits["outcome"], "fits")
        self.assertEqual(
            set(checks_by_name(fits)),
            {
                "encoded_words",
                "lines",
                "leading_indentation",
                "post_newline_indentation",
            },
        )
        self.assertEqual(overflow["outcome"], "overflow")
        self.assertLess(
            checks_by_name(overflow)["encoded_words"]["remaining"],
            0,
        )

    def test_fixed_words_distinguishes_native_runtime_and_fallback(self) -> None:
        fits = analyze_capacity("fixed_words/LEVEL_UP.BIN.json", [0], "A")
        runtime = analyze_capacity(
            "fixed_words/LEVEL_UP.BIN.json",
            [0],
            "Learned Magic",
        )
        fallback = analyze_capacity(
            "fixed_words/LEVEL_UP.BIN.json",
            [0],
            "X" * 30,
        )

        self.assertEqual(fits["outcome"], "fits")
        self.assertEqual(runtime["outcome"], "runtime")
        self.assertEqual(fallback["outcome"], "fallback")
        self.assertEqual(
            checks_by_name(runtime)["native_words"]["outcome"],
            "overflow",
        )
        self.assertEqual(
            checks_by_name(runtime)["runtime_words"]["outcome"],
            "fits",
        )

    def test_name_description_checks_each_nested_field(self) -> None:
        name = analyze_capacity(
            "name_description/ITEMNAME.DAT.json",
            [0, "name", "tr"],
            "X" * 40,
        )
        description = analyze_capacity(
            "name_description/ITEMNAME.DAT.json",
            [0, "description"],
            "X" * 100,
        )

        self.assertEqual(name["pointer"], [0, "name"])
        self.assertEqual(name["outcome"], "fallback")
        self.assertEqual(
            set(checks_by_name(name)),
            {"name_bytes", "name_width", "shared_name_pool_bytes"},
        )
        self.assertEqual(description["outcome"], "fallback")
        self.assertEqual(
            set(checks_by_name(description)),
            {"description_words", "shared_name_pool_bytes"},
        )
        self.assertTrue(name["exact"])
        self.assertIn("shared full-name", name["note"])

    def test_mirrored_and_deduplicated_records_check_every_physical_slot(self) -> None:
        runtime = analyze_capacity(
            "mirrored_words/NORMCOM.tables.json",
            [0],
            "X" * 10,
        )
        strict = analyze_capacity(
            "mirrored_words/NORMCOM.tables.json",
            [109],
            "X" * 30,
        )
        deduplicated = analyze_capacity(
            "deduplicated_words/COMBAT.BIN.debug_text.json",
            [0],
            "X" * 30,
        )

        self.assertEqual(runtime["outcome"], "runtime")
        self.assertEqual(len(runtime["checks"]), 5)
        self.assertTrue(
            all(
                check["name"].startswith("physical_words:")
                for check in runtime["checks"]
            )
        )
        self.assertEqual(strict["outcome"], "fallback")
        self.assertEqual(len(strict["checks"]), 3)
        self.assertEqual(deduplicated["outcome"], "fallback")
        self.assertTrue(
            all(
                check["name"].startswith("physical_words@")
                for check in deduplicated["checks"]
            )
        )

    def test_ascii_fields_include_nul_and_return_encoding_errors(self) -> None:
        fits = analyze_capacity("ascii_fields/SNDTEST.BIN.json", [0], "A")
        fallback = analyze_capacity(
            "ascii_fields/SNDTEST.BIN.json",
            [0],
            "X" * 20,
        )
        invalid = analyze_capacity("ascii_fields/SNDTEST.BIN.json", [0], "雪")

        check = checks_by_name(fits)["bytes_including_nul"]
        self.assertEqual((check["used"], check["capacity"]), (2, 20))
        self.assertEqual(fallback["outcome"], "fallback")
        self.assertEqual(invalid["outcome"], "overflow")
        self.assertEqual(invalid["checks"][0]["name"], "encoding")

    def test_static_layouts_report_cells_rows_lines_pixels_and_ascii(self) -> None:
        cells = analyze_capacity(
            "static/SAVE.BIN.static.json",
            [0],
            "X" * 30,
        )
        rows = analyze_capacity(
            "static/SAVE.BIN.static.json",
            [11],
            "word " * 100,
        )
        split = analyze_capacity(
            "static/SAVE.BIN.static.json",
            [12],
            "Only one line",
        )
        ascii_result = analyze_capacity(
            "locations/MAZE_AUTOMAP.json",
            [0],
            "Library",
        )

        self.assertEqual(cells["outcome"], "overflow")
        self.assertEqual(
            checks_by_name(cells)["location_home:cells"]["outcome"],
            "overflow",
        )
        self.assertEqual(
            checks_by_name(cells)["location_home:width"]["outcome"],
            "overflow",
        )
        self.assertEqual(rows["outcome"], "overflow")
        self.assertEqual(
            checks_by_name(rows)["save_write_failure:rows"]["outcome"],
            "overflow",
        )
        self.assertEqual(split["outcome"], "overflow")
        self.assertEqual(
            checks_by_name(split)["save_capacity_error:lines"]["outcome"],
            "overflow",
        )
        self.assertEqual(ascii_result["outcome"], "fits")
        self.assertGreater(len(ascii_result["checks"]), 1)
        self.assertTrue(
            all(
                check["name"].endswith("bytes_including_nul")
                for check in ascii_result["checks"]
            )
        )

    def test_fusion_confirmations_reserve_terminators_beyond_visible_cells(
        self,
    ) -> None:
        level = analyze_capacity(
            "static/EVENT.fusion_confirmation.json",
            [1],
            "I'm afraid your level is too low.",
        )
        duplicate = analyze_capacity(
            "static/EVENT.fusion_confirmation.json",
            [2],
            "You already have this demon.",
        )

        self.assertEqual(level["outcome"], "fits")
        self.assertEqual(duplicate["outcome"], "fits")
        level_checks = checks_by_name(level)
        duplicate_checks = checks_by_name(duplicate)
        self.assertEqual(
            (
                level_checks["level_too_low:cells"]["used"],
                level_checks["level_too_low:cells"]["capacity"],
            ),
            (33, 33),
        )
        self.assertEqual(
            (
                level_checks["level_too_low:width"]["used"],
                level_checks["level_too_low:width"]["capacity"],
            ),
            (164, 320),
        )
        self.assertEqual(
            (
                duplicate_checks["duplicate_demon:cells"]["used"],
                duplicate_checks["duplicate_demon:cells"]["capacity"],
            ),
            (28, 29),
        )
        self.assertEqual(
            (
                duplicate_checks["duplicate_demon:width"]["used"],
                duplicate_checks["duplicate_demon:width"]["capacity"],
            ),
            (152, 320),
        )

    def test_indexed_formats_return_advisory_shared_body_projections(self) -> None:
        indexed_bytes = analyze_capacity(
            "indexed_bytes/BTL_MES.MD8.json",
            [1],
            "ATTACK",
        )
        indexed_words = analyze_capacity(
            "indexed_words/BTL_SRF.MDT.json",
            [0],
            "HEY, SUMMONER...{n}YOU SAY SOMETHING?{demon_name}",
        )

        self.assertFalse(indexed_bytes["exact"])
        self.assertIn("shared_body_bytes", checks_by_name(indexed_bytes))
        self.assertFalse(indexed_words["exact"])
        self.assertIn("shared_body_words", checks_by_name(indexed_words))
        self.assertIn("advisory", indexed_words["note"])

    def test_bad_indexed_draft_is_a_structured_check(self) -> None:
        result = analyze_capacity(
            "indexed_bytes/BTL_MES.MD8.json",
            [1],
            "snowman: ☃",
        )

        self.assertEqual(result["outcome"], "overflow")
        self.assertFalse(result["exact"])
        self.assertEqual(result["checks"][0]["name"], "encoding")

    def test_eve_is_advisory_and_runtime_ui_width_is_exact(self) -> None:
        eve = analyze_capacity("eve/MESFILE.EVE.json", [0], "Draft")
        runtime_ui = analyze_capacity(
            "runtime_ui/healing_ui.json",
            ["all_members"],
            "All Members",
        )
        runtime_overflow = analyze_capacity(
            "runtime_ui/shop_ui.json",
            ["talk_labels", 0],
            "W" * 20,
        )

        self.assertFalse(eve["exact"])
        self.assertIn("shared_bank_bytes", checks_by_name(eve))
        self.assertIn("advisory", eve["note"])
        self.assertEqual(runtime_ui["outcome"], "fits")
        self.assertTrue(runtime_ui["exact"])
        self.assertEqual(runtime_ui["source"], "engine_runtime_ui")
        self.assertEqual(runtime_overflow["outcome"], "overflow")
        self.assertEqual(
            checks_by_name(runtime_overflow)["rendered_width"]["capacity"],
            64,
        )

    def test_eve_message_encodings_are_reused_for_an_identical_draft(self) -> None:
        capacity._encode_eve_message_cached.cache_clear()
        try:
            with patch.object(
                capacity,
                "encode_eve_translation",
                wraps=capacity.encode_eve_translation,
            ) as encode:
                first = analyze_capacity("eve/MESFILE.EVE.json", [0], "Draft")
                cold_calls = encode.call_count
                second = analyze_capacity("eve/MESFILE.EVE.json", [0], "Draft")

            self.assertGreater(cold_calls, 1)
            self.assertEqual(encode.call_count, cold_calls)
            self.assertEqual(first, second)
        finally:
            capacity._encode_eve_message_cached.cache_clear()

    def test_unregistered_sources_remain_explicitly_unavailable(self) -> None:
        result = analyze_capacity("unregistered.json", ["field"], "Draft")

        self.assertEqual(result["outcome"], "unavailable")
        self.assertFalse(result["exact"])
        self.assertIsNone(result["source"])

    def test_request_validation_remains_strict(self) -> None:
        with self.assertRaisesRegex(ValueError, "proposed tr"):
            analyze_capacity("fixed_bytes/CHARNAME.DAT.json", [0], None)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "outside|remain"):
            analyze_capacity("../outside.json", [0], "Draft")
        with self.assertRaisesRegex(ValueError, "components"):
            analyze_capacity("unregistered.json", [True], "Draft")
        with self.assertRaisesRegex(ValueError, "non-negative"):
            analyze_capacity("indexed_bytes/BTL_MES.MD8.json", [-1], "snowman: ☃")


if __name__ == "__main__":
    unittest.main()
