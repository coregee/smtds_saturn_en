"""Repack only editable Saturn images whose pixel hashes changed."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import cast

from PIL import Image

from visual.script.translation_images import (
    ORIGINAL_IMAGE_ROOT,
    TRANSLATED_IMAGE_ROOT,
    TRANSLATION_IMAGE_MAP_PATH,
    load_translation_images,
    split_translation_image,
)
from visual.script.util.images import (
    BUILD_ROOT,
    EXTRACTED_ROOT,
    INDEXED8_RGB555_ENCODING,
    MANIFEST_PATH,
    TITLE_INDEXED_IMAGES,
    ImageAsset,
    asset_from_row,
    encode_adaptive_indexed8_group,
    encode_image,
    file_sha256,
    load_manifest,
    pixel_sha256,
)

# These overlays also receive runtime/code patches. The visual stage still owns,
# validates, and reports their PNGs, while the later engine stage composes the
# changed pixels with every other patch before writing the final whole file.
ENGINE_COMPOSED_SOURCES = frozenset({"SAVE.BIN", "LOAD.BIN"})


def translation_image_changes(
    document: dict[str, object],
    *,
    map_path: Path = TRANSLATION_IMAGE_MAP_PATH,
    original_root: Path = ORIGINAL_IMAGE_ROOT,
    translated_root: Path = TRANSLATED_IMAGE_ROOT,
    announce: bool = True,
) -> tuple[
    dict[str, list[tuple[ImageAsset, Image.Image]]],
    dict[str, int],
    int,
]:
    rows = document.get("assets")
    if not isinstance(rows, list):
        raise ValueError("visual image manifest has no asset array")
    manifest_rows = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("visual image manifest asset must be an object")
        asset = asset_from_row(row)
        manifest_rows[asset.image.casefold()] = row

    translation_images = load_translation_images(
        document,
        map_path=map_path,
        original_root=original_root,
        translated_root=translated_root,
    )
    changes: dict[str, list[tuple[ImageAsset, Image.Image]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    target_count = 0
    for translation_image in translation_images:
        path = translated_root / translation_image.file
        with Image.open(path) as opened:
            image = opened.copy()
        pieces = split_translation_image(image, translation_image)
        for asset, piece in zip(translation_image.targets, pieces, strict=True):
            target_count += 1
            counts[asset.source] += 1
            row = manifest_rows[asset.image.casefold()]
            if pixel_sha256(piece) == row["pixel_sha256"]:
                continue
            changes[asset.source].append((asset, piece))
            if announce:
                print(
                    f"changed   {translation_image.file} -> "
                    f"{asset.image} -> {asset.source}"
                )
    return changes, counts, target_count


def expected_source(
    source: str,
    source_row: dict[str, object],
    changes: list[tuple[ImageAsset, Image.Image]],
) -> bytes:
    original = (EXTRACTED_ROOT / source).read_bytes()
    if (
        len(original) != source_row["size"]
        or file_sha256(original) != source_row["sha256"]
    ):
        raise ValueError(f"{source}: extracted source changed since image extraction")
    output = bytearray(original)
    indexed_changes = {
        asset: image
        for asset, image in changes
        if asset.encoding == INDEXED8_RGB555_ENCODING
    }
    grouped: set[ImageAsset] = set()
    for palette_offset in sorted(
        {
            asset.palette_offset
            for asset in indexed_changes
            if asset.source == "TITLE.BIN" and asset.palette_offset is not None
        }
    ):
        group = tuple(
            asset
            for asset in TITLE_INDEXED_IMAGES
            if asset.palette_offset == palette_offset
        )
        replacements = {
            asset: image
            for asset, image in indexed_changes.items()
            if asset.source == "TITLE.BIN" and asset.palette_offset == palette_offset
        }
        encode_adaptive_indexed8_group(output, group, replacements)
        grouped.update(replacements)
    for asset, image in changes:
        if asset in grouped:
            continue
        encode_image(output, asset, image)
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="show changed images without writing"
    )
    parser.add_argument(
        "--check", action="store_true", help="verify current build outputs"
    )
    parser.add_argument(
        "--if-extracted",
        action="store_true",
        help="do nothing when the local image manifest has not been generated",
    )
    args = parser.parse_args()
    if args.list and args.check:
        parser.error("--list and --check cannot be combined")
    if not MANIFEST_PATH.is_file() and args.if_extracted:
        print("visual images: inactive (run visual/script/extract.py to enable)")
        return
    try:
        document = load_manifest()
        sources_value = document.get("sources")
        if not isinstance(sources_value, dict):
            raise ValueError("visual image manifest has no source object")
        sources = cast(dict[str, object], sources_value)
        for source, source_row in sources.items():
            path = Path(source)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe visual source path: {source}")
            if not isinstance(source_row, dict) or set(source_row) != {
                "size",
                "sha256",
            }:
                raise ValueError(f"{source}: malformed source fingerprint")
            original = (EXTRACTED_ROOT / source).read_bytes()
            if (
                len(original) != source_row["size"]
                or file_sha256(original) != source_row["sha256"]
            ):
                raise ValueError(
                    f"{source}: extracted source changed since image extraction"
                )
        changes, counts, target_count = translation_image_changes(document)

        changed_count = sum(len(rows) for rows in changes.values())
        print(
            f"visual images: {changed_count:,}/{target_count:,} translation targets "
            "changed "
            f"across {len(changes):,}/{len(counts):,} mapped sources"
        )
        if args.list:
            return

        for source, source_row in sources.items():
            output = BUILD_ROOT / source
            source_changes = changes.get(source, [])
            if source in ENGINE_COMPOSED_SOURCES:
                print(
                    f"deferred  {source} ({len(source_changes):,}/{counts[source]:,} "
                    "images changed; composed by engine)"
                )
                continue
            if not source_changes:
                if args.check:
                    if output.is_file():
                        original = (EXTRACTED_ROOT / source).read_bytes()
                        if output.read_bytes() != original:
                            raise ValueError(
                                f"{output}: stale visual replacement has no changed PNG"
                            )
                    continue
                if output.is_file():
                    output.unlink()
                    print(f"removed unchanged visual output: {output}")
                continue

            expected = expected_source(
                source, cast(dict[str, object], source_row), source_changes
            )
            if args.check:
                if not output.is_file() or output.read_bytes() != expected:
                    raise ValueError(
                        f"{output}: visual replacement is missing or stale"
                    )
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(expected)
            print(
                f"rebuilt   {source} ({len(source_changes):,}/{counts[source]:,} images changed)"
            )

        print(f"visual images: {'verified' if args.check else 'repacked'} successfully")
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
