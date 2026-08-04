import struct
from pathlib import Path

from text.script.codec.atlas import FONT16_GLYPHS
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.source_models import FixedWordsSource


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


def visible_words(
    words: tuple[int, ...],
    terminator: int | None,
    context: str,
) -> tuple[int, ...]:
    if terminator is None:
        return words
    if words.count(terminator) != 1:
        raise ValueError(f"{context}: expected exactly one terminator")
    end = words.index(terminator)
    if any(words[end + 1 :]):
        raise ValueError(f"{context}: nonzero data follows the terminator")
    return words[:end]


def decode_words(words: tuple[int, ...], zero_mode: str) -> str:
    if zero_mode not in {"space", "skip", "newline"}:
        raise ValueError(f"unknown zero mode {zero_mode!r}")
    output = []
    pending_separator = False
    for word in words:
        if word == 0:
            pending_separator = bool(output) and zero_mode != "skip"
            continue
        if pending_separator:
            output.append(" " if zero_mode == "space" else "{n}")
            pending_separator = False
        output.append(FONT16_GLYPHS.get(word, f"{{GLYPH:{word:04x}}}"))
    return "".join(output)


def extract_corpus(source: FixedWordsSource, corpus_root: Path) -> list[dict]:
    data = source.input_path.read_bytes()
    existing = load_existing(corpus_root / source.corpus_path)
    rows = []
    occupied = []
    for field in source.fields:
        start = field.file_offset
        end = start + field.word_count * 2
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
        words = struct.unpack_from(f">{field.word_count}H", data, start)
        visible = visible_words(
            words,
            field.terminator,
            f"{source.path}:{field.kind}",
        )
        rows.append(
            {
                "kind": field.kind,
                "file_offset": f"0x{start:x}",
                "word_count": field.word_count,
                **translation_pair(
                    decode_words(visible, field.zero_mode),
                    existing.get(field.kind),
                ),
            }
        )
    return rows
