import unittest

from engine.script.combat.vwf import (
    ASM_ROOT,
    CAVE_ADDRESS,
    CAVE_LIMIT,
    CHOICE_ANCHOR_CODE,
    FONT16_GLYPH_COUNT,
    FONT16_POINTER,
    FRAMEBUFFER_POINTER,
    FRAMEBUFFER_STRIDE,
    GLYPH_MASK_LUT,
    GLYPH_PATTERN_LUT,
    MEASURE_END_CODE,
    MEASURE_START_CODE,
    SOFT_WRAP_CODE,
    STATIC_HINT_BASE,
    STATIC_HINT_LIMIT,
    ZERO_SEPARATOR_CODE,
    build_dialogue_vwf,
    load_layout,
)


class CombatZeroSeparatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ASM_ROOT / "dialogue_vwf.s").read_text(encoding="utf-8")
        cls.layout = load_layout()
        cls.payload, cls.labels, _, _ = build_dialogue_vwf(
            CAVE_ADDRESS,
            font16_pointer=FONT16_POINTER,
            framebuffer_pointer=FRAMEBUFFER_POINTER,
            framebuffer_stride=FRAMEBUFFER_STRIDE,
            glyph_pattern_lut=GLYPH_PATTERN_LUT,
            glyph_mask_lut=GLYPH_MASK_LUT,
            code_limit=cls.layout.code_limit,
            width_offset=cls.layout.width_offset,
            layout=cls.layout,
        )

    def routine(self, start: str, end: str) -> str:
        return self.source.split(f"{start}:", 1)[1].split(f"{end}:", 1)[0]

    def test_separator_marker_is_private_and_unambiguous(self) -> None:
        self.assertGreaterEqual(ZERO_SEPARATOR_CODE, FONT16_GLYPH_COUNT)
        self.assertGreaterEqual(ZERO_SEPARATOR_CODE, STATIC_HINT_LIMIT)
        self.assertLess(ZERO_SEPARATOR_CODE, 0x8000)
        self.assertNotEqual(ZERO_SEPARATOR_CODE, CHOICE_ANCHOR_CODE)
        self.assertNotIn(
            ZERO_SEPARATOR_CODE,
            {SOFT_WRAP_CODE, MEASURE_START_CODE, MEASURE_END_CODE},
        )
        self.assertLess(STATIC_HINT_BASE, STATIC_HINT_LIMIT)

    def test_committed_zero_is_marked_before_normal_storage(self) -> None:
        store_prefix = self.routine("combat_store", "store_check_static_hint")
        self.assertIn("tst     r8, r8", store_prefix)
        self.assertIn("mov.w   =ZERO_SEPARATOR_CODE, r8", store_prefix)
        self.assertLess(
            store_prefix.index("tst     r8, r8"),
            store_prefix.index("mov.w   =ZERO_SEPARATOR_CODE, r8"),
        )

    def test_marker_advances_without_blitting_in_render_and_measure(self) -> None:
        render = self.routine("render_zero_separator", "render_anchor")
        width = self.routine("row_width_zero_separator", "row_width_anchor")
        self.assertIn("add     #16, r10", render)
        self.assertNotIn("draw_one", render)
        self.assertIn("add     #16, r11", width)
        self.assertNotIn("glyph_width", width)

    def test_unused_zero_grid_cells_remain_invisible(self) -> None:
        render_cell = self.routine("render_cell", "render_zero_separator")
        self.assertLess(
            render_cell.index("tst     r4, r4"),
            render_cell.index("mov.w   =ZERO_SEPARATOR_CODE, r0"),
        )
        self.assertIn("bt      render_next_cell", render_cell)

    def test_dialogue_cave_builds_with_separator_handlers(self) -> None:
        self.assertIn("render_zero_separator", self.labels)
        self.assertIn("row_width_zero_separator", self.labels)
        self.assertIn("store_check_static_hint", self.labels)
        self.assertLessEqual(CAVE_ADDRESS + len(self.payload), CAVE_LIMIT)


if __name__ == "__main__":
    unittest.main()
