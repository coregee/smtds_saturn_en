import struct
import unittest

from engine.script.fixed_text_fields.generated import RuntimeWordField
from engine.script.hosi_messages.patch import (
    HOSI_BASE,
    HOSI_FIELDS,
    HOSI_LINE_CELLS,
    HOSI_MAX_LINES,
    HOSI_NEWLINE,
    HOSI_POOL_ADDRESS,
    HOSI_REVEAL_SCALE_REPLACEMENT,
    HOSI_REVEAL_SCALE_SITE,
    HOSI_SPACE,
    HOSI_TERMINATOR,
    build_hosi_group,
    build_hosi_pool,
)
from engine.script.patching import apply_patch_groups
from project_paths import TEXT_CORPUS_ROOT
from text.script.formats.fixed_words.repack import repack_fixed_words
from text.script.profiles import RuntimeCapability
from text.script.source_models import FixedWordsSource
from text.script.sources import get_source

EXPECTED_WORD_COUNTS = (51, 35, 51, 49, 31, 31, 32, 54)
EXPECTED_LINE_LENGTHS = (
    (18, 17, 13),
    (19, 14),
    (18, 18, 12),
    (19, 18, 9),
    (19, 10),
    (19, 10),
    (18, 12),
    (15, 20, 16),
)
EXPECTED_POOL_ADDRESSES = (
    0x06020400,
    0x06020466,
    0x060204AC,
    0x06020512,
    0x06020574,
    0x060205B2,
    0x060205F0,
    0x06020630,
)


def repacked_hosi() -> tuple[FixedWordsSource, tuple[RuntimeWordField, ...]]:
    source = get_source("hosi_messages")
    if not isinstance(source, FixedWordsSource):
        raise AssertionError("hosi_messages is not a fixed-word source")
    result = repack_fixed_words(source, TEXT_CORPUS_ROOT)
    if (
        result.requested_translations,
        result.translated_records,
        result.capacity_fallbacks,
    ) != (8, 8, 0):
        raise AssertionError("HOSI did not produce all eight runtime messages")
    return source, tuple(
        RuntimeWordField(field.kind, field.file_offset, field.words)
        for field in result.runtime_fields
    )


class HosiMessageTests(unittest.TestCase):
    def test_all_horoscope_text_is_exported_at_full_length(self) -> None:
        source, fields = repacked_hosi()

        self.assertEqual(source.engine_load_address, HOSI_BASE)
        self.assertIn(RuntimeCapability.HOSI_MESSAGES, source.runtime_requirements)
        self.assertEqual(
            tuple(field.runtime_word_count for field in source.fields), (64,) * 8
        )
        self.assertEqual(
            tuple(len(field.words) for field in fields), EXPECTED_WORD_COUNTS
        )

    def test_pool_wraps_at_word_boundaries_without_losing_glyphs(self) -> None:
        _source, fields = repacked_hosi()
        payload, addresses, layouts = build_hosi_pool(fields)

        self.assertEqual(len(payload), 668)
        self.assertEqual(
            tuple(addresses[name] for name, _offset, _literal in HOSI_FIELDS),
            EXPECTED_POOL_ADDRESSES,
        )
        for field, expected_lengths in zip(fields, EXPECTED_LINE_LENGTHS):
            with self.subTest(field=field.name):
                layout = layouts[field.name]
                lines = []
                line_length = 0
                for word in layout[:-1]:
                    if word == HOSI_NEWLINE:
                        lines.append(line_length)
                        line_length = 0
                    else:
                        line_length += 1
                lines.append(line_length)

                self.assertEqual(tuple(lines), expected_lengths)
                self.assertLessEqual(len(lines), HOSI_MAX_LINES)
                self.assertTrue(all(length <= HOSI_LINE_CELLS for length in lines))
                self.assertEqual(layout[-1], HOSI_TERMINATOR)
                self.assertEqual(
                    tuple(
                        HOSI_SPACE if word == HOSI_NEWLINE else word for word in layout
                    ),
                    field.words,
                )

    def test_overlay_redirects_each_literal_and_scales_the_stock_reveal(self) -> None:
        source, fields = repacked_hosi()
        payload, addresses, _layouts = build_hosi_pool(fields)
        group = build_hosi_group(HOSI_BASE, fields)

        self.assertEqual(group.capability, "hosi_messages")
        self.assertEqual(len(group.patches), 10)
        self.assertEqual(
            tuple(patch.name for patch in group.patches),
            (
                "hosi_message_pool",
                *(f"{name}_pointer" for name, _offset, _literal in HOSI_FIELDS),
                "hosi_reveal_scale",
            ),
        )

        original = source.input_path.read_bytes()
        patched = apply_patch_groups(original, (group,))
        pool_offset = HOSI_POOL_ADDRESS - HOSI_BASE
        self.assertEqual(patched[pool_offset : pool_offset + len(payload)], payload)

        for name, source_offset, literal in HOSI_FIELDS:
            with self.subTest(field=name):
                literal_offset = literal - HOSI_BASE
                self.assertEqual(
                    original[literal_offset : literal_offset + 4],
                    struct.pack(">I", HOSI_BASE + source_offset),
                )
                self.assertEqual(
                    patched[literal_offset : literal_offset + 4],
                    struct.pack(">I", addresses[name]),
                )

        reveal_offset = HOSI_REVEAL_SCALE_SITE - HOSI_BASE
        self.assertEqual(
            original[reveal_offset - 2 : reveal_offset + 2].hex(), "410b0009"
        )
        self.assertEqual(
            patched[reveal_offset - 2 : reveal_offset + 2],
            bytes.fromhex("410b") + HOSI_REVEAL_SCALE_REPLACEMENT,
        )


if __name__ == "__main__":
    unittest.main()
