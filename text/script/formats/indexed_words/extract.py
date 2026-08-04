import struct
from pathlib import Path

from text.script.codec.atlas import FONT16_GLYPHS
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.dialects import get_dialect
from text.script.source_models import IndexedWordsSource


def read_records(
    data: bytes,
    source: IndexedWordsSource,
) -> tuple[list[int], int, list[tuple[int, ...]], bytes]:
    if len(data) < source.body_offset or (len(data) - source.body_offset) % 2:
        raise ValueError(f"{source.path}: invalid file size {len(data)}")

    pointers = []
    sentinel_offset = -1
    for offset in range(0, source.body_offset, 2):
        value = struct.unpack_from(">H", data, offset)[0]
        if value == source.table_sentinel:
            sentinel_offset = offset
            break
        pointers.append(value)
    if sentinel_offset < 0:
        raise ValueError(f"{source.path}: pointer table has no sentinel")
    if not pointers or pointers[0] != 0 or pointers != sorted(set(pointers)):
        raise ValueError(f"{source.path}: invalid pointer ordering")

    body_words = (len(data) - source.body_offset) // 2
    if pointers[-1] >= body_words:
        raise ValueError(f"{source.path}: final pointer exceeds the body")

    records = []
    for index, start in enumerate(pointers):
        end = pointers[index + 1] if index + 1 < len(pointers) else body_words
        words = struct.unpack_from(
            f">{end - start}H",
            data,
            source.body_offset + start * 2,
        )
        if index + 1 < len(pointers):
            if (
                not words
                or words[-1] != source.terminator
                or source.terminator in words[:-1]
            ):
                raise ValueError(
                    f"{source.path}: message {index} has invalid terminator framing"
                )
            records.append(words)
            continue

        try:
            terminator = words.index(source.terminator)
        except ValueError as error:
            raise ValueError(
                f"{source.path}: final message has no terminator"
            ) from error
        records.append(words[: terminator + 1])
        trailing_offset = source.body_offset + (start + terminator + 1) * 2
        trailing = data[trailing_offset:]

    return pointers, sentinel_offset, records, trailing


def decode_message(words: tuple[int, ...], source: IndexedWordsSource) -> str:
    dialect = get_dialect(source.dialect)
    output = []
    for word in words[:-1]:
        if word == 0:
            continue
        if word & 0x8000:
            output.append(dialect.decode_control(word))
        else:
            output.append(FONT16_GLYPHS.get(word, f"{{GLYPH:{word:04x}}}"))
    return "".join(output)


def load_existing(path: Path) -> dict[int, TranslationState]:
    rows = load_json_array(path)
    existing = {}
    for row_number, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {row_number} must be an object")
        index = row.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError(f"{path}: row {row_number}.index must be non-negative")
        if index in existing:
            raise ValueError(f"{path}: duplicate message index {index}")
        existing[index] = load_translation_state(row, f"{path}: row {row_number}")
    return existing


def extract_corpus(source: IndexedWordsSource, corpus_root: Path) -> list[dict]:
    data = source.input_path.read_bytes()
    pointers, _, records, _ = read_records(data, source)
    existing = load_existing(corpus_root / source.corpus_path)
    return [
        {
            "index": index,
            "pointer_offset": f"0x{index * 2:04x}",
            "file_offset": f"0x{source.body_offset + start * 2:04x}",
            **translation_pair(decode_message(words, source), existing.get(index)),
        }
        for index, (start, words) in enumerate(zip(pointers, records))
    ]
