import unittest

from PIL import ImageFont

from fmv.script import repack
from project_paths import FMV_ROOT


class SubtitleFontTests(unittest.TestCase):
    def test_tracked_script_uses_bundled_16px_face(self) -> None:
        face = ImageFont.truetype(str(repack.SUBTITLE_FONT_PATH), size=16)
        family, style = face.getname()
        script = (FMV_ROOT / "subtitles" / "BGDATA" / "START2.ass").read_text(
            encoding="utf-8"
        )

        self.assertEqual((family, style), ("Ark Pixel 16px Prop latin", "Regular"))
        self.assertIn(f"Style: Default,{family},16,", script)
        self.assertNotIn("Ark Pixel 12px", script)


if __name__ == "__main__":
    unittest.main()
