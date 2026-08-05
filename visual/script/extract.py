"""Extract proven Saturn images into a sparse editable PNG working set."""

from __future__ import annotations

import argparse
import json

from PIL import Image

from visual.script.translation_images import load_translation_images
from visual.script.util.images import (
    EXTRACTED_ROOT,
    GENERATED_ROOT,
    IMAGE_ROOT,
    MANIFEST_PATH,
    ImageAsset,
    asset_from_row,
    build_manifest,
    decode_image,
    load_manifest,
    manifest_text,
)


def selected(asset: ImageAsset, filters: tuple[str, ...]) -> bool:
    if not filters:
        return True
    values = (asset.source.casefold(), asset.image.casefold())
    return any(
        any(value.startswith(item.casefold()) for value in values) for item in filters
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "filters",
        nargs="*",
        help="optional disc/image path prefixes; the manifest always covers every image",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace existing PNGs"
    )
    parser.add_argument(
        "--restore-missing",
        action="store_true",
        help="recreate registered PNGs that were removed from the working set",
    )
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args()
    try:
        previous_images: set[str] = set()
        if MANIFEST_PATH.is_file():
            try:
                previous = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
                previous_images = {
                    str(row["image"]).casefold()
                    for row in previous.get("assets", [])
                    if isinstance(row, dict) and "image" in row
                }
            except (json.JSONDecodeError, OSError):
                previous_images = set()
        document = build_manifest()
        translation_images = load_translation_images(document)
        translation_targets = sum(len(image.targets) for image in translation_images)
        expected_text = manifest_text(document)
        rows = document["assets"]
        source_cache = {}
        created = 0
        preserved = 0
        skipped = 0
        for row in rows:
            asset = asset_from_row(row)
            if not selected(asset, tuple(args.filters)):
                continue
            output = IMAGE_ROOT / asset.image
            if output.is_file() and not args.overwrite:
                with Image.open(output) as image:
                    if image.size != (asset.width, asset.height):
                        raise ValueError(
                            f"{output}: image is {image.width}x{image.height}; "
                            f"expected {asset.width}x{asset.height}"
                        )
                preserved += 1
                continue
            was_registered = asset.image.casefold() in previous_images
            if not output.is_file() and was_registered and not args.restore_missing:
                skipped += 1
                continue
            if args.check:
                continue
            data = source_cache.setdefault(
                asset.source, (EXTRACTED_ROOT / asset.source).read_bytes()
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            decode_image(data, asset).save(output)
            created += 1

        if args.check:
            if not MANIFEST_PATH.is_file():
                raise ValueError(f"visual image manifest is missing: {MANIFEST_PATH}")
            if manifest_text(load_manifest()) != expected_text:
                raise ValueError(f"{MANIFEST_PATH}: manifest is stale")
            print(
                f"visual images: verified {preserved:,} working-set PNGs / "
                f"{skipped:,} intentionally absent, "
                f"{len(translation_images):,} original + "
                f"{len(translation_images):,} translated PNGs / "
                f"{translation_targets:,} targets, and manifest"
            )
            return

        GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(expected_text, encoding="utf-8", newline="\n")
        print(
            f"visual images: {len(rows):,} registered / {created:,} extracted / "
            f"{preserved:,} preserved / {skipped:,} intentionally absent"
        )
        print(
            f"translation images: {len(translation_images):,} original + "
            f"{len(translation_images):,} translated PNGs / "
            f"{translation_targets:,} targets"
        )
        print(f"editable images: {IMAGE_ROOT}")
        print(f"hash manifest:   {MANIFEST_PATH}")
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
