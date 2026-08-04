import struct
from pathlib import Path

from text.script.codec.atlas import FONT16_GLYPHS
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.source_models import MirroredWordsSource

TERMINATOR = 0x8000


def load_existing(path: Path) -> dict[tuple[str, int], TranslationState]:
    rows = load_json_array(path)
    existing = {}
    for row_number, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {row_number} must be an object")
        table = row.get("table")
        index = row.get("index")
        if not isinstance(table, str) or not table:
            raise ValueError(f"{path}: row {row_number}.table must be nonempty text")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError(f"{path}: row {row_number}.index must be nonnegative")
        key = (table, index)
        if key in existing:
            raise ValueError(f"{path}: duplicate record {table}[{index}]")
        existing[key] = load_translation_state(row, f"{path}: row {row_number}")
    return existing


def visible_words(
    words: tuple[int, ...],
    terminator_mode: str,
    context: str,
) -> tuple[int, ...]:
    if terminator_mode == "required":
        if words.count(TERMINATOR) != 1:
            raise ValueError(f"{context}: expected exactly one terminator")
        end = words.index(TERMINATOR)
        if any(words[end + 1 :]):
            raise ValueError(f"{context}: nonzero data follows the terminator")
        return words[:end]
    if terminator_mode == "optional_full":
        if TERMINATOR not in words:
            if any(word == 0 for word in words):
                raise ValueError(f"{context}: unterminated record contains padding")
            return words
        if words.count(TERMINATOR) != 1:
            raise ValueError(f"{context}: expected at most one terminator")
        end = words.index(TERMINATOR)
        if any(words[end + 1 :]):
            raise ValueError(f"{context}: nonzero data follows the terminator")
        return words[:end]
    raise ValueError(f"{context}: unknown terminator mode {terminator_mode!r}")


def decode_words(words: tuple[int, ...], zero_mode: str) -> str:
    if zero_mode not in {"skip", "space", "newline"}:
        raise ValueError(f"unknown zero mode {zero_mode!r}")
    output = []
    pending_separator = False
    for word in words:
        if word == 0:
            pending_separator = bool(output) and zero_mode != "skip"
            continue
        if pending_separator:
            output.append("{n}" if zero_mode == "newline" else " ")
            pending_separator = False
        output.append(FONT16_GLYPHS.get(word, f"{{GLYPH:{word:04x}}}"))
    return "".join(output)


def extract_corpus(source: MirroredWordsSource, corpus_root: Path) -> list[dict]:
    existing = load_existing(corpus_root / source.corpus_path)
    files = {
        location.path: (source.extracted_root / location.path).read_bytes()
        for table in source.tables
        for location in table.locations
    }
    occupied: dict[Path, list[tuple[int, int]]] = {path: [] for path in files}
    rows = []
    for table in source.tables:
        if not table.locations:
            raise ValueError(f"{source.name}:{table.name}: table has no locations")
        for index in range(table.record_count):
            decoded = None
            reference_raw = None
            locations = []
            for location in table.locations:
                start = location.table_offset + index * location.words_per_record * 2
                end = start + location.words_per_record * 2
                data = files[location.path]
                context = f"{location.path}:{table.name}[{index}]"
                if start < 0 or end > len(data):
                    raise ValueError(f"{context}: record exceeds the file")
                if any(
                    start < other_end and other_start < end
                    for other_start, other_end in occupied[location.path]
                ):
                    raise ValueError(f"{context}: record overlaps another table")
                occupied[location.path].append((start, end))
                raw = data[start:end]
                words = struct.unpack(f">{location.words_per_record}H", raw)
                text = decode_words(
                    visible_words(words, table.terminator_mode, context),
                    table.zero_mode,
                )
                if decoded is None:
                    decoded = text
                    reference_raw = raw
                elif text != decoded:
                    raise ValueError(f"{context}: {text!r} != {decoded!r}")
                elif table.require_identical and raw != reference_raw:
                    raise ValueError(f"{context}: mirrored bytes differ")
                locations.append(
                    {
                        "source": location.path.as_posix(),
                        "file_offset": f"0x{start:x}",
                        "word_count": location.words_per_record,
                    }
                )
            assert decoded is not None
            rows.append(
                {
                    "table": table.name,
                    "index": index,
                    "locations": locations,
                    **translation_pair(
                        decoded,
                        existing.get((table.name, index)),
                    ),
                }
            )
    return rows
