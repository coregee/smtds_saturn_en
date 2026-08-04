"""Load and validate the parent build's release replacement manifest."""

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_files(root: Path, manifest: Path) -> list[Path]:
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"version", "files"}:
        raise ValueError(f"{manifest}: expected version and files")
    if document["version"] != 1 or not isinstance(document["files"], list):
        raise ValueError(f"{manifest}: unsupported release manifest")

    root = root.resolve()
    paths = []
    seen = set()
    for index, row in enumerate(document["files"]):
        context = f"{manifest}: files[{index}]"
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            raise ValueError(f"{context}: expected path, size, and sha256")
        relative = row["path"]
        size = row["size"]
        digest = row["sha256"]
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"{context}.path must be nonempty text")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"{context}.path must stay below the replacement root")
        key = relative_path.as_posix().casefold()
        if key in seen:
            raise ValueError(f"{manifest}: duplicate replacement path {relative}")
        seen.add(key)
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"{context}: replacement is missing: {path}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"{context}.size must be a nonnegative integer")
        if path.stat().st_size != size:
            raise ValueError(f"{context}: replacement size changed: {path}")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"{context}.sha256 must be lowercase SHA-256")
        if sha256(path) != digest:
            raise ValueError(f"{context}: replacement digest changed: {path}")
        paths.append(path)
    if not paths:
        raise ValueError(f"{manifest}: release manifest has no replacement files")
    return paths
