"""Loopback-only HTTP server for the visual corpus editor."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import tempfile
import threading
import webbrowser
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from project_paths import FONT_GENERATED_ROOT, FONT_ROOT, TEXT_CORPUS_ROOT
from text.editor.capacity import analyze_capacity
from text.editor.preview import (
    SOURCE_BY_CORPUS,
    render_menu_slot_previews,
    render_pipeline_preview,
)
from text.script.dialects import TextDialect
from text.script.formats.eve.readers import find_menu_groups
from text.script.source_models import EveSource

STATIC_ROOT = Path(__file__).with_name("static")
FONT_PATH = (
    FONT_ROOT / "source" / "ark-pixel-font" / "ark-pixel-12px-proportional-latin.otf"
)
FONT16_METRICS_PATH = FONT_GENERATED_ROOT / "font16_metrics.json"
FONT12_METRICS_PATH = FONT_GENERATED_ROOT / "font12_metrics.json"
FONT8_METRICS_PATH = FONT_GENERATED_ROOT / "font8_metrics.json"
MAX_REQUEST_BYTES = 1024 * 1024
TRANSLATION_STATUSES = ("untranslated", "translated", "reviewed", "excluded")
CLIENT_ENTRY_FIELDS = (
    "file",
    "pointer",
    "tr",
    "reviewed",
    "excluded",
    "status",
    "source",
    "source_language",
    "metadata",
    "ordinal",
    "id",
    "label",
)


def translation_status(*, tr: str, reviewed: bool, excluded: bool) -> str:
    """Classify one target using the corpus status precedence contract."""

    if excluded:
        return "excluded"
    if reviewed:
        return "reviewed"
    if tr.strip():
        return "translated"
    return "untranslated"


def status_counts(entries: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(TRANSLATION_STATUSES, 0)
    for entry in entries:
        counts[entry["status"]] += 1
    return counts


class JsonSpanParser:
    """Parse JSON while retaining source spans for scalar values."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.position = 0
        self.string_spans: dict[tuple[str | int, ...], tuple[int, int]] = {}
        self.scalar_spans: dict[tuple[str | int, ...], tuple[int, int]] = {}

    def parse(self) -> Any:
        value = self._value(())
        self._whitespace()
        if self.position != len(self.source):
            raise ValueError(f"unexpected JSON data at offset {self.position}")
        return value

    def _whitespace(self) -> None:
        while (
            self.position < len(self.source) and self.source[self.position] in " \t\r\n"
        ):
            self.position += 1

    def _value(self, path: tuple[str | int, ...]) -> Any:
        self._whitespace()
        if self.position >= len(self.source):
            raise ValueError("unexpected end of JSON")
        marker = self.source[self.position]
        if marker == "{":
            return self._object(path)
        if marker == "[":
            return self._array(path)
        if marker == '"':
            value, start, end = self._string()
            self.string_spans[path] = (start, end)
            self.scalar_spans[path] = (start, end)
            return value
        start = self.position
        value = self._literal()
        self.scalar_spans[path] = (start, self.position)
        return value

    def _object(self, path: tuple[str | int, ...]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        self.position += 1
        self._whitespace()
        if self._consume("}"):
            return result
        while True:
            self._whitespace()
            if self.position >= len(self.source) or self.source[self.position] != '"':
                raise ValueError(f"expected object key at offset {self.position}")
            key, _start, _end = self._string()
            self._whitespace()
            if not self._consume(":"):
                raise ValueError(f"expected ':' at offset {self.position}")
            result[key] = self._value((*path, key))
            self._whitespace()
            if self._consume("}"):
                return result
            if not self._consume(","):
                raise ValueError(f"expected ',' at offset {self.position}")

    def _array(self, path: tuple[str | int, ...]) -> list[Any]:
        result = []
        self.position += 1
        self._whitespace()
        if self._consume("]"):
            return result
        index = 0
        while True:
            result.append(self._value((*path, index)))
            index += 1
            self._whitespace()
            if self._consume("]"):
                return result
            if not self._consume(","):
                raise ValueError(f"expected ',' at offset {self.position}")

    def _string(self) -> tuple[str, int, int]:
        start = self.position
        self.position += 1
        while self.position < len(self.source):
            character = self.source[self.position]
            if character == "\\":
                self.position += 2
                continue
            self.position += 1
            if character == '"':
                end = self.position
                return json.loads(self.source[start:end]), start, end
        raise ValueError(f"unterminated JSON string at offset {start}")

    def _literal(self) -> Any:
        start = self.position
        while (
            self.position < len(self.source)
            and self.source[self.position] not in " \t\r\n,]}"
        ):
            self.position += 1
        if start == self.position:
            raise ValueError(f"expected JSON value at offset {self.position}")
        return json.loads(self.source[start : self.position])

    def _consume(self, character: str) -> bool:
        if self.position < len(self.source) and self.source[self.position] == character:
            self.position += 1
            return True
        return False


def _contains_translation(value: Any) -> bool:
    if isinstance(value, dict):
        if "jp" in value and "tr" in value:
            return True
        return any(_contains_translation(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_translation(child) for child in value)
    return False


def _local_metadata(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: child
        for key, child in value.items()
        if key not in {"jp", "en", "tr", "reviewed", "excluded"}
        and not _contains_translation(child)
    }


def discover_translation_entries(
    document: Any,
    *,
    file: str,
) -> list[dict[str, Any]]:
    """Return every nested object that owns a canonical translation record."""

    entries: list[dict[str, Any]] = []

    def visit(
        value: Any,
        path: tuple[str | int, ...],
        inherited_metadata: dict[str, Any],
    ) -> None:
        if isinstance(value, dict):
            metadata = {**inherited_metadata, **_local_metadata(value)}
            if "jp" in value or "tr" in value:
                if not isinstance(value.get("jp"), str) or not isinstance(
                    value.get("tr"), str
                ):
                    raise ValueError(f"{file} {list(path)} must contain jp/tr text")
                if type(value.get("reviewed")) is not bool:
                    raise ValueError(
                        f"{file} {list(path)} must contain reviewed as a boolean"
                    )
                if type(value.get("excluded")) is not bool:
                    raise ValueError(
                        f"{file} {list(path)} must contain excluded as a boolean"
                    )
                if "en" in value and not isinstance(value["en"], str):
                    raise ValueError(
                        f"{file} {list(path)} optional en reference must be text"
                    )
                field = path[-1] if path and isinstance(path[-1], str) else None
                source_language = "en" if "en" in value else "jp"
                entries.append(
                    {
                        "file": file,
                        "pointer": list(path),
                        "field": field,
                        "jp": value["jp"],
                        "tr": value["tr"],
                        "reviewed": value["reviewed"],
                        "excluded": value["excluded"],
                        "status": translation_status(
                            tr=value["tr"],
                            reviewed=value["reviewed"],
                            excluded=value["excluded"],
                        ),
                        "source": value[source_language],
                        "source_language": source_language,
                        "metadata": metadata,
                    }
                )
            for key, child in value.items():
                if key not in {"jp", "en", "tr", "reviewed", "excluded"}:
                    visit(child, (*path, key), metadata)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index), inherited_metadata)

    visit(document, (), {})
    for ordinal, entry in enumerate(entries, start=1):
        entry["ordinal"] = ordinal
        entry["id"] = f"{file}::{json.dumps(entry['pointer'], separators=(',', ':'))}"
        entry["label"] = _entry_label(entry)
        source_terms = (
            (entry["jp"],)
            if entry["source"] == entry["jp"]
            else (entry["jp"], entry["source"])
        )
        entry["_search"] = " ".join(
            (
                file,
                entry["label"],
                *source_terms,
                entry["tr"],
                json.dumps(entry["metadata"], ensure_ascii=False),
            )
        ).casefold()
    return entries


def _entry_label(entry: dict[str, Any]) -> str:
    metadata = entry["metadata"]
    parts = []
    if entry.get("field"):
        parts.append(str(entry["field"]).replace("_", " ").title())
    for key in ("kind", "index", "record", "message", "file_offset"):
        if key in metadata and not isinstance(metadata[key], (dict, list)):
            label = str(metadata[key])
            if label not in parts:
                parts.append(label)
        if len(parts) >= 2:
            break
    if not parts:
        parts.append(f"Entry {entry['ordinal']}")
    return " · ".join(parts)


def resolve_pointer(document: Any, pointer: Sequence[str | int]) -> Any:
    value = document
    for component in pointer:
        if isinstance(value, list) and type(component) is int and component >= 0:
            try:
                value = value[component]
            except IndexError as error:
                raise KeyError(
                    f"JSON pointer index {component} is outside the array"
                ) from error
        elif isinstance(value, dict) and isinstance(component, str):
            try:
                value = value[component]
            except KeyError as error:
                raise KeyError(
                    f"JSON pointer key {component!r} does not exist"
                ) from error
        else:
            raise KeyError(f"invalid JSON pointer component {component!r}")
    return value


def valid_pointer(pointer: Any) -> bool:
    return (
        isinstance(pointer, Sequence)
        and not isinstance(pointer, (str, bytes))
        and all(
            isinstance(component, str) or (type(component) is int and component >= 0)
            for component in pointer
        )
    )


def update_translation_entry(
    path: Path,
    pointer: Sequence[str | int],
    *,
    expected_tr: str,
    new_tr: str,
    expected_reviewed: bool,
    new_reviewed: bool,
    expected_excluded: bool,
    new_excluded: bool,
) -> tuple[bool, bool]:
    """Atomically update one target string and its workflow flags."""

    if (
        not valid_pointer(pointer)
        or not isinstance(expected_tr, str)
        or not isinstance(new_tr, str)
        or type(expected_reviewed) is not bool
        or type(new_reviewed) is not bool
        or type(expected_excluded) is not bool
        or type(new_excluded) is not bool
    ):
        raise ValueError("translation values have invalid types")

    with path.open("r", encoding="utf-8", newline="") as source_file:
        source = source_file.read()
    parser = JsonSpanParser(source)
    document = parser.parse()
    pair = resolve_pointer(document, pointer)
    if (
        not isinstance(pair, dict)
        or not isinstance(pair.get("jp"), str)
        or not isinstance(pair.get("tr"), str)
        or type(pair.get("reviewed")) is not bool
        or type(pair.get("excluded")) is not bool
    ):
        raise ValueError("selected JSON object is not a translation record")
    if pair["tr"] != expected_tr:
        raise FileExistsError("the translation field changed on disk")
    if pair["reviewed"] is not expected_reviewed:
        raise FileExistsError("the reviewed status changed on disk")
    if pair["excluded"] is not expected_excluded:
        raise FileExistsError("the excluded status changed on disk")

    effective_reviewed = True if new_tr != expected_tr else new_reviewed
    replacements: list[tuple[int, int, str]] = []
    for key, replacement in (
        ("tr", json.dumps(new_tr, ensure_ascii=False)),
        ("reviewed", json.dumps(effective_reviewed)),
        ("excluded", json.dumps(new_excluded)),
    ):
        requested = {
            "tr": new_tr,
            "reviewed": effective_reviewed,
            "excluded": new_excluded,
        }[key]
        if pair[key] == requested:
            continue
        target = (*pointer, key)
        try:
            start, end = parser.scalar_spans[target]
        except KeyError as error:
            raise ValueError(
                f"could not locate the {key} value in the source"
            ) from error
        replacements.append((start, end, replacement))

    updated = source
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = f"{updated[:start]}{replacement}{updated[end:]}"
    reparsed = json.loads(updated)
    updated_pair = resolve_pointer(reparsed, pointer)
    if (
        updated_pair["tr"] != new_tr
        or updated_pair["reviewed"] is not effective_reviewed
        or updated_pair["excluded"] is not new_excluded
    ):
        raise ValueError("updated JSON did not retain the requested record")

    if updated == source:
        return effective_reviewed, new_excluded

    mode = stat.S_IMODE(path.stat().st_mode)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(updated)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return effective_reviewed, new_excluded


class CorpusIndex:
    def __init__(self, corpus_root: Path = TEXT_CORPUS_ROOT) -> None:
        self.corpus_root = corpus_root.resolve()
        self._refresh_lock = threading.RLock()
        self.signature: tuple[tuple[str, int, int], ...] = ()
        self.entries: list[dict[str, Any]] = []
        self.entries_by_file: dict[str, list[dict[str, Any]]] = {}
        self._menu_groups_by_file: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.menu_groups_by_entry: dict[str, list[dict[str, Any]]] = {}

    def _current_signature(self) -> tuple[tuple[str, int, int], ...]:
        rows = []
        for path in sorted(self.corpus_root.rglob("*.json")):
            relative = path.relative_to(self.corpus_root).as_posix()
            info = path.stat()
            rows.append((relative, info.st_mtime_ns, info.st_size))
        return tuple(rows)

    def refresh(self, *, force: bool = False) -> None:
        with self._refresh_lock:
            signature = self._current_signature()
            if not force and signature == self.signature:
                return

            previous_signature = {
                relative: (modified, size)
                for relative, modified, size in self.signature
            }
            current_signature = {
                relative: (modified, size) for relative, modified, size in signature
            }
            if force or not self.signature:
                changed_files = set(current_signature)
                entries_by_file: dict[str, list[dict[str, Any]]] = {}
                menu_groups_by_file: dict[str, dict[str, list[dict[str, Any]]]] = {}
            else:
                changed_files = {
                    relative
                    for relative, details in current_signature.items()
                    if previous_signature.get(relative) != details
                }
                changed_files.update(
                    previous_signature.keys() - current_signature.keys()
                )
                entries_by_file = dict(self.entries_by_file)
                menu_groups_by_file = dict(self._menu_groups_by_file)

            for relative in changed_files:
                entries_by_file.pop(relative, None)
                menu_groups_by_file.pop(relative, None)
                if relative not in current_signature:
                    continue
                path = self.corpus_root / Path(relative)
                document = json.loads(path.read_text(encoding="utf-8"))
                discovered = discover_translation_entries(document, file=relative)
                if not discovered:
                    continue
                entries_by_file[relative] = discovered
                groups = self._build_menu_groups_for_file(relative, discovered)
                if groups:
                    menu_groups_by_file[relative] = groups

            entries_by_file = {
                relative: entries_by_file[relative]
                for relative, _modified, _size in signature
                if relative in entries_by_file
            }
            menu_groups_by_file = {
                relative: menu_groups_by_file[relative]
                for relative, _modified, _size in signature
                if relative in menu_groups_by_file
            }
            entries = [
                entry
                for relative, _modified, _size in signature
                for entry in entries_by_file.get(relative, ())
            ]
            menu_groups_by_entry = {
                entry_id: contexts
                for relative, _modified, _size in signature
                for entry_id, contexts in menu_groups_by_file.get(relative, {}).items()
            }

            # Publish the coherent snapshot only after all changed files and menu
            # contexts have been rebuilt.
            self.signature = signature
            self.entries = entries
            self.entries_by_file = entries_by_file
            self._menu_groups_by_file = menu_groups_by_file
            self.menu_groups_by_entry = menu_groups_by_entry

    @staticmethod
    def _entry_message_pages(entry: dict[str, Any]) -> dict[int, tuple[int, ...]]:
        pages: dict[int, set[int]] = {}
        locations = entry["metadata"].get("locations", ())
        if not isinstance(locations, list):
            return {}
        for location in locations:
            if not isinstance(location, dict):
                continue
            message = location.get("message")
            page = location.get("page", 0)
            if type(message) is int and type(page) is int:
                pages.setdefault(message, set()).add(page)
        return {
            message: tuple(sorted(message_pages))
            for message, message_pages in pages.items()
        }

    def _build_menu_groups_for_file(
        self,
        file: str,
        entries: Sequence[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        contexts: dict[str, list[dict[str, Any]]] = {}
        source = SOURCE_BY_CORPUS.get(file)
        if not isinstance(source, EveSource):
            return contexts

        by_message: dict[int, list[tuple[int, dict[str, Any]]]] = {}
        for entry in entries:
            for message, pages in self._entry_message_pages(entry).items():
                by_message.setdefault(message, []).extend(
                    (page, entry) for page in pages
                )
        for message_entries in by_message.values():
            message_entries.sort(key=lambda item: (item[0], item[1]["ordinal"]))

        for group in find_menu_groups(source.input_path.read_bytes(), source):
            option_entries = [
                [entry for _page, entry in by_message.get(message, ())]
                for message in group.option_messages
            ]
            if any(not rows for rows in option_entries):
                continue
            lead_entry_groups = [
                [entry for _page, entry in by_message.get(message, ())]
                for message in group.lead_messages
            ]
            prompt_message_entries = (
                by_message.get(group.prompt_message, ())
                if group.prompt_message is not None
                else ()
            )
            final_prompt_page = (
                prompt_message_entries[-1][0] if prompt_message_entries else None
            )
            prompt_entries = [
                entry
                for page, entry in prompt_message_entries
                if page == final_prompt_page
            ]
            context = {
                "script_index": group.script_index,
                "word_offset": group.word_offset,
                "prompt_entries": prompt_entries,
                "option_entries": option_entries,
                "option_slots": 2 if len(option_entries) <= 2 else 4,
                "geometry_exact": source.default_profile.dialect is TextDialect.COMBAT,
            }
            participant_ids = {
                entry["id"]
                for rows in (
                    *lead_entry_groups,
                    [entry for _page, entry in prompt_message_entries],
                    *option_entries,
                )
                for entry in rows
            }
            for entry_id in participant_ids:
                contexts.setdefault(entry_id, []).append(context)
        return contexts

    @staticmethod
    def _menu_text(
        entries: Sequence[dict[str, Any]],
        *,
        key: str,
        selected_id: str,
        proposed_tr: str,
    ) -> str:
        seen = set()
        values = []
        for entry in entries:
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            values.append(
                proposed_tr
                if key == "tr" and entry["id"] == selected_id
                else entry[key]
            )
        return "\n".join(values)

    def _menu_item(
        self,
        entries: Sequence[dict[str, Any]],
        *,
        file: str,
        role: str,
        selected_id: str,
        proposed_tr: str,
    ) -> dict[str, Any]:
        source_text = self._menu_text(
            entries,
            key="source",
            selected_id=selected_id,
            proposed_tr=proposed_tr,
        )
        translation = self._menu_text(
            entries,
            key="tr",
            selected_id=selected_id,
            proposed_tr=proposed_tr,
        )
        first = entries[0]
        metadata = {**first["metadata"], "_field": first["field"]}
        return {
            "source": source_text,
            "tr": translation,
            "slot_previews": render_menu_slot_previews(
                file,
                metadata,
                translation,
                role=role,
            ),
        }

    def menu_contexts(
        self,
        *,
        file: str,
        pointer: Sequence[str | int],
        proposed_tr: str,
        refresh_index: bool = True,
    ) -> list[dict[str, Any]]:
        if refresh_index:
            self.refresh()
        selected_id = f"{file}::{json.dumps(pointer, separators=(',', ':'))}"
        output = []
        for context in self.menu_groups_by_entry.get(selected_id, ()):
            prompt_entries = context["prompt_entries"]
            output.append(
                {
                    "script_index": context["script_index"],
                    "word_offset": context["word_offset"],
                    "option_slots": context["option_slots"],
                    "prompt": (
                        self._menu_item(
                            prompt_entries,
                            file=file,
                            role="prompt",
                            selected_id=selected_id,
                            proposed_tr=proposed_tr,
                        )
                        if prompt_entries
                        else None
                    ),
                    "options": [
                        {
                            **self._menu_item(
                                entries,
                                file=file,
                                role="option",
                                selected_id=selected_id,
                                proposed_tr=proposed_tr,
                            ),
                            "selected": any(
                                entry["id"] == selected_id for entry in entries
                            ),
                        }
                        for entries in context["option_entries"]
                    ],
                    "geometry_exact": context["geometry_exact"],
                    "grouping_exact": True,
                }
            )
        return output

    def files(self) -> list[dict[str, Any]]:
        self.refresh()
        return [
            {
                "path": file,
                "name": Path(file).name,
                "group": Path(file).parent.as_posix(),
                "count": len(entries),
                "status_counts": status_counts(entries),
            }
            for file, entries in self.entries_by_file.items()
        ]

    def query(
        self,
        *,
        file: str,
        search: str,
        offset: int,
        limit: int,
        status_filter: str = "all",
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        self.refresh()
        source = self.entries if not file else self.entries_by_file.get(file, [])
        needle = search.strip().casefold()
        query_matches = (
            [entry for entry in source if needle in entry["_search"]]
            if needle
            else source
        )
        counts = status_counts(query_matches)
        if status_filter == "all":
            matches = query_matches
        elif status_filter in TRANSLATION_STATUSES:
            matches = [
                entry for entry in query_matches if entry["status"] == status_filter
            ]
        else:
            allowed = ", ".join(("all", *TRANSLATION_STATUSES))
            raise ValueError(f"status filter must be one of: {allowed}")
        visible = []
        for entry in matches[offset : offset + limit]:
            visible.append({key: entry[key] for key in CLIENT_ENTRY_FIELDS})
        return visible, len(matches), counts

    def entry(
        self,
        *,
        file: str,
        pointer: Sequence[str | int],
        refresh_index: bool = True,
    ) -> dict[str, Any]:
        if refresh_index:
            self.refresh()
        entry_id = f"{file}::{json.dumps(pointer, separators=(',', ':'))}"
        return next(
            entry
            for entry in self.entries_by_file.get(file, ())
            if entry["id"] == entry_id
        )

    def corpus_path(self, relative: str) -> Path:
        candidate = (self.corpus_root / Path(relative)).resolve()
        if candidate.suffix.lower() != ".json" or not candidate.is_relative_to(
            self.corpus_root
        ):
            raise ValueError("corpus path must be a JSON file below text/corpus")
        return candidate


class EditorHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        index: CorpusIndex,
    ) -> None:
        super().__init__(server_address, EditorRequestHandler)
        self.index = index
        self.editor_token = secrets.token_urlsafe(32)
        self.save_lock = threading.Lock()


class EditorRequestHandler(BaseHTTPRequestHandler):
    server: EditorHTTPServer

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        if request.path == "/api/bootstrap":
            self._bootstrap()
            return
        if request.path == "/api/entries":
            self._entries(parse_qs(request.query))
            return
        if request.path == "/health":
            self._json({"status": "ok"})
            return
        if request.path == "/assets/ark-pixel-12px.otf":
            self._file(FONT_PATH, "font/otf")
            return

        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        selected = static_files.get(request.path)
        if selected is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        name, content_type = selected
        self._file(STATIC_ROOT / name, content_type)

    def do_PATCH(self) -> None:
        request = urlsplit(self.path)
        if request.path != "/api/entry":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get("X-Editor-Token") != self.server.editor_token:
            self._json({"error": "invalid editor token"}, HTTPStatus.FORBIDDEN)
            return
        try:
            payload = self._request_json()
            file = payload["file"]
            pointer = payload["pointer"]
            expected_tr = payload["expected_tr"]
            new_tr = payload["tr"]
            expected_reviewed = payload["expected_reviewed"]
            new_reviewed = payload["reviewed"]
            expected_excluded = payload["expected_excluded"]
            new_excluded = payload["excluded"]
            if (
                not isinstance(file, str)
                or not isinstance(pointer, list)
                or not valid_pointer(pointer)
                or not isinstance(expected_tr, str)
                or not isinstance(new_tr, str)
                or type(expected_reviewed) is not bool
                or type(new_reviewed) is not bool
                or type(expected_excluded) is not bool
                or type(new_excluded) is not bool
            ):
                raise ValueError("invalid save request")
            path = self.server.index.corpus_path(file)
            # The read/compare/replace sequence is atomic only while serialized.
            # Without this lock, two tabs can both pass their optimistic checks
            # before either replacement reaches disk.
            with self.server.save_lock:
                reviewed, excluded = update_translation_entry(
                    path,
                    pointer,
                    expected_tr=expected_tr,
                    new_tr=new_tr,
                    expected_reviewed=expected_reviewed,
                    new_reviewed=new_reviewed,
                    expected_excluded=expected_excluded,
                    new_excluded=new_excluded,
                )
                # The atomic replacement changes this file's signature.  Refresh
                # only that changed corpus file and its menu contexts.
                self.server.index.refresh()
            self._json(
                {
                    "tr": new_tr,
                    "reviewed": reviewed,
                    "excluded": excluded,
                    "status": translation_status(
                        tr=new_tr,
                        reviewed=reviewed,
                        excluded=excluded,
                    ),
                }
            )
        except FileExistsError as error:
            self._json({"error": str(error)}, HTTPStatus.CONFLICT)
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except OSError as error:
            self._json(
                {"error": f"could not save the corpus file: {error}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_POST(self) -> None:
        request = urlsplit(self.path)
        if request.path not in {"/api/preview", "/api/capacity"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._request_json()
            file = payload["file"]
            pointer = payload["pointer"]
            translation = payload["tr"]
            if (
                not isinstance(file, str)
                or not isinstance(pointer, list)
                or not valid_pointer(pointer)
                or not isinstance(translation, str)
            ):
                raise ValueError("invalid preview request")
            if request.path == "/api/capacity":
                self._json(
                    analyze_capacity(
                        file,
                        pointer,
                        translation,
                        corpus_root=self.server.index.corpus_root,
                    )
                )
                return

            self.server.index.refresh()
            entry = self.server.index.entry(
                file=file,
                pointer=pointer,
                refresh_index=False,
            )
            preview = render_pipeline_preview(
                file,
                {**entry["metadata"], "_field": entry["field"]},
                translation,
            )
            preview["menus"] = self.server.index.menu_contexts(
                file=file,
                pointer=pointer,
                proposed_tr=translation,
                refresh_index=False,
            )
            self._json(preview)
        except (KeyError, StopIteration, ValueError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _bootstrap(self) -> None:
        try:
            font16_metrics = json.loads(FONT16_METRICS_PATH.read_text(encoding="utf-8"))
            font12_metrics = json.loads(FONT12_METRICS_PATH.read_text(encoding="utf-8"))
            font8_metrics = json.loads(FONT8_METRICS_PATH.read_text(encoding="utf-8"))
            for name, metrics in (
                ("FONT16", font16_metrics),
                ("FONT12", font12_metrics),
                ("FONT8", font8_metrics),
            ):
                if metrics.get("version") != 2 or not metrics.get("complete"):
                    raise ValueError(f"{name} metrics are incomplete")
            self._json(
                {
                    "files": self.server.index.files(),
                    "total": len(self.server.index.entries),
                    "status_counts": status_counts(self.server.index.entries),
                    "fonts": {
                        "font16": font16_metrics,
                        "font12": font12_metrics,
                        "font8": font8_metrics,
                    },
                    "editor_token": self.server.editor_token,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._json(
                {"error": f"could not load the editor data: {error}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _entries(self, query: dict[str, list[str]]) -> None:
        try:
            file = query.get("file", [""])[0]
            search = query.get("q", [""])[0]
            status_filter = query.get("status", ["all"])[0]
            offset = max(0, int(query.get("offset", ["0"])[0]))
            limit = min(250, max(1, int(query.get("limit", ["100"])[0])))
            entries, total, counts = self.server.index.query(
                file=file,
                search=search,
                offset=offset,
                limit=limit,
                status_filter=status_filter,
            )
            self._json(
                {
                    "entries": entries,
                    "total": total,
                    "status_counts": counts,
                }
            )
        except ValueError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _request_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid content length") from error
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError("request body is empty or too large")
        body = self.rfile.read(length)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self._common_headers(content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(
        self,
        value: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self._common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _common_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[wrap-editor] {self.address_string()} {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open the local visual editor for text/corpus JSON files."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="loopback port to use (default: 8765; use 0 for an available port)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="serve the editor without opening the default browser",
    )
    return parser


def run(*, port: int, open_browser: bool) -> None:
    index = CorpusIndex()
    index.refresh()
    server = EditorHTTPServer(("127.0.0.1", port), index)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"Corpus wrap editor: {url}")
    print(
        f"Indexed {len(index.entries)} JP/TR fields in {len(index.entries_by_file)} files."
    )
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.35, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping corpus wrap editor.")
    finally:
        server.server_close()


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        raise SystemExit("--port must be between 0 and 65535")
    run(port=args.port, open_browser=not args.no_browser)
