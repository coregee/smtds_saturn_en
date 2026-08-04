import json
import struct
from pathlib import Path

from text.script.dialects import DialectSpec, get_dialect
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.fixed_words.extract import extract_corpus
from text.script.formats.fixed_words.model import FixedWordsResult, RuntimeFixedWords
from text.script.patch_assets import PatchSpan, build_asset_json
from text.script.source_models import FixedWordsSource

INSERT_TOKEN = "{insert}"
PACKED_INSERT_WORD = 0xFFF0


def encode_fixed_text(
    translation: str,
    *,
    packed: bool,
    zero_mode: str,
    latin,
    dialect: DialectSpec | None = None,
) -> tuple[int, ...]:
    """Encode a fixed field, including the MAZE runtime insertion marker."""

    def encode_part(part: str) -> tuple[int, ...]:
        if dialect is None:
            return tuple(latin.encode_segment(part, packed=packed))
        return tuple(latin.encode(part, dialect, packed=packed))

    if INSERT_TOKEN not in translation:
        parts = tuple(translation.split("{n}"))
        if zero_mode != "newline" and len(parts) != 1:
            raise ValueError("newlines are not supported by this field")
        encoded_parts = tuple(encode_part(part) for part in parts)
        return tuple(
            word
            for index, part in enumerate(encoded_parts)
            for word in ((*(() if index == 0 else (0,)), *part))
        )

    if not packed:
        raise ValueError(f"{INSERT_TOKEN} requires a packed fixed-word field")
    if translation.count(INSERT_TOKEN) != 1:
        raise ValueError(f"exactly one {INSERT_TOKEN} is required")
    if "{n}" in translation:
        raise ValueError(f"{INSERT_TOKEN} cannot be combined with newlines")

    prefix, suffix = translation.split(INSERT_TOKEN)
    return (
        *encode_part(prefix),
        PACKED_INSERT_WORD,
        *encode_part(suffix),
    )


def asset_json(
    source: FixedWordsSource,
    corpus_path: Path,
    result: FixedWordsResult,
) -> str:
    if source.engine_load_address is None:
        raise ValueError(f"{source.path}: is not an engine-managed source")
    original = source.input_path.read_bytes()
    return build_asset_json(
        source_path=source.path,
        original=original,
        replacement=result.data,
        corpus_relative=source.corpus_path,
        corpus_path=corpus_path,
        load_address=source.engine_load_address,
        spans=(
            PatchSpan(field.kind, field.file_offset, field.word_count * 2)
            for field in source.fields
        ),
        extra={
            "runtime_fields": [
                {
                    "name": field.kind,
                    "file_offset": f"0x{field.file_offset:x}",
                    "word_count": len(field.words),
                    "words_hex": struct.pack(
                        f">{len(field.words)}H",
                        *field.words,
                    ).hex(),
                }
                for field in result.runtime_fields
            ],
        }
        if result.runtime_fields
        else None,
    )


def repack_fixed_words(
    source: FixedWordsSource,
    corpus_root: Path,
) -> FixedWordsResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )

    original = source.input_path.read_bytes()
    output = bytearray(original)
    latin = load_latin_encoding()
    requested = 0
    translated = 0
    fallbacks = 0
    longest = 0
    runtime_fields = []
    rows_by_kind = {row["kind"]: row for row in rows}

    for field in source.fields:
        if (
            field.runtime_word_count is not None
            and field.runtime_word_count < field.word_count
        ):
            raise ValueError(
                f"{source.path}:{field.kind}: runtime capacity "
                f"{field.runtime_word_count} is smaller than native capacity "
                f"{field.word_count}"
            )
        translation = rows_by_kind[field.kind]["tr"].strip()
        if not translation:
            continue
        requested += 1
        try:
            words = encode_fixed_text(
                translation,
                packed=source.packed,
                zero_mode=field.zero_mode,
                latin=latin,
                dialect=(
                    get_dialect(source.dialect) if source.dialect is not None else None
                ),
            )
        except ValueError as error:
            raise ValueError(
                f"{source.path}:{field.kind}: {error}; text {translation!r}"
            ) from error
        payload = words + (() if field.terminator is None else (field.terminator,))
        longest = max(longest, len(payload))
        capacity = field.runtime_word_count or field.word_count
        if len(payload) > capacity:
            fallbacks += 1
            continue
        if field.runtime_word_count is not None:
            runtime_fields.append(
                RuntimeFixedWords(
                    kind=field.kind,
                    file_offset=field.file_offset,
                    words=payload,
                )
            )
        if len(payload) <= field.word_count:
            padded = payload + (0,) * (field.word_count - len(payload))
            struct.pack_into(
                f">{field.word_count}H",
                output,
                field.file_offset,
                *padded,
            )
        translated += 1

    return FixedWordsResult(
        data=bytes(output),
        records=len(source.fields),
        requested_translations=requested,
        translated_records=translated,
        capacity_fallbacks=fallbacks,
        longest_words=longest,
        runtime_fields=tuple(runtime_fields),
    )
