import unittest

from engine.script.map_ui.patch import FIXED_TARGETS


class MapUITests(unittest.TestCase):
    def test_fixed_targets_match_stock_record_order(self) -> None:
        table_offset = 0x1E684
        record_size = 10
        expected = (
            (0x1E68E, "location_rinkai_park"),
            (0x1E698, "location_mount_kasagi"),
            (0x1E6A2, "location_yarai"),
            (0x1E6AC, "location_chuo"),
            (0x1E6B6, "location_hibarigaoka"),
        )
        actual = tuple(
            (table_offset + target_index * record_size, name)
            for target_index, name in FIXED_TARGETS
        )

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
