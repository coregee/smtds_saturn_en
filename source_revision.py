"""Neutral identity contract for the one supported source-disc revision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from project_paths import DISC_ROOT, ORIGINAL_ROOT
from safe_paths import safe_relative_path

CONFIG_PATH = DISC_ROOT / "config.json"


@dataclass(frozen=True)
class TrackContract:
    number: int
    mode: str
    file_type: str
    indexes: tuple[tuple[int, int], ...]
    size: int
    sha256: str


@dataclass(frozen=True)
class SourceDiscContract:
    name: str
    cue: Path
    tracks: tuple[TrackContract, ...]


def _required_text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be non-empty text")
    return value


def _required_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _track_contract(value: object, context: str) -> TrackContract:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    required = {"number", "mode", "file_type", "indexes", "size", "sha256"}
    if set(value) != required:
        raise ValueError(f"{context} must contain exactly {sorted(required)}")

    indexes_value = value["indexes"]
    if not isinstance(indexes_value, dict) or not indexes_value:
        raise ValueError(f"{context}.indexes must be a non-empty object")
    indexes = []
    for raw_index, raw_sector in indexes_value.items():
        if not isinstance(raw_index, str) or not raw_index.isdecimal():
            raise ValueError(f"{context}.indexes keys must be decimal strings")
        index = int(raw_index)
        sector = _required_int(raw_sector, f"{context}.indexes[{raw_index!r}]")
        indexes.append((index, sector))
    indexes.sort()

    digest = _required_text(value["sha256"], f"{context}.sha256").lower()
    if len(digest) != 64:
        raise ValueError(f"{context}.sha256 must be a 64-character SHA-256")
    try:
        bytes.fromhex(digest)
    except ValueError as error:
        raise ValueError(f"{context}.sha256 must be hexadecimal") from error

    return TrackContract(
        number=_required_int(value["number"], f"{context}.number"),
        mode=_required_text(value["mode"], f"{context}.mode").upper(),
        file_type=_required_text(value["file_type"], f"{context}.file_type").upper(),
        indexes=tuple(indexes),
        size=_required_int(value["size"], f"{context}.size"),
        sha256=digest,
    )


def load_source_contract(path: Path = CONFIG_PATH) -> SourceDiscContract:
    """Load the configured CUE name and exact supported track identities."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: expected a JSON object")
    required = {"source_cue", "source_revision"}
    if set(document) != required:
        raise ValueError(f"{path}: expected exactly {sorted(required)}")

    revision = document["source_revision"]
    if not isinstance(revision, dict) or set(revision) != {"name", "tracks"}:
        raise ValueError(f"{path}: source_revision must contain name and tracks")
    tracks_value = revision["tracks"]
    if not isinstance(tracks_value, list) or not tracks_value:
        raise ValueError(f"{path}: source_revision.tracks must be a non-empty array")
    tracks = tuple(
        _track_contract(value, f"{path}: source_revision.tracks[{index}]")
        for index, value in enumerate(tracks_value)
    )
    numbers = [track.number for track in tracks]
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"{path}: source_revision contains duplicate track numbers")

    cue_name = _required_text(document["source_cue"], f"{path}: source_cue")
    cue = safe_relative_path(
        cue_name,
        f"{path}: source_cue",
        allow_backslashes=True,
    )
    return SourceDiscContract(
        name=_required_text(revision["name"], f"{path}: source_revision.name"),
        cue=ORIGINAL_ROOT / cue,
        tracks=tracks,
    )


def contract_sha256(contract: SourceDiscContract) -> str:
    """Fingerprint the revision identity independently of local CUE filenames."""
    document = {
        "name": contract.name,
        "tracks": [
            {
                "number": track.number,
                "mode": track.mode,
                "file_type": track.file_type,
                "indexes": dict(track.indexes),
                "size": track.size,
                "sha256": track.sha256,
            }
            for track in contract.tracks
        ],
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
