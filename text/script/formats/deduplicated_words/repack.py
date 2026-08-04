import json
import struct
from pathlib import Path

from text.script.encoding.latin import PACKED_TOKEN_BASE, load_latin_encoding
from text.script.formats.deduplicated_words.extract import (
    TERMINATOR,
    extract_corpus,
    load_layout,
    parse_hex,
)
from text.script.formats.deduplicated_words.model import DeduplicatedWordsResult
from text.script.patch_assets import PatchSpan, build_asset_json
from text.script.source_models import DeduplicatedWordsSource

PACKED_SPACE_WORD = PACKED_TOKEN_BASE << 8


def encode_record(translation: str, *, packed: bool, latin) -> tuple[int, ...]:
    return tuple(latin.encode_segment(translation, packed=packed))


def asset_json(
    source: DeduplicatedWordsSource,
    corpus_path: Path,
    result: DeduplicatedWordsResult,
) -> str:
    original = source.input_path.read_bytes()
    rows = load_layout(source.layout_input_path, source)
    return build_asset_json(
        source_path=source.path,
        original=original,
        replacement=result.data,
        corpus_relative=source.corpus_path,
        corpus_path=corpus_path,
        load_address=source.engine_load_address,
        spans=(
            PatchSpan(
                f"debug_{row['index']:03d}_{location_index}",
                parse_hex(location["file_offset"], "file offset"),
                location["word_count"] * 2,
            )
            for row in rows
            for location_index, location in enumerate(row["locations"])
        ),
    )


def repack_deduplicated_words(
    source: DeduplicatedWordsSource,
    corpus_root: Path,
) -> DeduplicatedWordsResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )
    output = bytearray(source.input_path.read_bytes())
    latin = load_latin_encoding()
    requested = 0
    translated = 0
    fallbacks = 0
    longest = 0
    physical = 0
    for row in rows:
        physical += len(row["locations"])
        translation = row["tr"].strip()
        if not translation:
            continue
        requested += 1
        try:
            words = encode_record(translation, packed=source.packed, latin=latin)
        except ValueError as error:
            raise ValueError(
                f"{source.path}: record {row['index']}: {error}; text {translation!r}"
            ) from error
        longest = max(longest, len(words))
        capacities = tuple(
            location["word_count"]
            - (parse_hex(location["boundary_word"], "boundary word") == TERMINATOR)
            for location in row["locations"]
        )
        if any(len(words) > capacity for capacity in capacities):
            fallbacks += 1
            continue
        for location in row["locations"]:
            start = parse_hex(location["file_offset"], "file offset")
            word_count = location["word_count"]
            boundary = parse_hex(location["boundary_word"], "boundary word")
            payload = words + (() if boundary != TERMINATOR else (TERMINATOR,))
            padding_word = PACKED_SPACE_WORD if source.packed else 0
            payload += (padding_word,) * (word_count - len(payload))
            struct.pack_into(f">{word_count}H", output, start, *payload)
        translated += 1
    return DeduplicatedWordsResult(
        data=bytes(output),
        records=len(rows),
        physical_fields=physical,
        requested_translations=requested,
        translated_records=translated,
        capacity_fallbacks=fallbacks,
        longest_words=longest,
    )
