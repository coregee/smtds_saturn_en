"""ISO9660 directory traversal over a raw Mode 1 track."""

from __future__ import annotations

from dataclasses import dataclass

from .sector import USER_DATA_SIZE, Mode1Track


def both_endian_u32(value: bytes, label: str) -> int:
    if len(value) != 8:
        raise ValueError(f"invalid {label} field")
    little = int.from_bytes(value[:4], "little")
    big = int.from_bytes(value[4:], "big")
    if little != big:
        raise ValueError(f"ISO9660 {label} endian copies disagree")
    return little


@dataclass(frozen=True)
class IsoEntry:
    path: str
    extent: int
    size: int
    record_offset: int

    @property
    def sector_count(self) -> int:
        return (self.size + USER_DATA_SIZE - 1) // USER_DATA_SIZE


class IsoImage:
    def __init__(self, track: Mode1Track):
        self.track = track

    def entries(self) -> dict[str, IsoEntry]:
        pvd = self.track.read(16 * USER_DATA_SIZE, USER_DATA_SIZE)
        if pvd[0] != 1 or pvd[1:6] != b"CD001" or pvd[6] != 1:
            raise ValueError("Track 1 lacks a valid ISO9660 primary volume descriptor")

        root_length = pvd[156]
        root = pvd[156 : 156 + root_length]
        root_extent = both_endian_u32(root[2:10], "root extent")
        root_size = both_endian_u32(root[10:18], "root size")
        found: dict[str, IsoEntry] = {}
        visited: set[tuple[int, int]] = set()

        def walk(extent: int, size: int, prefix: str = "") -> None:
            identity = (extent, size)
            if identity in visited:
                raise ValueError(f"ISO9660 directory cycle at {prefix or '/'}")
            visited.add(identity)
            directory = self.track.read(extent * USER_DATA_SIZE, size)
            cursor = 0

            while cursor < len(directory):
                record_length = directory[cursor]
                if record_length == 0:
                    cursor = (cursor // USER_DATA_SIZE + 1) * USER_DATA_SIZE
                    continue
                if record_length < 34 or cursor + record_length > len(directory):
                    raise ValueError(
                        f"invalid ISO9660 directory record in {prefix or '/'}"
                    )

                record_offset = extent * USER_DATA_SIZE + cursor
                record = directory[cursor : cursor + record_length]
                cursor += record_length
                identifier_length = record[32]
                identifier = record[33 : 33 + identifier_length]
                if identifier in (b"\x00", b"\x01"):
                    continue

                name = identifier.decode("ascii").split(";", 1)[0]
                path = f"{prefix}/{name}" if prefix else name
                child_extent = both_endian_u32(record[2:10], f"{path} extent")
                child_size = both_endian_u32(record[10:18], f"{path} size")
                flags = record[25]

                if flags & 2:
                    walk(child_extent, child_size, path)
                else:
                    if flags & 0x80:
                        raise ValueError(
                            f"multi-extent ISO9660 file is unsupported: {path}"
                        )
                    key = path.upper()
                    if key in found:
                        raise ValueError(
                            f"duplicate case-insensitive ISO9660 path: {path}"
                        )
                    found[key] = IsoEntry(path, child_extent, child_size, record_offset)

        walk(root_extent, root_size)
        return found

    def read_entry(self, entry: IsoEntry) -> bytes:
        return self.track.read(entry.extent * USER_DATA_SIZE, entry.size)
