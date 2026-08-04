import json
import re
import struct
from pathlib import Path

from text.script.codec.atlas import FontAtlas
from text.script.formats.indexed_bytes.extract import (
    extract_corpus,
    load_atlases,
    read_message_spans,
    read_pointers,
)
from text.script.formats.indexed_bytes.model import IndexedBytesResult
from text.script.source_models import IndexedBytesSource

CONTROL_TOKEN = re.compile(r"\{(?:(OP|GLYPH):([0-9a-fA-F]{2})|([A-Za-z0-9_]+))\}")


def encoding_map(
    source: IndexedBytesSource,
    primary: FontAtlas,
    secondary: FontAtlas,
) -> dict[str, int]:
    mapping = {
        text: index
        for text, index in primary.by_text.items()
        if index < source.secondary_base
    }
    for text, index in secondary.by_text.items():
        if index < source.secondary_glyphs:
            mapping.setdefault(text, source.secondary_base + index)
    return mapping


def encode_message(
    text: str,
    source: IndexedBytesSource,
    primary: FontAtlas,
    secondary: FontAtlas,
) -> bytes:
    glyphs = encoding_map(source, primary, secondary)
    compounds = tuple(sorted(glyphs, key=lambda value: (-len(value), value)))
    controls = {name: value for value, name in source.named_controls}
    output = bytearray()
    position = 0

    while position < len(text):
        token = CONTROL_TOKEN.match(text, position)
        if token is not None:
            if token.group(1) is not None:
                kind = token.group(1)
                value = int(token.group(2), 16)
                if kind == "GLYPH" and value >= source.terminator:
                    raise ValueError(f"glyph byte {value:02x} is in the control range")
                if kind == "OP" and value < source.terminator:
                    raise ValueError(f"control byte {value:02x} is in the glyph range")
            else:
                name = token.group(3)
                try:
                    value = controls[name]
                except KeyError as error:
                    raise ValueError(f"unknown control token {{{name}}}") from error
            if value == source.terminator:
                raise ValueError("a message cannot contain its terminator")
            output.append(value)
            position = token.end()
            continue

        match = next(
            (glyph for glyph in compounds if text.startswith(glyph, position)),
            None,
        )
        if match is None:
            raise ValueError(
                f"unsupported character at {position}: {text[position : position + 8]!r}"
            )
        output.append(glyphs[match])
        position += len(match)

    output.append(source.terminator)
    return bytes(output)


def repack_indexed_bytes(
    source: IndexedBytesSource,
    corpus_root: Path,
) -> IndexedBytesResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )

    original = source.input_path.read_bytes()
    pointers, sentinel_offset = read_pointers(original, source)
    spans, original_body_end = read_message_spans(original, source, pointers)
    output_body_offset = source.output_body_offset
    if output_body_offset < sentinel_offset + 2:
        raise ValueError(
            f"{source.path}: repacked body at {output_body_offset:#x} overlaps "
            "the pointer table"
        )
    if output_body_offset & 1:
        raise ValueError(
            f"{source.path}: repacked body offset must be even: {output_body_offset:#x}"
        )
    primary, secondary = load_atlases(source)
    original_messages = [original[start:end] for start, end in spans]

    messages = []
    requested = 0
    translated_indices = set()
    for index, (row, raw) in enumerate(zip(rows, original_messages)):
        translation = row["tr"]
        if translation.strip():
            requested += 1
            try:
                raw = encode_message(translation, source, primary, secondary)
            except ValueError as error:
                raise ValueError(
                    f"{source.path}: message {index}: {error}; text {translation!r}"
                ) from error
            translated_indices.add(index)
        messages.append(raw)

    capacity = original_body_end - output_body_offset
    if capacity <= 0:
        raise ValueError(
            f"{source.path}: repacked body at {output_body_offset:#x} has no capacity"
        )
    body_size = sum(map(len, messages))
    fallbacks = 0
    if body_size > capacity:
        candidates = sorted(
            (
                (len(messages[index]) - len(original_messages[index]), index)
                for index in translated_indices
                if len(messages[index]) > len(original_messages[index])
            ),
            key=lambda item: (-item[0], item[1]),
        )
        for savings, index in candidates:
            messages[index] = original_messages[index]
            translated_indices.remove(index)
            body_size -= savings
            fallbacks += 1
            if body_size <= capacity:
                break
    body = b"".join(messages)
    if len(body) > capacity:
        raise ValueError(
            f"{source.path}: rebuilt body uses {len(body)}/{capacity} bytes"
        )

    output = bytearray(original)
    output[output_body_offset:original_body_end] = bytes(capacity)
    output[output_body_offset : output_body_offset + len(body)] = body

    offset = 0
    rebuilt_offsets = []
    for index, message in enumerate(messages):
        rebuilt_offsets.append(offset)
        struct.pack_into(">H", output, index * 2, offset)
        offset += len(message)
    struct.pack_into(">H", output, sentinel_offset, source.table_sentinel)

    rebuilt_pointers, rebuilt_sentinel = read_pointers(
        bytes(output), source, body_offset=output_body_offset
    )
    _, rebuilt_body_end = read_message_spans(
        bytes(output),
        source,
        rebuilt_pointers,
        body_offset=output_body_offset,
    )
    if (
        rebuilt_sentinel != sentinel_offset
        or rebuilt_pointers != rebuilt_offsets
        or rebuilt_body_end != output_body_offset + len(body)
    ):
        raise ValueError(f"{source.path}: rebuilt pointer table is inconsistent")
    if len(output) != len(original):
        raise ValueError(f"{source.path}: rebuilt file size changed")

    return IndexedBytesResult(
        data=bytes(output),
        messages=len(messages),
        requested_translations=requested,
        translated_messages=len(translated_indices),
        capacity_fallbacks=fallbacks,
        body_offset=output_body_offset,
        body_size=len(body),
        body_capacity=capacity,
        free_bytes=capacity - len(body),
    )
