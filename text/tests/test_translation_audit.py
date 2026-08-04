import json
import tempfile
import unittest
from pathlib import Path

from project_paths import TEXT_CORPUS_ROOT
from text.script.audit_translations import invalid_translation_tokens, scan_file


def pair(
    japanese: str,
    translation: str,
    *,
    reviewed: bool = False,
    excluded: bool = False,
    english_reference: str | None = None,
) -> dict:
    row = {
        "jp": japanese,
        "tr": translation,
        "reviewed": reviewed,
        "excluded": excluded,
    }
    if english_reference is not None:
        row["en"] = english_reference
    return row


class TranslationAuditTests(unittest.TestCase):
    def scan(self, relative: str, rows: list[dict]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / relative
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(rows, ensure_ascii=False),
                encoding="utf-8",
            )
            return scan_file(path)

    def test_opcode_order_may_follow_english_grammar(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [pair("{last_name}{first_name}", "{first_name} {last_name}")],
        )
        self.assertEqual(status.opcode_mismatches, 0)
        self.assertEqual(issues, [])

    def test_name_tokens_may_change_kind_and_count_in_english(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [
                pair("{last_name}{first_name}", "{first_name}"),
                pair("{last_name}", "{first_name} {last_name}"),
            ],
        )
        self.assertEqual(status.opcode_mismatches, 0)
        self.assertEqual(issues, [])

    def test_missing_or_changed_opcode_fails(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [pair("{last_name}{first_name}", "{first_name} {drink_name}")],
        )
        self.assertEqual(status.opcode_mismatches, 1)
        self.assertIn("opcode mismatch", issues[0])

    def test_wait_opcode_is_preserved_and_valid(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [pair("Before{WAIT}{n}after", "Before{WAIT}{n}after")],
        )
        self.assertEqual(status.opcode_mismatches, 0)
        self.assertEqual(status.invalid_tokens, 0)
        self.assertEqual(issues, [])

    def test_layout_line_breaks_may_be_removed_for_autowrap(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [pair("Before{NL}{n}after", "Before and after")],
        )
        self.assertEqual(status.opcode_mismatches, 0)
        self.assertEqual(status.invalid_tokens, 0)
        self.assertEqual(issues, [])

    def test_fixed_word_insert_marker_is_allowed(self) -> None:
        status, issues = self.scan(
            "fixed_words/test.json",
            [pair("Japanese", "{insert} is full.")],
        )
        self.assertEqual(status.invalid_tokens, 0)
        self.assertEqual(issues, [])

    def test_dialect_fixed_words_allow_stock_glyph_tokens(self) -> None:
        path = TEXT_CORPUS_ROOT / "fixed_words" / "COMBAT.BIN.condition_messages.json"
        self.assertEqual(
            invalid_translation_tokens(
                path,
                "Round{maru_symbol} arrow {GLYPH:010d}> heart『",
            ),
            (),
        )

    def test_empty_and_unknown_token_are_reported(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [
                pair("Japanese", ""),
                pair("Japanese", "Bad {UNKNOWN:010d}"),
            ],
        )
        self.assertEqual(status.empty, 1)
        self.assertEqual(status.invalid_tokens, 1)
        self.assertIn("invalid translation tokens", issues[0])

    def test_literal_word_glyph_is_allowed_but_not_compared_as_an_opcode(
        self,
    ) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [pair("{10d} synthetic source", "Visible {GLYPH:010d} marker")],
        )
        self.assertEqual(status.opcode_mismatches, 0)
        self.assertEqual(status.invalid_tokens, 0)
        self.assertEqual(issues, [])

    def test_named_stock_glyphs_are_allowed(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [
                pair(
                    "Japanese",
                    "Cash {yen_symbol}500, {mag_symbol}10, {white_square}, "
                    "or {maru_symbol}",
                )
            ],
        )
        self.assertEqual(status.opcode_mismatches, 0)
        self.assertEqual(status.invalid_tokens, 0)
        self.assertEqual(issues, [])

    def test_padding_only_source_is_not_translation_work(self) -> None:
        status, issues = self.scan(
            "name_description/test.json",
            [pair("                    {n}", "", excluded=True)],
        )
        self.assertEqual(status.fields, 0)
        self.assertEqual(status.status_fields, 1)
        self.assertEqual(status.status_excluded, 1)
        self.assertEqual(status.empty, 0)
        self.assertEqual(issues, [])

    def test_padding_only_target_is_still_validated_when_nonblank(self) -> None:
        status, issues = self.scan(
            "name_description/test.json",
            [pair("                    {n}", "Bad {UNKNOWN}", excluded=True)],
        )

        self.assertEqual(status.fields, 0)
        self.assertEqual(status.status_fields, 1)
        self.assertEqual(status.status_excluded, 1)
        self.assertEqual(status.invalid_tokens, 1)
        self.assertIn("invalid translation tokens", issues[0])

    def test_review_status_buckets_use_documented_precedence(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [
                pair("A", "One", reviewed=True, excluded=True),
                pair("B", "Two", reviewed=True),
                pair("C", "Three"),
                pair("D", ""),
            ],
        )
        self.assertEqual(
            (
                status.status_excluded,
                status.status_reviewed,
                status.status_translated,
                status.status_untranslated,
            ),
            (1, 1, 1, 1),
        )
        self.assertEqual(status.empty, 1)
        self.assertEqual(issues, [])

    def test_optional_english_reference_is_not_a_target_fallback(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [pair("Japanese", "", english_reference="English reference")],
        )
        self.assertEqual(status.empty, 1)
        self.assertEqual(status.status_untranslated, 1)
        self.assertEqual(issues, [])

    def test_exclusion_does_not_bypass_translation_validity(self) -> None:
        status, issues = self.scan(
            "eve/test.json",
            [pair("Japanese", "", excluded=True)],
        )
        self.assertEqual(status.status_excluded, 1)
        self.assertEqual(status.empty, 1)
        self.assertEqual(issues, [])

    def test_legacy_or_incomplete_target_schema_is_rejected(self) -> None:
        for row, error in (
            ({"jp": "Japanese", "en": "Legacy target"}, ".tr must be text"),
            ({"jp": "Japanese", "tr": "Target"}, ".reviewed must be boolean"),
            (
                {"jp": "Japanese", "tr": "Target", "reviewed": False},
                ".excluded must be boolean",
            ),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.scan("eve/test.json", [row])


if __name__ == "__main__":
    unittest.main()
