import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT
from engine.script.fixed_text_fields.end_roll import (
    ASSET,
    BASE,
    BITMAP_POOL,
    CAVE,
    CAVE_LIMIT,
    LIVE_BUFFER,
    LIVE_BUFFER_SIZE,
    MAIN_RENDERER_LITERAL,
    MAIN_SOURCE_TABLE,
    MAIN_VDP_BITMAP,
    MAIN_VDP_LITERAL,
    RENDERER,
    SOURCE,
    SOURCE_ZERO_START,
    STOCK_MAIN_DRAWER,
    STOCK_TEST_DRAWER,
    TEST_EXTRA_SOURCE_TABLE,
    TEST_MAIN_SOURCE_TABLE,
    TEST_MAIN_WRAPPER,
    TEST_VDP_BITMAP,
    build_patch_group,
    build_runtime,
    load_advances,
)
from engine.script.fixed_text_fields.generated import RuntimeWordField
from engine.script.patching import apply_patch_groups
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.fixed_words.repack import asset_json, repack_fixed_words
from text.script.repack_pipeline import CORPUS_ROOT
from text.script.sources import SOURCES

EXPECTED_NAMES = (
    "Koji Okada",
    "Kazuma Kaneko",
    "Masami Sato",
    "Tsuyoshi Kunieda",
    "Kazuya Mukai",
    "Naoya Yabe",
    "Masahiro Horikoshi",
    "Tomohiro Hosoya",
    "Futoshi Yamaguchi",
    "Ryutaro Ito",
    "Shogo Isogai",
    "Yuji Hosono",
    "Katsura Hashino",
    "Hajime Tanigawa",
    "Yutaka Akiyama",
    "Kazunori Sakai",
    "Sawako Sato",
    "Tetsuya Murakami",
    "Akira Noguchi",
    "Shiro Takashima",
    "Tomomi Iwasaki",
    "Izumi Kataoka",
    "Satoshi Shio",
    "Tatsuya Igarashi",
    "Shigenori Soejima",
    "Jun Kawasaki",
    "Tsukasa Masuko",
    "Hisako Tasaki",
    "Ikudai Kitahara",
    "Yoshihiro Sumiya",
    "Takahiro Toda",
    "Rei Otake",
    "Kunihiko Kozai",
    "Takatoshi Akiyama",
    "Keiji Yoshimura",
    "Natsuki Uryu",
    "Kazuto Sekine",
    "Takahiro Fujita",
    "Etsuko Yoshida",
    "Hiroaki Murai",
)


def end_roll_source():
    return next(source for source in SOURCES if source.name == "end_roll_names")


def runtime_fields():
    source = end_roll_source()
    result = repack_fixed_words(source, CORPUS_ROOT)
    return result, tuple(
        RuntimeWordField(field.kind, field.file_offset, field.words)
        for field in result.runtime_fields
    )


class EndRollRuntimeTests(unittest.TestCase):
    def test_all_exact_credit_names_reach_the_runtime_pool(self) -> None:
        source = end_roll_source()
        rows = json.loads((CORPUS_ROOT / source.corpus_path).read_text("utf-8"))
        self.assertEqual(tuple(row["tr"] for row in rows), EXPECTED_NAMES)

        result, fields = runtime_fields()
        latin = load_latin_encoding()
        self.assertEqual(result.translated_records, 40)
        self.assertEqual(result.capacity_fallbacks, 0)
        self.assertEqual(len(fields), 40)
        for row, field in zip(rows, fields, strict=True):
            self.assertEqual(field.name, row["kind"])
            self.assertEqual(
                field.words,
                tuple(latin.encode_segment(row["tr"], packed=False)),
            )

    def test_runtime_preserves_every_name_with_bounded_overflow_scaling(self) -> None:
        _result, fields = runtime_fields()
        runtime = build_runtime(
            fields,
            (DEFAULT_CONTEXT.build_root / "FONT16.FON").read_bytes(),
            load_advances(DEFAULT_CONTEXT.font_generated_root / "font16_metrics.json"),
        )

        self.assertEqual(runtime.labels["bitmap_pool"], BITMAP_POOL)
        self.assertLessEqual(runtime.labels["end"], CAVE_LIMIT)
        self.assertEqual(
            runtime.compressed_fields,
            ("main_staff_06", "main_staff_08"),
        )
        self.assertEqual(runtime.widths[6], 100)
        self.assertEqual(runtime.widths[8], 99)
        self.assertEqual(runtime.widths[33], 100)
        self.assertGreaterEqual(7 * 16, runtime.widths[33])

    def test_three_consumers_and_the_zero_cave_are_source_verified(self) -> None:
        original = (DEFAULT_CONTEXT.extracted_root / SOURCE).read_bytes()

        def literal_sites(value: int) -> tuple[int, ...]:
            encoded = value.to_bytes(4, "big")
            return tuple(
                BASE + offset
                for offset in range(0, len(original) - 3, 2)
                if original[offset : offset + 4] == encoded
            )

        self.assertEqual(literal_sites(MAIN_SOURCE_TABLE), (0x0602D018,))
        self.assertEqual(literal_sites(TEST_MAIN_SOURCE_TABLE), (0x0602D20C,))
        self.assertEqual(literal_sites(TEST_EXTRA_SOURCE_TABLE), (0x0602D26C,))
        self.assertEqual(literal_sites(STOCK_MAIN_DRAWER), (0x0602D01C,))
        self.assertEqual(
            literal_sites(STOCK_TEST_DRAWER),
            (0x0602D208, 0x0602D268),
        )

        self.assertEqual(
            original[CAVE - BASE : CAVE_LIMIT - BASE],
            bytes(CAVE_LIMIT - CAVE),
        )
        zero_run_references = tuple(
            (BASE + offset, int.from_bytes(original[offset : offset + 4], "big"))
            for offset in range(0, len(original) - 3, 2)
            if SOURCE_ZERO_START
            <= int.from_bytes(original[offset : offset + 4], "big")
            < CAVE_LIMIT
        )
        self.assertEqual(
            zero_run_references,
            ((0x0602B510, LIVE_BUFFER), (0x0602B544, LIVE_BUFFER)),
        )
        self.assertLessEqual(LIVE_BUFFER + LIVE_BUFFER_SIZE, CAVE)

    def test_patch_is_source_bound_and_preserves_exact_file_size(self) -> None:
        source = end_roll_source()
        result = repack_fixed_words(source, CORPUS_ROOT)
        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_root = Path(temporary_directory)
            path = generated_root / ASSET
            path.parent.mkdir(parents=True)
            path.write_text(
                asset_json(
                    source,
                    CORPUS_ROOT / source.corpus_path,
                    result,
                ),
                encoding="utf-8",
            )
            context = replace(DEFAULT_CONTEXT, text_generated_root=generated_root)
            group = build_patch_group(context)

        original = (DEFAULT_CONTEXT.extracted_root / SOURCE).read_bytes()
        patched = apply_patch_groups(original, (group,))
        self.assertEqual(len(patched), len(original))
        self.assertEqual(
            patched[MAIN_VDP_LITERAL - BASE : MAIN_VDP_LITERAL - BASE + 4],
            MAIN_VDP_BITMAP.to_bytes(4, "big"),
        )
        self.assertEqual(
            patched[MAIN_RENDERER_LITERAL - BASE : MAIN_RENDERER_LITERAL - BASE + 4],
            RENDERER.to_bytes(4, "big"),
        )
        self.assertEqual(
            patched[TEST_MAIN_WRAPPER - BASE + 0x1C : TEST_MAIN_WRAPPER - BASE + 0x20],
            TEST_VDP_BITMAP.to_bytes(4, "big"),
        )


if __name__ == "__main__":
    unittest.main()
