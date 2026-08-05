import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fmv.script import repack
from fmv.script.util.media import (
    REPACK_MANIFEST_VERSION,
    file_sha256,
    load_repack_manifest,
)


class RepackCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "MOVIE.CPK"
        self.editable = self.root / "MOVIE.mkv"
        self.subtitles = self.root / "MOVIE.ass"
        self.output = self.root / "build" / "MOVIE.CPK"
        self.font_root = self.root / "fonts"
        self.font = self.font_root / "ark-pixel-16px-proportional-latin.otf"
        self.source.write_bytes(b"source-cpk" * 32)
        self.editable.write_bytes(b"editable-mkv" * 32)
        self.subtitles.write_text("Dialogue: first\n", encoding="utf-8")
        self.output.parent.mkdir()
        self.output.write_bytes(b"rebuilt-cpk")
        self.font_root.mkdir()
        self.font.write_bytes(b"font-v1")
        self.font_patches = (
            patch.object(repack, "SUBTITLE_FONT_ROOT", self.font_root),
            patch.object(repack, "SUBTITLE_FONT_PATH", self.font),
        )
        for font_patch in self.font_patches:
            font_patch.start()

    def tearDown(self) -> None:
        for font_patch in reversed(self.font_patches):
            font_patch.stop()
        self.temporary.cleanup()

    def state(
        self,
        *,
        qscale: int = 6,
        max_bytes: int | None = None,
    ) -> dict[str, object]:
        return repack.repack_input_state(
            relative=Path("BGDATA/MOVIE.CPK"),
            source=self.source,
            source_sha256=file_sha256(self.source),
            editable=self.editable,
            editable_sha256=file_sha256(self.editable),
            subtitles=self.subtitles,
            max_bytes=(self.source.stat().st_size if max_bytes is None else max_bytes),
            qscale=qscale,
            auto_fit=True,
            codebook_iterations=2,
        )

    def test_matching_state_and_output_are_cached(self) -> None:
        state = self.state()
        record = repack.repack_record(Path("BGDATA/MOVIE.CPK"), state, self.output)

        self.assertTrue(repack.cache_matches(record, state, self.output))

        manifest = self.root / "repacked.json"
        legacy = {
            "source": "BGDATA/LEGACY.CPK",
            "editable_sha256": "a" * 64,
            "transform_sha256": None,
            "output_size": 1,
            "output_sha256": "b" * 64,
        }
        document = {
            "version": REPACK_MANIFEST_VERSION,
            "movies": [legacy, record],
        }
        repack.write_repack_manifest(manifest, document)
        self.assertEqual(load_repack_manifest(manifest)["movies"], [legacy, record])
        self.assertEqual(list(self.root.glob(".repacked.json.*.tmp")), [])

    def test_nonpositive_allocation_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "max bytes must be positive"):
            self.state(max_bytes=0)

    def test_changed_subtitle_or_rendering_input_invalidates_cache(self) -> None:
        original = self.state()
        record = repack.repack_record(Path("BGDATA/MOVIE.CPK"), original, self.output)

        self.subtitles.write_text("Dialogue: changed\n", encoding="utf-8")
        changed_subtitles = self.state()
        self.assertNotEqual(
            original["transform_sha256"], changed_subtitles["transform_sha256"]
        )
        self.assertFalse(repack.cache_matches(record, changed_subtitles, self.output))

        self.subtitles.write_text("Dialogue: first\n", encoding="utf-8")
        self.font.write_bytes(b"font-v2")
        changed_font = self.state()
        self.assertNotEqual(
            original["font_set_sha256"], changed_font["font_set_sha256"]
        )
        self.assertFalse(repack.cache_matches(record, changed_font, self.output))

        changed_recipe = self.state(qscale=8)
        self.assertNotEqual(original["recipe_sha256"], changed_recipe["recipe_sha256"])
        self.assertFalse(repack.cache_matches(record, changed_recipe, self.output))

    def test_missing_or_modified_output_invalidates_cache(self) -> None:
        state = self.state()
        record = repack.repack_record(Path("BGDATA/MOVIE.CPK"), state, self.output)

        self.output.write_bytes(b"corrupt")
        self.assertFalse(repack.cache_matches(record, state, self.output))

        self.output.unlink()
        self.assertFalse(repack.cache_matches(record, state, self.output))


if __name__ == "__main__":
    unittest.main()
