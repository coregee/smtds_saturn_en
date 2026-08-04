import json
import struct
from pathlib import Path

from text.script.encoding.latin import load_latin_encoding
from text.script.formats.mirrored_words.extract import TERMINATOR, extract_corpus
from text.script.formats.mirrored_words.model import (
    MirroredWordsOutput,
    MirroredWordsResult,
)
from text.script.patch_assets import PatchSpan, build_asset_json
from text.script.source_models import MirroredWordsSource


def asset_path(source: MirroredWordsSource, output: MirroredWordsOutput) -> Path:
    return Path("mirrored_words") / source.name / f"{output.path.name}.json"


def asset_json(
    source: MirroredWordsSource,
    output: MirroredWordsOutput,
    corpus_path: Path,
) -> str:
    if output.engine_load_address is None:
        raise ValueError(f"{output.path}: is not an engine-managed source")
    original = (source.extracted_root / output.path).read_bytes()
    return build_asset_json(
        source_path=output.path,
        original=original,
        replacement=output.data,
        corpus_relative=source.corpus_path,
        corpus_path=corpus_path,
        load_address=output.engine_load_address,
        spans=(
            PatchSpan(
                f"{table.name}_{index:03d}",
                location.table_offset + index * location.words_per_record * 2,
                location.words_per_record * 2,
            )
            for table in source.tables
            for location in table.locations
            if location.path == output.path
            for index in range(table.record_count)
        ),
    )


def encode_translation(text: str, zero_mode: str) -> tuple[int, ...]:
    parts = tuple(text.split("{n}"))
    if zero_mode != "newline" and len(parts) != 1:
        raise ValueError("newlines are not supported by this table")
    latin = load_latin_encoding()
    encoded = tuple(tuple(latin.encode_segment(part)) for part in parts)
    return tuple(
        word
        for index, part in enumerate(encoded)
        for word in ((*(() if index == 0 else (0,)), *part))
    )


def encode_record(
    words: tuple[int, ...],
    word_count: int,
    terminator_mode: str,
) -> tuple[int, ...] | None:
    if terminator_mode == "required":
        payload = words + (TERMINATOR,)
        if len(payload) > word_count:
            return None
    elif terminator_mode == "optional_full":
        if len(words) > word_count:
            return None
        payload = words if len(words) == word_count else words + (TERMINATOR,)
    else:
        raise ValueError(f"unknown terminator mode {terminator_mode!r}")
    return payload + (0,) * (word_count - len(payload))


def repack_mirrored_words(
    source: MirroredWordsSource,
    corpus_root: Path,
) -> MirroredWordsResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )

    originals = {
        location.path: (source.extracted_root / location.path).read_bytes()
        for table in source.tables
        for location in table.locations
    }
    outputs = {path: bytearray(data) for path, data in originals.items()}
    load_addresses = {
        location.path: location.engine_load_address
        for table in source.tables
        for location in table.locations
    }
    rows_by_key = {(row["table"], row["index"]): row for row in rows}
    requested = 0
    translated = 0
    fallbacks = 0
    runtime_fallbacks = 0
    runtime_requirements = set()
    longest = 0

    for table in source.tables:
        for index in range(table.record_count):
            translation = rows_by_key[(table.name, index)]["tr"].strip()
            if not translation:
                continue
            requested += 1
            try:
                words = encode_translation(translation, table.zero_mode)
            except ValueError as error:
                raise ValueError(
                    f"{source.name}:{table.name}[{index}]: {error}; "
                    f"text {translation!r}"
                ) from error
            longest = max(longest, len(words) + (table.terminator_mode == "required"))
            encoded = [
                encode_record(words, location.words_per_record, table.terminator_mode)
                for location in table.locations
            ]
            if any(record is None for record in encoded):
                requirements = table.runtime_requirements_for_capacity_fallback(index)
                if not requirements:
                    fallbacks += 1
                else:
                    missing = requirements - source.runtime_requirements
                    if missing:
                        names = ", ".join(sorted(item.value for item in missing))
                        raise ValueError(
                            f"{source.name}:{table.name}[{index}]: runtime-covered "
                            f"capacity fallback requirements are not emitted by the "
                            f"source: {names}"
                        )
                    runtime_fallbacks += 1
                    runtime_requirements.update(requirements)
                continue
            for location, record in zip(table.locations, encoded, strict=True):
                assert record is not None
                start = location.table_offset + index * location.words_per_record * 2
                struct.pack_into(
                    f">{location.words_per_record}H",
                    outputs[location.path],
                    start,
                    *record,
                )
            translated += 1

    return MirroredWordsResult(
        outputs=tuple(
            MirroredWordsOutput(path, bytes(data), load_addresses[path])
            for path, data in outputs.items()
        ),
        records=sum(table.record_count for table in source.tables),
        requested_translations=requested,
        translated_records=translated,
        capacity_fallbacks=fallbacks,
        runtime_covered_capacity_fallbacks=runtime_fallbacks,
        runtime_requirements=frozenset(runtime_requirements),
        longest_words=longest,
    )
