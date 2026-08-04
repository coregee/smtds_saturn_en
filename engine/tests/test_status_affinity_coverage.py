import json
import struct
import unittest
from pathlib import Path

from engine.script.status_ui.data import load_status_terms
from engine.script.status_ui.model import (
    AFFINITY_DRAWER_PTR,
    AFFINITY_SELECTOR,
    AFFINITY_SOURCE,
    DA3D_AFFINITY_DRAWER_PTR,
    DA3D_AFFINITY_SELECTOR,
    DA3D_AFFINITY_SOURCE,
    DA3D_FONT16_DRAWER,
    EVENT_AFFINITY_DRAWER_PTR,
    EVENT_AFFINITY_SELECTOR,
    EVENT_AFFINITY_SOURCE,
    EVENT_FONT16_DRAWER,
    FONT16_DRAWER,
)
from project_paths import TEXT_CORPUS_ROOT
from text.script.source_catalog.records import MIRRORED_WORDS_SOURCES

BASE = 0x06020000
RECORD_BYTES = 17 * 2
RECORD_COUNT = 96
LIVE_RECORD_COUNT = 66


def occurrences(data: bytes, needle: bytes) -> tuple[int, ...]:
    found = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return tuple(found)
        found.append(offset)
        start = offset + 1


def movl_xrefs(data: bytes, target: int) -> tuple[int, ...]:
    found = []
    for offset in range(0, len(data) - 1, 2):
        opcode = struct.unpack_from(">H", data, offset)[0]
        if opcode & 0xF000 != 0xD000:
            continue
        address = BASE + offset
        literal = ((address + 4) & ~3) + (opcode & 0xFF) * 4
        if literal == target:
            found.append(address)
    return tuple(found)


class StatusAffinityCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = next(
            source
            for source in MIRRORED_WORDS_SOURCES
            if source.name == "normcom_tables"
        )
        cls.extracted_root = cls.source.extracted_root
        cls.affinities = next(
            table for table in cls.source.tables if table.name == "affinities"
        )

    def test_catalog_contains_exactly_three_identical_physical_copies(self) -> None:
        expected = {
            Path("NORMCOM.BIN"): (0x1FA76, AFFINITY_SOURCE),
            Path("DA_3D.BIN"): (0x44488, DA3D_AFFINITY_SOURCE),
            Path("EVENT.BIN"): (0x5492A, EVENT_AFFINITY_SOURCE),
        }
        actual = {
            location.path: (location.table_offset, BASE + location.table_offset)
            for location in self.affinities.locations
        }
        self.assertEqual(actual, expected)

        table_size = RECORD_COUNT * RECORD_BYTES
        canonical = (self.extracted_root / "NORMCOM.BIN").read_bytes()[
            0x1FA76 : 0x1FA76 + table_size
        ]
        self.assertEqual(len(canonical), table_size)
        for path, (offset, _address) in expected.items():
            data = (self.extracted_root / path).read_bytes()
            self.assertEqual(occurrences(data, canonical), (offset,))
        for path in (Path("COMBAT.BIN"), Path("MSGR.COF")):
            data = (self.extracted_root / path).read_bytes()
            self.assertEqual(occurrences(data, canonical), ())

    def test_each_stock_overlay_has_one_computed_table_consumer(self) -> None:
        # These three stock routines are byte-identical.  Each reads a selector
        # in the 32-based domain, multiplies it by the 34-byte record stride,
        # adds the raw base, and invokes one drawer slot for each of two lines.
        bindings = (
            (
                "NORMCOM.BIN",
                0x06036F94,
                AFFINITY_SOURCE,
                AFFINITY_SELECTOR,
                AFFINITY_DRAWER_PTR,
                FONT16_DRAWER,
                0x06036FB6,
                0x06036FC8,
                0x06036FCE,
            ),
            (
                "EVENT.BIN",
                0x06055DB0,
                EVENT_AFFINITY_SOURCE,
                EVENT_AFFINITY_SELECTOR,
                EVENT_AFFINITY_DRAWER_PTR,
                EVENT_FONT16_DRAWER,
                0x06055DD2,
                0x06055DE4,
                0x06055DEA,
            ),
            (
                "DA_3D.BIN",
                0x0602D844,
                DA3D_AFFINITY_SOURCE,
                DA3D_AFFINITY_SELECTOR,
                DA3D_AFFINITY_DRAWER_PTR,
                DA3D_FONT16_DRAWER,
                0x0602D866,
                0x0602D878,
                0x0602D87E,
            ),
        )
        bodies = []
        for (
            filename,
            routine,
            source,
            selector,
            drawer_pointer,
            stock_drawer,
            selector_xref,
            source_xref,
            drawer_xref,
        ) in bindings:
            data = (self.extracted_root / filename).read_bytes()
            body = data[routine - BASE : routine - BASE + 0x80]
            bodies.append(body)
            raw_source = source - 32 * RECORD_BYTES

            self.assertEqual(
                occurrences(data, struct.pack(">I", raw_source)),
                (drawer_pointer - BASE - 4,),
            )
            self.assertEqual(
                data[drawer_pointer - BASE - 8 : drawer_pointer - BASE + 4],
                struct.pack(">III", selector, raw_source, stock_drawer),
            )
            self.assertEqual(movl_xrefs(data, drawer_pointer - 8), (selector_xref,))
            self.assertEqual(movl_xrefs(data, drawer_pointer - 4), (source_xref,))
            self.assertEqual(movl_xrefs(data, drawer_pointer), (drawer_xref,))
            self.assertEqual(body.count(struct.pack(">H", 0x4B0B)), 2)

            # No code or data stores a direct pointer into the canonical table;
            # the single raw-base consumer above is therefore exhaustive.
            table_end = source + RECORD_COUNT * RECORD_BYTES
            self.assertFalse(
                any(
                    source <= struct.unpack_from(">I", data, offset)[0] < table_end
                    for offset in range(len(data) - 3)
                )
            )
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[0], bodies[2])

    def test_status_ui_redirects_all_three_drawer_slots_into_generated_runtime(
        self,
    ) -> None:
        from engine.script.context import DEFAULT_CONTEXT
        from engine.script.status_ui.patch import build_patch_groups

        groups = build_patch_groups(DEFAULT_CONTEXT)
        self.assertEqual(
            tuple(group.target.name for group in groups),
            ("NORMCOM.BIN", "EVENT.BIN", "DA_3D.BIN", "LEVEL_UP.BIN"),
        )
        by_target = {group.target.name: group for group in groups}

        cases = (
            (
                by_target["NORMCOM.BIN"],
                "affinity_drawer",
                AFFINITY_DRAWER_PTR,
                FONT16_DRAWER,
                "english_status_runtime",
            ),
            (
                by_target["EVENT.BIN"],
                "fusion_affinity_drawer",
                EVENT_AFFINITY_DRAWER_PTR,
                EVENT_FONT16_DRAWER,
                "fusion_status_runtime",
            ),
            (
                by_target["DA_3D.BIN"],
                "demon_analyzer_affinity_drawer",
                DA3D_AFFINITY_DRAWER_PTR,
                DA3D_FONT16_DRAWER,
                "demon_analyzer_runtime",
            ),
        )
        for group, drawer_name, drawer_pointer, stock_drawer, runtime_name in cases:
            self.assertEqual(group.capability, "status_ui")
            drawer = next(patch for patch in group.patches if patch.name == drawer_name)
            runtime = next(
                patch for patch in group.patches if patch.name == runtime_name
            )
            self.assertEqual(drawer.address, drawer_pointer)
            self.assertEqual(drawer.expected, struct.pack(">I", stock_drawer))
            replacement = struct.unpack(">I", drawer.replacement)[0]
            self.assertLessEqual(runtime.address, replacement)
            self.assertLess(replacement, runtime.address + len(runtime.replacement))
            drawer_blob = runtime.replacement[
                replacement - runtime.address : replacement - runtime.address + 64
            ]
            guard_opcode = (
                b"\xe1\x42" if group.target.name == "DA_3D.BIN" else b"\xe0\x42"
            )
            self.assertIn(guard_opcode, drawer_blob)

    def test_runtime_dataset_is_the_first_66_physical_records(self) -> None:
        rows = [
            row
            for row in json.loads(
                (TEXT_CORPUS_ROOT / self.source.corpus_path).read_text(encoding="utf-8")
            )
            if row["table"] == "affinities"
        ]
        self.assertEqual(len(rows), RECORD_COUNT)
        self.assertEqual(
            [row["index"] for row in rows[:LIVE_RECORD_COUNT]],
            list(range(LIVE_RECORD_COUNT)),
        )
        _races, runtime_affinities, _names = load_status_terms("affinity coverage test")
        self.assertEqual(
            runtime_affinities,
            [row["tr"] for row in rows[:LIVE_RECORD_COUNT]],
        )


if __name__ == "__main__":
    unittest.main()
