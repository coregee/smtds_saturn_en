"""Load and validate the supported source-disc contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

from disc.script.util.cue import CueSheet
from source_revision import (
    CONFIG_PATH,
    SourceDiscContract,
    TrackContract,
    contract_sha256,
    load_source_contract,
)

__all__ = [
    "CONFIG_PATH",
    "SourceDiscContract",
    "TrackContract",
    "contract_sha256",
    "load_source_contract",
    "validate_source_disc",
]


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate_source_disc(
    sheet: CueSheet,
    contract: SourceDiscContract,
    *,
    verify_hashes: bool = True,
) -> None:
    """Reject a CUE whose complete track contract is not the supported revision."""
    referenced_file_ids = {id(track.file) for track in sheet.tracks}
    unreferenced = [
        file.name for file in sheet.files if id(file) not in referenced_file_ids
    ]
    if unreferenced:
        raise ValueError(
            f"{sheet.path.name}: unreferenced FILE records: {', '.join(unreferenced)}"
        )
    by_number = {track.number: track for track in sheet.tracks}
    if len(by_number) != len(sheet.tracks):
        raise ValueError(f"{sheet.path.name}: duplicate track numbers")
    expected_numbers = {track.number for track in contract.tracks}
    if set(by_number) != expected_numbers:
        raise ValueError(
            f"{sheet.path.name}: expected tracks {sorted(expected_numbers)}, "
            f"found {sorted(by_number)}"
        )

    for expected in contract.tracks:
        actual = by_number[expected.number]
        label = f"track {expected.number:02d}"
        if actual.mode != expected.mode:
            raise ValueError(
                f"{sheet.path.name}: {label} mode is {actual.mode}, "
                f"expected {expected.mode}"
            )
        if actual.file.kind != expected.file_type:
            raise ValueError(
                f"{sheet.path.name}: {label} file type is {actual.file.kind}, "
                f"expected {expected.file_type}"
            )
        if tuple(sorted(actual.indexes.items())) != expected.indexes:
            raise ValueError(
                f"{sheet.path.name}: {label} indexes are "
                f"{dict(sorted(actual.indexes.items()))}, expected "
                f"{dict(expected.indexes)}"
            )

        source = sheet.source_path(actual.file)
        if not source.is_file():
            raise ValueError(f"{sheet.path.name}: {label} file is missing: {source}")
        size = source.stat().st_size
        if size != expected.size:
            raise ValueError(
                f"{sheet.path.name}: {label} is {size:,} bytes, "
                f"expected {expected.size:,}"
            )
        if verify_hashes:
            digest = sha256(source)
            if digest != expected.sha256:
                raise ValueError(
                    f"{sheet.path.name}: {label} SHA-256 is {digest}, "
                    f"expected {expected.sha256}"
                )
