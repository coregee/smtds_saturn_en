import json
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class IndexedBytesPlan:
    """Read-only result of planning an indexed-byte rebuild."""

    original: bytes
    sentinel_offset: int
    original_body_end: int
    output_body_offset: int
    projected_messages: tuple[bytes, ...]
    final_messages: tuple[bytes, ...]
    requested_indices: frozenset[int]
    retained_indices: frozenset[int]
    fallback_indices: tuple[int, ...]
    body_capacity: int
    projected_body_size: int
    body_size: int

    @property
    def fits(self) -> bool:
        return self.body_size <= self.body_capacity

    @property
    def body(self) -> bytes:
        return b"".join(self.final_messages)


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


def plan_encoded_messages(
    *,
    original: bytes,
    sentinel_offset: int,
    original_body_end: int,
    output_body_offset: int,
    original_messages: Sequence[bytes],
    projected_messages: Sequence[bytes],
    requested_indices: frozenset[int],
    body_capacity: int,
) -> IndexedBytesPlan:
    """Choose deterministic capacity fallbacks for already encoded messages."""
    if len(original_messages) != len(projected_messages):
        raise ValueError("original and projected message counts differ")
    if any(not 0 <= index < len(projected_messages) for index in requested_indices):
        raise ValueError("requested translation index is outside the message table")

    final_messages = list(projected_messages)
    retained_indices = set(requested_indices)
    body_size = sum(map(len, projected_messages))
    projected_body_size = body_size
    fallback_indices = []
    if body_size > body_capacity:
        candidates = sorted(
            (
                (
                    len(projected_messages[index]) - len(original_messages[index]),
                    index,
                )
                for index in requested_indices
                if len(projected_messages[index]) > len(original_messages[index])
            ),
            key=lambda item: (-item[0], item[1]),
        )
        for savings, index in candidates:
            final_messages[index] = original_messages[index]
            retained_indices.remove(index)
            body_size -= savings
            fallback_indices.append(index)
            if body_size <= body_capacity:
                break

    return IndexedBytesPlan(
        original=original,
        sentinel_offset=sentinel_offset,
        original_body_end=original_body_end,
        output_body_offset=output_body_offset,
        projected_messages=tuple(projected_messages),
        final_messages=tuple(final_messages),
        requested_indices=requested_indices,
        retained_indices=frozenset(retained_indices),
        fallback_indices=tuple(fallback_indices),
        body_capacity=body_capacity,
        projected_body_size=projected_body_size,
        body_size=body_size,
    )


def plan_indexed_bytes(
    source: IndexedBytesSource,
    rows: Sequence[Mapping[str, Any]],
    *,
    translation_overrides: Mapping[int, str] | None = None,
) -> IndexedBytesPlan:
    """Parse and encode an indexed-byte source without writing rebuilt data."""
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

    original_messages = tuple(original[start:end] for start, end in spans)
    if len(rows) != len(original_messages):
        raise ValueError(
            f"{source.path}: corpus and indexed-byte message counts differ"
        )

    primary, secondary = load_atlases(source)
    overrides = {} if translation_overrides is None else translation_overrides
    projected_messages = []
    requested_indices = set()
    for index, (row, raw) in enumerate(zip(rows, original_messages)):
        translation = overrides[index] if index in overrides else row["tr"]
        if translation.strip():
            try:
                raw = encode_message(translation, source, primary, secondary)
            except ValueError as error:
                raise ValueError(
                    f"{source.path}: message {index}: {error}; text {translation!r}"
                ) from error
            requested_indices.add(index)
        projected_messages.append(raw)

    capacity = original_body_end - output_body_offset
    if capacity <= 0:
        raise ValueError(
            f"{source.path}: repacked body at {output_body_offset:#x} has no capacity"
        )
    return plan_encoded_messages(
        original=original,
        sentinel_offset=sentinel_offset,
        original_body_end=original_body_end,
        output_body_offset=output_body_offset,
        original_messages=original_messages,
        projected_messages=projected_messages,
        requested_indices=frozenset(requested_indices),
        body_capacity=capacity,
    )


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

    plan = plan_indexed_bytes(source, rows)
    body = plan.body
    if not plan.fits:
        raise ValueError(
            f"{source.path}: rebuilt body uses "
            f"{plan.body_size}/{plan.body_capacity} bytes"
        )

    output = bytearray(plan.original)
    output[plan.output_body_offset : plan.original_body_end] = bytes(plan.body_capacity)
    output[plan.output_body_offset : plan.output_body_offset + len(body)] = body

    offset = 0
    rebuilt_offsets = []
    for index, message in enumerate(plan.final_messages):
        rebuilt_offsets.append(offset)
        struct.pack_into(">H", output, index * 2, offset)
        offset += len(message)
    struct.pack_into(">H", output, plan.sentinel_offset, source.table_sentinel)

    rebuilt_pointers, rebuilt_sentinel = read_pointers(
        bytes(output), source, body_offset=plan.output_body_offset
    )
    _, rebuilt_body_end = read_message_spans(
        bytes(output),
        source,
        rebuilt_pointers,
        body_offset=plan.output_body_offset,
    )
    if (
        rebuilt_sentinel != plan.sentinel_offset
        or rebuilt_pointers != rebuilt_offsets
        or rebuilt_body_end != plan.output_body_offset + len(body)
    ):
        raise ValueError(f"{source.path}: rebuilt pointer table is inconsistent")
    if len(output) != len(plan.original):
        raise ValueError(f"{source.path}: rebuilt file size changed")

    return IndexedBytesResult(
        data=bytes(output),
        messages=len(plan.final_messages),
        requested_translations=len(plan.requested_indices),
        translated_messages=len(plan.retained_indices),
        capacity_fallbacks=len(plan.fallback_indices),
        body_offset=plan.output_body_offset,
        body_size=plan.body_size,
        body_capacity=plan.body_capacity,
        free_bytes=plan.body_capacity - plan.body_size,
    )
