import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import visual.script.validate as catalog_validate


class VisualCatalogTests(unittest.TestCase):
    def validate_row(self, row: dict[str, object]) -> tuple[int, int]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extracted = root / "extracted"
            extracted.mkdir()
            source = extracted / "TEST.BIN"
            payload = b"visual catalog fixture"
            source.write_bytes(payload)

            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "method": "test review",
                        "assets": [
                            {
                                "path": source.name,
                                "format": "test",
                                "review": "complete",
                                "fingerprint": {
                                    "size": len(payload),
                                    "sha256": hashlib.sha256(payload).hexdigest(),
                                },
                                "text": [row],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(catalog_validate, "CATALOG_PATH", catalog),
                mock.patch.object(catalog_validate, "EXTRACTED_ROOT", extracted),
            ):
                return catalog_validate.validate()

    def test_active_translation_uses_tr(self) -> None:
        self.assertEqual(
            self.validate_row({"kind": "label", "jp": "原文", "tr": "Target"}),
            (1, 1),
        )

    def test_optional_english_reference_is_allowed(self) -> None:
        self.assertEqual(
            self.validate_row(
                {
                    "kind": "label",
                    "jp": "原文",
                    "en": "English reference",
                    "tr": "Target",
                }
            ),
            (1, 1),
        )

    def test_english_reference_cannot_replace_tr(self) -> None:
        with self.assertRaisesRegex(ValueError, "malformed"):
            self.validate_row(
                {"kind": "label", "jp": "原文", "en": "English reference"}
            )


if __name__ == "__main__":
    unittest.main()
