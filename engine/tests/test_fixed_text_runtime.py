import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT
from engine.script.fixed_text_fields.generated import load_runtime_fields
from engine.script.generated_asset import load_runtime_ui
from engine.script.status_ui.data import load_font16_metrics
from engine.script.status_ui.model import (
    BASE,
    LEVEL_UP_CHARACTER_SELECTOR,
    LEVEL_UP_LEARNED_SKILL_LIST_PTR,
    LEVEL_UP_RUNTIME_CAVE_FILE,
    LEVEL_UP_RUNTIME_CAVE_LIMIT,
    MAGNAME_BASE,
)
from engine.script.status_ui.runtime import (
    build_level_up_name_runtime,
    build_level_up_text_copy,
    level_up_font8_to_font16,
)
from engine.script.text_render.font8_metrics import font8_metrics


def generated_magic_names() -> tuple[str, ...]:
    rows = load_runtime_ui(DEFAULT_CONTEXT).section("magic_names")
    return tuple(row["name"]["tr"] for row in rows)


class FixedTextRuntimeTests(unittest.TestCase):
    def test_runtime_field_asset_is_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            extracted = root / "extracted"
            relative = Path("fixed_words/LEVEL_UP.BIN.json")
            source = Path("LEVEL_UP.BIN")
            (generated / relative.parent).mkdir(parents=True)
            extracted.mkdir()
            original = bytes(0x100)
            (extracted / source).write_bytes(original)
            (generated / relative).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "source": source.as_posix(),
                        "source_sha256": hashlib.sha256(original).hexdigest(),
                        "load_address": "0x06020000",
                        "runtime_fields": [
                            {
                                "name": "learned_magic",
                                "file_offset": "0x20",
                                "word_count": 3,
                                "words_hex": "001600298000",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            load_address, fields = load_runtime_fields(
                relative,
                generated,
                extracted,
                expected_source=source,
                max_words=18,
            )

        self.assertEqual(load_address, 0x06020000)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].name, "learned_magic")
        self.assertEqual(fields[0].file_offset, 0x20)
        self.assertEqual(fields[0].words, (0x0016, 0x0029, 0x8000))

    def test_level_up_copy_uses_the_runtime_word_count(self) -> None:
        code = build_level_up_text_copy(0x06028F4C, 14, 0x28)
        self.assertEqual(len(code), 0x28)
        self.assertEqual(
            code[:16].hex(),
            "62f3ed0e6315223172024d108bfaed24",
        )
        self.assertEqual(code[16:], bytes.fromhex("0009") * 12)

    def test_level_up_actor_names_use_the_generated_character_pool(self) -> None:
        names = (
            "Hajime Tanigawa",
            "Rei Reiho",
            "Kyouji",
            "Taro Tanigawa",
            "Jiro Tanigawa",
            "Saburo Tanigawa",
        )
        runtime, wrapper, _learned_magic, table, dispatcher = (
            build_level_up_name_runtime(
                (0x0016, 0x8000),
                names,
                generated_magic_names(),
            )
        )
        runtime_address = BASE + LEVEL_UP_RUNTIME_CAVE_FILE
        self.assertLessEqual(
            runtime_address + len(runtime),
            BASE + LEVEL_UP_RUNTIME_CAVE_LIMIT,
        )
        wrapper_bytes = runtime[wrapper - runtime_address : table - runtime_address]
        self.assertIn(struct.pack(">I", LEVEL_UP_CHARACTER_SELECTOR), wrapper_bytes)
        self.assertIn(struct.pack(">I", table), wrapper_bytes)

        _widths, codes = load_font16_metrics()
        table_offset = table - runtime_address
        pointers = struct.unpack_from(">5I", runtime, table_offset)
        for pointer, name in zip(pointers, names[1:], strict=True):
            expected = (*[codes[character] for character in name], 0x8000)
            actual = struct.unpack_from(
                f">{len(expected)}H", runtime, pointer - runtime_address
            )
            self.assertEqual(actual, expected)

        dispatcher_bytes = runtime[dispatcher - runtime_address :]
        self.assertIn(
            struct.pack(">I", LEVEL_UP_LEARNED_SKILL_LIST_PTR), dispatcher_bytes
        )
        self.assertIn(struct.pack(">I", MAGNAME_BASE), dispatcher_bytes)
        self.assertIn(struct.pack(">I", runtime_address), dispatcher_bytes)

    def test_level_up_dia_codes_map_from_font8_to_font16(self) -> None:
        _widths8, codes8 = font8_metrics()
        _widths16, codes16 = load_font16_metrics()
        compact = tuple(codes8[character] for character in "Dia")
        expected = tuple(codes16[character] for character in "Dia")

        self.assertEqual(compact, (0x4D, 0x6C, 0x64))
        self.assertEqual(expected, (0x0E, 0x2D, 0x25))
        self.assertEqual(
            tuple(level_up_font8_to_font16(code) for code in compact),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
