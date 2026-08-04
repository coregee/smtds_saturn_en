"""Validate generated static-text assets consumed by engine patches."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from project_paths import EXTRACTED_ROOT, TEXT_GENERATED_ROOT


@dataclass(frozen=True)
class StaticBlock:
    offset: int
    size: int
    storage: str
    unit_count: int

    @property
    def word_count(self) -> int:
        if self.storage != "u16be":
            raise ValueError("static-text block is not stored as u16 words")
        return self.unit_count


@dataclass(frozen=True)
class StaticTextAsset:
    data: bytes
    blocks: dict[str, StaticBlock]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_static_asset(
    relative_path: Path,
    source: Path,
    generated_root: Path = TEXT_GENERATED_ROOT,
    extracted_root: Path = EXTRACTED_ROOT,
) -> StaticTextAsset:
    asset_path = generated_root / relative_path
    source_path = extracted_root / source
    try:
        document = json.loads(asset_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(
            f"missing static-text asset {asset_path}; run text/script/repack.py"
        ) from error

    if document.get("version") != 2:
        raise ValueError(f"{asset_path}: unsupported static-text asset version")
    if document.get("source") != source.as_posix():
        raise ValueError(f"{asset_path}: source does not match {source}")
    if document.get("padding_code") != "0xffff":
        raise ValueError(f"{asset_path}: unsupported padding code")

    source_data = source_path.read_bytes()
    if document.get("source_sha256") != sha256(source_data):
        raise ValueError(
            f"{asset_path}: stale for {source_path}; repack the text package"
        )

    data_hex = document.get("data_hex")
    if not isinstance(data_hex, str):
        raise ValueError(f"{asset_path}: data_hex must be text")
    try:
        data = bytes.fromhex(data_hex)
    except ValueError as error:
        raise ValueError(f"{asset_path}: invalid data_hex") from error

    raw_blocks = document.get("blocks")
    if not isinstance(raw_blocks, dict) or not raw_blocks:
        raise ValueError(f"{asset_path}: blocks must be a nonempty object")
    blocks = {}
    intervals = []
    for name, raw in raw_blocks.items():
        if not isinstance(name, str) or not name or not isinstance(raw, dict):
            raise ValueError(f"{asset_path}: invalid block entry")
        if set(raw) != {"offset", "size", "storage", "unit_count"}:
            raise ValueError(f"{asset_path}: invalid fields for block {name!r}")
        offset = raw["offset"]
        size = raw["size"]
        storage = raw["storage"]
        unit_count = raw["unit_count"]
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
            or offset % 4
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or storage not in {"u16be", "bytes"}
            or not isinstance(unit_count, int)
            or isinstance(unit_count, bool)
            or unit_count <= 0
            or offset + size > len(data)
        ):
            raise ValueError(f"{asset_path}: invalid block {name!r}")
        if (storage == "u16be" and (size % 2 or unit_count != size // 2)) or (
            storage == "bytes" and unit_count != size
        ):
            raise ValueError(f"{asset_path}: invalid unit count for block {name!r}")
        blocks[name] = StaticBlock(offset, size, storage, unit_count)
        intervals.append((offset, offset + size, name))

    intervals.sort()
    for (_, left_end, left_name), (right_start, _, right_name) in zip(
        intervals, intervals[1:]
    ):
        if left_end > right_start:
            raise ValueError(
                f"{asset_path}: blocks {left_name!r} and {right_name!r} overlap"
            )
    return StaticTextAsset(data=data, blocks=blocks)
