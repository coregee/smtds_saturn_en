import tempfile
import unittest
from pathlib import Path

from disc.script.util.sector import (
    SECTOR_SIZE,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
    Mode1Track,
    repair_mode1_sector,
)


def sector(payload: bytes) -> bytes:
    if len(payload) != USER_DATA_SIZE:
        raise ValueError("payload must fill one logical sector")
    value = bytearray(SECTOR_SIZE)
    value[15] = 1
    value[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE] = payload
    repair_mode1_sector(value)
    return bytes(value)


class Mode1SectorTests(unittest.TestCase):
    def test_repair_is_idempotent_and_rejects_other_modes(self) -> None:
        value = bytearray(sector(bytes(range(256)) * 8))
        expected = bytes(value)
        repair_mode1_sector(value)
        self.assertEqual(bytes(value), expected)

        value[15] = 2
        with self.assertRaisesRegex(ValueError, "expected a Mode 1 sector"):
            repair_mode1_sector(value)

    def test_track_reads_and_writes_across_sector_boundaries(self) -> None:
        first = bytes([0x11]) * USER_DATA_SIZE
        second = bytes([0x22]) * USER_DATA_SIZE
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track.bin"
            path.write_bytes(sector(first) + sector(second))
            with Mode1Track(path, writable=True) as track:
                self.assertEqual(track.read(USER_DATA_SIZE - 2, 4), b"\x11\x11\x22\x22")
                changed = track.write(USER_DATA_SIZE - 1, b"AB")
                self.assertEqual(changed, 2)
                self.assertEqual(track.dirty_sectors, {0, 1})
                self.assertTrue(track.sector_checksums_are_valid(0))
                self.assertTrue(track.sector_checksums_are_valid(1))
                self.assertEqual(track.read(USER_DATA_SIZE - 1, 2), b"AB")

    def test_read_only_track_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track.bin"
            path.write_bytes(sector(bytes(USER_DATA_SIZE)))
            with Mode1Track(path) as track:
                with self.assertRaisesRegex(ValueError, "opened read-only"):
                    track.write(0, b"x")
                with self.assertRaisesRegex(ValueError, "opened read-only"):
                    track.replace_extent(0, b"x")


if __name__ == "__main__":
    unittest.main()
