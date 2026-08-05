"""Read-only, format-aware capacity projections for corpus editor proposals."""

from __future__ import annotations

import json
import struct
import threading
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from project_paths import TEXT_CORPUS_ROOT, TEXT_GENERATED_ROOT
from text.script.dialects import get_dialect
from text.script.encoding.event_codec import (
    EventDictionary,
    dictionary_from_manifest,
)
from text.script.encoding.latin import load_latin_encoding
from text.script.encoding.tokens import normalize_english
from text.script.formats.ascii_fields.model import AsciiField
from text.script.formats.deduplicated_words.extract import (
    TERMINATOR as DEDUPLICATED_TERMINATOR,
)
from text.script.formats.deduplicated_words.extract import parse_hex
from text.script.formats.deduplicated_words.repack import (
    encode_record as encode_deduplicated_record,
)
from text.script.formats.eve.extract import extract_bank
from text.script.formats.eve.repack import group_corpus_pages
from text.script.formats.fixed_bytes.repack import FONT8_METRICS_PATH
from text.script.formats.fixed_help.repack import (
    encode_record as encode_help_record,
)
from text.script.formats.fixed_help.repack import indentation
from text.script.formats.fixed_words.repack import encode_fixed_text
from text.script.formats.indexed_bytes.repack import (
    plan_indexed_bytes,
)
from text.script.formats.indexed_words.extract import read_records
from text.script.formats.indexed_words.repack import (
    encode_message as encode_indexed_words_message,
)
from text.script.formats.mirrored_words.repack import (
    encode_record as encode_mirrored_record,
)
from text.script.formats.mirrored_words.repack import (
    encode_translation as encode_mirrored_translation,
)
from text.script.formats.name_description.repack import (
    FONT8_METRICS_PATH as NAME_FONT8_METRICS_PATH,
)
from text.script.formats.name_description.repack import (
    NAME_TERMINATOR,
    encode_description,
    free_ranges,
)
from text.script.formats.static_overlay.extract import (
    extract_records as extract_static_records,
)
from text.script.formats.static_overlay.model import (
    AsciiString,
    FixedCells,
    FixedRows,
    SplitLines,
    StaticRecordSpec,
)
from text.script.formats.static_overlay.repack import (
    build_ascii_string,
    build_fixed_cells,
    build_fixed_rows,
    build_split_lines,
)
from text.script.formats.static_overlay.repack import (
    wrap_message as wrap_static_message,
)
from text.script.message import encode_translation as encode_eve_translation
from text.script.profiles import RuntimeCapability
from text.script.source_models import (
    AsciiFieldsSource,
    DeduplicatedWordsSource,
    EveSource,
    FixedBytesSource,
    FixedHelpSource,
    FixedWordsSource,
    IndexedBytesSource,
    IndexedWordsSource,
    MirroredWordsSource,
    NameDescriptionSource,
    StaticOverlaySource,
    TextSource,
)
from text.script.sources import SOURCES

Outcome = Literal["fits", "runtime", "fallback", "overflow", "unavailable"]

_SOURCES_BY_CORPUS = {source.corpus_path.as_posix(): source for source in SOURCES}
_EVENT_CODEC_PATH = TEXT_GENERATED_ROOT / "event_codec.json"
_RUNTIME_UI_WIDTHS = {
    "runtime_ui/healing_ui.json": 144,
    "runtime_ui/shop_ui.json": 64,
}


def _check(
    name: str,
    *,
    exact: bool,
    used: int | None = None,
    capacity: int | None = None,
    unit: str | None = None,
    outcome: Outcome | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    if outcome is None:
        outcome = (
            "fits"
            if capacity is None or used is None or used <= capacity
            else "overflow"
        )
    remaining = None if capacity is None or used is None else capacity - used
    return {
        "name": name,
        "outcome": outcome,
        "exact": exact,
        "used": used,
        "capacity": capacity,
        "remaining": remaining,
        "unit": unit,
        "message": message,
    }


def _result(
    format_name: str,
    outcome: Outcome,
    checks: Sequence[dict[str, Any]],
    *,
    exact: bool = True,
    runtime_requirements: Sequence[RuntimeCapability] = (),
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "format": format_name,
        "outcome": outcome,
        "exact": exact and all(check["exact"] for check in checks),
        "checks": list(checks),
        "runtime_requirements": sorted(
            requirement.value for requirement in runtime_requirements
        ),
        "note": note,
    }


def _encoding_failure(
    format_name: str,
    error: Exception,
    *,
    exact: bool = True,
) -> dict[str, Any]:
    return _result(
        format_name,
        "overflow",
        (
            _check(
                "encoding",
                exact=exact,
                outcome="overflow",
                message=str(error),
            ),
        ),
        exact=exact,
    )


def _unavailable(format_name: str, message: str) -> dict[str, Any]:
    return _result(
        format_name,
        "unavailable",
        (
            _check(
                "capacity",
                exact=False,
                outcome="unavailable",
                message=message,
            ),
        ),
        exact=False,
        note=message,
    )


def _blank(
    format_name: str, *, required: bool = False, exact: bool = True
) -> dict[str, Any]:
    outcome: Outcome = "overflow" if required else "fallback"
    message = (
        "This format requires a nonblank translation."
        if required
        else "A blank translation preserves the source text."
    )
    return _result(
        format_name,
        outcome,
        (
            _check(
                "translation",
                exact=exact,
                used=0,
                unit="characters",
                outcome=outcome,
                message=message,
            ),
        ),
        exact=exact,
    )


def _normalize_corpus_file(file: str, corpus_root: Path) -> str:
    if not isinstance(file, str) or not file.strip():
        raise ValueError("corpus file must be nonempty text")
    candidate = Path(file)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(corpus_root.resolve()).as_posix()
        except ValueError as error:
            raise ValueError("corpus file is outside text/corpus") from error

    normalized = file.replace("\\", "/")
    for prefix in ("text/corpus/", "corpus/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("corpus file must remain below text/corpus")
    return relative.as_posix()


def _resolve_pointer(document: Any, pointer: Sequence[str | int]) -> Any:
    value = document
    for component in pointer:
        if isinstance(value, list) and type(component) is int:
            value = value[component]
        elif isinstance(value, dict) and isinstance(component, str):
            value = value[component]
        else:
            raise ValueError(f"invalid JSON pointer component {component!r}")
    return value


def _translation_pointer(
    document: Any,
    pointer: Sequence[str | int],
    *,
    require_array_row: bool = True,
) -> tuple[tuple[str | int, ...], dict[str, Any]]:
    if not isinstance(pointer, Sequence) or isinstance(pointer, (str, bytes)):
        raise ValueError("JSON pointer must be a sequence")
    normalized = tuple(pointer)
    if any(type(component) is int and component < 0 for component in normalized):
        raise ValueError("JSON pointer array indices must be non-negative")
    if normalized and normalized[-1] == "tr":
        normalized = normalized[:-1]
    if not normalized or (require_array_row and type(normalized[0]) is not int):
        raise ValueError("capacity checks require an array-row JSON pointer")
    try:
        value = _resolve_pointer(document, normalized)
    except (IndexError, KeyError) as error:
        raise ValueError("JSON pointer does not exist") from error
    if not isinstance(value, dict) or not isinstance(value.get("tr"), str):
        raise ValueError("JSON pointer does not select a translation record")
    return normalized, value


def _fixed_bytes(
    source: FixedBytesSource,
    row: dict[str, Any],
    row_index: int,
    translation: str,
) -> dict[str, Any]:
    format_name = "fixed_bytes"
    translation = translation.strip()
    if not translation:
        return _blank(format_name)
    metadata_record = row.get("record")
    if metadata_record is not None and metadata_record != row_index:
        return _encoding_failure(
            format_name,
            ValueError("fixed-byte record metadata does not match its array index"),
        )
    record = row_index
    if not 0 <= record < source.record_count:
        return _encoding_failure(
            format_name, ValueError("invalid fixed-byte record index")
        )
    try:
        encoding = load_latin_encoding(FONT8_METRICS_PATH)
        encoded = bytes(encoding.encode_segment(translation))
        pixels = encoding.measure_segment(translation)
    except ValueError as error:
        return _encoding_failure(format_name, error)

    checks = (
        _check(
            "encoded_bytes",
            exact=True,
            used=len(encoded),
            capacity=source.field_size,
            unit="bytes",
        ),
        _check(
            "rendered_width",
            exact=True,
            used=pixels,
            capacity=source.pixel_limit,
            unit="pixels",
        ),
    )
    if all(check["outcome"] == "fits" for check in checks):
        return _result(format_name, "fits", checks)

    requirements = source.runtime_requirements_for_capacity_fallback(record)
    missing = requirements - source.runtime_requirements
    if missing:
        names = ", ".join(sorted(requirement.value for requirement in missing))
        return _result(
            format_name,
            "overflow",
            (
                *checks,
                _check(
                    "runtime_configuration",
                    exact=True,
                    outcome="overflow",
                    message=(
                        "Runtime-covered capacity fallback requirements are not "
                        f"emitted by the source: {names}."
                    ),
                ),
            ),
        )
    if requirements:
        return _result(
            format_name,
            "runtime",
            checks,
            runtime_requirements=requirements,
            note="The native field overflows, but declared runtime consumers supply it.",
        )
    return _result(
        format_name,
        "fallback",
        checks,
        note="The repacker preserves the source record when native capacity is exceeded.",
    )


def _fixed_help(
    source: FixedHelpSource,
    row_index: int,
    translation: str,
) -> dict[str, Any]:
    format_name = "fixed_help"
    translation = translation.strip()
    if not translation:
        return _blank(format_name, required=True)
    try:
        original = source.input_path.read_bytes()
        offset = row_index * source.record_words * 2
        words = struct.unpack_from(f">{source.record_words}H", original, offset)
        leading, post_newline = indentation(words)
        encoded = encode_help_record(translation, source, leading, post_newline)
    except (OSError, struct.error, ValueError) as error:
        return _encoding_failure(format_name, error)

    line_count = len(normalize_english(translation).split("\n"))
    checks = (
        _check(
            "encoded_words",
            exact=True,
            used=len(encoded),
            capacity=source.record_words,
            unit="words",
        ),
        _check(
            "lines",
            exact=True,
            used=line_count,
            capacity=source.max_lines,
            unit="lines",
        ),
        _check(
            "leading_indentation",
            exact=True,
            used=leading,
            unit="words",
            message="Preserved from the source record and included in encoded_words.",
        ),
        _check(
            "post_newline_indentation",
            exact=True,
            used=post_newline,
            unit="words",
            message="Preserved from the source record and included after a newline.",
        ),
    )
    outcome: Outcome = "fits" if len(encoded) <= source.record_words else "overflow"
    return _result(format_name, outcome, checks)


def _fixed_words(
    source: FixedWordsSource,
    row: dict[str, Any],
    translation: str,
) -> dict[str, Any]:
    format_name = "fixed_words"
    translation = translation.strip()
    if not translation:
        return _blank(format_name)
    kind = row.get("kind")
    field = next((item for item in source.fields if item.kind == kind), None)
    if field is None:
        return _encoding_failure(
            format_name, ValueError(f"unknown field kind {kind!r}")
        )
    if (
        field.runtime_word_count is not None
        and field.runtime_word_count < field.word_count
    ):
        return _encoding_failure(
            format_name,
            ValueError("runtime capacity is smaller than native capacity"),
        )
    try:
        words = encode_fixed_text(
            translation,
            packed=source.packed,
            zero_mode=field.zero_mode,
            latin=load_latin_encoding(),
            dialect=(
                get_dialect(source.dialect) if source.dialect is not None else None
            ),
        )
    except ValueError as error:
        return _encoding_failure(format_name, error)
    payload_words = len(words) + (field.terminator is not None)
    checks = [
        _check(
            "native_words",
            exact=True,
            used=payload_words,
            capacity=field.word_count,
            unit="words",
        )
    ]
    if field.runtime_word_count is not None:
        checks.append(
            _check(
                "runtime_words",
                exact=True,
                used=payload_words,
                capacity=field.runtime_word_count,
                unit="words",
            )
        )
    if payload_words <= field.word_count:
        outcome: Outcome = "fits"
        requirements: Sequence[RuntimeCapability] = ()
    elif (
        field.runtime_word_count is not None
        and payload_words <= field.runtime_word_count
    ):
        outcome = "runtime"
        requirements = tuple(source.runtime_requirements)
    else:
        outcome = "fallback"
        requirements = ()
    return _result(
        format_name,
        outcome,
        checks,
        runtime_requirements=requirements,
        note=(
            "The runtime-owned field accepts text beyond the native slot."
            if outcome == "runtime"
            else None
        ),
    )


def _name_description(
    source: NameDescriptionSource,
    document: list[dict[str, Any]],
    pointer: Sequence[str | int],
    translation: str,
) -> dict[str, Any]:
    format_name = "name_description"
    translation = translation.strip()
    if len(pointer) != 2 or pointer[1] not in {"name", "description"}:
        return _encoding_failure(
            format_name,
            ValueError("name-description pointer must select name or description"),
        )
    try:
        if len(document) != source.record_count:
            raise ValueError("corpus and name-description record counts differ")
        selected_index = pointer[0]
        assert isinstance(selected_index, int)
        original = source.input_path.read_bytes()
        output = bytearray(original)
        description_capacity = (source.pointer_offset - source.description_offset) // 2
        selected_fallback = not translation
        selected_checks: list[dict[str, Any]] = []

        # Description edits change the padding arena that owns every relocated
        # full name, so project all current descriptions before testing names.
        for index, row in enumerate(document):
            candidate = (
                translation
                if index == selected_index and pointer[1] == "description"
                else row["description"]["tr"].strip()
            )
            if not candidate:
                continue
            words = encode_description(candidate, source)
            if index == selected_index and pointer[1] == "description":
                selected_checks.append(
                    _check(
                        "description_words",
                        exact=True,
                        used=len(words),
                        capacity=description_capacity,
                        unit="words",
                    )
                )
                selected_fallback = len(words) > description_capacity
            if len(words) > description_capacity:
                continue
            base = index * source.record_size + source.description_offset
            output[base : base + description_capacity * 2] = bytes(
                description_capacity * 2
            )
            struct.pack_into(f">{len(words)}H", output, base, *words)

        ranges = free_ranges(bytes(output), source)
        pool_capacity = sum(stop - start for start, stop in ranges)
        font8 = load_latin_encoding(NAME_FONT8_METRICS_PATH)
        packed_name_bytes = 0
        allocation_error: ValueError | None = None
        for index, row in enumerate(document):
            candidate = (
                translation
                if index == selected_index and pointer[1] == "name"
                else row["name"]["tr"].strip()
            )
            record_base = index * source.record_size
            if candidate:
                normalized = normalize_english(candidate)
                encoded = bytes(font8.encode_segment(normalized))
                pixels = font8.measure_segment(normalized)
                name_fallback = (
                    len(encoded) > source.max_full_name_bytes
                    or pixels > source.max_full_name_pixels
                )
                if index == selected_index and pointer[1] == "name":
                    selected_checks.extend(
                        (
                            _check(
                                "name_bytes",
                                exact=True,
                                used=len(encoded),
                                capacity=source.max_full_name_bytes,
                                unit="bytes",
                            ),
                            _check(
                                "name_width",
                                exact=True,
                                used=pixels,
                                capacity=source.max_full_name_pixels,
                                unit="pixels",
                            ),
                        )
                    )
                    selected_fallback = name_fallback
                if name_fallback:
                    start = record_base + source.name_offset
                    encoded = original[start : start + source.name_bytes].rstrip(
                        b"\x00"
                    )
            else:
                start = record_base + source.name_offset
                encoded = original[start : start + source.name_bytes].rstrip(b"\x00")
            if NAME_TERMINATOR in encoded:
                raise ValueError(f"name {index} contains terminator byte 0xff")
            if len(encoded) > source.max_full_name_bytes:
                raise ValueError(f"original name {index} is too long")
            payload_size = len(encoded) + 1
            packed_name_bytes += payload_size
            span = next(
                (item for item in ranges if item[1] - item[0] >= payload_size),
                None,
            )
            if span is None:
                allocation_error = ValueError(
                    "description padding cannot fit the projected full-name pool"
                )
                break
            span[0] += payload_size
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        return _encoding_failure(format_name, error)

    if not selected_checks:
        selected_checks.append(
            _check(
                "translation",
                exact=True,
                used=0,
                unit="characters",
                outcome="fallback",
                message="A blank translation preserves the source text.",
            )
        )
    selected_checks.append(
        _check(
            "shared_name_pool_bytes",
            exact=True,
            used=packed_name_bytes,
            capacity=pool_capacity,
            unit="bytes",
            outcome="overflow" if allocation_error else "fits",
            message=str(allocation_error) if allocation_error else None,
        )
    )
    if allocation_error:
        outcome: Outcome = "overflow"
    elif selected_fallback:
        outcome = "fallback"
    else:
        outcome = "fits"
    return _result(
        format_name,
        outcome,
        selected_checks,
        note="Includes the exact shared full-name allocation over description padding.",
    )


def _mirrored_words(
    source: MirroredWordsSource,
    row: dict[str, Any],
    translation: str,
) -> dict[str, Any]:
    format_name = "mirrored_words"
    translation = translation.strip()
    if not translation:
        return _blank(format_name)
    table_name = row.get("table")
    index = row.get("index")
    table = next((item for item in source.tables if item.name == table_name), None)
    if table is None or type(index) is not int or not 0 <= index < table.record_count:
        return _encoding_failure(format_name, ValueError("invalid mirrored table row"))
    try:
        words = encode_mirrored_translation(translation, table.zero_mode)
    except ValueError as error:
        return _encoding_failure(format_name, error)
    checks = []
    overflow = False
    for location in table.locations:
        record = encode_mirrored_record(
            words,
            location.words_per_record,
            table.terminator_mode,
        )
        overflow = overflow or record is None
        if table.terminator_mode == "required":
            used = len(words) + 1
        else:
            used = (
                len(words)
                if len(words) >= location.words_per_record
                else len(words) + 1
            )
        checks.append(
            _check(
                f"physical_words:{location.path.as_posix()}@0x{location.table_offset:x}",
                exact=True,
                used=used,
                capacity=location.words_per_record,
                unit="words",
            )
        )
    if not overflow:
        return _result(format_name, "fits", checks)
    requirements = table.runtime_requirements_for_capacity_fallback(index)
    missing = requirements - source.runtime_requirements
    if missing:
        names = ", ".join(sorted(requirement.value for requirement in missing))
        checks.append(
            _check(
                "runtime_configuration",
                exact=True,
                outcome="overflow",
                message=(
                    "Runtime-covered capacity fallback requirements are not "
                    f"emitted by the source: {names}."
                ),
            )
        )
        return _result(format_name, "overflow", checks)
    if requirements:
        return _result(
            format_name,
            "runtime",
            checks,
            runtime_requirements=requirements,
        )
    return _result(format_name, "fallback", checks)


def _deduplicated_words(
    source: DeduplicatedWordsSource,
    row: dict[str, Any],
    translation: str,
) -> dict[str, Any]:
    format_name = "deduplicated_words"
    translation = translation.strip()
    if not translation:
        return _blank(format_name)
    try:
        words = encode_deduplicated_record(
            translation,
            packed=source.packed,
            latin=load_latin_encoding(),
        )
        checks = []
        for location in row["locations"]:
            has_terminator = (
                parse_hex(location["boundary_word"], "boundary word")
                == DEDUPLICATED_TERMINATOR
            )
            capacity = location["word_count"] - has_terminator
            checks.append(
                _check(
                    f"physical_words@{location['file_offset']}",
                    exact=True,
                    used=len(words),
                    capacity=capacity,
                    unit="words",
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        return _encoding_failure(format_name, error)
    outcome: Outcome = (
        "fits" if all(check["outcome"] == "fits" for check in checks) else "fallback"
    )
    return _result(format_name, outcome, checks)


def _ascii_fields(
    source: AsciiFieldsSource,
    row: dict[str, Any],
    translation: str,
) -> dict[str, Any]:
    format_name = "ascii_fields"
    if not translation:
        return _blank(format_name)
    field: AsciiField | None = next(
        (item for item in source.fields if item.kind == row.get("kind")),
        None,
    )
    if field is None:
        return _encoding_failure(format_name, ValueError("unknown ASCII field"))
    if field.runtime_capacity is not None and field.runtime_capacity < field.capacity:
        return _encoding_failure(
            format_name,
            ValueError("runtime capacity is smaller than native capacity"),
        )
    try:
        payload = translation.encode("ascii") + b"\x00"
    except UnicodeEncodeError as error:
        return _encoding_failure(format_name, error)
    checks = [
        _check(
            "bytes_including_nul",
            exact=True,
            used=len(payload),
            capacity=field.capacity,
            unit="bytes",
            message="The terminating NUL byte is included.",
        )
    ]
    if field.runtime_capacity is not None:
        checks.append(
            _check(
                "runtime_bytes_including_nul",
                exact=True,
                used=len(payload),
                capacity=field.runtime_capacity,
                unit="bytes",
                message="The terminating NUL byte is included.",
            )
        )
    if len(payload) <= field.capacity:
        outcome: Outcome = "fits"
        requirements: Sequence[RuntimeCapability] = ()
    elif field.runtime_capacity is not None and len(payload) <= field.runtime_capacity:
        outcome = "runtime"
        requirements = tuple(source.runtime_requirements)
    else:
        outcome = "fallback"
        requirements = ()
    return _result(
        format_name,
        outcome,
        checks,
        runtime_requirements=requirements,
        note=(
            "The runtime-owned field accepts text beyond the native slot."
            if outcome == "runtime"
            else None
        ),
    )


def _static_specs_for_row(
    source: StaticOverlaySource,
    row: dict[str, Any],
) -> tuple[StaticRecordSpec, ...]:
    by_kind = {record.kind: record for record in source.records}
    if not source.deduplicate_by_jp:
        try:
            return (by_kind[row["kind"]],)
        except KeyError as error:
            raise ValueError("unknown static record kind") from error
    try:
        kinds = {
            record["kind"]
            for record in extract_static_records(source)
            if record["jp"] == row["jp"]
        }
        return tuple(by_kind[kind] for kind in sorted(kinds))
    except (KeyError, OSError) as error:
        raise ValueError("could not resolve deduplicated static records") from error


def _static_layout_checks(
    record: StaticRecordSpec,
    translation: str,
) -> tuple[list[dict[str, Any]], str | None]:
    encoding = load_latin_encoding()
    layout = record.layout
    prefix = f"{record.kind}:"
    checks: list[dict[str, Any]] = []
    try:
        if isinstance(layout, FixedCells):
            codes = tuple(encoding.encode_segment(translation))
            pixels = encoding.measure_segment(translation)
            checks.append(
                _check(
                    f"{prefix}cells",
                    exact=True,
                    used=len(codes),
                    capacity=layout.cells - int(layout.terminator_required),
                    unit="cells",
                )
            )
            if layout.pixel_limit is not None:
                checks.append(
                    _check(
                        f"{prefix}width",
                        exact=True,
                        used=pixels,
                        capacity=layout.pixel_limit,
                        unit="pixels",
                    )
                )
            build_fixed_cells(translation, layout, encoding)
        elif isinstance(layout, FixedRows):
            lines = wrap_static_message(
                translation,
                layout.pixel_limit,
                max(layout.rows, len(translation) + 1),
                encoding,
            )
            checks.append(
                _check(
                    f"{prefix}rows",
                    exact=True,
                    used=len(lines),
                    capacity=layout.rows,
                    unit="rows",
                )
            )
            for index, line in enumerate(lines):
                checks.extend(
                    (
                        _check(
                            f"{prefix}row_{index}_cells",
                            exact=True,
                            used=len(tuple(encoding.encode_segment(line))),
                            capacity=layout.cells,
                            unit="cells",
                        ),
                        _check(
                            f"{prefix}row_{index}_width",
                            exact=True,
                            used=encoding.measure_segment(line),
                            capacity=layout.pixel_limit,
                            unit="pixels",
                        ),
                    )
                )
            build_fixed_rows(translation, layout, encoding)
        elif isinstance(layout, SplitLines):
            lines = tuple(translation.split("{n}"))
            checks.append(
                _check(
                    f"{prefix}lines",
                    exact=True,
                    used=len(lines),
                    capacity=layout.lines,
                    unit="lines",
                    outcome=(
                        "fits"
                        if len(lines) == layout.lines and all(lines)
                        else "overflow"
                    ),
                )
            )
            for index, line in enumerate(lines):
                checks.extend(
                    (
                        _check(
                            f"{prefix}line_{index}_cells",
                            exact=True,
                            used=len(tuple(encoding.encode_segment(line))),
                            capacity=layout.cells,
                            unit="cells",
                        ),
                        _check(
                            f"{prefix}line_{index}_width",
                            exact=True,
                            used=encoding.measure_segment(line),
                            capacity=layout.pixel_limit,
                            unit="pixels",
                        ),
                    )
                )
            build_split_lines(translation, layout, encoding)
        elif isinstance(layout, AsciiString):
            data = translation.encode("ascii") + b"\x00"
            checks.append(
                _check(
                    f"{prefix}bytes_including_nul",
                    exact=True,
                    used=len(data),
                    capacity=layout.max_bytes,
                    unit="bytes",
                )
            )
            build_ascii_string(translation, layout)
        else:
            return checks, f"unknown static layout {type(layout).__name__}"
    except ValueError as error:
        return checks, str(error)
    return checks, None


def _static_overlay(
    source: StaticOverlaySource,
    row: dict[str, Any],
    translation: str,
) -> dict[str, Any]:
    format_name = "static_overlay"
    translation = translation.strip()
    if not translation:
        return _blank(format_name, required=True)
    try:
        records = _static_specs_for_row(source, row)
        if not records:
            raise ValueError("translation has no physical static records")
        checks: list[dict[str, Any]] = []
        errors = []
        for record in records:
            record_checks, error = _static_layout_checks(record, translation)
            checks.extend(record_checks)
            if error is not None:
                errors.append(f"{record.kind}: {error}")
    except (OSError, ValueError) as error:
        return _encoding_failure(format_name, error)
    if errors:
        checks.extend(
            _check(
                "layout",
                exact=True,
                outcome="overflow",
                message=error,
            )
            for error in errors
        )
        return _result(format_name, "overflow", checks)
    return _result(format_name, "fits", checks)


def _indexed_bytes(
    source: IndexedBytesSource,
    document: list[dict[str, Any]],
    row_index: int,
    translation: str,
) -> dict[str, Any]:
    format_name = "indexed_bytes"
    exact = False
    try:
        plan = plan_indexed_bytes(
            source,
            document,
            translation_overrides={row_index: translation},
        )
        projected_message = plan.projected_messages[row_index]
    except (IndexError, KeyError, OSError, ValueError) as error:
        return _encoding_failure(format_name, error, exact=exact)

    checks = [
        _check(
            "message_bytes",
            exact=exact,
            used=len(projected_message),
            unit="bytes",
            message="Includes the message terminator.",
        ),
        _check(
            "shared_body_bytes",
            exact=exact,
            used=plan.projected_body_size,
            capacity=plan.body_capacity,
            unit="bytes",
        ),
    ]
    if plan.fallback_indices:
        checks.append(
            _check(
                "projected_fallbacks",
                exact=exact,
                used=len(plan.fallback_indices),
                capacity=0,
                unit="records",
                outcome="fallback",
                message=(
                    "The proposed record is among the projected fallbacks."
                    if row_index in plan.fallback_indices
                    else "Other translated records are projected to fall back."
                ),
            )
        )
    if not plan.fits:
        outcome: Outcome = "overflow"
    elif not translation.strip() or plan.fallback_indices:
        outcome = "fallback"
    else:
        outcome = "fits"
    return _result(
        format_name,
        outcome,
        checks,
        exact=exact,
        note="Shared-body projection uses the current corpus and is advisory.",
    )


def _current_event_dictionary() -> tuple[EventDictionary | None, str]:
    try:
        document = json.loads(_EVENT_CODEC_PATH.read_text(encoding="utf-8"))
        return (
            dictionary_from_manifest(document),
            "Uses the currently generated shared EVENT dictionary; a complete "
            "build may retrain it after this edit.",
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return (
            None,
            "No usable generated EVENT dictionary was available, so the projection "
            f"uses unpacked words ({error}).",
        )


def _indexed_words(
    source: IndexedWordsSource,
    document: list[dict[str, Any]],
    row_index: int,
    translation: str,
) -> dict[str, Any]:
    format_name = "indexed_words"
    exact = False
    try:
        original = source.input_path.read_bytes()
        _pointers, _sentinel, original_records, trailing = read_records(
            original, source
        )
        if len(document) != len(original_records):
            raise ValueError("corpus and indexed-word message counts differ")
        event_dictionary, codec_note = _current_event_dictionary()
        records = []
        for index, (row, words) in enumerate(zip(document, original_records)):
            candidate = translation if index == row_index else row["tr"]
            if candidate.strip():
                words = encode_indexed_words_message(
                    candidate,
                    source,
                    event_dictionary,
                )
            records.append(words)
        projected_message = records[row_index]
        body_words = sum(len(words) for words in records)
        capacity_words = (len(original) - source.body_offset - len(trailing)) // 2
    except (IndexError, KeyError, OSError, ValueError) as error:
        return _encoding_failure(format_name, error, exact=exact)
    checks = (
        _check(
            "message_words",
            exact=exact,
            used=len(projected_message),
            unit="words",
            message="Includes the message terminator.",
        ),
        _check(
            "shared_body_words",
            exact=exact,
            used=body_words,
            capacity=capacity_words,
            unit="words",
        ),
    )
    if body_words > capacity_words:
        outcome: Outcome = "overflow"
    elif not translation.strip():
        outcome = "fallback"
    else:
        outcome = "fits"
    return _result(
        format_name,
        outcome,
        checks,
        exact=exact,
        note=f"Shared-body projection is advisory. {codec_note}",
    )


_EVE_PROJECTION_LOCK = threading.Lock()


@lru_cache(maxsize=16384)
def _encode_eve_message_cached(
    source_key: str,
    original_words: tuple[int, ...],
    pages_json: str,
    event_dictionary: EventDictionary | None,
) -> tuple[int, ...] | None:
    """Encode one physical message, retaining unchanged messages across drafts."""

    source = _SOURCES_BY_CORPUS[source_key]
    pages = json.loads(pages_json)
    encoded = encode_eve_translation(
        source,
        original_words,
        pages,
        event_dictionary=event_dictionary,
    )
    return None if encoded is None else encoded.words


def _eve(
    source: EveSource,
    document: list[dict[str, Any]],
    row_index: int,
    translation: str,
) -> dict[str, Any]:
    # ThreadingHTTPServer can otherwise launch several identical cold whole-bank
    # projections.  Serializing this cache fill avoids GIL contention while warm
    # requests remain only a few milliseconds long.
    with _EVE_PROJECTION_LOCK:
        return _eve_locked(source, document, row_index, translation)


def _eve_locked(
    source: EveSource,
    document: list[dict[str, Any]],
    row_index: int,
    translation: str,
) -> dict[str, Any]:
    format_name = "eve"
    exact = False
    try:
        source_data = source.input_path.read_bytes()
        bank = extract_bank(source)
        proposed_rows = [
            {**row, "tr": translation} if index == row_index else row
            for index, row in enumerate(document)
        ]
        grouped = group_corpus_pages(proposed_rows)
        affected_messages = {
            location["message"] for location in document[row_index]["locations"]
        }
        event_dictionary, codec_note = _current_event_dictionary()
        projected_by_message: dict[int, tuple[int, ...]] = {}
        partial_messages: set[int] = set()
        layout_fallbacks: set[int] = set()
        for message in bank.messages:
            pages = grouped.get(message.index, [])
            translations = [page["tr"].strip() for page in pages]
            if translations and any(translations) and not all(translations):
                partial_messages.add(message.index)
                projected_by_message[message.index] = message.words
                continue
            if not translations or not all(translations):
                projected_by_message[message.index] = message.words
                continue
            encoded_words = _encode_eve_message_cached(
                source.corpus_path.as_posix(),
                message.words,
                json.dumps(
                    pages,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                event_dictionary,
            )
            if encoded_words is None:
                layout_fallbacks.add(message.index)
                projected_by_message[message.index] = message.words
            else:
                projected_by_message[message.index] = encoded_words
        body_size = sum(len(words) * 2 for words in projected_by_message.values())
        body_capacity = len(source_data) - source.body_offset
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        return _encoding_failure(format_name, error, exact=exact)

    checks = [
        *(
            _check(
                f"message_{message_index}_bytes",
                exact=exact,
                used=len(projected_by_message[message_index]) * 2,
                unit="bytes",
                message="Projected encoded size for an affected physical message.",
            )
            for message_index in sorted(affected_messages)
        ),
        _check(
            "shared_bank_bytes",
            exact=exact,
            used=body_size,
            capacity=body_capacity,
            unit="bytes",
        ),
    ]
    affected_fallbacks = affected_messages & (partial_messages | layout_fallbacks)
    if affected_fallbacks:
        checks.append(
            _check(
                "affected_message_fallbacks",
                exact=exact,
                used=len(affected_fallbacks),
                capacity=0,
                unit="messages",
                outcome="fallback",
                message=(
                    "Affected message(s) would retain source layout: "
                    + ", ".join(str(index) for index in sorted(affected_fallbacks))
                ),
            )
        )
    if body_size > body_capacity:
        outcome: Outcome = "overflow"
    elif not translation.strip() or affected_fallbacks:
        outcome = "fallback"
    else:
        outcome = "fits"
    return _result(
        format_name,
        outcome,
        checks,
        exact=exact,
        note=(
            "Whole-bank projection uses the current corpus and is advisory. "
            f"{codec_note}"
        ),
    )


def _runtime_ui(relative: str, translation: str) -> dict[str, Any]:
    format_name = "runtime_ui"
    translation = translation.strip()
    if not translation:
        return _blank(format_name, required=True)
    try:
        encoding = load_latin_encoding(FONT8_METRICS_PATH)
        glyphs = encoding.segment_glyphs(translation)
    except ValueError as error:
        return _encoding_failure(format_name, error)
    rendered_width = sum(glyph.advance for glyph in glyphs) + max(0, len(glyphs) - 1)
    check = _check(
        "rendered_width",
        exact=True,
        used=rendered_width,
        capacity=_RUNTIME_UI_WIDTHS[relative],
        unit="pixels",
        message="Includes the runtime renderer's one-pixel inter-glyph spacing.",
    )
    outcome: Outcome = "fits" if check["outcome"] == "fits" else "overflow"
    return _result(
        format_name,
        outcome,
        (check,),
        note="Uses the canonical generated FONT8 runtime width contract.",
    )


def analyze_capacity(
    file: str,
    pointer: Sequence[str | int],
    tr: str,
    *,
    corpus_root: Path = TEXT_CORPUS_ROOT,
) -> dict[str, Any]:
    """Return structured, write-free capacity checks for a proposed target value."""

    if not isinstance(tr, str):
        raise ValueError("proposed tr must be text")
    relative = _normalize_corpus_file(file, corpus_root)
    source: TextSource | None = _SOURCES_BY_CORPUS.get(relative)
    if source is None:
        if not isinstance(pointer, Sequence) or isinstance(pointer, (str, bytes)):
            raise ValueError("JSON pointer must be a sequence")
        if not all(isinstance(part, str) or type(part) is int for part in pointer):
            raise ValueError("JSON pointer components must be strings or integers")
        if relative in _RUNTIME_UI_WIDTHS:
            try:
                document = json.loads(
                    (corpus_root / Path(relative)).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"could not read corpus file {relative!r}: {error}"
                ) from error
            normalized_pointer, _row = _translation_pointer(
                document,
                pointer,
                require_array_row=False,
            )
            return {
                "file": relative,
                "pointer": list(normalized_pointer),
                "source": "engine_runtime_ui",
                **_runtime_ui(relative, tr),
            }
        unavailable = _unavailable(
            "unregistered",
            "No registered source model provides an exact capacity check for "
            f"{relative!r}.",
        )
        return {
            "file": relative,
            "pointer": list(pointer),
            "source": None,
            **unavailable,
        }
    corpus_path = corpus_root / Path(relative)
    try:
        document = json.loads(corpus_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read corpus file {relative!r}: {error}") from error
    normalized_pointer, row = _translation_pointer(document, pointer)
    row_index = normalized_pointer[0]
    assert isinstance(row_index, int)

    if isinstance(source, FixedBytesSource):
        analysis = _fixed_bytes(source, row, row_index, tr)
    elif isinstance(source, FixedHelpSource):
        analysis = _fixed_help(source, row_index, tr)
    elif isinstance(source, FixedWordsSource):
        analysis = _fixed_words(source, row, tr)
    elif isinstance(source, NameDescriptionSource):
        if not isinstance(document, list):
            raise ValueError("name-description corpus must be a JSON array")
        analysis = _name_description(source, document, normalized_pointer, tr)
    elif isinstance(source, MirroredWordsSource):
        analysis = _mirrored_words(source, row, tr)
    elif isinstance(source, DeduplicatedWordsSource):
        analysis = _deduplicated_words(source, row, tr)
    elif isinstance(source, AsciiFieldsSource):
        analysis = _ascii_fields(source, row, tr)
    elif isinstance(source, StaticOverlaySource):
        analysis = _static_overlay(source, row, tr)
    elif isinstance(source, IndexedBytesSource):
        if not isinstance(document, list):
            raise ValueError("indexed-byte corpus must be a JSON array")
        analysis = _indexed_bytes(source, document, row_index, tr)
    elif isinstance(source, IndexedWordsSource):
        if not isinstance(document, list):
            raise ValueError("indexed-word corpus must be a JSON array")
        analysis = _indexed_words(source, document, row_index, tr)
    elif isinstance(source, EveSource):
        if not isinstance(document, list):
            raise ValueError("EVE corpus must be a JSON array")
        analysis = _eve(source, document, row_index, tr)
    else:
        raise TypeError(f"unsupported text source {type(source).__name__}")

    return {
        "file": relative,
        "pointer": list(normalized_pointer),
        "source": source.name,
        **analysis,
    }


__all__ = ("Outcome", "analyze_capacity")
