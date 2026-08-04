import json
import struct
import tempfile
import unittest
from pathlib import Path

from engine.script.dungeon_locations.model import (
    AUTOMAP_ASCII_CHOICES_DRAWER_SITE,
    AUTOMAP_ASCII_DRAWER,
    AUTOMAP_ASCII_NO_DATA_DRAWER_SITE,
    AUTOMAP_DELETE_DRAWER,
    AUTOMAP_DELETE_DRAWER_SITE,
    BASE,
    SPECS,
)
from engine.script.dungeon_locations.patch import (
    MARKER_UI_ORDER,
    build_group,
    build_label_bitmaps,
    build_marker_ui_strips,
    label_append_offsets,
    label_catalog,
    load_marker_name_aliases,
    text_width,
)
from project_paths import BUILD_ROOT, EXTRACTED_ROOT, TEXT_CORPUS_ROOT
from text.script.formats.ascii_fields.repack import (
    asset_json as ascii_asset_json,
)
from text.script.formats.ascii_fields.repack import repack_ascii_fields
from text.script.formats.fixed_words.repack import asset_json as word_asset_json
from text.script.formats.fixed_words.repack import repack_fixed_words
from text.script.source_models import AsciiFieldsSource, FixedWordsSource
from text.script.sources import get_source


class AutomapMarkerVwfTests(unittest.TestCase):
    def marker_aliases(self) -> dict[str, str]:
        document = json.loads(
            (TEXT_CORPUS_ROOT / "runtime_ui/dungeon_marker_names.json").read_text(
                encoding="utf-8"
            )
        )
        return load_marker_name_aliases(document)

    def build_generated_root(self, root: Path) -> None:
        for source_name, repack, encode_asset in (
            ("automap_marker_ui", repack_ascii_fields, ascii_asset_json),
            ("automap_system", repack_fixed_words, word_asset_json),
        ):
            source = get_source(source_name)
            self.assertIsInstance(source, (AsciiFieldsSource, FixedWordsSource))
            result = repack(source, TEXT_CORPUS_ROOT)
            path = root / source.corpus_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                encode_asset(
                    source,
                    TEXT_CORPUS_ROOT / source.corpus_path,
                    result,
                ),
                encoding="utf-8",
            )

    def test_marker_strips_use_requested_text_and_exact_vwf_widths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            generated_root = Path(temporary)
            self.build_generated_root(generated_root)
            strips = build_marker_ui_strips(
                (BUILD_ROOT / "FONT16.FON").read_bytes(),
                generated_root,
                EXTRACTED_ROOT,
            )

        self.assertEqual(tuple(strip.name for strip in strips), MARKER_UI_ORDER)
        self.assertEqual(
            tuple((strip.width, strip.cells) for strip in strips),
            ((51, 4), (40, 3), (20, 2), (13, 1)),
        )
        self.assertTrue(all(len(strip.bitmap) == 4 * 32 for strip in strips))

    def test_automap_group_redirects_all_fixed_width_marker_drawers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            generated_root = Path(temporary)
            self.build_generated_root(generated_root)
            group = build_group(
                SPECS[1],
                EXTRACTED_ROOT,
                BUILD_ROOT / "FONT16.FON",
                (EXTRACTED_ROOT / "MAZE.BIN").read_bytes(),
                generated_root,
                self.marker_aliases(),
            )

        patches = {patch.name: patch for patch in group.patches}
        no_data = patches["marker_no_data_drawer_pointer"]
        choices = patches["marker_choice_drawer_pointer"]
        delete = patches["marker_delete_drawer_pointer"]
        self.assertEqual(no_data.address, AUTOMAP_ASCII_NO_DATA_DRAWER_SITE)
        self.assertEqual(choices.address, AUTOMAP_ASCII_CHOICES_DRAWER_SITE)
        self.assertEqual(delete.address, AUTOMAP_DELETE_DRAWER_SITE)
        self.assertEqual(no_data.expected, struct.pack(">I", AUTOMAP_ASCII_DRAWER))
        self.assertEqual(choices.expected, struct.pack(">I", AUTOMAP_ASCII_DRAWER))
        self.assertEqual(delete.expected, struct.pack(">I", AUTOMAP_DELETE_DRAWER))
        self.assertEqual(no_data.replacement, choices.replacement)

        ascii_wrapper = struct.unpack(">I", no_data.replacement)[0]
        delete_wrapper = struct.unpack(">I", delete.replacement)[0]
        cave = patches["renderer_cave"]
        cave_end = cave.address + len(cave.replacement)
        self.assertLess(cave_end, BASE + SPECS[1].cave_limit)
        self.assertTrue(cave.address <= ascii_wrapper < cave_end)
        self.assertTrue(cave.address <= delete_wrapper < cave_end)
        self.assertEqual(
            cave.replacement[ascii_wrapper - cave.address :][:16].hex(),
            "2f862f962fa62fb62fc62fd62fe64f22",
        )
        self.assertEqual(
            cave.replacement[delete_wrapper - cave.address :][:2].hex(),
            "4f22",
        )

    def test_marker_aliases_are_automap_only_and_fit_the_visible_row(self) -> None:
        aliases = self.marker_aliases()
        self.assertEqual(
            aliases,
            {
                "Kitayama University": "Kitayama Uni",
                "Underground Sewer": "Sewer",
                "University Main Bldg.": "Main Bldg.",
            },
        )
        automap_data = (EXTRACTED_ROOT / SPECS[1].target.path).read_bytes()
        maze_data = (EXTRACTED_ROOT / SPECS[0].target.path).read_bytes()
        automap_labels = label_catalog(automap_data, SPECS[1], aliases)
        maze_labels = label_catalog(maze_data, SPECS[0])

        self.assertIn(("Sewer", "", text_width("B1F")), automap_labels)
        self.assertIn(("Kitayama Uni", "", 0), automap_labels)
        self.assertIn(("Main Bldg.", "", text_width("1F")), automap_labels)
        self.assertNotIn(("Sewer", "", text_width("B1F")), maze_labels)

        bitmaps = build_label_bitmaps(
            (BUILD_ROOT / "FONT16.FON").read_bytes(),
            automap_labels,
            automap=True,
        )
        offsets = label_append_offsets(automap_labels, automap=True)
        self.assertEqual(len(bitmaps), len(automap_labels) * 8 * 32)
        for (name, lower, floor_width), append_offset in zip(
            automap_labels, offsets, strict=True
        ):
            self.assertEqual(lower, "")
            right_edge = max(
                text_width(name),
                64 + append_offset + floor_width,
            )
            self.assertLessEqual(right_edge, 112)


if __name__ == "__main__":
    unittest.main()
