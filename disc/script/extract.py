"""Extract the supported source disc into the read-only local file mirror."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from disc.script.source import load_source_contract, validate_source_disc
from disc.script.util.cue import CueSheet
from disc.script.util.iso9660 import IsoEntry, IsoImage
from disc.script.util.sector import Mode1Track
from project_paths import EXTRACTED_ROOT


class EntryReader(Protocol):
    def read_entry(self, entry: IsoEntry) -> bytes: ...


@dataclass(frozen=True)
class ExtractionStatus:
    created: int = 0
    current: int = 0
    stale: int = 0
    bytes_written: int = 0


def output_path(root: Path, entry: IsoEntry) -> Path:
    relative = PurePosixPath(entry.path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe ISO9660 path: {entry.path!r}")
    output = root.joinpath(*relative.parts)
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"ISO9660 path escapes extraction root: {entry.path!r}")
    return output


def extract_entries(
    iso: EntryReader,
    entries: tuple[IsoEntry, ...],
    root: Path,
    *,
    check: bool = False,
    overwrite: bool = False,
) -> ExtractionStatus:
    """Write or verify ISO files without silently replacing a local mismatch."""
    created = current = stale = bytes_written = 0
    for entry in entries:
        destination = output_path(root, entry)
        value = iso.read_entry(entry)
        if len(value) != entry.size:
            raise ValueError(
                f"{entry.path}: read {len(value):,} bytes, expected {entry.size:,}"
            )

        if destination.is_file() and destination.read_bytes() == value:
            current += 1
            continue
        if check:
            stale += 1
            continue
        if destination.exists() and not destination.is_file():
            raise ValueError(f"extraction target is not a file: {destination}")
        if destination.exists() and not overwrite:
            raise ValueError(
                f"{destination}: existing file differs; pass --overwrite only "
                "after confirming it is disposable extracted data"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        if temporary.exists():
            raise ValueError(f"temporary extraction path already exists: {temporary}")
        try:
            temporary.write_bytes(value)
            os.replace(temporary, destination)
        finally:
            if temporary.is_file():
                temporary.unlink()
        created += 1
        bytes_written += len(value)

    return ExtractionStatus(created, current, stale, bytes_written)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cue", type=Path, help="source CUE (default: disc/config.json)"
    )
    parser.add_argument("--output", type=Path, default=EXTRACTED_ROOT)
    parser.add_argument(
        "--list", action="store_true", help="validate and list files without writing"
    )
    parser.add_argument(
        "--check", action="store_true", help="verify the complete extracted mirror"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace differing files already present in the extraction directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if sum((args.list, args.check, args.overwrite)) > 1:
        raise SystemExit("--list, --check, and --overwrite cannot be combined")

    try:
        contract = load_source_contract()
        cue = (args.cue or contract.cue).resolve()
        output = args.output.resolve()
        if not cue.is_file():
            raise ValueError(f"source CUE does not exist: {cue}")

        sheet = CueSheet.read(cue)
        validate_source_disc(sheet, contract)
        for file in sheet.files:
            source = sheet.source_path(file).resolve()
            if source.is_relative_to(output):
                raise ValueError(
                    f"extraction directory would contain source track: {source}"
                )

        data_track = sheet.mode1_track()
        source_track = sheet.source_path(data_track.file)
        with Mode1Track(source_track, data_track.index_one) as track:
            iso = IsoImage(track)
            entries = tuple(
                sorted(iso.entries().values(), key=lambda entry: entry.path.upper())
            )
            total_size = sum(entry.size for entry in entries)
            if args.list:
                for entry in entries:
                    print(f"{entry.path} ({entry.size:,} bytes, LBA {entry.extent})")
                print(
                    f"supported source: {contract.name}; "
                    f"{len(entries):,} files / {total_size:,} bytes"
                )
                return

            status = extract_entries(
                iso,
                entries,
                output,
                check=args.check,
                overwrite=args.overwrite,
            )

        if args.check and status.stale:
            raise ValueError(
                f"{status.stale:,} extracted files are missing or differ under {output}"
            )
        action = "verified" if args.check else "extracted"
        print(
            f"{action} {len(entries):,} files from {contract.name}: "
            f"{status.created:,} written, {status.current:,} already current, "
            f"{status.bytes_written:,} bytes written"
        )
        print(f"extracted mirror: {output}")
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(error) from error


if __name__ == "__main__":
    main()
