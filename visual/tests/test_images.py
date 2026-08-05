import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from visual.script.repack import ENGINE_COMPOSED_SOURCES, translation_image_changes
from visual.script.translation_images import (
    ORIGINAL_IMAGE_ROOT,
    TRANSLATED_IMAGE_ROOT,
    TRANSLATION_IMAGE_MAP_PATH,
    load_translation_images,
)
from visual.script.util.images import (
    EXTRACTED_ROOT,
    INDEXED8_RGB555_ENCODING,
    LEGACY_MANIFEST_VERSION,
    MANIFEST_ENCODING,
    MANIFEST_VERSION,
    RGB555_ENCODING,
    RGB888_ENCODING,
    SAVELOAD_IMAGE_RECORDS,
    TITLE_BIN_IMAGES,
    TITLE_BIN_RGB555_IMAGES,
    TITLE_FULL_RASTER_IMAGE,
    TITLE_IMAGE_RECORDS,
    TITLE_IMAGES,
    TITLE_INDEXED_IMAGES,
    TITLE_PRESS_START_GLYPHS,
    TITLE_START_BUTTON_GLYPHS,
    ImageAsset,
    asset_from_row,
    decode_image,
    decode_indexed8,
    decode_rgb555,
    decode_rgb888,
    encode_adaptive_indexed8_group,
    encode_image,
    encode_indexed8,
    encode_rgb555,
    encode_rgb888,
    load_manifest,
    pixel_sha256,
    saveload_image_records,
    validate_saveload_image_records,
)


class ImageCodecTests(unittest.TestCase):
    def test_decode_encode_is_byte_exact_and_preserves_high_bit(self) -> None:
        source = bytes.fromhex("0000 001f 03e0 7c00 ffff 8421")
        asset = ImageAsset("test.bin", "test.png", 0, 3, 2)
        image = decode_rgb555(source, asset)
        rebuilt = bytearray(source)
        encode_rgb555(rebuilt, asset, image)
        self.assertEqual(bytes(rebuilt), source)

    def test_changed_pixel_is_quantized_without_changing_high_bit(self) -> None:
        source = bytearray.fromhex("8000 0000")
        asset = ImageAsset("test.bin", "test.png", 0, 2, 1)
        image = Image.new("RGB", (2, 1))
        image.putdata(((255, 0, 0), (0, 255, 0)))
        encode_rgb555(source, asset, image)
        self.assertEqual(source, bytearray.fromhex("801f 03e0"))

    def test_tiled_decode_encode_is_byte_exact(self) -> None:
        source = b"".join(value.to_bytes(2, "big") for value in range(128))
        asset = ImageAsset("tiles.bin", "tiles.png", 0, 16, 8, "tiled8")
        image = decode_rgb555(source, asset)
        self.assertNotEqual(image.getpixel((8, 0)), image.getpixel((7, 0)))
        rebuilt = bytearray(source)
        encode_rgb555(rebuilt, asset, image)
        self.assertEqual(bytes(rebuilt), source)

    def test_rgb888_decode_encode_is_byte_exact_and_preserves_control_byte(
        self,
    ) -> None:
        source = bytes.fromhex("80 00 00 00 80 00 00 FF 80 00 FF 00 80 FF 00 00")
        asset = ImageAsset(
            "test.bin",
            "test.png",
            0,
            4,
            1,
            encoding=RGB888_ENCODING,
        )
        image = decode_rgb888(source, asset)
        self.assertEqual(
            [image.getpixel((x, 0)) for x in range(image.width)],
            [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)],
        )
        rebuilt = bytearray(source)
        encode_rgb888(rebuilt, asset, image)
        self.assertEqual(bytes(rebuilt), source)

    def test_indexed_decode_encode_is_byte_exact_with_duplicate_colors(self) -> None:
        source = bytearray(520)
        source[0:8] = bytes((0, 1, 2, 1, 2, 0, 1, 2))
        source[8:14] = bytes.fromhex("0000 001f 001f")
        asset = ImageAsset(
            "title.bin",
            "title.png",
            0,
            4,
            2,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=8,
            palette_entries=256,
        )
        image = decode_indexed8(bytes(source), asset)
        rebuilt = bytearray(source)
        encode_indexed8(rebuilt, asset, image)
        self.assertEqual(rebuilt, source)

    def test_indexed_encode_rejects_colors_outside_fixed_palette(self) -> None:
        source = bytearray(514)
        asset = ImageAsset(
            "title.bin",
            "title.png",
            0,
            2,
            1,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=2,
            palette_entries=256,
        )
        image = Image.new("RGB", (2, 1), (1, 2, 3))
        with self.assertRaisesRegex(ValueError, "absent from its fixed palette"):
            encode_indexed8(source, asset, image)

    def test_indexed_decode_rejects_runtime_out_of_range_index(self) -> None:
        source = bytearray.fromhex("04 0000 8000 801F 83E0")
        asset = ImageAsset(
            "title.bin",
            "bad-index.png",
            0,
            1,
            1,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=1,
            palette_entries=4,
        )

        with self.assertRaisesRegex(ValueError, "exceeds its 4-entry runtime palette"):
            decode_indexed8(bytes(source), asset)

    def test_adaptive_indexed_palette_preserves_unchanged_consumer(self) -> None:
        source = bytearray(12)
        source[0:4] = bytes((0, 2, 0, 0))
        source[4:12] = bytes.fromhex("0000 8000 83E0 0000")
        unchanged = ImageAsset(
            "title.bin",
            "unchanged.png",
            0,
            2,
            1,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=4,
            palette_entries=4,
        )
        changed = ImageAsset(
            "title.bin",
            "changed.png",
            2,
            2,
            1,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=4,
            palette_entries=4,
        )
        replacement = Image.new("RGBA", (2, 1))
        replacement.putdata(((255, 0, 0, 255), (0, 0, 255, 0)))

        encode_adaptive_indexed8_group(
            source, (unchanged, changed), {changed: replacement}
        )

        self.assertEqual(source[0:2], bytes((0, 2)))
        self.assertEqual(source[2:4], bytes((3, 0)))
        self.assertEqual(source[4:12], bytes.fromhex("0000 8000 83E0 801F"))

    def test_adaptive_indexed_alpha_becomes_palette_shades(self) -> None:
        asset = ImageAsset(
            "title.bin",
            "gradient.png",
            0,
            4,
            1,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=4,
            palette_entries=5,
        )
        replacement = Image.new("RGBA", (4, 1))
        replacement.putdata(
            (
                (0, 0, 255, 0),
                (255, 0, 0, 64),
                (255, 0, 0, 128),
                (255, 0, 0, 255),
            )
        )
        first = bytearray(14)
        first[4:8] = bytes.fromhex("0000 8000")
        second = first.copy()

        encode_adaptive_indexed8_group(first, (asset,), {asset: replacement})
        encode_adaptive_indexed8_group(second, (asset,), {asset: replacement})

        self.assertEqual(first, second)
        self.assertEqual(first[:4], bytes((0, 2, 3, 4)))
        self.assertEqual(first[4:14], bytes.fromhex("0000 8000 8008 8010 801F"))
        self.assertTrue(all(index < asset.palette_entries for index in first[:4]))

    def test_adaptive_indexed_requires_alpha_for_two_black_semantics(self) -> None:
        source = bytearray.fromhex("00 01 0000 8000")
        asset = ImageAsset(
            "title.bin",
            "black.png",
            0,
            2,
            1,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=2,
            palette_entries=2,
        )
        replacement = Image.new("RGB", (2, 1), (255, 0, 0))

        with self.assertRaisesRegex(ValueError, "RGBA input is required"):
            encode_adaptive_indexed8_group(source, (asset,), {asset: replacement})

    def test_adaptive_indexed_over_capacity_is_deterministic_and_bounded(self) -> None:
        asset = ImageAsset(
            "title.bin",
            "many-colors.png",
            0,
            4,
            1,
            encoding=INDEXED8_RGB555_ENCODING,
            palette_offset=4,
            palette_entries=4,
        )
        replacement = Image.new("RGB", (4, 1))
        replacement.putdata(((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)))
        first = bytearray(12)
        first[4:8] = bytes.fromhex("0000 8000")
        second = first.copy()

        encode_adaptive_indexed8_group(first, (asset,), {asset: replacement})
        encode_adaptive_indexed8_group(second, (asset,), {asset: replacement})

        self.assertEqual(first, second)
        self.assertLess(max(first[:4]), asset.palette_entries)
        self.assertTrue(all(first[4 + index * 2] & 0x80 for index in set(first[:4])))

    def test_title_registry_covers_all_declared_images(self) -> None:
        self.assertEqual(len(TITLE_BIN_IMAGES), 31)
        self.assertEqual(len(TITLE_IMAGES), 32)
        self.assertEqual(len(TITLE_IMAGE_RECORDS), len(TITLE_BIN_IMAGES))
        self.assertEqual(TITLE_FULL_RASTER_IMAGE.source, "TESTLOGO.COF")
        self.assertEqual(
            (TITLE_FULL_RASTER_IMAGE.width, TITLE_FULL_RASTER_IMAGE.height),
            (352, 240),
        )
        self.assertEqual(TITLE_FULL_RASTER_IMAGE.encoding, RGB888_ENCODING)
        self.assertEqual(
            [asset.palette_offset for asset in TITLE_INDEXED_IMAGES],
            [0x1A1E4, 0x1CC64, 0x1DB84],
        )
        self.assertEqual(
            [asset.palette_entries for asset in TITLE_INDEXED_IMAGES],
            [198, 64, 64],
        )
        self.assertEqual(
            [asset.offset + asset.byte_length for asset in TITLE_INDEXED_IMAGES],
            [0x1A1E4, 0x1CC64, 0x1DB84],
        )
        self.assertEqual(
            "".join(
                asset.image.rsplit("_", 1)[-1][0] for asset in TITLE_PRESS_START_GLYPHS
            ),
            "pressstartbutton",
        )
        self.assertEqual(
            "".join(
                asset.image.rsplit("_", 1)[-1][0] for asset in TITLE_START_BUTTON_GLYPHS
            ),
            "startbutton",
        )
        self.assertEqual(
            {asset.encoding for asset in TITLE_BIN_RGB555_IMAGES},
            {RGB555_ENCODING},
        )
        spans = sorted(
            (asset.offset, asset.offset + asset.byte_length)
            for asset in TITLE_BIN_RGB555_IMAGES
        )
        self.assertEqual(spans[0][0], 0x1DD84)
        self.assertEqual(spans[-1][1], 0x20F64)
        self.assertTrue(
            all(
                spans[index][1] == spans[index + 1][0]
                for index in range(len(spans) - 1)
            )
        )

    @unittest.skipUnless(
        all(
            (EXTRACTED_ROOT / source).is_file()
            for source in ("TITLE.BIN", "TESTLOGO.COF")
        ),
        "requires extracted TITLE.BIN and TESTLOGO.COF",
    )
    def test_registered_title_images_round_trip_exactly(self) -> None:
        sources = {
            asset.source: (EXTRACTED_ROOT / asset.source).read_bytes()
            for asset in TITLE_IMAGES
        }
        for asset in TITLE_IMAGES:
            with self.subTest(image=asset.image):
                source = sources[asset.source]
                image = decode_image(source, asset)
                rebuilt = bytearray(source)
                encode_image(rebuilt, asset, image)
                self.assertEqual(bytes(rebuilt), source)

    @unittest.skipUnless(
        all((EXTRACTED_ROOT / source).is_file() for source in ("SAVE.BIN", "LOAD.BIN")),
        "requires extracted SAVE.BIN and LOAD.BIN",
    )
    def test_registered_saveload_images_match_descriptors_and_each_other(self) -> None:
        sources = {
            source: (EXTRACTED_ROOT / source).read_bytes()
            for source in ("SAVE.BIN", "LOAD.BIN")
        }
        self.assertEqual(len(SAVELOAD_IMAGE_RECORDS), 8)
        for source, data in sources.items():
            validate_saveload_image_records(data, source)
            records = saveload_image_records(source)
            self.assertEqual(len(records), 4)
            for record in records:
                with self.subTest(source=source, image=record.asset.image):
                    image = decode_image(data, record.asset)
                    rebuilt = bytearray(data)
                    encode_image(rebuilt, record.asset, image)
                    self.assertEqual(bytes(rebuilt), data)

        save = {record.key: record for record in saveload_image_records("SAVE.BIN")}
        load = {record.key: record for record in saveload_image_records("LOAD.BIN")}
        self.assertEqual(save.keys(), load.keys())
        for key in save:
            save_asset = save[key].asset
            load_asset = load[key].asset
            self.assertEqual(
                sources["SAVE.BIN"][
                    save_asset.offset : save_asset.offset + save_asset.byte_length
                ],
                sources["LOAD.BIN"][
                    load_asset.offset : load_asset.offset + load_asset.byte_length
                ],
            )


class ManifestTests(unittest.TestCase):
    def test_asset_row_uses_only_normalized_pixel_hash(self) -> None:
        asset = ImageAsset("test.bin", "test.png", 0, 2, 1)
        row = asset.manifest_row(bytes.fromhex("001F 03E0"))

        self.assertEqual(
            set(row),
            {
                "source",
                "image",
                "encoding",
                "layout",
                "offset",
                "palette_offset",
                "palette_entries",
                "length",
                "width",
                "height",
                "pixel_sha256",
            },
        )
        self.assertEqual(asset_from_row(row), asset)

    def test_legacy_manifest_is_normalized_and_unknown_version_is_rejected(
        self,
    ) -> None:
        asset = ImageAsset("test.bin", "test.png", 0, 2, 1)
        row = asset.manifest_row(bytes.fromhex("001F 03E0"))
        row["png_sha256"] = "legacy-unused-hash"
        document = {
            "version": LEGACY_MANIFEST_VERSION,
            "encoding": MANIFEST_ENCODING,
            "sources": {},
            "assets": [row],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "images.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            loaded = load_manifest(path)
            self.assertEqual(loaded["version"], MANIFEST_VERSION)
            self.assertNotIn("png_sha256", loaded["assets"][0])
            self.assertEqual(asset_from_row(loaded["assets"][0]), asset)

            document["version"] = MANIFEST_VERSION + 1
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "unsupported visual image manifest"
            ):
                load_manifest(path)


class TranslationImageTests(unittest.TestCase):
    @staticmethod
    def manifest_row(
        image: str,
        pixel_hash: str,
        *,
        offset: int = 0,
    ) -> dict[str, object]:
        return {
            "source": "textures.bin",
            "image": image,
            "encoding": RGB555_ENCODING,
            "layout": "linear",
            "offset": offset,
            "palette_offset": None,
            "palette_entries": None,
            "length": 4,
            "width": 2,
            "height": 1,
            "pixel_sha256": pixel_hash,
        }

    def test_one_flat_image_can_repack_identical_source_targets(self) -> None:
        clean = Image.new("RGB", (2, 1), (255, 0, 0))
        clean_hash = pixel_sha256(clean)
        manifest = {
            "assets": [
                self.manifest_row("TEX3D/A/001.png", clean_hash),
                self.manifest_row("TEX3D/B/001.png", clean_hash, offset=4),
            ]
        }
        mapping = {
            "version": 2,
            "images": [
                {
                    "file": "tex3d_a_001.png",
                    "layout": "identity",
                    "targets": ["TEX3D/A/001.png", "TEX3D/B/001.png"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_path = root / "translation_images.json"
            original_root = root / "original"
            translated_root = root / "translated"
            original_root.mkdir()
            translated_root.mkdir()
            map_path.write_text(json.dumps(mapping), encoding="utf-8")
            clean.save(original_root / "tex3d_a_001.png")
            clean.save(translated_root / "tex3d_a_001.png")

            images = load_translation_images(
                manifest,
                map_path=map_path,
                original_root=original_root,
                translated_root=translated_root,
            )
            unchanged, _, target_count = translation_image_changes(
                manifest,
                map_path=map_path,
                original_root=original_root,
                translated_root=translated_root,
                announce=False,
            )
            Image.new("RGB", (2, 1), (0, 0, 255)).save(
                translated_root / "tex3d_a_001.png"
            )
            changed, _, _ = translation_image_changes(
                manifest,
                map_path=map_path,
                original_root=original_root,
                translated_root=translated_root,
                announce=False,
            )

        self.assertEqual(len(images), 1)
        self.assertEqual(len(images[0].targets), 2)
        self.assertEqual(target_count, 2)
        self.assertEqual(unchanged, {})
        self.assertEqual(len(changed["textures.bin"]), 2)

    def test_deduplication_requires_identical_original_pixels(self) -> None:
        manifest = {
            "assets": [
                self.manifest_row("TEX3D/A/001.png", "a"),
                self.manifest_row("TEX3D/B/001.png", "b", offset=4),
            ]
        }
        mapping = {
            "version": 2,
            "images": [
                {
                    "file": "shared.png",
                    "layout": "identity",
                    "targets": ["TEX3D/A/001.png", "TEX3D/B/001.png"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_path = root / "translation_images.json"
            original_root = root / "original"
            translated_root = root / "translated"
            original_root.mkdir()
            translated_root.mkdir()
            map_path.write_text(json.dumps(mapping), encoding="utf-8")
            Image.new("RGB", (2, 1)).save(original_root / "shared.png")
            Image.new("RGB", (2, 1)).save(translated_root / "shared.png")

            with self.assertRaisesRegex(ValueError, "identical source pixels"):
                load_translation_images(
                    manifest,
                    map_path=map_path,
                    original_root=original_root,
                    translated_root=translated_root,
                )

    def test_horizontal_image_is_split_back_into_two_targets(self) -> None:
        left = Image.new("RGB", (2, 1), (255, 0, 0))
        right = Image.new("RGB", (2, 1), (0, 255, 0))
        manifest = {
            "assets": [
                self.manifest_row("TEX3D/A/001.png", pixel_sha256(left)),
                self.manifest_row("TEX3D/A/002.png", pixel_sha256(right), offset=4),
            ]
        }
        mapping = {
            "version": 2,
            "images": [
                {
                    "file": "wide.png",
                    "layout": "horizontal",
                    "targets": ["TEX3D/A/001.png", "TEX3D/A/002.png"],
                }
            ],
        }
        original = Image.new("RGB", (4, 1))
        original.paste(left, (0, 0))
        original.paste(right, (2, 0))
        translated = original.copy()
        translated.paste(Image.new("RGB", (2, 1), (0, 0, 255)), (2, 0))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_path = root / "translation_images.json"
            original_root = root / "original"
            translated_root = root / "translated"
            original_root.mkdir()
            translated_root.mkdir()
            map_path.write_text(json.dumps(mapping), encoding="utf-8")
            original.save(original_root / "wide.png")
            translated.save(translated_root / "wide.png")

            changes, _, target_count = translation_image_changes(
                manifest,
                map_path=map_path,
                original_root=original_root,
                translated_root=translated_root,
                announce=False,
            )

        self.assertEqual(target_count, 2)
        self.assertEqual(
            [asset.image for asset, _image in changes["textures.bin"]],
            ["TEX3D/A/002.png"],
        )
        self.assertEqual(changes["textures.bin"][0][1].size, (2, 1))

    def test_tracked_translation_images_are_flat_and_match_the_map(self) -> None:
        document = json.loads(TRANSLATION_IMAGE_MAP_PATH.read_text(encoding="utf-8"))
        declared = [row["file"] for row in document["images"]]
        targets = [target for row in document["images"] for target in row["targets"]]
        actual = sorted(
            path.name for path in ORIGINAL_IMAGE_ROOT.iterdir() if path.is_file()
        )
        translated = sorted(
            path.name for path in TRANSLATED_IMAGE_ROOT.iterdir() if path.is_file()
        )

        self.assertEqual(document["version"], 2)
        self.assertEqual(len(declared), 54)
        self.assertEqual(len(targets), 68)
        self.assertEqual(sorted(declared), actual)
        self.assertEqual(actual, translated)
        self.assertTrue(all(Path(file).name == file for file in declared))
        self.assertEqual(
            sum(row["layout"] == "horizontal" for row in document["images"]), 8
        )
        self.assertEqual(ENGINE_COMPOSED_SOURCES, {"SAVE.BIN", "LOAD.BIN"})

    def test_translation_image_directory_must_match_the_map_exactly(self) -> None:
        clean = Image.new("RGB", (2, 1))
        manifest = {
            "assets": [self.manifest_row("TEX3D/A/001.png", pixel_sha256(clean))]
        }
        mapping = {
            "version": 2,
            "images": [
                {
                    "file": "source.png",
                    "layout": "identity",
                    "targets": ["TEX3D/A/001.png"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_path = root / "translation_images.json"
            original_root = root / "original"
            translated_root = root / "translated"
            original_root.mkdir()
            translated_root.mkdir()
            map_path.write_text(json.dumps(mapping), encoding="utf-8")
            clean.save(original_root / "source.png")
            clean.save(translated_root / "source.png")
            clean.save(translated_root / "unmapped.png")

            with self.assertRaisesRegex(ValueError, "does not match its map"):
                load_translation_images(
                    manifest,
                    map_path=map_path,
                    original_root=original_root,
                    translated_root=translated_root,
                )


if __name__ == "__main__":
    unittest.main()
