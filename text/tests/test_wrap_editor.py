import hashlib
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from text.editor.apply_semantic_wrap import plan_migration
from text.editor.server import (
    CorpusIndex,
    EditorHTTPServer,
    JsonSpanParser,
    discover_translation_entries,
    translation_status,
    update_translation_entry,
)


def write_exact(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        output.write(text)


class EditorDiscoveryTests(unittest.TestCase):
    def test_optional_english_is_the_preferred_editor_source(self) -> None:
        entries = discover_translation_entries(
            [
                {
                    "kind": "record",
                    "name": {
                        "jp": "日本語",
                        "en": "English reference",
                        "tr": "Target",
                        "reviewed": False,
                        "excluded": False,
                    },
                    "description": {
                        "jp": "説明",
                        "tr": "",
                        "reviewed": True,
                        "excluded": True,
                    },
                }
            ],
            file="nested/example.json",
        )

        self.assertEqual(len(entries), 2)
        name, description = entries
        self.assertEqual(
            (name["source_language"], name["source"]),
            (
                "en",
                "English reference",
            ),
        )
        self.assertEqual(name["status"], "translated")
        self.assertNotIn("en", name["metadata"])
        self.assertNotIn("reviewed", name["metadata"])
        self.assertNotIn("excluded", name["metadata"])
        self.assertEqual(description["source_language"], "jp")
        self.assertEqual(description["status"], "excluded")

    def test_canonical_flags_are_required_booleans(self) -> None:
        invalid_records = (
            {"jp": "JP", "tr": "TR", "excluded": False},
            {"jp": "JP", "tr": "TR", "reviewed": False},
            {
                "jp": "JP",
                "tr": "TR",
                "reviewed": 1,
                "excluded": False,
            },
            {
                "jp": "JP",
                "tr": "TR",
                "reviewed": False,
                "excluded": 0,
            },
        )
        for record in invalid_records:
            with self.subTest(record=record), self.assertRaises(ValueError):
                discover_translation_entries([record], file="invalid.json")

    def test_status_precedence_is_mutually_exclusive(self) -> None:
        cases = (
            ({"tr": "", "reviewed": False, "excluded": False}, "untranslated"),
            ({"tr": "  ", "reviewed": False, "excluded": False}, "untranslated"),
            ({"tr": "Target", "reviewed": False, "excluded": False}, "translated"),
            ({"tr": "", "reviewed": True, "excluded": False}, "reviewed"),
            ({"tr": "Target", "reviewed": True, "excluded": True}, "excluded"),
        )
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(translation_status(**values), expected)


class EditorSaveTests(unittest.TestCase):
    def test_scalar_spans_cover_strings_and_booleans(self) -> None:
        source = '[{"jp":"JP","tr":"TR","reviewed":false,"excluded":true}]'
        parser = JsonSpanParser(source)
        parser.parse()

        tr_start, tr_end = parser.scalar_spans[(0, "tr")]
        reviewed_start, reviewed_end = parser.scalar_spans[(0, "reviewed")]
        excluded_start, excluded_end = parser.scalar_spans[(0, "excluded")]
        self.assertEqual(source[tr_start:tr_end], '"TR"')
        self.assertEqual(source[reviewed_start:reviewed_end], "false")
        self.assertEqual(source[excluded_start:excluded_end], "true")

    def test_edit_forces_reviewed_and_preserves_all_other_formatting(self) -> None:
        source = (
            "[\r\n"
            "  {\r\n"
            '    "kind": "demo",\r\n'
            '    "jp": "日本語",\r\n'
            '    "tr" : "Old",\r\n'
            '    "reviewed"  : false,\r\n'
            '    "excluded": true,\r\n'
            '    "note": "leave me exactly alone"\r\n'
            "  }\r\n"
            "]\r\n"
        )
        expected = source.replace('"Old"', '"New translation"', 1).replace(
            "false", "true", 1
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.json"
            write_exact(path, source)
            digest, reviewed, excluded = update_translation_entry(
                path,
                [0],
                expected_tr="Old",
                new_tr="New translation",
                expected_reviewed=False,
                new_reviewed=False,
                expected_excluded=True,
                new_excluded=True,
            )
            with path.open("r", encoding="utf-8", newline="") as saved_file:
                saved = saved_file.read()

        self.assertEqual(saved, expected)
        self.assertTrue(reviewed)
        self.assertTrue(excluded)
        self.assertEqual(digest, hashlib.sha256(expected.encode("utf-8")).hexdigest())

    def test_review_and_exclusion_can_change_without_a_text_edit(self) -> None:
        source = '[{"jp":"JP","tr":"Target","reviewed":true,"excluded":true}]'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.json"
            write_exact(path, source)
            _digest, reviewed, excluded = update_translation_entry(
                path,
                [0],
                expected_tr="Target",
                new_tr="Target",
                expected_reviewed=True,
                new_reviewed=False,
                expected_excluded=True,
                new_excluded=False,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))[0]

        self.assertFalse(reviewed)
        self.assertFalse(excluded)
        self.assertFalse(saved["reviewed"])
        self.assertFalse(saved["excluded"])

    def test_conflicts_cover_translation_review_and_exclusion(self) -> None:
        external_values = (
            {"tr": "External", "reviewed": False, "excluded": False},
            {"tr": "Old", "reviewed": True, "excluded": False},
            {"tr": "Old", "reviewed": False, "excluded": True},
        )
        for external in external_values:
            with (
                self.subTest(external=external),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "example.json"
                write_exact(path, json.dumps([{"jp": "JP", **external}]))
                with self.assertRaises(FileExistsError):
                    update_translation_entry(
                        path,
                        [0],
                        expected_tr="Old",
                        new_tr="Edited",
                        expected_reviewed=False,
                        new_reviewed=False,
                        expected_excluded=False,
                        new_excluded=False,
                    )

    def test_negative_and_out_of_range_pointers_are_rejected(self) -> None:
        source = '[{"jp":"JP","tr":"Target","reviewed":false,"excluded":false}]'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.json"
            write_exact(path, source)
            for pointer in ([-1], [1]):
                with (
                    self.subTest(pointer=pointer),
                    self.assertRaises((KeyError, ValueError)),
                ):
                    update_translation_entry(
                        path,
                        pointer,
                        expected_tr="Target",
                        new_tr="Edited",
                        expected_reviewed=False,
                        new_reviewed=False,
                        expected_excluded=False,
                        new_excluded=False,
                    )
            self.assertEqual(path.read_text(encoding="utf-8"), source)


class CorpusIndexTests(unittest.TestCase):
    def test_status_filters_and_counts_share_one_precedence(self) -> None:
        rows = [
            {"jp": "A", "tr": "", "reviewed": False, "excluded": False},
            {"jp": "B", "tr": "B", "reviewed": False, "excluded": False},
            {"jp": "C", "tr": "C", "reviewed": True, "excluded": False},
            {"jp": "D", "tr": "D", "reviewed": True, "excluded": True},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "group" / "example.json"
            write_exact(path, json.dumps(rows, ensure_ascii=False))
            index = CorpusIndex(root)
            index.refresh(force=True)

            entries, total, counts = index.query(
                file="",
                search="",
                offset=0,
                limit=100,
            )
            excluded, excluded_total, filtered_counts = index.query(
                file="",
                search="",
                offset=0,
                limit=100,
                status_filter="excluded",
            )
            file_row = index.files()[0]

        expected_counts = {
            "untranslated": 1,
            "translated": 1,
            "reviewed": 1,
            "excluded": 1,
        }
        self.assertEqual(total, 4)
        self.assertEqual(len(entries), 4)
        self.assertEqual(counts, expected_counts)
        self.assertEqual(excluded_total, 1)
        self.assertEqual(excluded[0]["status"], "excluded")
        self.assertEqual(filtered_counts, expected_counts)
        self.assertEqual(file_row["status_counts"], expected_counts)

    def test_refresh_reindexes_only_changed_corpus_files(self) -> None:
        first_rows = [{"jp": "A", "tr": "One", "reviewed": False, "excluded": False}]
        second_rows = [{"jp": "B", "tr": "Two", "reviewed": False, "excluded": False}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = root / "first.json"
            second_path = root / "second.json"
            write_exact(first_path, json.dumps(first_rows))
            write_exact(second_path, json.dumps(second_rows))
            index = CorpusIndex(root)
            index.refresh(force=True)
            unchanged_entries = index.entries_by_file["first.json"]

            second_rows[0]["tr"] = "A longer changed translation"
            write_exact(second_path, json.dumps(second_rows))
            with patch(
                "text.editor.server.discover_translation_entries",
                wraps=discover_translation_entries,
            ) as discover:
                index.refresh()

            self.assertEqual(discover.call_count, 1)
            self.assertEqual(discover.call_args.kwargs["file"], "second.json")
            self.assertEqual(list(index.entries_by_file), ["first.json", "second.json"])
            self.assertIs(index.entries_by_file["first.json"], unchanged_entries)
            self.assertEqual(
                index.entries_by_file["second.json"][0]["tr"],
                "A longer changed translation",
            )


class EditorHTTPTests(unittest.TestCase):
    def test_patch_contract_forces_review_and_keeps_exclusion_explicit(self) -> None:
        row = {
            "jp": "JP",
            "tr": "Old",
            "reviewed": False,
            "excluded": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "example.json"
            write_exact(path, json.dumps([row]))
            index = CorpusIndex(root)
            index.refresh(force=True)
            server = EditorHTTPServer(("127.0.0.1", 0), index)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=3
                )
                payload = {
                    "file": "example.json",
                    "pointer": [0],
                    "expected_tr": "Old",
                    "tr": "Edited",
                    "expected_reviewed": False,
                    "reviewed": False,
                    "expected_excluded": False,
                    "excluded": True,
                }
                connection.request(
                    "PATCH",
                    "/api/entry",
                    body=json.dumps(payload),
                    headers={
                        "Content-Type": "application/json",
                        "X-Editor-Token": server.editor_token,
                    },
                )
                response = connection.getresponse()
                result = json.loads(response.read())
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

            saved = json.loads(path.read_text(encoding="utf-8"))[0]
            indexed = index.entry(file="example.json", pointer=[0])

        self.assertEqual(response.status, 200)
        self.assertTrue(result["reviewed"])
        self.assertTrue(result["excluded"])
        self.assertEqual(result["status"], "excluded")
        self.assertEqual(saved["tr"], "Edited")
        self.assertTrue(saved["reviewed"])
        self.assertTrue(saved["excluded"])
        self.assertEqual(indexed["tr"], "Edited")
        self.assertEqual(indexed["status"], "excluded")

    def test_visual_preview_does_not_wait_for_capacity_analysis(self) -> None:
        row = {
            "jp": "JP",
            "tr": "Old",
            "reviewed": False,
            "excluded": False,
        }
        capacity_result = {
            "format": "unregistered",
            "outcome": "unavailable",
            "checks": [],
            "exact": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_exact(root / "example.json", json.dumps([row]))
            index = CorpusIndex(root)
            index.refresh(force=True)
            server = EditorHTTPServer(("127.0.0.1", 0), index)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            payload = json.dumps(
                {"file": "example.json", "pointer": [0], "tr": "Draft"}
            )

            def post(path: str) -> tuple[int, dict]:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=3
                )
                connection.request(
                    "POST",
                    path,
                    body=payload,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                result = json.loads(response.read())
                connection.close()
                return response.status, result

            try:
                with patch(
                    "text.editor.server.analyze_capacity",
                    return_value=capacity_result,
                ) as analyze:
                    preview_status, preview = post("/api/preview")
                    self.assertEqual(analyze.call_count, 0)
                    capacity_status, measured = post("/api/capacity")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

        self.assertEqual(preview_status, 200)
        self.assertIsNone(preview["capacity"])
        self.assertTrue(preview["variants"])
        self.assertEqual(capacity_status, 200)
        self.assertEqual(measured, capacity_result)
        self.assertEqual(analyze.call_count, 1)

    def test_concurrent_saves_are_serialized_before_conflict_checks(self) -> None:
        row = {
            "jp": "JP",
            "tr": "Old",
            "reviewed": False,
            "excluded": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "example.json"
            write_exact(path, json.dumps([row]))
            index = CorpusIndex(root)
            index.refresh(force=True)
            server = EditorHTTPServer(("127.0.0.1", 0), index)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            active = 0
            maximum_active = 0
            activity_lock = threading.Lock()
            original_update = update_translation_entry

            def observed_update(*args, **kwargs):
                nonlocal active, maximum_active
                with activity_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    time.sleep(0.05)
                    return original_update(*args, **kwargs)
                finally:
                    with activity_lock:
                        active -= 1

            start = threading.Barrier(3)
            results: list[int] = []

            def save(translation: str) -> None:
                start.wait()
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=3
                )
                payload = {
                    "file": "example.json",
                    "pointer": [0],
                    "expected_tr": "Old",
                    "tr": translation,
                    "expected_reviewed": False,
                    "reviewed": False,
                    "expected_excluded": False,
                    "excluded": False,
                }
                connection.request(
                    "PATCH",
                    "/api/entry",
                    body=json.dumps(payload),
                    headers={
                        "Content-Type": "application/json",
                        "X-Editor-Token": server.editor_token,
                    },
                )
                response = connection.getresponse()
                response.read()
                results.append(response.status)
                connection.close()

            workers = [
                threading.Thread(target=save, args=(translation,))
                for translation in ("First", "Second")
            ]
            try:
                with patch(
                    "text.editor.server.update_translation_entry",
                    side_effect=observed_update,
                ):
                    for worker in workers:
                        worker.start()
                    start.wait()
                    for worker in workers:
                        worker.join(timeout=3)
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=3)

        self.assertEqual(maximum_active, 1)
        self.assertEqual(sorted(results), [200, 409])


class SemanticMigrationTests(unittest.TestCase):
    def test_automated_wrap_resets_review_but_preserves_exclusion(self) -> None:
        source = json.dumps(
            [
                {
                    "jp": "日本語",
                    "tr": "Before after",
                    "reviewed": True,
                    "excluded": True,
                }
            ],
            ensure_ascii=False,
        )
        with (
            patch(
                "text.editor.apply_semantic_wrap._eligible_mode",
                return_value=object(),
            ),
            patch(
                "text.editor.apply_semantic_wrap.semantic_event_lines",
                return_value=["Before", "after"],
            ),
        ):
            plan = plan_migration(source, file="eve/example.json", encoding=object())

        updated = json.loads(plan.updated_text)[0]
        self.assertEqual(plan.changed, 1)
        self.assertEqual(updated["tr"], "Before\nafter")
        self.assertFalse(updated["reviewed"])
        self.assertTrue(updated["excluded"])


if __name__ == "__main__":
    unittest.main()
