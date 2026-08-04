"""Build a testable BIN/CUE disc from files under rom/build."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from disc.script.manifest import manifest_files
from disc.script.source import load_source_contract, validate_source_disc
from disc.script.util.cue import CueFile, CueSheet
from disc.script.util.iso9660 import IsoEntry, IsoImage
from disc.script.util.sector import SECTOR_SIZE, USER_DATA_SIZE, Mode1Track
from project_paths import BUILD_ROOT as BUILD
from project_paths import DISC_BUILD_ROOT

DEFAULT_OUTPUT = DISC_BUILD_ROOT


@dataclass(frozen=True)
class Replacement:
    path: Path
    relative: str
    entry: IsoEntry
    changed: bool

    @property
    def output_entry(self) -> IsoEntry:
        return IsoEntry(
            self.entry.path,
            self.entry.extent,
            self.path.stat().st_size,
            self.entry.record_offset,
        )

    @property
    def size_changed(self) -> bool:
        return self.path.stat().st_size != self.entry.size


def output_path(output: Path, file: CueFile) -> Path:
    return output / file.relative_path


def replacement_files(
    root: Path, output: Path, manifest: Path | None = None
) -> list[Path]:
    if manifest is not None:
        return manifest_files(root, manifest)
    output = output.resolve()
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.resolve().is_relative_to(output):
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix().upper())


def plan_replacements(
    root: Path,
    output: Path,
    entries: dict[str, IsoEntry],
    iso: IsoImage,
    manifest: Path | None = None,
) -> list[Replacement]:
    paths = replacement_files(root, output, manifest)
    if not paths:
        raise ValueError(f"no replacement files found under {root}")

    planned = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        entry = entries.get(relative.upper())
        if entry is None:
            raise ValueError(f"replacement is not present on the disc: {relative}")
        size = path.stat().st_size
        if size > entry.size:
            raise ValueError(
                f"{relative}: replacement is {size:,} bytes, exceeding the "
                f"disc file's {entry.size:,}-byte allocation"
            )
        if size < entry.size and path.suffix.casefold() != ".cpk":
            raise ValueError(
                f"{relative}: only CPK replacements may be smaller than their "
                "disc file; fixed binary replacements must remain exact-size"
            )
        value = path.read_bytes()
        planned.append(
            Replacement(path, relative, entry, value != iso.read_entry(entry))
        )
    return planned


def copy_disc(sheet: CueSheet, output: Path) -> None:
    if (output / sheet.path.name).resolve() == sheet.path:
        raise ValueError("output directory would overwrite the original CUE")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sheet.path, output / sheet.path.name)
    copied: set[Path] = set()
    for file in sheet.files:
        relative = file.relative_path
        if relative in copied:
            continue
        source = sheet.source_path(file)
        destination = output / relative
        if destination.resolve() == source.resolve():
            raise ValueError(
                f"output directory would overwrite the original track: {source}"
            )
        if not source.is_file():
            raise ValueError(f"CUE track file is missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.add(relative)


def differing_sectors(
    source: Path, output: Path, first_sector: int, allowed: set[int]
) -> int:
    size = source.stat().st_size
    if output.stat().st_size != size:
        raise ValueError("output data track size changed")
    if size % SECTOR_SIZE:
        raise ValueError("MODE1/2352 track size is not a whole number of sectors")

    count = 0
    sectors_per_block = 1024
    block_size = sectors_per_block * SECTOR_SIZE
    physical_sector = 0
    with source.open("rb") as original, output.open("rb") as built:
        while original_block := original.read(block_size):
            built_block = built.read(len(original_block))
            if original_block != built_block:
                block_sectors = len(original_block) // SECTOR_SIZE
                for within in range(block_sectors):
                    start = within * SECTOR_SIZE
                    original_sector = original_block[start : start + SECTOR_SIZE]
                    built_sector = built_block[start : start + SECTOR_SIZE]
                    if original_sector == built_sector:
                        continue
                    logical_sector = physical_sector + within - first_sector
                    if logical_sector not in allowed:
                        raise ValueError(
                            f"unexpected raw-disc change at logical sector {logical_sector}"
                        )
                    if original_sector[:16] != built_sector[:16]:
                        raise ValueError(
                            f"raw sector header changed at logical sector {logical_sector}"
                        )
                    count += 1
            physical_sector += len(original_block) // SECTOR_SIZE
    return count


def verify(
    sheet: CueSheet,
    output: Path,
    replacements: list[Replacement],
) -> tuple[int, int]:
    output_cue = output / sheet.path.name
    if not output_cue.is_file() or output_cue.read_bytes() != sheet.path.read_bytes():
        raise ValueError("output CUE does not match its source")

    data_track = sheet.mode1_track()
    output_track_path = output_path(output, data_track.file)
    source_track_path = sheet.source_path(data_track.file)
    data_relative = data_track.file.relative_path
    for file in sheet.files:
        if file.relative_path == data_relative:
            continue
        source = sheet.source_path(file)
        copied = output_path(output, file)
        if not copied.is_file() or not filecmp.cmp(source, copied, shallow=False):
            raise ValueError(f"output track does not match its source: {file.name}")

    checked_sectors: set[int] = set()
    allowed_changes: set[int] = set()
    for replacement in replacements:
        if replacement.changed:
            allowed_changes.update(
                range(
                    replacement.entry.extent,
                    replacement.entry.extent + replacement.entry.sector_count,
                )
            )
        if replacement.size_changed:
            allowed_changes.add(replacement.entry.record_offset // USER_DATA_SIZE)

    with Mode1Track(output_track_path, data_track.index_one) as track:
        iso = IsoImage(track)
        output_entries = iso.entries()
        for replacement in replacements:
            entry = output_entries.get(replacement.relative.upper())
            if entry != replacement.output_entry:
                raise ValueError(
                    f"output ISO9660 entry changed: {replacement.relative}"
                )
            if iso.read_entry(entry) != replacement.path.read_bytes():
                raise ValueError(
                    f"output file differs from replacement: {replacement.relative}"
                )
            checked_sectors.update(
                range(
                    replacement.entry.extent,
                    replacement.entry.extent + replacement.entry.sector_count,
                )
            )
            if replacement.size_changed:
                checked_sectors.add(replacement.entry.record_offset // USER_DATA_SIZE)

        for sector in sorted(checked_sectors):
            if not track.sector_checksums_are_valid(sector):
                raise ValueError(f"invalid Mode 1 EDC/ECC at logical sector {sector}")
    raw_changes = differing_sectors(
        source_track_path,
        output_track_path,
        data_track.index_one,
        allowed_changes,
    )
    return len(checked_sectors), raw_changes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cue", type=Path, help="source CUE (default: disc/config.json)"
    )
    parser.add_argument("--replacements", type=Path, default=BUILD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="inject only hash-bound replacement paths declared by this manifest",
    )
    parser.add_argument(
        "--list", action="store_true", help="show the injection plan without writing"
    )
    parser.add_argument(
        "--check", action="store_true", help="verify an existing output without writing"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    contract = load_source_contract()
    cue = (args.cue or contract.cue).resolve()
    replacements_root = args.replacements.resolve()
    output = args.output.resolve()
    manifest = args.manifest.resolve() if args.manifest is not None else None
    if not cue.is_file():
        raise SystemExit(f"source CUE does not exist: {cue}")
    if not replacements_root.is_dir():
        raise SystemExit(f"replacement directory does not exist: {replacements_root}")
    if args.list and args.check:
        raise SystemExit("--list and --check cannot be combined")

    try:
        sheet = CueSheet.read(cue)
        validate_source_disc(sheet, contract)
        data_track = sheet.mode1_track()
        source_track = sheet.source_path(data_track.file)
        with Mode1Track(source_track, data_track.index_one) as track:
            iso = IsoImage(track)
            replacements = plan_replacements(
                replacements_root, output, iso.entries(), iso, manifest
            )

        changed = [replacement for replacement in replacements if replacement.changed]
        for replacement in replacements:
            state = "replace" if replacement.changed else "unchanged"
            print(
                f"{state:9} {replacement.relative} "
                f"({replacement.path.stat().st_size:,}/{replacement.entry.size:,} bytes, "
                f"LBA {replacement.entry.extent})"
            )
        print(
            f"planned {len(changed)} changed and {len(replacements) - len(changed)} unchanged files"
        )

        if args.list:
            return
        if args.check:
            sectors, raw_changes = verify(sheet, output, replacements)
            print(f"verified {len(replacements)} files and {sectors} Mode 1 sectors")
            print(
                f"confirmed all {raw_changes} raw-sector changes belong to replacement files"
            )
            return

        copy_disc(sheet, output)
        output_track = output_path(output, data_track.file)
        with Mode1Track(output_track, data_track.index_one, writable=True) as track:
            for replacement in changed:
                value = replacement.path.read_bytes()
                if replacement.size_changed:
                    allocation = replacement.entry.sector_count * USER_DATA_SIZE
                    value += bytes(allocation - len(value))
                track.replace_extent(replacement.entry.extent, value)
                if replacement.size_changed:
                    size = replacement.path.stat().st_size
                    track.write(
                        replacement.entry.record_offset + 10,
                        struct.pack("<I", size) + struct.pack(">I", size),
                    )
            changed_sectors = len(track.dirty_sectors)
        checked_sectors, raw_changes = verify(sheet, output, replacements)
        print(f"rewrote {changed_sectors} sectors and regenerated their EDC/ECC")
        print(f"verified {len(replacements)} files across {checked_sectors} sectors")
        print(
            f"confirmed all {raw_changes} raw-sector changes belong to replacement files"
        )
        print(f"test disc: {output / sheet.path.name}")
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(error) from error


if __name__ == "__main__":
    main()
