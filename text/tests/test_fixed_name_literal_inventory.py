import unittest

from project_paths import EXTRACTED_ROOT

# Exact top-level Saturn resource occurrences. Nested CPK/MDEC payloads are
# compressed media, not overlays which can consume these loaded table bases.
EXPECTED = {
    0x0023FFD0: {
        "COMBAT.BIN": (0x2C3BC, 0x2C704, 0x2CAA8, 0x2F1C4, 0x52224),
        "EVENT.BIN": (0x37354, 0x4254C),
        "HOSI.BIN": (0x104C0, 0x104C4),
        "LEVEL_UP.BIN": (0x8460,),
        "LOAD.BIN": (0x51800,),
        "MAP2D.BIN": (0x1DB0C,),
        "MAZE.BIN": (0x1F1F0, 0x1F538, 0x1F8DC),
        "MSGR.COF": (0x15E3C,),
        "NAME.BIN": (0x15E74, 0x20E1C),
        "NORMCOM.BIN": (0x8584, 0x8EF0, 0x9238, 0x95DC, 0x1859C),
        "SAVE.BIN": (0x5071C,),
        "TITLE.BIN": (0xFB84,),
    },
    0x0023F5D0: {
        "COMBAT.BIN": (0x2C52C, 0x2C828, 0x2CAAC, 0x2FD58, 0x300A0, 0x52220),
        "DA_3D.BIN": (0xE370, 0xEE14, 0xF40C, 0xF70C),
        "EVENT.BIN": (0x3736C, 0x42550),
        "MAP2D.BIN": (0x1DB08,),
        "MAZE.BIN": (0x1F360, 0x1F65C, 0x1F8E0),
        "MSGR.COF": (0x15E40,),
        "NAME.BIN": (0x15E70,),
        "NORMCOM.BIN": (0x857C, 0x9060, 0x935C, 0x95E0, 0x185B4),
        "TITLE.BIN": (0xFB7C,),
    },
}

VISIBLE_OVERLAYS = {
    "COMBAT.BIN",
    "DA_3D.BIN",
    "EVENT.BIN",
    "LEVEL_UP.BIN",
    "MAZE.BIN",
    "MSGR.COF",
    "NORMCOM.BIN",
}
NON_RENDERING_RESOURCES = {
    "HOSI.BIN",
    "LOAD.BIN",
    "MAP2D.BIN",
    "NAME.BIN",
    "SAVE.BIN",
    "TITLE.BIN",
}


def offsets(data: bytes, needle: bytes) -> tuple[int, ...]:
    found = []
    start = 0
    while (offset := data.find(needle, start)) >= 0:
        found.append(offset)
        start = offset + 1
    return tuple(found)


class FixedNameLiteralInventoryTests(unittest.TestCase):
    def test_exact_top_level_base_literal_inventory_is_classified(self) -> None:
        for address, expected in EXPECTED.items():
            needle = address.to_bytes(4, "big")
            actual = {
                path.name: found
                for path in EXTRACTED_ROOT.iterdir()
                if path.is_file() and (found := offsets(path.read_bytes(), needle))
            }
            with self.subTest(address=f"{address:#010x}"):
                self.assertEqual(actual, expected)
                self.assertEqual(
                    set(actual),
                    (VISIBLE_OVERLAYS - {"DA_3D.BIN"}) | NON_RENDERING_RESOURCES
                    if address == 0x0023FFD0
                    else (VISIBLE_OVERLAYS - {"LEVEL_UP.BIN"})
                    | (NON_RENDERING_RESOURCES - {"HOSI.BIN", "LOAD.BIN", "SAVE.BIN"}),
                )


if __name__ == "__main__":
    unittest.main()
