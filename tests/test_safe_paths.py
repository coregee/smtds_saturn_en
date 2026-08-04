import unittest
from pathlib import Path

from safe_paths import safe_relative_path


class SafeRelativePathTests(unittest.TestCase):
    def test_accepts_a_forward_slash_relative_path(self) -> None:
        self.assertEqual(
            safe_relative_path("folder/file.json", "fixture"),
            Path("folder") / "file.json",
        )

    def test_rejects_parent_absolute_drive_and_unc_paths(self) -> None:
        values = (
            "../secret.json",
            r"..\secret.json",
            r"folder\..\secret.json",
            "/absolute/secret.json",
            "C:/secret.json",
            r"C:\secret.json",
            r"\\server\share\secret.json",
        )
        for value in values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError, "safe relative|forward slashes"
                ):
                    safe_relative_path(value, "fixture")

    def test_cue_mode_normalizes_safe_backslashes_only(self) -> None:
        self.assertEqual(
            safe_relative_path(
                r"tracks\track01.bin",
                "fixture",
                allow_backslashes=True,
            ),
            Path("tracks") / "track01.bin",
        )
        with self.assertRaisesRegex(ValueError, "safe relative"):
            safe_relative_path(
                r"..\track01.bin",
                "fixture",
                allow_backslashes=True,
            )


if __name__ == "__main__":
    unittest.main()
