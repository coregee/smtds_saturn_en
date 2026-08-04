import struct
from pathlib import Path

from text.script.codec.words import decode_words
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.source_models import FixedHelpSource

TERMINATOR = 0x8000


def load_existing(path: Path) -> dict[int, TranslationState]:
    rows = load_json_array(path)

    existing = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index} must be an object")
        raw_offset = row.get("file_offset")
        try:
            offset = int(raw_offset, 16)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{path}: row {index} has no hexadecimal file offset"
            ) from error
        if offset in existing:
            raise ValueError(f"{path}: duplicate file offset {offset:#x}")
        existing[offset] = load_translation_state(row, f"{path}: row {index}")
    return existing


def extract_corpus(source: FixedHelpSource, corpus_root: Path) -> list[dict]:
    data = source.input_path.read_bytes()
    expected_size = source.record_count * source.record_words * 2
    if len(data) != expected_size:
        raise ValueError(
            f"{source.path}: expected {expected_size} bytes, found {len(data)}"
        )

    existing = load_existing(corpus_root / source.corpus_path)
    rows = []
    for record in range(source.record_count):
        offset = record * source.record_words * 2
        words = struct.unpack_from(f">{source.record_words}H", data, offset)
        terminators = [index for index, word in enumerate(words) if word == TERMINATOR]
        if len(terminators) != 1:
            raise ValueError(
                f"{source.path}: record {record} has {len(terminators)} terminators"
            )
        end = terminators[0] + 1
        if any(words[end:]):
            raise ValueError(
                f"{source.path}: record {record} has data after its terminator"
            )
        rows.append(
            {
                "file_offset": f"0x{offset:04x}",
                "word_count": source.record_words,
                **translation_pair(
                    decode_words(words[:end], source.dialect),
                    existing.get(offset),
                ),
            }
        )
    return rows
