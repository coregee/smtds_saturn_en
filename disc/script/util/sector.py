"""Raw CD-ROM Mode 1 sector access and checksum generation."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

SECTOR_SIZE = 2352
USER_DATA_OFFSET = 16
USER_DATA_SIZE = 2048

ECC_FORWARD = [0] * 256
ECC_BACKWARD = [0] * 256
EDC_TABLE = [0] * 256

for table_index in range(256):
    doubled = (table_index << 1) ^ (0x11D if table_index & 0x80 else 0)
    doubled &= 0xFF
    ECC_FORWARD[table_index] = doubled
    ECC_BACKWARD[table_index ^ doubled] = table_index

    edc_value = table_index
    for _ in range(8):
        edc_value = (edc_value >> 1) ^ (0xD8018001 if edc_value & 1 else 0)
    EDC_TABLE[table_index] = edc_value & 0xFFFFFFFF


def edc(data: bytes | bytearray) -> int:
    value = 0
    for byte in data:
        value = (value >> 8) ^ EDC_TABLE[(value ^ byte) & 0xFF]
    return value & 0xFFFFFFFF


def write_ecc(
    source: bytearray,
    major_count: int,
    minor_count: int,
    major_multiplier: int,
    minor_increment: int,
    destination: bytearray,
    destination_offset: int,
) -> None:
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_multiplier + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _ in range(minor_count):
            value = source[index]
            index = (index + minor_increment) % size
            ecc_a ^= value
            ecc_b ^= value
            ecc_a = ECC_FORWARD[ecc_a]
        ecc_a = ECC_BACKWARD[ECC_FORWARD[ecc_a] ^ ecc_b]
        destination[destination_offset + major] = ecc_a
        destination[destination_offset + major + major_count] = ecc_a ^ ecc_b


def repair_mode1_sector(sector: bytearray) -> None:
    if len(sector) != SECTOR_SIZE:
        raise ValueError(f"expected a {SECTOR_SIZE}-byte raw sector")
    if sector[15] != 1:
        raise ValueError(f"expected a Mode 1 sector, found mode {sector[15]}")

    struct.pack_into("<I", sector, 2064, edc(sector[:2064]))
    sector[2068:2076] = bytes(8)

    operand = bytearray(sector[12:2248])
    write_ecc(operand, 86, 24, 2, 86, sector, 2076)
    operand = bytearray(sector[12:2248])
    write_ecc(operand, 52, 43, 86, 88, sector, 2248)


class Mode1Track:
    """Expose the 2048-byte payload stream inside a MODE1/2352 track file."""

    def __init__(self, path: Path, first_sector: int = 0, writable: bool = False):
        self.path = path
        self.first_sector = first_sector
        self.file: BinaryIO = path.open("r+b" if writable else "rb")
        self.writable = writable
        self.dirty_sectors: set[int] = set()

    def __enter__(self) -> "Mode1Track":
        return self

    def __exit__(self, *_: object) -> None:
        self.file.close()

    def _raw_offset(self, logical_sector: int) -> int:
        return (self.first_sector + logical_sector) * SECTOR_SIZE

    def read_sector(self, logical_sector: int) -> bytes:
        self.file.seek(self._raw_offset(logical_sector))
        sector = self.file.read(SECTOR_SIZE)
        if len(sector) != SECTOR_SIZE:
            raise ValueError(f"track ends inside logical sector {logical_sector}")
        if sector[15] != 1:
            raise ValueError(f"logical sector {logical_sector} is not Mode 1")
        return sector

    def read(self, offset: int, size: int) -> bytes:
        result = bytearray()
        while size:
            sector_number, within = divmod(offset, USER_DATA_SIZE)
            take = min(size, USER_DATA_SIZE - within)
            sector = self.read_sector(sector_number)
            result += sector[
                USER_DATA_OFFSET + within : USER_DATA_OFFSET + within + take
            ]
            offset += take
            size -= take
        return bytes(result)

    def replace_extent(self, extent: int, value: bytes) -> int:
        if not self.writable:
            raise ValueError("track was opened read-only")

        changed = 0
        for within in range(0, len(value), USER_DATA_SIZE):
            sector_number = extent + within // USER_DATA_SIZE
            chunk = value[within : within + USER_DATA_SIZE]
            sector = bytearray(self.read_sector(sector_number))
            start = USER_DATA_OFFSET
            if sector[start : start + len(chunk)] == chunk:
                continue
            sector[start : start + len(chunk)] = chunk
            repair_mode1_sector(sector)
            self.file.seek(self._raw_offset(sector_number))
            self.file.write(sector)
            self.dirty_sectors.add(sector_number)
            changed += 1
        return changed

    def write(self, offset: int, value: bytes) -> int:
        if not self.writable:
            raise ValueError("track was opened read-only")
        changed = 0
        cursor = 0
        while cursor < len(value):
            sector_number, within = divmod(offset, USER_DATA_SIZE)
            take = min(len(value) - cursor, USER_DATA_SIZE - within)
            sector = bytearray(self.read_sector(sector_number))
            start = USER_DATA_OFFSET + within
            replacement = value[cursor : cursor + take]
            if sector[start : start + take] != replacement:
                sector[start : start + take] = replacement
                repair_mode1_sector(sector)
                self.file.seek(self._raw_offset(sector_number))
                self.file.write(sector)
                self.dirty_sectors.add(sector_number)
                changed += 1
            cursor += take
            offset += take
        return changed

    def sector_checksums_are_valid(self, logical_sector: int) -> bool:
        sector = bytearray(self.read_sector(logical_sector))
        expected = bytearray(sector)
        repair_mode1_sector(expected)
        return sector == expected
