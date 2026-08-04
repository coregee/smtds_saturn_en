import json
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from text.script.formats.indexed_bytes.extract import extract_corpus
from text.script.formats.indexed_bytes.repack import repack_indexed_bytes
from text.script.source_models import IndexedBytesSource


class IndexedBytesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.extracted_root = self.root / "extracted"
        self.corpus_root = self.root / "corpus"
        self.extracted_root.mkdir()
        (self.corpus_root / "indexed_bytes").mkdir(parents=True)
        self.source = IndexedBytesSource(
            name="test_indexed_bytes",
            path=Path("TEST.MD8"),
            corpus_path=Path("indexed_bytes/TEST.MD8.json"),
            table_size=0x10,
            table_sentinel=0xFFFF,
            terminator=0x80,
            primary_atlas="fnt8x12.json",
            secondary_atlas="fnt12x12.json",
            secondary_base=0x48,
            secondary_glyphs=0x38,
            named_controls=(),
            runtime_requirements=frozenset(),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_source(self, *, final_terminator: bool = True) -> bytes:
        table = bytearray(b"\x00" * self.source.table_size)
        for index, pointer in enumerate((0, 2, 5)):
            struct.pack_into(">H", table, index * 2, pointer)
        struct.pack_into(">H", table, 6, self.source.table_sentinel)
        table[8:] = b"TABLEPAD"

        final = b"\x0c\x0d\x0e\x0f" + (b"\x80" if final_terminator else b"")
        body = b"\x0c\x80\x0d\x0e\x80" + final
        trailing = b"\xde\xad\xbe\xef"
        data = bytes(table) + body + trailing
        (self.extracted_root / self.source.path).write_bytes(data)
        return data

    def write_existing_corpus(self) -> None:
        rows = [
            {
                "index": 0,
                "en": "Existing A reference",
                "tr": "Existing A",
                "reviewed": True,
                "excluded": False,
            },
            {
                "index": 1,
                "tr": "Existing B",
                "reviewed": False,
                "excluded": True,
            },
        ]
        (self.corpus_root / self.source.corpus_path).write_text(
            json.dumps(rows), encoding="utf-8"
        )

    def test_extract_treats_every_pointer_as_a_message_start(self) -> None:
        self.write_source()
        self.write_existing_corpus()

        with patch("text.script.source_models.EXTRACTED_PATH", self.extracted_root):
            rows = extract_corpus(self.source, self.corpus_root)

        self.assertEqual([row["index"] for row in rows], [0, 1, 2])
        self.assertEqual(
            [row["file_offset"] for row in rows], ["0x0010", "0x0012", "0x0015"]
        )
        self.assertEqual([row["tr"] for row in rows], ["Existing A", "Existing B", ""])
        self.assertEqual(rows[0]["en"], "Existing A reference")
        self.assertNotIn("en", rows[2])
        self.assertEqual(
            [(row["reviewed"], row["excluded"]) for row in rows],
            [(True, False), (False, True), (False, False)],
        )

    def test_repack_preserves_capacity_and_bytes_after_final_terminator(self) -> None:
        original = self.write_source()
        self.write_existing_corpus()

        with patch("text.script.source_models.EXTRACTED_PATH", self.extracted_root):
            rows = extract_corpus(self.source, self.corpus_root)
            rows[1]["tr"] = "A"
            rows[2]["tr"] = "AB"
            (self.corpus_root / self.source.corpus_path).write_text(
                json.dumps(rows), encoding="utf-8"
            )
            result = repack_indexed_bytes(self.source, self.corpus_root)

        self.assertEqual(result.messages, 3)
        self.assertEqual(result.body_capacity, 10)
        self.assertEqual(result.body_size, 7)
        self.assertEqual(result.free_bytes, 3)
        self.assertEqual(
            [struct.unpack_from(">H", result.data, offset)[0] for offset in (0, 2, 4)],
            [0, 2, 4],
        )
        self.assertEqual(struct.unpack_from(">H", result.data, 6)[0], 0xFFFF)
        self.assertEqual(result.data[8:16], b"TABLEPAD")
        self.assertEqual(result.data[16:23], b"\x0c\x80\x0c\x80\x0c\x0d\x80")
        self.assertEqual(result.data[23:26], b"\x00\x00\x00")
        self.assertEqual(result.data[26:], original[26:])

    def test_repack_can_reclaim_unused_pointer_table_padding(self) -> None:
        original = self.write_source()
        self.write_existing_corpus()
        source = replace(self.source, repacked_body_offset=0x08)

        with patch("text.script.source_models.EXTRACTED_PATH", self.extracted_root):
            rows = extract_corpus(source, self.corpus_root)
            rows[0]["tr"] = "A"
            rows[1]["tr"] = "A"
            rows[2]["tr"] = "AB"
            (self.corpus_root / source.corpus_path).write_text(
                json.dumps(rows), encoding="utf-8"
            )
            result = repack_indexed_bytes(source, self.corpus_root)

        self.assertEqual(result.body_offset, 0x08)
        self.assertEqual(result.body_capacity, 18)
        self.assertEqual(result.body_size, 7)
        self.assertEqual(result.free_bytes, 11)
        self.assertEqual(result.capacity_fallbacks, 0)
        self.assertEqual(
            [struct.unpack_from(">H", result.data, offset)[0] for offset in (0, 2, 4)],
            [0, 2, 4],
        )
        self.assertEqual(struct.unpack_from(">H", result.data, 6)[0], 0xFFFF)
        self.assertEqual(result.data[8:15], b"\x0c\x80\x0c\x80\x0c\x0d\x80")
        self.assertEqual(result.data[15:26], bytes(11))
        self.assertEqual(result.data[26:], original[26:])

    def test_extract_rejects_an_unterminated_final_message(self) -> None:
        self.write_source(final_terminator=False)
        self.write_existing_corpus()

        with (
            patch("text.script.source_models.EXTRACTED_PATH", self.extracted_root),
            self.assertRaisesRegex(ValueError, "final message lacks 80 terminator"),
        ):
            extract_corpus(self.source, self.corpus_root)


if __name__ == "__main__":
    unittest.main()
