import struct
import sys
import unittest

from engine.script.context import DEFAULT_CONTEXT
from engine.script.generated_asset import load_runtime_ui
from engine.script.name.fields import FIELD_BY_KIND
from engine.script.patching import DigestPatch, PatchGroup, apply_patch_groups
from engine.script.smallfont.model import OVERLAYS
from engine.script.status_ui.model import (
    EVENT_CHARACTER_INSERT_END,
    EVENT_CHARACTER_INSERT_STOCK,
)
from engine.script.text_render.font8_metrics import font8_metrics


def select_patch_groups_isolated(names: list[str]) -> tuple[PatchGroup, ...]:
    """Build a selection without leaking lazy feature imports to later tests."""
    loaded = frozenset(sys.modules)
    try:
        from engine.script.registry import select_patch_groups

        return select_patch_groups(names, DEFAULT_CONTEXT)
    finally:
        for module in tuple(sys.modules):
            if module not in loaded and module.startswith("engine.script."):
                sys.modules.pop(module, None)


class DialogueNameCoverageTests(unittest.TestCase):
    def test_raw_menu_names_use_complete_generated_rows(self) -> None:
        from engine.script.name.inserts import (
            EVENT_RAW_MENU,
            MSGR_RAW_MENU,
            build_patch_groups,
        )

        groups = build_patch_groups(DEFAULT_CONTEXT)
        expected_results = (
            ["6903a0377a02", "6903a01e7a02"],
            ["6903a0377a02", "6903a01e7a02"],
        )
        for group, spec, results in zip(
            groups,
            (EVENT_RAW_MENU, MSGR_RAW_MENU),
            expected_results,
        ):
            patches = {patch.address: patch for patch in group.patches}
            renderer = patches[spec.renderer]
            self.assertIsInstance(renderer, DigestPatch)
            self.assertEqual(
                len(renderer.replacement),
                spec.renderer_end - spec.renderer,
            )
            self.assertEqual(renderer.replacement[86:], bytes(10))
            self.assertIn(bytes.fromhex("eb08"), renderer.replacement)
            self.assertIn(
                bytes.fromhex("d1083c108b02d1086011600d390c"),
                renderer.replacement,
            )
            self.assertIn(
                struct.pack(">I", spec.original_blitter),
                renderer.replacement,
            )
            self.assertIn(
                struct.pack(">I", spec.stock_advance),
                renderer.replacement,
            )
            self.assertIn(bytes.fromhex("2fc6"), renderer.replacement)
            self.assertIn(bytes.fromhex("6cf6"), renderer.replacement)
            self.assertIn(bytes.fromhex("6093"), renderer.replacement)

            for field, address, original_pointer in spec.pointer_sites:
                patch = patches[address]
                self.assertEqual(patch.expected, struct.pack(">I", original_pointer))
                self.assertEqual(
                    patch.replacement,
                    struct.pack(">I", FIELD_BY_KIND[field].runtime_address),
                )

            self.assertEqual(
                [patches[address].replacement.hex() for address in spec.result_sites],
                results,
            )

    def test_raw_menu_names_support_selective_and_vwf_builds(self) -> None:
        from engine.script.name.inserts import EVENT_RAW_MENU, MSGR_RAW_MENU

        standalone = select_patch_groups_isolated(["name_runtime"])
        composed = select_patch_groups_isolated(
            ["event_vwf", "msgr_text", "name_runtime"]
        )
        for spec in (EVENT_RAW_MENU, MSGR_RAW_MENU):
            self.assertFalse(
                any(
                    patch.address == spec.blitter_pointer
                    for group in standalone
                    for patch in group.patches
                )
            )
            adapter_patches = [
                patch
                for group in composed
                for patch in group.patches
                if patch.address == spec.blitter_pointer
            ]
            self.assertEqual(len(adapter_patches), 1)
            self.assertEqual(
                adapter_patches[0].expected,
                struct.pack(">I", spec.original_blitter),
            )
            self.assertNotEqual(
                adapter_patches[0].replacement,
                adapter_patches[0].expected,
            )

    @unittest.skipUnless(
        all(
            (DEFAULT_CONTEXT.extracted_root / source).is_file()
            for source in ("EVENT.BIN", "MSGR.COF")
        ),
        "requires extracted EVENT.BIN and MSGR.COF",
    )
    def test_raw_menu_name_compositions_apply_to_extracted_overlays(self) -> None:
        from engine.script.name.inserts import EVENT_RAW_MENU, MSGR_RAW_MENU

        standalone = select_patch_groups_isolated(["name_runtime"])
        composed = select_patch_groups_isolated(
            ["event_vwf", "msgr_text", "name_runtime"]
        )
        for spec in (EVENT_RAW_MENU, MSGR_RAW_MENU):
            runtime_group = next(
                group
                for group in standalone
                if any(patch.address == spec.renderer for patch in group.patches)
            )
            target = runtime_group.target
            original = (DEFAULT_CONTEXT.extracted_root / target.path).read_bytes()
            standalone_binary = apply_patch_groups(
                original,
                tuple(group for group in standalone if group.target == target),
            )
            composed_binary = apply_patch_groups(
                original,
                tuple(group for group in composed if group.target == target),
            )
            pointer_offset = target.file_offset(spec.blitter_pointer)
            renderer_offset = target.file_offset(spec.renderer)
            renderer_end = target.file_offset(spec.renderer_end)
            self.assertEqual(
                standalone_binary[pointer_offset : pointer_offset + 4],
                struct.pack(">I", spec.original_blitter),
            )
            self.assertNotEqual(
                composed_binary[pointer_offset : pointer_offset + 4],
                struct.pack(">I", spec.original_blitter),
            )
            self.assertEqual(
                standalone_binary[renderer_offset:renderer_end],
                composed_binary[renderer_offset:renderer_end],
            )

    def test_event_character_insert_replaces_the_complete_stock_handler(self) -> None:
        try:
            from engine.script.status_ui.patch import build_event_patch

            group = build_event_patch(
                DEFAULT_CONTEXT,
                load_runtime_ui(DEFAULT_CONTEXT),
            )
            patch = next(
                patch
                for patch in group.patches
                if patch.name == "event_dialogue_character_name_insert"
            )
            self.assertEqual(patch.address, EVENT_CHARACTER_INSERT_STOCK)
            self.assertEqual(
                len(patch.replacement),
                EVENT_CHARACTER_INSERT_END - EVENT_CHARACTER_INSERT_STOCK,
            )
            self.assertEqual(len(patch.expected), len(patch.replacement))
        finally:
            sys.modules.pop("engine.script.status_ui.patch", None)

    def test_msgr_redirects_all_three_fixed_term_handlers(self) -> None:
        from engine.script.context import DEFAULT_CONTEXT
        from engine.script.msgr.inserts import (
            CHARACTER_INSERT_POINTER,
            CHARACTER_INSERT_STOCK,
            DEMON_INSERT_POINTER,
            DEMON_INSERT_STOCK,
            RACE_INSERT_POINTER,
            RACE_INSERT_STOCK,
            RUNTIME_ADDRESS,
            RUNTIME_LIMIT,
            build_runtime,
        )
        from engine.script.msgr.inserts import (
            build_patch_groups as build_msgr_inserts,
        )

        group = build_msgr_inserts(DEFAULT_CONTEXT)
        runtime = next(
            patch
            for patch in group.patches
            if patch.name == "dialogue_full_term_runtime"
        )
        self.assertEqual(runtime.address, RUNTIME_ADDRESS)
        self.assertLessEqual(runtime.address + len(runtime.replacement), RUNTIME_LIMIT)

        sites = {
            patch.address: (
                struct.unpack(">I", patch.expected)[0],
                struct.unpack(">I", patch.replacement)[0],
            )
            for patch in group.patches[1:]
        }
        self.assertEqual(
            {address: expected for address, (expected, _target) in sites.items()},
            {
                CHARACTER_INSERT_POINTER: CHARACTER_INSERT_STOCK,
                DEMON_INSERT_POINTER: DEMON_INSERT_STOCK,
                RACE_INSERT_POINTER: RACE_INSERT_STOCK,
            },
        )
        self.assertTrue(
            all(
                RUNTIME_ADDRESS <= target < RUNTIME_ADDRESS + len(runtime.replacement)
                for _expected, target in sites.values()
            )
        )

        _widths, codes = font8_metrics()
        for name in ("Rei Reiho", "Mysterious Man", "Guan Yu"):
            encoded = bytes(codes[character] for character in name) + b"\0"
            self.assertIn(encoded, runtime.replacement)

        probe, labels = build_runtime(("A",) * 319, ("A",) * 6, ("A",) * 43)
        prepare = labels["name_prepare"] - RUNTIME_ADDRESS
        self.assertEqual(
            struct.unpack_from(">H", probe, prepare + 2)[0],
            0xE500,  # mov #0,r5: invalid demon IDs must take the stock fallback.
        )

    def test_maze_redirects_all_three_party_panel_callbacks(self) -> None:
        maze = next(
            overlay for overlay in OVERLAYS if overlay.target.name == "MAZE.BIN"
        )
        panel = next(drawer for drawer in maze.drawers if drawer.name == "panel")
        self.assertEqual(
            panel.pointer_sites,
            (0x0603F364, 0x0603F660, 0x0603F8E4),
        )


if __name__ == "__main__":
    unittest.main()
