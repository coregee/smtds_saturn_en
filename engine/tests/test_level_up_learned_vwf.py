import struct
import unittest

from engine.script.context import DEFAULT_CONTEXT
from engine.script.generated_asset import load_runtime_ui
from engine.script.patching import apply_patch_groups
from engine.script.status_ui.data import load_font16_metrics
from engine.script.status_ui.model import (
    BASE,
    LEVEL_UP_FONT16_DRAWER,
    LEVEL_UP_LEARNED_DRAWER_PTR,
    LEVEL_UP_LEARNED_SKILL_LIST_PTR,
    LEVEL_UP_RUNTIME_CAVE_FILE,
    LEVEL_UP_RUNTIME_CAVE_LIMIT,
    MAGNAME_BASE,
)
from engine.script.status_ui.patch import build_level_up_patch
from engine.script.status_ui.runtime import validate_level_up_packed_skill_names


def movl_xrefs(data: bytes, target: int) -> tuple[int, ...]:
    found: list[int] = []
    for offset in range(0, len(data) - 1, 2):
        opcode = struct.unpack_from(">H", data, offset)[0]
        if opcode & 0xF000 != 0xD000:
            continue
        address = BASE + offset
        literal = ((address + 4) & ~3) + (opcode & 0xFF) * 4
        if literal == target:
            found.append(address)
    return tuple(found)


class LevelUpLearnedVwfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = (DEFAULT_CONTEXT.extracted_root / "LEVEL_UP.BIN").read_bytes()
        cls.group = build_level_up_patch(DEFAULT_CONTEXT)
        cls.patches = {patch.name: patch for patch in cls.group.patches}

    def test_shared_stock_drawer_has_label_and_skill_callers(self) -> None:
        pointer_offset = LEVEL_UP_LEARNED_DRAWER_PTR - BASE
        self.assertEqual(
            struct.unpack_from(">I", self.original, pointer_offset)[0],
            LEVEL_UP_FONT16_DRAWER,
        )
        self.assertEqual(
            movl_xrefs(self.original, LEVEL_UP_LEARNED_DRAWER_PTR),
            (0x06029096, 0x060290E4),
        )
        self.assertEqual(self.original[0x9092:0x9094], bytes.fromhex("e505"))
        self.assertEqual(self.original[0x90E0:0x90E2], bytes.fromhex("e508"))

    def test_dispatcher_redirects_both_callers_into_the_runtime_cave(self) -> None:
        drawer = self.patches["level_up_learned_drawer"]
        runtime = self.patches["level_up_name_runtime"]
        dispatcher = struct.unpack(">I", drawer.replacement)[0]

        self.assertEqual(drawer.expected, struct.pack(">I", LEVEL_UP_FONT16_DRAWER))
        self.assertGreaterEqual(dispatcher, runtime.address)
        self.assertLess(dispatcher, runtime.address + len(runtime.replacement))
        self.assertLessEqual(
            runtime.address + len(runtime.replacement),
            BASE + LEVEL_UP_RUNTIME_CAVE_LIMIT,
        )
        dispatcher_bytes = runtime.replacement[dispatcher - runtime.address :]
        self.assertTrue(dispatcher_bytes.startswith(bytes.fromhex("e00835008902")))
        self.assertIn(bytes.fromhex("30ac70016000600c2008"), dispatcher_bytes)
        self.assertIn(bytes.fromhex("e1600017001a70a4"), dispatcher_bytes)
        self.assertIn(bytes.fromhex("705a6001600d"), dispatcher_bytes)
        self.assertIn(bytes.fromhex("e4206024600ce1ff611c3010"), dispatcher_bytes)
        self.assertIn(bytes.fromhex("230173024410"), dispatcher_bytes)
        self.assertEqual(dispatcher_bytes.count(bytes.fromhex("402b0009")), 2)
        self.assertIn(
            struct.pack(">I", LEVEL_UP_LEARNED_SKILL_LIST_PTR), dispatcher_bytes
        )
        self.assertIn(struct.pack(">I", MAGNAME_BASE), dispatcher_bytes)
        self.assertIn(
            struct.pack(">I", BASE + LEVEL_UP_RUNTIME_CAVE_FILE),
            dispatcher_bytes,
        )

        patched = apply_patch_groups(self.original, (self.group,))
        self.assertEqual(
            struct.unpack_from(">I", patched, drawer.address - BASE)[0],
            dispatcher,
        )

        label_pointer = struct.unpack(
            ">I", self.patches["level_up_learned_magic_pointer"].replacement
        )[0]
        _widths, codes = load_font16_metrics()
        expected_label = (*[codes[character] for character in "Learned Magic"], 0x8000)
        self.assertEqual(
            struct.unpack_from(
                f">{len(expected_label)}H",
                runtime.replacement,
                label_pointer - runtime.address,
            ),
            expected_label,
        )

    def test_dia_is_source_row_46_and_has_a_full_packed_name(self) -> None:
        rows = load_runtime_ui(DEFAULT_CONTEXT).section("magic_names")
        dia = rows[45]["name"]
        self.assertEqual(dia["jp"], "ディア")
        self.assertEqual(dia["tr"], "Dia")

        packed = (DEFAULT_CONTEXT.build_root / "MAGNAME.DAT").read_bytes()
        record = 45 * 0x60
        self.assertEqual(packed[record + 4 : record + 12], b"\x4d\x6c\x64\0\0\0\0\0")
        full_name = struct.unpack_from(">H", packed, record + 0x5E)[0]
        self.assertEqual(packed[full_name : full_name + 4], b"\x4d\x6c\x64\xff")

    def test_all_packed_full_names_match_the_generated_contract(self) -> None:
        rows = load_runtime_ui(DEFAULT_CONTEXT).section("magic_names")
        names = tuple(row["name"]["tr"] for row in rows)
        packed = (DEFAULT_CONTEXT.build_root / "MAGNAME.DAT").read_bytes()
        validate_level_up_packed_skill_names(packed, names)

        stale = bytearray(packed)
        dia_pointer = struct.unpack_from(">H", stale, 45 * 0x60 + 0x5E)[0]
        stale[dia_pointer] ^= 1
        with self.assertRaisesRegex(ValueError, "row 45 .* is stale"):
            validate_level_up_packed_skill_names(bytes(stale), names)

    def test_generated_level_up_member_matches_the_patch_graph(self) -> None:
        expected = apply_patch_groups(self.original, (self.group,))
        self.assertEqual(
            (DEFAULT_CONTEXT.build_root / "LEVEL_UP.BIN").read_bytes(),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
