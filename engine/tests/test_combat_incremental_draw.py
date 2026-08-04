import struct
import unittest
from typing import Any

from engine.script.combat.model import COMBAT_BASE
from engine.script.combat.vwf import (
    ASM_ROOT,
    CAVE_ADDRESS,
    CAVE_LIMIT,
    CHOICE_ANCHOR_CODE,
    EXTERNAL_SURFACE_CLEAR_POINTER_SITES,
    FONT16_POINTER,
    FRAMEBUFFER_POINTER,
    FRAMEBUFFER_STRIDE,
    GLYPH_MASK_LUT,
    GLYPH_PATTERN_LUT,
    MEASURE_MODE,
    ORIGINAL_SURFACE_CLEAR,
    RIGHT_MARGIN,
    SURFACE_VALID,
    TYPEWRITER_DELAY_BRANCH,
    TYPEWRITER_DELAY_BRANCH_ORIGINAL,
    TYPEWRITER_DRAIN_FUNCTION,
    TYPEWRITER_DRAIN_ORIGINAL,
    TYPEWRITER_DRAIN_POINTER,
    TYPEWRITER_MODE_PENDING_BRANCH,
    TYPEWRITER_MODE_PENDING_BRANCH_ORIGINAL,
    TYPEWRITER_WHOLE_DRAIN,
    ZERO_SEPARATOR_CODE,
    CombatVwfLayout,
    build_dialogue_vwf,
    build_patch_groups,
    load_layout,
)
from engine.script.context import DEFAULT_CONTEXT
from engine.script.patching import PatchGroup, apply_patch_groups
from project_paths import EXTRACTED_ROOT

RENDERED_COLOR_BIT = 0x80
COLOR_MASK = 0x7F
SURFACE_PRESENT_POINTER = 0x060598EC
ORIGINAL_SURFACE_PRESENT = 0x060516CC


class CombatIncrementalDrawTests(unittest.TestCase):
    source: str
    layout: CombatVwfLayout
    payload: bytes
    labels: dict[str, int]
    group: PatchGroup
    patches: dict[str, Any]

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
        cls.group = build_patch_groups(DEFAULT_CONTEXT)
        cls.patches = {patch.name: patch for patch in cls.group.patches}

    def routine(self, start: str, end: str) -> str:
        return self.source.split(f"{start}:", 1)[1].split(f"{end}:", 1)[0]

    def test_normal_frames_do_not_clear_or_replay_rendered_glyphs(self) -> None:
        invalidated = self.routine("combat_render", "render_surface_ready")
        normal = self.routine("render_surface_ready", "draw_one")
        dirty = self.routine("render_dirty_glyph", "render_zero_separator")

        self.assertEqual(invalidated.count("=ORIGINAL_SURFACE_CLEAR"), 1)
        self.assertNotIn("ORIGINAL_SURFACE_CLEAR", normal)
        self.assertIn("cmp/pz  r7", normal)
        self.assertIn("bf      render_next_cell", normal)
        self.assertIn("and     r0, r7", dirty)
        self.assertIn("or      #0x80, r0", dirty)
        self.assertIn("mov.b   r0, @r13", dirty)

    def test_visible_stores_are_unrendered_and_overwrites_invalidate(self) -> None:
        store = self.routine("store_row_ready", "store_page_replay_source")
        overwrite = self.routine("invalidate_occupied_cell", "occupied_cell_done")

        self.assertIn("bsr     invalidate_occupied_cell", store)
        self.assertIn("and     #0x7f, r0", store)
        self.assertIn("mov.w   @(r0,r4), r1", overwrite)
        self.assertIn("mov.l   =SURFACE_VALID, r1", overwrite)
        self.assertIn("mov.b   r2, @r1", overwrite)

    def test_logical_and_external_clears_force_one_authoritative_replay(self) -> None:
        full = self.routine("combat_clear", "clear_loop")
        partial = self.routine("combat_clear_options", "clear_options_loop")
        external = self.routine(
            "combat_external_surface_clear", "invalidate_occupied_cell"
        )

        for clear in (full, partial):
            self.assertIn("mov.l   =SURFACE_VALID, r1", clear)
            self.assertIn("mov.b   r0, @r1", clear)
        self.assertIn("mov.l   =SURFACE_VALID, r1", external)
        self.assertIn("mov.l   =ORIGINAL_SURFACE_CLEAR, r1", external)
        self.assertIn("jmp     @r1", external)

    def test_external_surface_clear_literals_use_the_invalidating_wrapper(self) -> None:
        wrapper = self.labels["combat_external_surface_clear"]
        for address in EXTERNAL_SURFACE_CLEAR_POINTER_SITES:
            patch = self.patches[f"dialogue_external_surface_clear_{address:08x}"]
            self.assertEqual(patch.address, address)
            self.assertEqual(
                patch.expected,
                struct.pack(">I", ORIGINAL_SURFACE_CLEAR),
            )
            self.assertEqual(patch.replacement, struct.pack(">I", wrapper))

    def test_incremental_state_and_code_stay_inside_the_verified_cave(self) -> None:
        self.assertLess(CAVE_ADDRESS + len(self.payload), MEASURE_MODE)
        self.assertLessEqual(CAVE_ADDRESS + len(self.payload), CAVE_LIMIT)
        self.assertEqual(SURFACE_VALID, MEASURE_MODE + 4)
        self.assertIn("combat_external_surface_clear", self.labels)
        self.assertIn("invalidate_occupied_cell", self.labels)

    def test_draw_change_does_not_touch_pacing_or_surface_present(self) -> None:
        original = (EXTRACTED_ROOT / "COMBAT.BIN").read_bytes()
        patched = apply_patch_groups(original, (self.group,))

        def region(address: int, size: int) -> bytes:
            start = address - COMBAT_BASE
            return patched[start : start + size]

        self.assertEqual(
            region(TYPEWRITER_DELAY_BRANCH, 2),
            TYPEWRITER_DELAY_BRANCH_ORIGINAL,
        )
        self.assertEqual(
            region(TYPEWRITER_MODE_PENDING_BRANCH, 2),
            TYPEWRITER_MODE_PENDING_BRANCH_ORIGINAL,
        )
        self.assertEqual(
            region(TYPEWRITER_WHOLE_DRAIN, len(TYPEWRITER_DRAIN_ORIGINAL)),
            TYPEWRITER_DRAIN_ORIGINAL,
        )
        self.assertEqual(
            region(TYPEWRITER_DRAIN_POINTER, 4),
            struct.pack(">I", TYPEWRITER_DRAIN_FUNCTION),
        )
        self.assertEqual(
            region(SURFACE_PRESENT_POINTER, 4),
            struct.pack(">I", ORIGINAL_SURFACE_PRESENT),
        )


class IncrementalRenderModelTests(unittest.TestCase):
    widths = {1: 6, 2: 7, 3: 5, 4: 8}

    def render(
        self,
        grid: list[list[int]],
        colors: list[list[int]],
        *,
        surface_valid: bool,
    ) -> list[tuple[int, int, int, int]]:
        draws: list[tuple[int, int, int, int]] = []
        force_replay = not surface_valid
        for row, cells in enumerate(grid):
            x = 0
            for column, code in enumerate(cells):
                if code == 0:
                    continue
                if code == ZERO_SEPARATOR_CODE:
                    x += 16
                    continue
                if code == CHOICE_ANCHOR_CODE:
                    x = RIGHT_MARGIN // 2
                    continue
                width = self.widths[code]
                if x >= RIGHT_MARGIN or x + width > RIGHT_MARGIN:
                    break
                color = colors[row][column]
                if force_replay or not color & RENDERED_COLOR_BIT:
                    draws.append((code, x, row * 16, color & COLOR_MASK))
                    colors[row][column] = color | RENDERED_COLOR_BIT
                x += width
        return draws

    def test_append_rasterizes_each_glyph_once(self) -> None:
        grid = [[1, 2, 0], [0, 0, 0], [0, 0, 0]]
        colors = [[2, 2, 0], [0, 0, 0], [0, 0, 0]]

        self.assertEqual(
            self.render(grid, colors, surface_valid=False),
            [(1, 0, 0, 2), (2, 6, 0, 2)],
        )
        self.assertEqual(self.render(grid, colors, surface_valid=True), [])

        grid[0][2] = 3
        colors[0][2] = 4
        self.assertEqual(
            self.render(grid, colors, surface_valid=True),
            [(3, 13, 0, 4)],
        )

    def test_separator_anchor_and_partial_clear_replay_match_full_geometry(
        self,
    ) -> None:
        grid = [
            [1, ZERO_SEPARATOR_CODE, 2],
            [3, CHOICE_ANCHOR_CODE, 4],
            [0, 0, 0],
        ]
        colors = [[2, 0, 2], [4, 0, 4], [0, 0, 0]]
        first = self.render(grid, colors, surface_valid=False)
        self.assertEqual(
            first, [(1, 0, 0, 2), (2, 22, 0, 2), (3, 0, 16, 4), (4, 160, 16, 4)]
        )

        grid[1] = [2, CHOICE_ANCHOR_CODE, 3]
        colors[1] = [6, 0, 6]
        replay = self.render(grid, colors, surface_valid=False)
        self.assertEqual(
            replay,
            [(1, 0, 0, 2), (2, 22, 0, 2), (2, 0, 16, 6), (3, 160, 16, 6)],
        )

    def test_occupied_cell_replacement_replays_shifted_following_glyphs(self) -> None:
        grid = [[4, 2], [], []]
        colors = [[2, 2], [], []]
        self.assertEqual(
            self.render(grid, colors, surface_valid=False),
            [(4, 0, 0, 2), (2, 8, 0, 2)],
        )

        grid[0][0] = 1
        colors[0][0] = 4
        self.assertEqual(
            self.render(grid, colors, surface_valid=False),
            [(1, 0, 0, 4), (2, 6, 0, 2)],
        )


if __name__ == "__main__":
    unittest.main()
