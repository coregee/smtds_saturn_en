import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from project_paths import TEXT_CORPUS_ROOT
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.fixed_bytes.repack import (
    FONT8_METRICS_PATH,
    repack_fixed_bytes,
)
from text.script.profiles import RuntimeCapability
from text.script.source_catalog.records import FIXED_BYTES_SOURCES

SOURCES = {source.name: source for source in FIXED_BYTES_SOURCES}


class FixedBytesFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.latin = load_latin_encoding(FONT8_METRICS_PATH)

    def overflow_indices(self, source_name: str) -> set[int]:
        source = SOURCES[source_name]
        rows = json.loads(
            (TEXT_CORPUS_ROOT / source.corpus_path).read_text(encoding="utf-8")
        )
        return {
            index
            for index, row in enumerate(rows)
            if row["tr"].strip()
            and (
                len(self.latin.encode_segment(row["tr"].strip())) > source.field_size
                or self.latin.measure_segment(row["tr"].strip()) > source.pixel_limit
            )
        }

    def test_every_current_character_overflow_has_exact_runtime_coverage(self) -> None:
        source = SOURCES["charname"]
        dialogue = frozenset(
            {
                RuntimeCapability.MSGR_TEXT,
                RuntimeCapability.STATUS_UI,
            }
        )
        visible = dialogue | {
            RuntimeCapability.FUSION_MENU,
            RuntimeCapability.ITEMNAME_RUNTIME,
            RuntimeCapability.SMALLFONT_VWF,
        }
        self.assertEqual(self.overflow_indices("charname"), {0, 1, 3, 4, 5})
        self.assertEqual(source.runtime_requirements_for_capacity_fallback(0), dialogue)
        for index in range(1, 6):
            self.assertEqual(
                source.runtime_requirements_for_capacity_fallback(index), visible
            )

        result = repack_fixed_bytes(source, TEXT_CORPUS_ROOT)
        self.assertEqual(result.capacity_fallbacks, 0)
        self.assertEqual(result.runtime_covered_capacity_fallbacks, 5)
        self.assertEqual(result.runtime_requirements, visible)

    def test_every_current_demon_overflow_excludes_mutable_zoma_rows(self) -> None:
        source = SOURCES["dvlname"]
        requirements = frozenset(
            {
                RuntimeCapability.COMBAT_VWF,
                RuntimeCapability.FUSION_MENU,
                RuntimeCapability.MSGR_TEXT,
                RuntimeCapability.SMALLFONT_VWF,
                RuntimeCapability.STATUS_UI,
            }
        )
        overflows = self.overflow_indices("dvlname")
        self.assertEqual(len(overflows), 109)
        self.assertFalse(overflows & set(range(255, 260)))
        for index in range(319):
            expected = frozenset() if 255 <= index < 260 else requirements
            self.assertEqual(
                source.runtime_requirements_for_capacity_fallback(index), expected
            )

        result = repack_fixed_bytes(source, TEXT_CORPUS_ROOT)
        self.assertEqual(result.capacity_fallbacks, 0)
        self.assertEqual(result.runtime_covered_capacity_fallbacks, 109)
        self.assertEqual(result.runtime_requirements, requirements)

    def test_mutable_zoma_rows_remain_strict_if_they_stop_fitting(self) -> None:
        source = SOURCES["dvlname"]
        rows = json.loads(
            (TEXT_CORPUS_ROOT / source.corpus_path).read_text(encoding="utf-8")
        )
        rows[255]["tr"] = "Mysterious Man"
        with tempfile.TemporaryDirectory() as temporary:
            corpus_root = Path(temporary)
            path = corpus_root / source.corpus_path
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = repack_fixed_bytes(source, corpus_root)
        self.assertEqual(result.capacity_fallbacks, 1)
        self.assertEqual(result.runtime_covered_capacity_fallbacks, 109)

    def test_runtime_coverage_requires_every_capability_to_be_emitted(self) -> None:
        source = SOURCES["dvlname"]
        incomplete = replace(
            source,
            runtime_requirements=source.runtime_requirements
            - {RuntimeCapability.FUSION_MENU},
        )
        with self.assertRaisesRegex(
            ValueError,
            "requirements are not emitted by the source: fusion_menu",
        ):
            repack_fixed_bytes(incomplete, TEXT_CORPUS_ROOT)


if __name__ == "__main__":
    unittest.main()
