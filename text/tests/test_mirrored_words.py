import json
import unittest
from dataclasses import replace

from project_paths import TEXT_CORPUS_ROOT
from text.script.formats.mirrored_words.repack import (
    encode_record,
    encode_translation,
    repack_mirrored_words,
)
from text.script.profiles import RuntimeCapability
from text.script.source_catalog.records import MIRRORED_WORDS_SOURCES

SOURCE = next(
    source for source in MIRRORED_WORDS_SOURCES if source.name == "normcom_tables"
)


class MirroredWordsFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = json.loads(
            (TEXT_CORPUS_ROOT / SOURCE.corpus_path).read_text(encoding="utf-8")
        )
        cls.result = repack_mirrored_words(SOURCE, TEXT_CORPUS_ROOT)

    def overflow_indices(self, table_name: str) -> set[int]:
        table = next(table for table in SOURCE.tables if table.name == table_name)
        indices = set()
        for row in self.rows:
            if row["table"] != table_name or not row["tr"].strip():
                continue
            words = encode_translation(row["tr"].strip(), table.zero_mode)
            if any(
                encode_record(words, location.words_per_record, table.terminator_mode)
                is None
                for location in table.locations
            ):
                indices.add(row["index"])
        return indices

    def test_all_live_table_fallbacks_are_runtime_covered(self) -> None:
        tables = {table.name: table for table in SOURCE.tables}
        self.assertEqual(
            tables["races"].capacity_fallback_requirements,
            frozenset(
                {
                    RuntimeCapability.STATUS_UI,
                    RuntimeCapability.COMBAT_VWF,
                    RuntimeCapability.MSGR_TEXT,
                }
            ),
        )
        self.assertEqual(
            tables["races"].capacity_fallback_indices,
            frozenset(range(43)),
        )
        self.assertEqual(
            tables["affinities"].capacity_fallback_requirements,
            frozenset({RuntimeCapability.STATUS_UI}),
        )
        self.assertEqual(
            tables["affinities"].capacity_fallback_indices,
            frozenset(range(66)),
        )
        self.assertEqual(
            tables["affinities"].runtime_requirements_for_capacity_fallback(65),
            frozenset({RuntimeCapability.STATUS_UI}),
        )
        self.assertEqual(
            tables["affinities"].runtime_requirements_for_capacity_fallback(66),
            frozenset(),
        )
        self.assertEqual(
            tables["races"].runtime_requirements_for_capacity_fallback(0),
            frozenset(
                {
                    RuntimeCapability.STATUS_UI,
                    RuntimeCapability.COMBAT_VWF,
                    RuntimeCapability.MSGR_TEXT,
                }
            ),
        )
        self.assertEqual(self.result.capacity_fallbacks, 0)
        self.assertEqual(self.result.runtime_covered_capacity_fallbacks, 102)
        self.assertEqual(
            self.result.runtime_requirements,
            frozenset(
                {
                    RuntimeCapability.STATUS_UI,
                    RuntimeCapability.COMBAT_VWF,
                    RuntimeCapability.MSGR_TEXT,
                }
            ),
        )

    def test_every_overflow_affinity_is_in_the_66_entry_runtime_domain(self) -> None:
        affinity_overflows = self.overflow_indices("affinities")
        self.assertEqual(len(affinity_overflows), 60)
        self.assertTrue(all(index < 66 for index in affinity_overflows))
        self.assertEqual(
            set(range(66)) - affinity_overflows,
            {1, 29, 51, 52, 60, 64},
        )
        self.assertFalse(affinity_overflows & set(range(66, 96)))

    def test_all_race_overflows_are_in_the_runtime_domain(self) -> None:
        self.assertEqual(len(self.overflow_indices("races")), 42)
        self.assertTrue(
            {
                RuntimeCapability.STATUS_UI,
                RuntimeCapability.COMBAT_VWF,
                RuntimeCapability.MSGR_TEXT,
            }.issubset(SOURCE.runtime_requirements)
        )

    def test_runtime_coverage_requires_every_declared_capability_to_be_emitted(
        self,
    ) -> None:
        incomplete = replace(
            SOURCE,
            runtime_requirements=SOURCE.runtime_requirements
            - {RuntimeCapability.MSGR_TEXT},
        )
        with self.assertRaisesRegex(
            ValueError,
            "requirements are not emitted by the source: msgr_text",
        ):
            repack_mirrored_words(incomplete, TEXT_CORPUS_ROOT)


if __name__ == "__main__":
    unittest.main()
