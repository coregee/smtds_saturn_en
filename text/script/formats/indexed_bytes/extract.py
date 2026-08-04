import struct
from pathlib import Path

from text.script.codec.atlas import FONT_ATLAS_PATH, FontAtlas, load_atlas
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.source_models import IndexedBytesSource


def read_pointers(
    data: bytes,
    source: IndexedBytesSource,
    *,
    body_offset: int | None = None,
) -> tuple[list[int], int]:
    body_offset = source.table_size if body_offset is None else body_offset
    if body_offset <= 0 or body_offset > len(data) or body_offset & 1:
        raise ValueError(f"{source.path}: invalid body offset {body_offset:#x}")

    pointers = []
    sentinel_offset = -1
    for offset in range(0, body_offset, 2):
        value = struct.unpack_from(">H", data, offset)[0]
        if value == source.table_sentinel:
            sentinel_offset = offset
            break
        pointers.append(value)

    if sentinel_offset < 0:
        raise ValueError(f"{source.path}: pointer table has no sentinel")
    if not pointers:
        raise ValueError(f"{source.path}: pointer table has no message pointers")
    if pointers[0] != 0 or pointers != sorted(pointers):
        raise ValueError(f"{source.path}: invalid pointer ordering")
    if body_offset + pointers[-1] >= len(data):
        raise ValueError(f"{source.path}: pointer body exceeds the file")
    return pointers, sentinel_offset


def read_message_spans(
    data: bytes,
    source: IndexedBytesSource,
    pointers: list[int],
    *,
    body_offset: int | None = None,
) -> tuple[list[tuple[int, int]], int]:
    """Return absolute message spans and the end of the managed body.

    Every table entry before the sentinel is a message start.  The next start
    bounds every message except the last, whose terminator supplies the only
    authoritative end boundary.  Bytes after that terminator are not part of
    the repackable body and must remain untouched.
    """
    body_offset = source.table_size if body_offset is None else body_offset
    starts = [body_offset + pointer for pointer in pointers]
    final_terminator = data.find(bytes((source.terminator,)), starts[-1])
    if final_terminator < 0:
        raise ValueError(
            f"{source.path}: final message lacks {source.terminator:02x} terminator"
        )
    body_end = final_terminator + 1
    return list(zip(starts, [*starts[1:], body_end])), body_end


def load_atlases(source: IndexedBytesSource) -> tuple[FontAtlas, FontAtlas]:
    primary = load_atlas(FONT_ATLAS_PATH / source.primary_atlas)
    secondary = load_atlas(FONT_ATLAS_PATH / source.secondary_atlas)
    return primary, secondary


def decode_message(
    raw: bytes,
    source: IndexedBytesSource,
    primary: FontAtlas,
    secondary: FontAtlas,
) -> str:
    if not raw or raw[-1] != source.terminator:
        raise ValueError(
            f"{source.path}: message lacks {source.terminator:02x} terminator"
        )
    if source.terminator in raw[:-1]:
        raise ValueError(f"{source.path}: message has an early terminator")

    named_controls = dict(source.named_controls)
    output = []
    for value in raw[:-1]:
        if value in named_controls:
            output.append(f"{{{named_controls[value]}}}")
        elif value in primary.by_index and value < source.secondary_base:
            output.append(primary.by_index[value])
        elif (
            source.secondary_base
            <= value
            < (source.secondary_base + source.secondary_glyphs)
            and value - source.secondary_base in secondary.by_index
        ):
            output.append(secondary.by_index[value - source.secondary_base])
        elif value < source.terminator:
            output.append(f"{{GLYPH:{value:02x}}}")
        else:
            output.append(f"{{OP:{value:02x}}}")
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


def extract_corpus(source: IndexedBytesSource, corpus_root: Path) -> list[dict]:
    data = source.input_path.read_bytes()
    pointers, _ = read_pointers(data, source)
    spans, _ = read_message_spans(data, source, pointers)
    primary, secondary = load_atlases(source)
    existing = load_existing(corpus_root / source.corpus_path)

    rows = []
    for index, (start, end) in enumerate(spans):
        raw = data[start:end]
        rows.append(
            {
                "index": index,
                "pointer_offset": f"0x{index * 2:04x}",
                "file_offset": f"0x{start:04x}",
                **translation_pair(
                    decode_message(raw, source, primary, secondary),
                    existing.get(index),
                ),
            }
        )
    return rows
