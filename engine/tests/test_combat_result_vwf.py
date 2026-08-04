import struct
import unittest

from engine.script.context import DEFAULT_CONTEXT
from engine.script.generated_asset import load_runtime_ui
from engine.script.name.fields import CODENAME_BYTES
from engine.script.smallfont.combat import (
    COMBAT_ANALYSIS_CAVE_LIMIT,
    COMBAT_RESULT_CHARACTER_NAME_POINTER,
    COMBAT_RESULT_NAME_POINTER,
    COMBAT_RESULT_NAME_STOCK_DRAWER,
)
from engine.script.smallfont.model import OVERLAYS
from engine.script.smallfont.renderer import build_character_panel_data
from engine.script.text_render.font8_metrics import font8_metrics


class CombatResultVwfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from engine.script.smallfont.patch import build_group

        combat = next(
            overlay for overlay in OVERLAYS if overlay.target.name == "COMBAT.BIN"
        )
        cls.group = build_group(combat)
        cls.patches = {patch.name: patch for patch in cls.group.patches}
        cls.analysis = cls.patches["analysis_english_cave"]

    def test_result_names_use_the_generated_full_character_pool(self) -> None:
        rows = load_runtime_ui(DEFAULT_CONTEXT).section("character_names")
        self.assertIsInstance(rows, list)
        offsets, pool = build_character_panel_data(rows, font8_metrics())
        character_data = offsets + pool
        self.assertEqual(self.analysis.replacement.count(character_data), 1)

        data_offset = self.analysis.replacement.index(character_data)
        offsets_address = self.analysis.address + data_offset
        pool_address = offsets_address + len(offsets)
        result_name_address = struct.unpack(
            ">I", self.patches["result_codename_pointer"].replacement
        )[0]
        codename_pointer = self.patches["result_codename_pointer"]
        character_pointer = self.patches["result_character_name_pointer"]
        self.assertEqual(codename_pointer.address, COMBAT_RESULT_NAME_POINTER)
        self.assertEqual(
            character_pointer.address,
            COMBAT_RESULT_CHARACTER_NAME_POINTER,
        )
        expected_stock = struct.pack(">I", COMBAT_RESULT_NAME_STOCK_DRAWER)
        self.assertEqual(codename_pointer.expected, expected_stock)
        self.assertEqual(character_pointer.expected, expected_stock)
        self.assertEqual(character_pointer.replacement, codename_pointer.replacement)
        result_item_address = struct.unpack(
            ">I", self.patches["result_item_pointer"].replacement
        )[0]
        result_name = self.analysis.replacement[
            result_name_address - self.analysis.address : result_item_address
            - self.analysis.address
        ]
        self.assertIn(struct.pack(">I", CODENAME_BYTES), result_name)
        self.assertIn(struct.pack(">I", offsets_address), result_name)
        self.assertIn(struct.pack(">I", pool_address), result_name)
        # The result callback's nonzero values are already CHARNAME record
        # indices: slot 1 is Rei, so the assembly must not subtract one.
        self.assertNotIn(bytes.fromhex("71ff"), result_name)  # add #-1,r1
        self.assertIn(bytes.fromhex("ec20"), result_name)  # mov #32,r12

        widths, codes = font8_metrics()
        del widths
        rei = bytes(codes[character] for character in "Rei Reiho") + b"\0"
        rei_offset = struct.unpack_from(">H", offsets, 2)[0]
        self.assertEqual(pool[rei_offset : rei_offset + len(rei)], rei)
        self.assertLessEqual(
            self.analysis.address + len(self.analysis.replacement),
            COMBAT_ANALYSIS_CAVE_LIMIT,
        )

    def test_result_labels_move_down_exactly_four_pixels(self) -> None:
        rows = load_runtime_ui(DEFAULT_CONTEXT).section("character_names")
        self.assertIsInstance(rows, list)
        offsets, pool = build_character_panel_data(rows, font8_metrics())
        character_data_offset = self.analysis.replacement.index(offsets + pool)
        label_address = struct.unpack(
            ">I", self.patches["result_label_glyph_pointer"].replacement
        )[0]
        label_drawer = self.analysis.replacement[
            label_address - self.analysis.address : character_data_offset
        ]

        # r5 is the pixel stride.  In 4bpp, moving four rows advances the
        # bitmap base by 4 * (r5 / 2), i.e. two strides.
        self.assertIn(bytes.fromhex("60534000390c"), label_drawer)


if __name__ == "__main__":
    unittest.main()
