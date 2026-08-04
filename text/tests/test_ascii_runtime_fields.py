import json
import unittest

from project_paths import TEXT_CORPUS_ROOT
from text.editor.capacity import analyze_capacity
from text.script.formats.ascii_fields.repack import asset_json, repack_ascii_fields
from text.script.source_models import AsciiFieldsSource
from text.script.sources import get_source


class AsciiRuntimeFieldTests(unittest.TestCase):
    def test_automap_marker_fields_repack_without_capacity_fallbacks(self) -> None:
        source = get_source("automap_marker_ui")
        self.assertIsInstance(source, AsciiFieldsSource)
        result = repack_ascii_fields(source, TEXT_CORPUS_ROOT)

        self.assertEqual(result.requested_translations, 3)
        self.assertEqual(result.translated_records, 3)
        self.assertEqual(result.capacity_fallbacks, 0)
        self.assertEqual(result.longest_bytes, 10)
        self.assertEqual(
            tuple((field.kind, field.data) for field in result.runtime_fields),
            (
                ("marker_no_data", b"(No data)\0"),
                ("marker_yes", b"Yes\0"),
                ("marker_no", b"No\0"),
            ),
        )

        original = source.input_path.read_bytes()
        self.assertEqual(result.data[0x9AA8:0x9AB0], original[0x9AA8:0x9AB0])
        self.assertEqual(result.data[0xA5E0:0xA5E4], b"Yes\0")
        self.assertEqual(result.data[0xA5E4:0xA5E8], b"No\0\0")

    def test_automap_ascii_asset_keeps_runtime_and_physical_ownership(self) -> None:
        source = get_source("automap_marker_ui")
        self.assertIsInstance(source, AsciiFieldsSource)
        result = repack_ascii_fields(source, TEXT_CORPUS_ROOT)
        document = json.loads(
            asset_json(
                source,
                TEXT_CORPUS_ROOT / source.corpus_path,
                result,
            )
        )

        self.assertEqual(
            [patch["name"] for patch in document["patches"]],
            ["marker_yes", "marker_no"],
        )
        self.assertEqual(
            [field["name"] for field in document["runtime_fields"]],
            ["marker_no_data", "marker_yes", "marker_no"],
        )

    def test_automap_over_capacity_text_is_runtime_covered(self) -> None:
        no_data = analyze_capacity(
            "ascii_fields/AUTOMAPC.BIN.marker_ui.json",
            [0],
            "(No data)",
        )
        delete = analyze_capacity(
            "fixed_words/AUTOMAPC.BIN.system.json",
            [0],
            "Delete?",
        )

        self.assertEqual(no_data["outcome"], "runtime")
        self.assertEqual(delete["outcome"], "runtime")
        self.assertIn("dungeon_locations", no_data["runtime_requirements"])
        self.assertIn("dungeon_locations", delete["runtime_requirements"])


if __name__ == "__main__":
    unittest.main()
