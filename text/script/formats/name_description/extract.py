import struct
from pathlib import Path

from text.script.codec.atlas import FONT8_GLYPHS, FONT16_GLYPHS
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.dialects import get_dialect
from text.script.source_models import NameDescriptionSource

TERMINATOR = 0x8000


def load_existing(path: Path) -> dict[int, dict[str, TranslationState]]:
    rows = load_json_array(path)

    existing = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index} must be an object")
        try:
            offset = int(row.get("file_offset"), 16)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{path}: row {index} has no hexadecimal file offset"
            ) from error
        if offset in existing:
            raise ValueError(f"{path}: duplicate file offset {offset:#x}")
        existing[offset] = {
            field: load_translation_state(
                row.get(field),
                f"{path}: row {index}.{field}",
            )
            for field in ("name", "description")
        }
    return existing


def decode_name(raw: bytes) -> str:
    return "".join(
        FONT8_GLYPHS.get(code, f"{{{code:02x}}}") for code in raw.rstrip(b"\x00")
    )


def decode_description(words: tuple[int, ...], source: NameDescriptionSource) -> str:
    dialect = get_dialect(source.dialect)
    output = []
    for word in words:
        if word == 0:
            output.append(" ")
        elif word & 0x8000:
            output.append(dialect.decode_control(word))
        else:
            output.append(FONT16_GLYPHS.get(word, f"{{{word:03x}}}"))
    return "".join(output).rstrip()


def extract_corpus(source: NameDescriptionSource, corpus_root: Path) -> list[dict]:
    data = source.input_path.read_bytes()
    expected_size = source.record_count * source.record_size
    if len(data) != expected_size:
        raise ValueError(
            f"{source.path}: expected {expected_size} bytes, found {len(data)}"
        )
    description_end = source.description_offset + source.description_words * 2
    if description_end > source.record_size:
        raise ValueError(f"{source.path}: description field exceeds its record")

    existing = load_existing(corpus_root / source.corpus_path)
    rows = []
    for record in range(source.record_count):
        offset = record * source.record_size
        name_start = offset + source.name_offset
        raw_name = data[name_start : name_start + source.name_bytes]
        words = struct.unpack_from(
            f">{source.description_words}H",
            data,
            offset + source.description_offset,
        )
        if words.count(TERMINATOR) != 1:
            raise ValueError(
                f"{source.path}: record {record} needs exactly one description terminator"
            )
        end = words.index(TERMINATOR)
        if any(words[end + 1 :]):
            raise ValueError(
                f"{source.path}: record {record} has data after its description terminator"
            )

        old_row = existing.get(offset)
        rows.append(
            {
                "file_offset": f"0x{offset:04x}",
                "name": translation_pair(
                    decode_name(raw_name),
                    old_row["name"] if old_row else None,
                ),
                "description": translation_pair(
                    decode_description(words[:end], source),
                    old_row["description"] if old_row else None,
                ),
            }
        )
    return rows
