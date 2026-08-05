import json
import struct
import sys
import unittest

from engine.script import registry
from engine.script.context import DEFAULT_CONTEXT
from engine.script.event.model import (
    FUSION_CONFIRMATION_OVERFLOW_ADDRESS,
    PACKED_FETCH_ADDRESS,
)
from engine.script.patching import apply_patch_groups
from engine.script.static_text import StaticBlock, StaticTextAsset
from engine.script.status_ui.fusion_confirmation import (
    EXPECTED_WORD_COUNTS,
    LOOKUP_SITE,
    MAIN_FILE,
    MAIN_SIZE,
    POINTER_TABLE_OFFSET,
    STORAGE_END_FILE,
    build_storage,
    pointer_lookup_patch,
)
from engine.script.status_ui.model import BASE
from project_paths import EXTRACTED_ROOT, TEXT_CORPUS_ROOT
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.static_overlay.repack import repack_static
from text.script.source_models import StaticOverlaySource
from text.script.sources import get_source


class FusionConfirmationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = get_source("fusion_confirmation_static")
        if not isinstance(source, StaticOverlaySource):
            raise TypeError("fusion_confirmation_static must be a static source")
        cls.source = source
        cls.rows = {
            row["kind"]: row["tr"]
            for row in json.loads(
                (TEXT_CORPUS_ROOT / source.corpus_path).read_text(encoding="utf-8")
            )
        }
        result = repack_static(source, TEXT_CORPUS_ROOT)
        cls.asset = result.asset
        cls.runtime_asset = StaticTextAsset(
            data=result.asset.data,
            blocks={
                name: StaticBlock(
                    block.offset,
                    block.size,
                    block.storage,
                    block.unit_count,
                )
                for name, block in result.asset.blocks.items()
            },
        )

    def test_source_blocks_reserve_a_terminator_after_every_translation(self) -> None:
        expected_blocks = {
            "confirm_prompt": (0, 40, 20),
            "level_too_low": (40, 68, 34),
            "duplicate_demon": (108, 60, 30),
            "begin_fusion": (168, 40, 20),
            "label_yes": (208, 8, 4),
            "label_no": (216, 8, 4),
        }
        self.assertEqual(len(self.asset.data), 224)
        encoding = load_latin_encoding()
        for name, (offset, size, word_count) in expected_blocks.items():
            block = self.asset.blocks[name]
            codes = tuple(encoding.encode_segment(self.rows[name]))
            words = struct.unpack(
                f">{block.unit_count}H",
                self.asset.data[block.offset : block.offset + block.size],
            )
            with self.subTest(name=name):
                self.assertEqual(
                    (block.offset, block.size, block.unit_count),
                    (offset, size, word_count),
                )
                self.assertEqual(word_count, EXPECTED_WORD_COUNTS[name])
                self.assertEqual(words[: len(codes)], codes)
                self.assertEqual(words[len(codes)], 0x8000)

    def test_pointer_table_reaches_all_four_full_confirmation_lines(self) -> None:
        storage = build_storage(self.runtime_asset)
        table_address = BASE + MAIN_FILE + POINTER_TABLE_OFFSET
        expected_pointers = (
            table_address + 16,
            FUSION_CONFIRMATION_OVERFLOW_ADDRESS,
            table_address + 56,
            table_address + 116,
        )
        self.assertEqual(table_address % 4, 0)
        self.assertEqual(storage.pointers, expected_pointers)
        self.assertEqual(
            struct.unpack(
                ">4I",
                storage.main[POINTER_TABLE_OFFSET : POINTER_TABLE_OFFSET + 16],
            ),
            expected_pointers,
        )
        self.assertEqual(len(storage.main), MAIN_SIZE)
        self.assertEqual(len(storage.level_too_low), 68)
        self.assertEqual(
            FUSION_CONFIRMATION_OVERFLOW_ADDRESS + len(storage.level_too_low),
            PACKED_FETCH_ADDRESS,
        )

    def test_lookup_patch_matches_stock_code_and_loads_the_pointer_table(self) -> None:
        patch = pointer_lookup_patch()
        original = (EXTRACTED_ROOT / "EVENT.BIN").read_bytes()
        offset = LOOKUP_SITE - BASE
        self.assertEqual(
            original[offset : offset + len(patch.expected)], patch.expected
        )
        self.assertEqual(len(patch.expected), 22)
        self.assertEqual(
            patch.replacement,
            bytes.fromhex("d21c2f26e200e700e602e51460834008d1197102041e"),
        )

    def test_fusion_menu_cave_stops_before_the_reserved_overflow(self) -> None:
        try:
            from engine.script.fusion_menu.patch import build_patch_groups

            group = build_patch_groups(DEFAULT_CONTEXT)
            cave = next(
                patch for patch in group.patches if patch.name == "fusion_menu_cave"
            )
            self.assertLessEqual(
                cave.address + len(cave.replacement),
                FUSION_CONFIRMATION_OVERFLOW_ADDRESS,
            )
        finally:
            sys.modules.pop("engine.script.fusion_menu.patch", None)

    def test_composed_event_patch_installs_without_overlap(self) -> None:
        try:
            groups = tuple(
                group
                for group in registry.select_patch_groups([], DEFAULT_CONTEXT)
                if group.target.name == "EVENT.BIN"
            )
            original = (EXTRACTED_ROOT / "EVENT.BIN").read_bytes()
            patched = apply_patch_groups(original, groups)
            self.assertEqual(
                patched, (DEFAULT_CONTEXT.build_root / "EVENT.BIN").read_bytes()
            )

            confirmation_patches = {
                patch.name: patch
                for group in groups
                for patch in group.patches
                if patch.name.startswith("fusion_confirmation_")
            }
            self.assertEqual(
                set(confirmation_patches),
                {
                    "fusion_confirmation_pointer_lookup",
                    "fusion_confirmation_main_storage",
                    "fusion_confirmation_level_too_low",
                    "fusion_confirmation_label_yes",
                    "fusion_confirmation_label_no",
                    "fusion_confirmation_vwf_drawer",
                },
            )
            for name in (
                "fusion_confirmation_main_storage",
                "fusion_confirmation_label_yes",
                "fusion_confirmation_label_no",
            ):
                patch = confirmation_patches[name]
                self.assertLessEqual(
                    patch.address + len(patch.replacement),
                    BASE + STORAGE_END_FILE,
                )
        finally:
            for loader in registry.PATCH_LOADERS:
                sys.modules.pop(loader.module, None)


if __name__ == "__main__":
    unittest.main()
