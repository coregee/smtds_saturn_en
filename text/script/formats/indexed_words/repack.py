import json
import struct
from pathlib import Path

from text.script.dialects import get_dialect
from text.script.encoding.event_codec import EventDictionary, base_token_runs
from text.script.encoding.latin import load_latin_encoding
from text.script.encoding.tokens import normalize_english
from text.script.formats.indexed_words.extract import extract_corpus, read_records
from text.script.formats.indexed_words.model import IndexedWordsResult
from text.script.source_models import IndexedWordsSource


def encode_message(
    text: str,
    source: IndexedWordsSource,
    event_dictionary: EventDictionary | None = None,
) -> tuple[int, ...]:
    encoding = load_latin_encoding()
    text = wrap_message(text, source, encoding)
    words = encoding.encode(
        text,
        get_dialect(source.dialect),
        pack_codes=(
            event_dictionary.encode_codes if event_dictionary is not None else None
        ),
    )
    if source.terminator in words:
        raise ValueError("message contains its terminator")
    return tuple((*words, source.terminator))


def wrap_message(text: str, source: IndexedWordsSource, encoding) -> str:
    if source.layout_width_pixels is None and source.layout_lines is None:
        return text
    if (
        source.layout_width_pixels is None
        or source.layout_lines is None
        or source.layout_width_pixels <= 0
        or source.layout_lines <= 0
    ):
        raise ValueError(f"{source.path}: incomplete indexed-word layout")

    dialect = get_dialect(source.dialect)

    def width(value: str) -> int:
        return encoding.measure(value, dialect, lambda _code: 0)

    # Existing BTL line breaks were placed for the stock 16px-cell renderer.
    # Reflow them with the translated FONT16 widths instead of treating them
    # as mandatory paragraph boundaries.
    lines = []
    current = ""
    for word in normalize_english(text).replace("\n", " ").split():
        if width(word) == 0:
            current += word
            continue
        candidate = word if not current else f"{current} {word}"
        if current and width(candidate) > source.layout_width_pixels:
            lines.append(current)
            current = word
        else:
            current = candidate
        if width(current) > source.layout_width_pixels:
            raise ValueError(
                f"{source.path}: word exceeds {source.layout_width_pixels}px: {word!r}"
            )
    if current:
        lines.append(current)

    if len(lines) > source.layout_lines:
        raise ValueError(
            f"{source.path}: message needs {len(lines)}/"
            f"{source.layout_lines} lines: {text!r}"
        )
    return "\n".join(lines)


def repack_indexed_words(
    source: IndexedWordsSource,
    corpus_root: Path,
    event_dictionary: EventDictionary | None = None,
) -> IndexedWordsResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )

    original = source.input_path.read_bytes()
    pointers, sentinel_offset, original_records, trailing = read_records(
        original, source
    )
    records = []
    translated = 0
    for index, (row, words) in enumerate(zip(rows, original_records)):
        translation = row["tr"]
        if translation.strip():
            try:
                words = encode_message(translation, source, event_dictionary)
            except ValueError as error:
                raise ValueError(
                    f"{source.path}: message {index}: {error}; text {translation!r}"
                ) from error
            translated += 1
        records.append(words)

    body_words = sum(len(words) for words in records)
    capacity_words = (len(original) - source.body_offset - len(trailing)) // 2
    if body_words > capacity_words:
        raise ValueError(
            f"{source.path}: rebuilt body uses {body_words}/{capacity_words} words"
        )

    output = bytearray(original)
    output[source.body_offset : len(original) - len(trailing)] = bytes(
        capacity_words * 2
    )
    if trailing:
        output[-len(trailing) :] = trailing

    position = 0
    for index, words in enumerate(records):
        struct.pack_into(">H", output, index * 2, position)
        struct.pack_into(
            f">{len(words)}H",
            output,
            source.body_offset + position * 2,
            *words,
        )
        position += len(words)
    struct.pack_into(">H", output, sentinel_offset, source.table_sentinel)

    rebuilt_pointers, rebuilt_sentinel, rebuilt_records, rebuilt_trailing = (
        read_records(bytes(output), source)
    )
    if rebuilt_sentinel != sentinel_offset or rebuilt_pointers != [
        sum(len(record) for record in records[:index]) for index in range(len(records))
    ]:
        raise ValueError(f"{source.path}: rebuilt pointer table is inconsistent")
    expected_trailing = bytes((capacity_words - body_words) * 2) + trailing
    if rebuilt_records != records or rebuilt_trailing != expected_trailing:
        raise ValueError(f"{source.path}: rebuilt records are inconsistent")
    if len(output) != len(original):
        raise ValueError(f"{source.path}: rebuilt file size changed")

    return IndexedWordsResult(
        data=bytes(output),
        messages=len(records),
        translated_messages=translated,
        body_words=body_words,
        body_capacity_words=capacity_words,
        free_words=capacity_words - body_words,
    )


def indexed_words_dictionary_sequences(
    source: IndexedWordsSource,
    corpus_root: Path,
) -> list[list[int]]:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )
    sequences = []
    for row in rows:
        translation = row["tr"]
        if translation.strip():
            sequences.extend(base_token_runs(encode_message(translation, source)))
    return sequences
