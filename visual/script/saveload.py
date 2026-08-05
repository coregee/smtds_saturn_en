"""Load canonical SAVE/LOAD storage-selector translations for engine composition."""

from dataclasses import replace
from pathlib import Path

from PIL import Image

from visual.script.translation_images import TRANSLATED_IMAGE_ROOT
from visual.script.util.images import (
    SaveLoadImageRecord,
    encode_rgb555,
)


def build_replacement(
    source_data: bytes,
    record: SaveLoadImageRecord,
    image_root: Path = TRANSLATED_IMAGE_ROOT,
) -> bytes:
    """Encode one tracked translation over its asserted original RGB555 span."""

    asset = record.asset
    end = asset.offset + asset.byte_length
    original = source_data[asset.offset : end]
    if len(original) != asset.byte_length:
        raise ValueError(f"{asset.source}: too small for {asset.image}")
    path = image_root / record.translation_file
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    local_asset = replace(asset, offset=0)
    replacement = bytearray(original)
    encode_rgb555(replacement, local_asset, image)
    return bytes(replacement)
