"""Validate the self-contained visual review catalog against extracted files."""

import argparse
import hashlib
import json
from pathlib import Path

from project_paths import EXTRACTED_ROOT, VISUAL_ROOT

CATALOG_PATH = VISUAL_ROOT / "catalog.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate() -> tuple[int, int]:
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {
        "version",
        "method",
        "assets",
    }:
        raise ValueError(f"{CATALOG_PATH}: expected version, method, and assets")
    if document["version"] != 1 or not isinstance(document["method"], str):
        raise ValueError(f"{CATALOG_PATH}: unsupported catalog header")
    assets = document["assets"]
    if not isinstance(assets, list) or not assets:
        raise ValueError(f"{CATALOG_PATH}: assets must be a nonempty array")

    seen = set()
    text_rows = 0
    for index, asset in enumerate(assets):
        context = f"{CATALOG_PATH}: asset {index}"
        if not isinstance(asset, dict):
            raise ValueError(f"{context} must be an object")
        required = {"path", "format", "review", "fingerprint"}
        if not required <= set(asset) or set(asset) - required - {"text", "no_text"}:
            raise ValueError(f"{context}: invalid fields")
        relative = asset["path"]
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"{context}.path must be nonempty text")
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or relative in seen:
            raise ValueError(f"{context}.path is unsafe or duplicated")
        seen.add(relative)
        if not all(
            isinstance(asset[field], str) and asset[field]
            for field in ("format", "review")
        ):
            raise ValueError(f"{context}: format and review must be nonempty text")
        has_text = "text" in asset
        has_no_text = "no_text" in asset
        if has_text == has_no_text:
            raise ValueError(f"{context}: expected exactly one of text or no_text")
        if has_text:
            rows = asset["text"]
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"{context}.text must be a nonempty array")
            for row_index, row in enumerate(rows):
                row_context = f"{context}.text[{row_index}]"
                required = {"kind", "jp", "tr"}
                if (
                    not isinstance(row, dict)
                    or not required <= set(row)
                    or set(row) - required - {"en"}
                ):
                    raise ValueError(f"{context}.text[{row_index}] is malformed")
                if not all(
                    isinstance(row[field], str) and row[field]
                    for field in ("kind", "jp")
                ):
                    raise ValueError(f"{row_context} needs kind and JP text")
                if not isinstance(row["tr"], str):
                    raise ValueError(f"{row_context}.tr must be text")
                if "en" in row and not isinstance(row["en"], str):
                    raise ValueError(f"{row_context}.en must be text when present")
            text_rows += len(rows)
        elif not isinstance(asset["no_text"], str) or not asset["no_text"]:
            raise ValueError(f"{context}.no_text must be nonempty text")

        source = EXTRACTED_ROOT / path
        fingerprint = asset["fingerprint"]
        if not isinstance(fingerprint, dict) or set(fingerprint) != {"size", "sha256"}:
            raise ValueError(f"{context}.fingerprint is malformed")
        if source.stat().st_size != fingerprint["size"]:
            raise ValueError(f"{source}: size changed since visual review")
        if sha256(source) != fingerprint["sha256"]:
            raise ValueError(f"{source}: hash changed since visual review")
    return len(assets), text_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    assets, rows = validate()
    print(f"visual catalog: verified {assets} reviewed assets / {rows} baked-text rows")


if __name__ == "__main__":
    main()
