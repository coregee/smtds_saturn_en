import json
import struct
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from engine.script.combat.vwf import (
    FULLWORD_INSERT_POINTER,
    INSERT_DATA_ADDRESS,
    ORIGINAL_FULLWORD_INSERT,
)
from engine.script.combat.vwf import (
    RACE_SOURCE as COMBAT_RACE_SOURCE,
)
from engine.script.combat.vwf import (
    build_patch_groups as build_combat_patch,
)
from engine.script.context import DEFAULT_CONTEXT
from engine.script.msgr.inserts import (
    RACE_INSERT_POINTER as MSGR_RACE_INSERT_POINTER,
)
from engine.script.msgr.inserts import (
    RACE_INSERT_STOCK as MSGR_RACE_INSERT_STOCK,
)
from engine.script.msgr.inserts import (
    RUNTIME_ADDRESS as MSGR_RUNTIME_ADDRESS,
)
from engine.script.msgr.inserts import (
    build_patch_groups as build_msgr_patch,
)
from engine.script.status_ui.data import load_font16_metrics, load_status_terms
from engine.script.status_ui.model import (
    DA3D_FONT16_DRAWER,
    DA3D_NAME_RACE_DRAWER_PTR,
    DA3D_RACE_SOURCE,
    EVENT_FONT16_DRAWER,
    EVENT_NAME_RACE_DRAWER_PTR,
    EVENT_RACE_SOURCE,
    FONT16_DRAWER,
    NAME_RACE_DRAWER_PTR,
    RACE_SOURCE,
)
from engine.script.status_ui.patch import build_patch_groups as build_status_patch
from engine.script.text_render.font8_metrics import font8_metrics
from project_paths import TEXT_CORPUS_ROOT
from text.script.formats.mirrored_words.model import MirroredWordTable
from text.script.profiles import RuntimeCapability
from text.script.source_catalog.records import MIRRORED_WORDS_SOURCES
from text.script.source_models import MirroredWordsSource

STATUS_BASE = 0x06020000
MSGR_BASE = 0x06060000
RACE_COUNT = 43


def occurrences(data: bytes, needle: bytes) -> tuple[int, ...]:
    found: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return tuple(found)
        found.append(offset)
        start = offset + 1


def movl_xrefs(data: bytes, base: int, target: int) -> tuple[int, ...]:
    found: list[int] = []
    for offset in range(0, len(data) - 1, 2):
        opcode = struct.unpack_from(">H", data, offset)[0]
        if opcode & 0xF000 != 0xD000:
            continue
        address = base + offset
        literal = ((address + 4) & ~3) + (opcode & 0xFF) * 4
        if literal == target:
            found.append(address)
    return tuple(found)


def direct_branch_xrefs(data: bytes, base: int, target: int) -> tuple[int, ...]:
    found: list[int] = []
    for offset in range(0, len(data) - 1, 2):
        opcode = struct.unpack_from(">H", data, offset)[0]
        if opcode & 0xF000 not in (0xA000, 0xB000):
            continue
        displacement = opcode & 0x0FFF
        if displacement & 0x0800:
            displacement -= 0x1000
        address = base + offset
        if address + 4 + displacement * 2 == target:
            found.append(address)
    return tuple(found)


@dataclass(frozen=True)
class Consumer:
    path: Path
    base: int
    source: int
    source_literal: int
    source_xrefs: tuple[int, ...]
    redirect_slot: int
    stock_target: int
    redirect_xrefs: tuple[int, ...]


CONSUMERS = (
    Consumer(
        Path("NORMCOM.BIN"),
        STATUS_BASE,
        RACE_SOURCE,
        0x06035D98,
        (0x06035D5C,),
        NAME_RACE_DRAWER_PTR,
        FONT16_DRAWER,
        (0x06035D06, 0x06035D60),
    ),
    Consumer(
        Path("DA_3D.BIN"),
        STATUS_BASE,
        DA3D_RACE_SOURCE,
        0x0602D204,
        (0x0602D19A, 0x0602D1CE),
        DA3D_NAME_RACE_DRAWER_PTR,
        DA3D_FONT16_DRAWER,
        (0x0602D144, 0x0602D19E, 0x0602D1D2),
    ),
    Consumer(
        Path("EVENT.BIN"),
        STATUS_BASE,
        EVENT_RACE_SOURCE,
        0x06054BD8,
        (0x06054B9C,),
        EVENT_NAME_RACE_DRAWER_PTR,
        EVENT_FONT16_DRAWER,
        (0x06054B46, 0x06054BA0),
    ),
    Consumer(
        Path("COMBAT.BIN"),
        STATUS_BASE,
        COMBAT_RACE_SOURCE,
        0x06051E64,
        (0x06051D98,),
        FULLWORD_INSERT_POINTER,
        ORIGINAL_FULLWORD_INSERT,
        (0x06051DD8, 0x06051DF8),
    ),
    Consumer(
        Path("MSGR.COF"),
        MSGR_BASE,
        0x06078D90,
        0x0606FB34,
        (0x0606FAD0,),
        MSGR_RACE_INSERT_POINTER,
        MSGR_RACE_INSERT_STOCK,
        (0x0606F10C, 0x0606F116, 0x0606F120),
    ),
)


class StatusRaceCoverageTests(unittest.TestCase):
    source: ClassVar[MirroredWordsSource]
    races: ClassVar[MirroredWordTable]
    extracted_root: ClassVar[Path]
    rows: ClassVar[list[dict]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = next(
            source
            for source in MIRRORED_WORDS_SOURCES
            if source.name == "normcom_tables"
        )
        cls.races = next(table for table in cls.source.tables if table.name == "races")
        cls.extracted_root = cls.source.extracted_root
        cls.rows = [
            row
            for row in json.loads(
                (TEXT_CORPUS_ROOT / cls.source.corpus_path).read_text(encoding="utf-8")
            )
            if row["table"] == "races"
        ]

    def test_catalog_maps_all_five_physical_copies(self) -> None:
        expected = {
            Path("NORMCOM.BIN"): (0x1F974, 3, RACE_SOURCE),
            Path("DA_3D.BIN"): (0x44386, 3, DA3D_RACE_SOURCE),
            Path("EVENT.BIN"): (0x54828, 3, EVENT_RACE_SOURCE),
            Path("COMBAT.BIN"): (0x543C0, 4, COMBAT_RACE_SOURCE),
            Path("MSGR.COF"): (0x18D90, 4, 0x06078D90),
        }
        actual = {}
        for location in self.races.locations:
            self.assertIsNotNone(location.engine_load_address)
            assert location.engine_load_address is not None
            actual[location.path] = (
                location.table_offset,
                location.words_per_record,
                location.engine_load_address + location.table_offset,
            )
        self.assertEqual(actual, expected)

        for location in self.races.locations:
            data = (self.extracted_root / location.path).read_bytes()
            size = RACE_COUNT * location.words_per_record * 2
            table = data[location.table_offset : location.table_offset + size]
            self.assertEqual(len(table), size)
            self.assertEqual(occurrences(data, table), (location.table_offset,))

    def test_stock_consumer_and_pointer_sets_are_exhaustive(self) -> None:
        for consumer in CONSUMERS:
            with self.subTest(path=consumer.path):
                data = (self.extracted_root / consumer.path).read_bytes()
                self.assertEqual(
                    occurrences(data, struct.pack(">I", consumer.source)),
                    (consumer.source_literal - consumer.base,),
                )
                self.assertEqual(
                    movl_xrefs(data, consumer.base, consumer.source_literal),
                    consumer.source_xrefs,
                )
                self.assertEqual(
                    struct.unpack_from(
                        ">I", data, consumer.redirect_slot - consumer.base
                    )[0],
                    consumer.stock_target,
                )
                self.assertEqual(
                    movl_xrefs(data, consumer.base, consumer.redirect_slot),
                    consumer.redirect_xrefs,
                )

                table_words = (
                    3
                    if consumer.path.name
                    in {
                        "NORMCOM.BIN",
                        "DA_3D.BIN",
                        "EVENT.BIN",
                    }
                    else 4
                )
                table_end = consumer.source + RACE_COUNT * table_words * 2
                range_literals = tuple(
                    (consumer.base + offset, value)
                    for offset in range(len(data) - 3)
                    if consumer.source
                    <= (value := struct.unpack_from(">I", data, offset)[0])
                    < table_end
                )
                self.assertEqual(
                    range_literals,
                    ((consumer.source_literal, consumer.source),),
                )

        # These two stock insertion routines are reached only through the
        # redirected function slots; no PC-relative direct call bypasses them.
        for consumer in CONSUMERS[-2:]:
            data = (self.extracted_root / consumer.path).read_bytes()
            self.assertEqual(
                occurrences(data, struct.pack(">I", consumer.stock_target)),
                (consumer.redirect_slot - consumer.base,),
            )
            self.assertEqual(
                direct_branch_xrefs(data, consumer.base, consumer.stock_target),
                (),
            )

    def test_each_overlay_redirects_its_complete_stock_consumer(self) -> None:
        status_groups = {
            group.target.name: group for group in build_status_patch(DEFAULT_CONTEXT)
        }
        status_cases = (
            (
                status_groups["NORMCOM.BIN"],
                "name_race_drawer",
                NAME_RACE_DRAWER_PTR,
                FONT16_DRAWER,
                "english_status_runtime",
            ),
            (
                status_groups["EVENT.BIN"],
                "fusion_name_race_drawer",
                EVENT_NAME_RACE_DRAWER_PTR,
                EVENT_FONT16_DRAWER,
                "fusion_status_runtime",
            ),
            (
                status_groups["DA_3D.BIN"],
                "demon_analyzer_name_race_drawer",
                DA3D_NAME_RACE_DRAWER_PTR,
                DA3D_FONT16_DRAWER,
                "demon_analyzer_runtime",
            ),
        )
        for group, patch_name, slot, stock, runtime_name in status_cases:
            self.assertEqual(group.capability, RuntimeCapability.STATUS_UI.value)
            redirect = next(
                patch for patch in group.patches if patch.name == patch_name
            )
            runtime = next(
                patch for patch in group.patches if patch.name == runtime_name
            )
            self.assertEqual(redirect.address, slot)
            self.assertEqual(redirect.expected, struct.pack(">I", stock))
            target = struct.unpack(">I", redirect.replacement)[0]
            self.assertLessEqual(runtime.address, target)
            self.assertLess(target, runtime.address + len(runtime.replacement))

        combat = build_combat_patch(DEFAULT_CONTEXT)
        combat_runtime = next(
            patch for patch in combat.patches if patch.name == "english_insert_data"
        )
        combat_redirect = next(
            patch for patch in combat.patches if patch.name == "fullword_insert_pointer"
        )
        self.assertEqual(combat.capability, RuntimeCapability.COMBAT_VWF.value)
        self.assertEqual(combat_runtime.address, INSERT_DATA_ADDRESS)
        self.assertEqual(combat_redirect.address, FULLWORD_INSERT_POINTER)
        self.assertEqual(
            combat_redirect.expected, struct.pack(">I", ORIGINAL_FULLWORD_INSERT)
        )
        combat_target = struct.unpack(">I", combat_redirect.replacement)[0]
        self.assertLessEqual(combat_runtime.address, combat_target)
        self.assertLess(
            combat_target, combat_runtime.address + len(combat_runtime.replacement)
        )

        msgr = build_msgr_patch(DEFAULT_CONTEXT)
        msgr_runtime = next(
            patch
            for patch in msgr.patches
            if patch.name == "dialogue_full_term_runtime"
        )
        msgr_redirect = next(
            patch for patch in msgr.patches if patch.name == "dialogue_race_insert"
        )
        self.assertEqual(msgr.capability, RuntimeCapability.MSGR_TEXT.value)
        self.assertEqual(msgr_runtime.address, MSGR_RUNTIME_ADDRESS)
        self.assertEqual(msgr_redirect.address, MSGR_RACE_INSERT_POINTER)
        self.assertEqual(
            msgr_redirect.expected, struct.pack(">I", MSGR_RACE_INSERT_STOCK)
        )
        msgr_target = struct.unpack(">I", msgr_redirect.replacement)[0]
        self.assertLessEqual(msgr_runtime.address, msgr_target)
        self.assertLess(
            msgr_target, msgr_runtime.address + len(msgr_runtime.replacement)
        )

    def test_all_three_runtime_owners_bind_the_same_43_translations(self) -> None:
        self.assertEqual(len(self.rows), RACE_COUNT)
        self.assertEqual([row["index"] for row in self.rows], list(range(RACE_COUNT)))
        expected = tuple(row["tr"] for row in self.rows)
        self.assertTrue(all(expected))
        runtime_races, _affinities, _names = load_status_terms("race coverage test")
        self.assertEqual(tuple(runtime_races), expected)

        _widths, codes = load_font16_metrics()
        encoded = tuple(
            struct.pack(
                f">{len(text) + 1}H",
                *(codes[character] for character in text),
                0x8000,
            )
            for text in expected
        )

        status_groups = {
            group.target.name: group for group in build_status_patch(DEFAULT_CONTEXT)
        }
        for target in ("NORMCOM.BIN", "EVENT.BIN"):
            combined = b"".join(
                patch.replacement for patch in status_groups[target].patches
            )
            for index, value in enumerate(encoded):
                self.assertIn(value, combined, f"{target} race {index}")

        _widths8, codes8 = font8_metrics()
        da3d_encoded = tuple(
            bytes(codes8[character] for character in text) + b"\xff"
            for text in expected
        )
        da3d_data = b"".join(
            patch.replacement for patch in status_groups["DA_3D.BIN"].patches
        )
        for index, value in enumerate(da3d_encoded):
            self.assertIn(value, da3d_data, f"DA_3D.BIN race {index}")

        combat = build_combat_patch(DEFAULT_CONTEXT)
        combat_data = next(
            patch.replacement
            for patch in combat.patches
            if patch.name == "english_insert_data"
        )
        msgr = build_msgr_patch(DEFAULT_CONTEXT)
        msgr_data = next(
            patch.replacement
            for patch in msgr.patches
            if patch.name == "dialogue_full_term_runtime"
        )
        for index, value in enumerate(encoded):
            self.assertIn(value, combat_data, f"COMBAT race {index}")
            self.assertIn(value, msgr_data, f"MSGR race {index}")


if __name__ == "__main__":
    unittest.main()
