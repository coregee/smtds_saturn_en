from pathlib import Path

from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.source_models import AsciiFieldsSource


def load_existing(path: Path) -> dict[str, TranslationState]:
    rows = load_json_array(path)
    existing = {}
    for row_number, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {row_number} must be an object")
        kind = row.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"{path}: row {row_number}.kind must be nonempty text")
        if kind in existing:
            raise ValueError(f"{path}: duplicate kind {kind!r}")
        existing[kind] = load_translation_state(row, f"{path}: row {row_number}")
    return existing


def extract_corpus(source: AsciiFieldsSource, corpus_root: Path) -> list[dict]:
    data = source.input_path.read_bytes()
    existing = load_existing(corpus_root / source.corpus_path)
    rows = []
    occupied = []
    for field in source.fields:
        start = field.file_offset
        end = start + field.capacity
        if start < 0 or end > len(data):
            raise ValueError(f"{source.path}:{field.kind}: field exceeds the file")
        if any(
            start < other_end and other_start < end
            for other_start, other_end in occupied
        ):
            raise ValueError(
                f"{source.path}:{field.kind}: field overlaps another field"
            )
        occupied.append((start, end))
        raw = data[start:end]
        if 0 not in raw:
            raise ValueError(f"{source.path}:{field.kind}: field has no NUL terminator")
        terminator = raw.index(0)
        if any(raw[terminator + 1 :]):
            raise ValueError(
                f"{source.path}:{field.kind}: nonzero data follows its terminator"
            )
        try:
            japanese = raw[:terminator].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"{source.path}:{field.kind}: field is not ASCII"
            ) from error
        if not japanese:
            raise ValueError(f"{source.path}:{field.kind}: field is empty")
        row = {
            "kind": field.kind,
            "file_offset": f"0x{start:x}",
            "capacity_bytes": field.capacity,
        }
        if field.runtime_capacity is not None:
            row["runtime_capacity_bytes"] = field.runtime_capacity
        row.update(translation_pair(japanese, existing.get(field.kind)))
        rows.append(row)
    return rows
