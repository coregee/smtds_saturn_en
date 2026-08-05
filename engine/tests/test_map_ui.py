import struct
import unittest

from engine.script.map_ui.patch import (
    BASE,
    CHOICE_NO_BITMAP_ADDR,
    CHOICE_NO_FIELD_ADDR,
    CHOICE_NO_ROW_ADDR,
    CHOICE_NO_ROW_FILE,
    CHOICE_YES_BITMAP_ADDR,
    CHOICE_YES_FIELD_ADDR,
    CHOICE_YES_ROW_ADDR,
    CHOICE_YES_ROW_FILE,
    FIXED_TARGETS,
    FONT16_PATH,
    ORIGINAL_FIXED_DRAW,
    PROMPT_BITMAP_ADDR,
    PROMPT_CAVE_FILE,
    PROMPT_FIELD_ADDR,
    build_choice_strips,
    build_map,
    build_prompt_wrapper,
)
from project_paths import EXTRACTED_ROOT


class MapUITests(unittest.TestCase):
    def test_fixed_targets_match_stock_record_order(self) -> None:
        table_offset = 0x1E684
        record_size = 10
        expected = (
            (0x1E68E, "location_rinkai_park"),
            (0x1E698, "location_mount_kasagi"),
            (0x1E6A2, "location_yarai"),
            (0x1E6AC, "location_chuo"),
            (0x1E6B6, "location_hibarigaoka"),
        )
        actual = tuple(
            (table_offset + target_index * record_size, name)
            for target_index, name in FIXED_TARGETS
        )

        self.assertEqual(actual, expected)

    def test_speech_choices_use_title_case_vwf_strips(self) -> None:
        strips = build_choice_strips(FONT16_PATH.read_bytes())

        self.assertEqual(
            tuple((strip.codes, strip.width, strip.cells) for strip in strips),
            (
                ((0x0023, 0x0029, 0x0037), 20, 3),
                ((0x0018, 0x0033), 13, 2),
            ),
        )
        self.assertEqual(tuple(len(strip.bitmap) for strip in strips), (96, 64))

    def test_speech_choice_wrapper_dispatches_all_three_rows(self) -> None:
        wrapper = build_prompt_wrapper()

        self.assertLess(PROMPT_CAVE_FILE + len(wrapper), 0x1200)
        for address in (
            PROMPT_FIELD_ADDR,
            CHOICE_YES_FIELD_ADDR,
            CHOICE_NO_FIELD_ADDR,
            PROMPT_BITMAP_ADDR,
            CHOICE_YES_BITMAP_ADDR,
            CHOICE_NO_BITMAP_ADDR,
            CHOICE_YES_ROW_ADDR,
            CHOICE_NO_ROW_ADDR,
            ORIGINAL_FIXED_DRAW,
        ):
            with self.subTest(address=f"{address:#010x}"):
                self.assertIn(struct.pack(">I", address), wrapper)

    def test_speech_choice_rows_keep_the_stock_cell_footprints(self) -> None:
        original = (EXTRACTED_ROOT / "MAP2D.BIN").read_bytes()
        patched = build_map(original)

        self.assertEqual(
            patched[CHOICE_YES_ROW_FILE : CHOICE_YES_ROW_FILE + 8],
            struct.pack(">4H", 0, 1, 2, 0x8000),
        )
        self.assertEqual(
            patched[CHOICE_NO_ROW_FILE : CHOICE_NO_ROW_FILE + 6],
            struct.pack(">3H", 0, 1, 0x8000),
        )
        self.assertEqual(
            struct.unpack_from(">4H", patched, CHOICE_YES_FIELD_ADDR - BASE),
            (0x0023, 0x0029, 0x0037, 0x8000),
        )
        self.assertEqual(
            struct.unpack_from(">3H", patched, CHOICE_NO_FIELD_ADDR - BASE),
            (0x0018, 0x0033, 0x8000),
        )


if __name__ == "__main__":
    unittest.main()
