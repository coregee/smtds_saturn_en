"""Validate the tracked original and translated image source sets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from project_paths import VISUAL_ROOT
from safe_paths import safe_relative_path
from visual.script.util.images import ImageAsset, asset_from_row, pixel_sha256

TRANSLATION_IMAGE_ROOT = VISUAL_ROOT / "translation_images"
ORIGINAL_IMAGE_ROOT = TRANSLATION_IMAGE_ROOT / "original"
TRANSLATED_IMAGE_ROOT = TRANSLATION_IMAGE_ROOT / "translated"
TRANSLATION_IMAGE_MAP_PATH = VISUAL_ROOT / "translation_images.json"


@dataclass(frozen=True)
class TranslationImage:
    file: str
    layout: str
    targets: tuple[ImageAsset, ...]


def _flat_png(value: object, context: str) -> str:
    relative = safe_relative_path(value, context)
    if len(relative.parts) != 1 or relative.suffix.casefold() != ".png":
        raise ValueError(f"{context} must be one flat PNG filename")
    return relative.as_posix()


def split_translation_image(
    image: Image.Image,
    translation_image: TranslationImage,
) -> tuple[Image.Image, ...]:
    """Return one target-sized image for every target in a mapped image."""
    if translation_image.layout == "identity":
        return tuple(image for _target in translation_image.targets)
    if translation_image.layout == "horizontal":
        pieces = []
        left = 0
        for target in translation_image.targets:
            right = left + target.width
            pieces.append(image.crop((left, 0, right, target.height)))
            left = right
        return tuple(pieces)
    raise ValueError(
        f"unsupported translation-image layout: {translation_image.layout}"
    )


def _validate_file_set(image_root: Path, expected: set[str], label: str) -> None:
    actual = {
        path.relative_to(image_root).as_posix().casefold()
        for path in image_root.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"{image_root}: {label} image set does not match its map; "
            f"missing={missing or 'none'}, unexpected={unexpected or 'none'}"
        )


def load_translation_images(
    manifest: dict[str, object],
    *,
    map_path: Path = TRANSLATION_IMAGE_MAP_PATH,
    original_root: Path = ORIGINAL_IMAGE_ROOT,
    translated_root: Path = TRANSLATED_IMAGE_ROOT,
) -> tuple[TranslationImage, ...]:
    """Bind tracked reference/editable PNGs to their extracted image targets."""
    document = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"version", "images"}:
        raise ValueError(f"{map_path}: expected exactly version and images")
    if document["version"] != 2:
        raise ValueError(f"{map_path}: unsupported translation-image map")
    image_rows = document["images"]
    if not isinstance(image_rows, list) or not image_rows:
        raise ValueError(f"{map_path}: images must be a nonempty array")

    manifest_rows = manifest.get("assets")
    if not isinstance(manifest_rows, list):
        raise ValueError("visual image manifest has no asset array")
    registered: dict[str, tuple[ImageAsset, dict[str, object]]] = {}
    for row_number, row in enumerate(manifest_rows):
        if not isinstance(row, dict):
            raise ValueError(f"visual manifest asset {row_number} must be an object")
        asset = asset_from_row(row)
        key = asset.image.casefold()
        if key in registered:
            raise ValueError(f"visual manifest repeats image target {asset.image}")
        registered[key] = (asset, row)

    files: set[str] = set()
    claimed_targets: set[str] = set()
    images = []
    original_hashes: list[tuple[TranslationImage, tuple[str, ...]]] = []
    for row_number, row in enumerate(image_rows):
        context = f"{map_path}: images[{row_number}]"
        if not isinstance(row, dict) or set(row) != {"file", "layout", "targets"}:
            raise ValueError(
                f"{context} must contain exactly file, layout, and targets"
            )
        file = _flat_png(row["file"], f"{context}.file")
        file_key = file.casefold()
        if file_key in files:
            raise ValueError(f"{context}: duplicate translation image {file}")
        files.add(file_key)

        layout = row["layout"]
        if layout not in {"identity", "horizontal"}:
            raise ValueError(f"{context}.layout must be identity or horizontal")
        target_values = row["targets"]
        if not isinstance(target_values, list) or not target_values:
            raise ValueError(f"{context}.targets must be a nonempty array")
        if layout == "horizontal" and len(target_values) != 2:
            raise ValueError(
                f"{context}: horizontal layout requires exactly two targets"
            )
        targets = []
        target_hashes = []
        dimensions = set()
        heights = set()
        encodings = set()
        for target_number, target_value in enumerate(target_values):
            target_context = f"{context}.targets[{target_number}]"
            target = safe_relative_path(target_value, target_context).as_posix()
            key = target.casefold()
            if key in claimed_targets:
                raise ValueError(f"{target_context}: target is claimed more than once")
            try:
                asset, manifest_row = registered[key]
            except KeyError:
                raise ValueError(
                    f"{target_context}: target is not in the visual manifest: {target}"
                ) from None
            if target != asset.image:
                raise ValueError(
                    f"{target_context}: expected canonical target spelling {asset.image}"
                )
            claimed_targets.add(key)
            targets.append(asset)
            target_hashes.append(str(manifest_row["pixel_sha256"]))
            dimensions.add((asset.width, asset.height))
            heights.add(asset.height)
            encodings.add(asset.encoding)
        if len(encodings) != 1:
            raise ValueError(f"{context}: targets do not use one image encoding")
        if layout == "identity":
            if len(set(target_hashes)) != 1:
                raise ValueError(
                    f"{context}: deduplicated targets do not have identical source pixels"
                )
            if len(dimensions) != 1:
                raise ValueError(
                    f"{context}: deduplicated targets do not have identical dimensions"
                )
            expected_size = next(iter(dimensions))
        else:
            if len(heights) != 1:
                raise ValueError(
                    f"{context}: horizontal targets have different heights"
                )
            expected_size = (
                sum(target.width for target in targets),
                next(iter(heights)),
            )

        translation_image = TranslationImage(file, str(layout), tuple(targets))
        for image_root, label in (
            (original_root, "original"),
            (translated_root, "translated"),
        ):
            path = image_root / file
            if not path.is_file():
                raise ValueError(f"{path}: tracked {label} image is missing")
            with Image.open(path) as opened:
                size = opened.size
            if size != expected_size:
                raise ValueError(
                    f"{path}: image is {size[0]}x{size[1]}; "
                    f"expected {expected_size[0]}x{expected_size[1]}"
                )
        images.append(translation_image)
        original_hashes.append((translation_image, tuple(target_hashes)))

    _validate_file_set(original_root, files, "original")
    _validate_file_set(translated_root, files, "translated")
    for translation_image, expected_hashes in original_hashes:
        path = original_root / translation_image.file
        with Image.open(path) as opened:
            original = opened.convert("RGB")
        pieces = split_translation_image(original, translation_image)
        for target, piece, expected_hash in zip(
            translation_image.targets, pieces, expected_hashes, strict=True
        ):
            if pixel_sha256(piece) != expected_hash:
                raise ValueError(
                    f"{path}: original pixels do not match mapped target {target.image}"
                )
    return tuple(images)
