import json
import struct
from pathlib import Path

from project_paths import PROJECT_ROOT as TRANSLATION_ROOT
from text.script.codec.atlas import FONT16_ATLAS
from text.script.dialects import get_dialect
from text.script.encoding.latin import load_latin_encoding, pack_direct_codes
from text.script.encoding.tokens import normalize_english, parse_inline_tokens
from text.script.formats.name_description.extract import TERMINATOR, extract_corpus
from text.script.formats.name_description.model import NameDescriptionResult
from text.script.source_models import NameDescriptionSource

FONT8_METRICS_PATH = TRANSLATION_ROOT / "font" / "generated" / "font8_metrics.json"
NEWLINE = 0x8001
NAME_TERMINATOR = 0xFF


def encode_literal(text: str) -> list[int]:
    latin = load_latin_encoding()
    by_text = latin.by_text
    compounds = latin.compound_glyphs
    output = []
    direct = []

    def flush() -> None:
        if direct:
            output.extend(pack_direct_codes(direct))
            direct.clear()

    position = 0
    while position < len(text):
        compound = next(
            (
                (token, glyph)
                for token, glyph in compounds
                if text.startswith(token, position)
            ),
            None,
        )
        if compound is not None:
            token, glyph = compound
            direct.append(glyph.code)
            position += len(token)
            continue

        character = text[position]
        glyph = by_text.get(character)
        if glyph is not None:
            direct.append(glyph.code)
        else:
            flush()
            output.append(FONT16_ATLAS.index_for(character))
        position += 1
    flush()
    return output


def encode_description(text: str, source: NameDescriptionSource) -> tuple[int, ...]:
    dialect = get_dialect(source.dialect)
    output = []
    for line_index, line in enumerate(normalize_english(text).split("\n")):
        if line_index:
            output.append(NEWLINE)
        for part in parse_inline_tokens(line, dialect):
            if isinstance(part, int):
                output.append(part)
            else:
                output.extend(encode_literal(part))
    output.append(TERMINATOR)
    return tuple(output)


def free_ranges(data: bytes, source: NameDescriptionSource) -> list[list[int]]:
    capacity = (source.pointer_offset - source.description_offset) // 2
    ranges = []
    for record in range(source.record_count):
        base = record * source.record_size
        words = struct.unpack_from(
            f">{capacity}H",
            data,
            base + source.description_offset,
        )
        try:
            end = words.index(TERMINATOR)
        except ValueError as error:
            raise ValueError(
                f"{source.path}: record {record} has no terminator before its name pointer"
            ) from error
        start = base + source.description_offset + (end + 1) * 2
        stop = base + source.pointer_offset
        if any(data[start:stop]):
            raise ValueError(
                f"{source.path}: record {record} description padding is not empty"
            )
        if start < stop:
            ranges.append([start, stop])
    return ranges


def allocate(
    ranges: list[list[int]], payload: bytes, source: NameDescriptionSource
) -> int:
    for span in ranges:
        start, stop = span
        if stop - start >= len(payload):
            span[0] += len(payload)
            return start
    raise ValueError(
        f"{source.path}: description padding cannot fit a {len(payload)}-byte name"
    )


def repack_name_descriptions(
    source: NameDescriptionSource,
    corpus_root: Path,
) -> NameDescriptionResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )

    original = source.input_path.read_bytes()
    output = bytearray(original)
    capacity = (source.pointer_offset - source.description_offset) // 2
    requested_descriptions = 0
    translated_descriptions = 0
    description_fallbacks = 0
    longest_description = 0
    for record, row in enumerate(rows):
        translation = row["description"]["tr"].strip()
        if not translation:
            continue
        requested_descriptions += 1
        words = encode_description(translation, source)
        longest_description = max(longest_description, len(words))
        if len(words) > capacity:
            description_fallbacks += 1
            continue
        base = record * source.record_size + source.description_offset
        output[base : base + capacity * 2] = bytes(capacity * 2)
        struct.pack_into(f">{len(words)}H", output, base, *words)
        translated_descriptions += 1

    ranges = free_ranges(bytes(output), source)
    font8 = load_latin_encoding(FONT8_METRICS_PATH)
    requested_names = 0
    translated_names = 0
    name_fallbacks = 0
    longest_name = 0
    longest_name_pixels = 0
    packed_name_bytes = 0
    for record, row in enumerate(rows):
        record_base = record * source.record_size
        translation = row["name"]["tr"].strip()
        if translation:
            requested_names += 1
            normalized = normalize_english(translation)
            name_pixels = font8.measure_segment(normalized)
            encoded = bytes(font8.encode_segment(normalized))
            longest_name_pixels = max(longest_name_pixels, name_pixels)
            if (
                name_pixels > source.max_full_name_pixels
                or len(encoded) > source.max_full_name_bytes
            ):
                start = record_base + source.name_offset
                encoded = original[start : start + source.name_bytes].rstrip(b"\x00")
                name_fallbacks += 1
            else:
                translated_names += 1
        else:
            start = record_base + source.name_offset
            encoded = original[start : start + source.name_bytes].rstrip(b"\x00")
        if NAME_TERMINATOR in encoded:
            raise ValueError(
                f"{source.path}: name {record} contains terminator byte 0xff"
            )
        if len(encoded) > source.max_full_name_bytes:
            raise ValueError(f"{source.path}: original name {record} is too long")

        payload = encoded + bytes([NAME_TERMINATOR])
        offset = allocate(ranges, payload, source)
        output[offset : offset + len(payload)] = payload
        fallback = encoded[: source.name_bytes].ljust(source.name_bytes, b"\x00")
        name_start = record_base + source.name_offset
        output[name_start : name_start + source.name_bytes] = fallback
        struct.pack_into(">H", output, record_base + source.pointer_offset, offset)
        longest_name = max(longest_name, len(encoded))
        packed_name_bytes += len(payload)

    for record in range(source.record_count):
        base = record * source.record_size
        offset = struct.unpack_from(">H", output, base + source.pointer_offset)[0]
        if (
            offset >= len(output)
            or NAME_TERMINATOR
            not in output[offset : offset + source.max_full_name_bytes + 1]
        ):
            raise ValueError(
                f"{source.path}: invalid full-name pointer in record {record}"
            )

    return NameDescriptionResult(
        data=bytes(output),
        records=source.record_count,
        requested_names=requested_names,
        translated_names=translated_names,
        name_capacity_fallbacks=name_fallbacks,
        requested_descriptions=requested_descriptions,
        translated_descriptions=translated_descriptions,
        description_capacity_fallbacks=description_fallbacks,
        longest_name_bytes=longest_name,
        longest_name_pixels=longest_name_pixels,
        longest_description_words=longest_description,
        description_capacity_words=capacity,
        packed_name_bytes=packed_name_bytes,
        free_bytes=sum(stop - start for start, stop in ranges),
    )
