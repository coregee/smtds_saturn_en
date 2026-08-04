import unittest
from unittest.mock import patch

from engine.script.saveload import system
from engine.script.static_text import StaticBlock, StaticTextAsset


def save_asset() -> StaticTextAsset:
    definitions = (
        ("save_write_failure", 72, 0x1111),
        ("save_capacity_error_0", 25, 0x2222),
        ("save_capacity_error_1", 25, 0x3333),
        ("save_capacity_failure", 72, 0x4444),
    )
    data = bytearray(b"unused source blocks")
    blocks = {}
    for name, words, value in definitions:
        data.extend(bytes((-len(data)) % 4))
        offset = len(data)
        payload = value.to_bytes(2, "big") * words
        data.extend(payload)
        blocks[name] = StaticBlock(offset, len(payload), "u16be", words)
    return StaticTextAsset(bytes(data), blocks)


class SaveSystemTests(unittest.TestCase):
    def test_capacity_consumers_use_relocated_blocks_and_generated_counts(self) -> None:
        with (
            patch.object(system, "save_text_asset", return_value=save_asset()),
            patch.object(system, "data_start", return_value=0x25AC),
        ):
            group = system.build_save_patch()

        patches = {patch.name: patch for patch in group.patches}
        base = system.SAVE_TARGET.load_address + 0x25AC

        self.assertEqual(len(patches["save_system_data"].replacement), 392)
        self.assertEqual(
            patches["save_capacity_line_0_pointer_a"].replacement,
            (base + 144).to_bytes(4, "big"),
        )
        self.assertEqual(
            patches["save_capacity_line_0_pointer_b"].replacement,
            (base + 144).to_bytes(4, "big"),
        )
        self.assertEqual(
            patches["save_capacity_line_1_pointer_a"].replacement,
            (base + 196).to_bytes(4, "big"),
        )
        self.assertEqual(
            patches["save_capacity_line_1_pointer_b"].replacement,
            (base + 196).to_bytes(4, "big"),
        )
        self.assertEqual(
            patches["save_capacity_failure_pointer"].replacement,
            (base + 248).to_bytes(4, "big"),
        )

        for name in (
            "save_capacity_line_0_count_a",
            "save_capacity_line_0_count_b",
            "save_capacity_line_1_count_a",
            "save_capacity_line_1_count_b",
        ):
            self.assertEqual(patches[name].replacement, bytes.fromhex("e5 19"))
        self.assertEqual(
            patches["save_capacity_failure_stride"].replacement,
            bytes.fromhex("e1 30"),
        )
        self.assertEqual(
            patches["save_capacity_failure_count"].replacement,
            bytes.fromhex("e5 18"),
        )


if __name__ == "__main__":
    unittest.main()
