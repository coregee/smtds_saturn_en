"""Digest-checked text patches for binaries composed by the engine package."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ASSET_VERSION = 1


@dataclass(frozen=True)
class PatchSpan:
    name: str
    file_offset: int
    size: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_asset_json(
    *,
    source_path: Path,
    original: bytes,
    replacement: bytes,
    corpus_relative: Path,
    corpus_path: Path,
    load_address: int,
    spans: Iterable[PatchSpan],
    extra: dict | None = None,
) -> str:
    if len(replacement) != len(original):
        raise ValueError(f"{source_path}: replacement changed the file size")
    patches = []
    occupied = []
    names = set()
    for span in spans:
        context = f"{source_path}:{span.name}"
        if not span.name or span.name in names:
            raise ValueError(f"{context}: empty or duplicate patch name")
        names.add(span.name)
        start = span.file_offset
        end = start + span.size
        if start < 0 or span.size <= 0 or end > len(original):
            raise ValueError(f"{context}: patch span exceeds the source")
        if any(
            start < other_end and other_start < end
            for other_start, other_end in occupied
        ):
            raise ValueError(f"{context}: patch span overlaps another field")
        occupied.append((start, end))
        before = original[start:end]
        after = replacement[start:end]
        if before == after:
            continue
        patches.append(
            {
                "name": span.name,
                "file_offset": f"0x{start:x}",
                "expected_sha256": sha256(before),
                "replacement_hex": after.hex(),
            }
        )
    asset = {
        "version": ASSET_VERSION,
        "source": source_path.as_posix(),
        "source_sha256": sha256(original),
        "corpus": corpus_relative.as_posix(),
        "corpus_sha256": sha256(corpus_path.read_bytes()),
        "load_address": f"0x{load_address:08x}",
        "patches": patches,
    }
    if extra:
        overlap = set(asset) & set(extra)
        if overlap:
            raise ValueError(f"{source_path}: duplicate asset keys {sorted(overlap)}")
        asset.update(extra)
    return json.dumps(asset, ensure_ascii=False, indent=2) + "\n"
