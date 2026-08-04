from pathlib import Path

from text.script.codec.atlas import FONT_ATLAS_PATH, load_atlas
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.source_models import FixedBytesSource


def load_existing(path: Path) -> dict[int, TranslationState]:
    rows = load_json_array(path)

    existing = {}
    for row_number, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {row_number} must be an object")
        record = row.get("record")
        if not isinstance(record, int) or isinstance(record, bool) or record < 0:
            raise ValueError(f"{path}: row {row_number}.record must be non-negative")
        if record in existing:
            raise ValueError(f"{path}: duplicate record {record}")
        existing[record] = load_translation_state(row, f"{path}: row {row_number}")
    return existing


def decode_field(raw: bytes, source: FixedBytesSource) -> str:
    atlas = load_atlas(FONT_ATLAS_PATH / source.atlas)
    raw = raw.rstrip(bytes([source.padding]))
    return "".join(atlas.by_index.get(value, f"{{GLYPH:{value:02x}}}") for value in raw)


def extract_corpus(source: FixedBytesSource, corpus_root: Path) -> list[dict]:
    data = source.input_path.read_bytes()
    expected_size = source.record_size * source.record_count
    if len(data) != expected_size:
        raise ValueError(
            f"{source.path}: expected {expected_size} bytes, found {len(data)}"
        )
    if source.field_offset + source.field_size > source.record_size:
        raise ValueError(f"{source.path}: text field exceeds its record")

    existing = load_existing(corpus_root / source.corpus_path)
    rows = []
    for record in range(source.record_count):
        offset = record * source.record_size + source.field_offset
        raw = data[offset : offset + source.field_size]
        rows.append(
            {
                "record": record,
                "file_offset": f"0x{offset:04x}",
                **translation_pair(decode_field(raw, source), existing.get(record)),
            }
        )
    return rows
