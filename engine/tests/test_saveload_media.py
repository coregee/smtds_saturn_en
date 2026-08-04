import struct
import unittest
from pathlib import Path

from PIL import Image

from engine.script.patching import PatchGroup, apply_patch_groups
from engine.script.saveload import ui
from project_paths import EXTRACTED_ROOT
from visual.script.translation_images import TRANSLATED_IMAGE_ROOT
from visual.script.util.images import (
    ImageAsset,
    decode_rgb555,
    pixel_sha256,
    saveload_image_records,
)


@unittest.skipUnless(
    all((EXTRACTED_ROOT / source).is_file() for source in ("SAVE.BIN", "LOAD.BIN")),
    "requires extracted SAVE.BIN and LOAD.BIN",
)
class SaveLoadMediaTests(unittest.TestCase):
    def test_storage_selector_patches_consume_visual_owned_pngs(self) -> None:
        replacements = {}
        for spec in ui.UI_SPECS:
            source = spec.target.path.as_posix()
            original = (EXTRACTED_ROOT / spec.target.path).read_bytes()
            patches = ui.storage_selector_patches(spec, original)
            self.assertEqual(len(patches), 4)
            patched = apply_patch_groups(
                original,
                (PatchGroup("saveload_ui", spec.target, patches),),
            )
            self.assertEqual(len(patched), len(original))

            records = {record.key: record for record in saveload_image_records(source)}
            prefix = f"{Path(source).stem.lower()}_storage_"
            self.assertEqual(
                {patch.name.removeprefix(prefix) for patch in patches}, set(records)
            )
            for patch in patches:
                key = patch.name.removeprefix(prefix)
                record = records[key]
                asset = record.asset
                offset = asset.offset
                replacement = patched[offset : offset + asset.byte_length]
                self.assertEqual(replacement, patch.replacement)
                with Image.open(
                    TRANSLATED_IMAGE_ROOT / record.translation_file
                ) as image:
                    expected_pixels = pixel_sha256(image.convert("RGB"))
                decoded = decode_rgb555(
                    replacement,
                    ImageAsset(source, asset.image, 0, asset.width, asset.height),
                )
                self.assertEqual(pixel_sha256(decoded), expected_pixels)

                original_words = struct.unpack(
                    f">{asset.width * asset.height}H",
                    original[offset : offset + asset.byte_length],
                )
                replacement_words = struct.unpack(
                    f">{asset.width * asset.height}H", replacement
                )
                self.assertTrue(
                    all(
                        (before & 0x8000) == (after & 0x8000)
                        for before, after in zip(
                            original_words, replacement_words, strict=True
                        )
                    )
                )
                replacements.setdefault(key, replacement)
                self.assertEqual(replacements[key], replacement)


if __name__ == "__main__":
    unittest.main()
