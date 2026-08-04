import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from text.script.formats.eve.extract import (
    extract_bank,
    extract_corpus,
    page_coordinates,
)
from text.script.formats.eve.model import EveBank
from text.script.source_models import EveSource


class EncodedMessage(Protocol):
    words: tuple[int, ...]
    runtime_requirements: frozenset


MessageEncoder = Callable[
    [EveSource, tuple[int, ...], list[dict]],
    EncodedMessage | None,
]


@dataclass(frozen=True)
class RepackCandidate:
    message: int
    pages: int
    words: tuple[int, ...]
    runtime_requirements: frozenset


@dataclass(frozen=True)
class EveRepackResult:
    data: bytes
    translated_messages: int
    translated_pages: int
    partial_messages: int
    layout_fallbacks: int
    body_size: int
    body_capacity: int
    runtime_requirements: frozenset


def load_validated_corpus(
    source: EveSource,
    corpus_root: Path,
) -> list[dict]:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    expected = extract_corpus(source, corpus_root)
    if rows != expected:
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )
    return rows


def expand_corpus_pages(rows: list[dict]) -> list[dict]:
    pages = []
    seen = set()
    for record_index, record in enumerate(rows):
        for location_index, location in enumerate(record["locations"]):
            coordinates = page_coordinates(
                location,
                f"EVE record {record_index} location {location_index}",
            )
            if coordinates in seen:
                raise ValueError(f"duplicate EVE page coordinates {coordinates}")
            seen.add(coordinates)
            pages.append(
                {
                    **location,
                    "jp": record["jp"],
                    "tr": record["tr"],
                }
            )
    return pages


def group_corpus_pages(records: list[dict]) -> dict[int, list[dict]]:
    grouped = {}
    for row in expand_corpus_pages(records):
        grouped.setdefault(row["message"], []).append(row)
    for message, pages in grouped.items():
        pages.sort(key=lambda row: row["page"])
        if [row["page"] for row in pages] != list(range(len(pages))):
            raise ValueError(f"EVE message {message} has non-contiguous corpus pages")
    return grouped


def validate_rebuilt_bank(
    source: EveSource,
    data: bytes,
    expected_words: list[tuple[int, ...]],
) -> EveBank:
    rebuilt = EveBank.parse(data, source.table_offset, source.body_offset)
    actual_words = [message.words for message in rebuilt.messages]
    if actual_words != expected_words:
        raise ValueError(f"{source.path}: rebuilt EVE messages did not round-trip")
    return rebuilt


def repack_eve(
    source: EveSource,
    corpus_root: Path,
    encode_message: MessageEncoder,
    message_indices: frozenset[int] | None = None,
) -> EveRepackResult:
    source_data = source.input_path.read_bytes()
    bank = extract_bank(source)
    if message_indices is not None:
        available = {message.index for message in bank.messages}
        unknown = sorted(message_indices - available)
        if unknown:
            raise ValueError(
                f"{source.path}: unknown message indices: "
                f"{', '.join(str(index) for index in unknown)}"
            )

    rows = load_validated_corpus(source, corpus_root)
    grouped = group_corpus_pages(rows)
    candidates = []
    partial_messages = 0
    layout_fallbacks = 0

    for message in bank.messages:
        if message_indices is not None and message.index not in message_indices:
            continue

        pages = grouped.get(message.index, [])
        translation_pages = [row["tr"].strip() for row in pages]
        if translation_pages and any(translation_pages) and not all(translation_pages):
            partial_messages += 1
            continue
        if not translation_pages or not all(translation_pages):
            continue

        encoded = encode_message(source, message.words, pages)
        if encoded is None:
            layout_fallbacks += 1
            continue
        candidates.append(
            RepackCandidate(
                message=message.index,
                pages=len(pages),
                words=encoded.words,
                runtime_requirements=encoded.runtime_requirements,
            )
        )

    body_capacity = len(source_data) - source.body_offset
    selected = {candidate.message: candidate for candidate in candidates}

    message_words = [
        selected[message.index].words if message.index in selected else message.words
        for message in bank.messages
    ]
    requested_body_size = sum(len(words) * 2 for words in message_words)
    if requested_body_size > body_capacity:
        raise ValueError(
            f"{source.path}: translated EVE body needs {requested_body_size} bytes; "
            f"capacity is {body_capacity} bytes. No translations were dropped."
        )
    if selected:
        output = bank.rebuild(source_data, message_words)
    else:
        output = source_data
    rebuilt = validate_rebuilt_bank(source, output, message_words)

    requirements = frozenset(
        requirement
        for candidate in selected.values()
        for requirement in candidate.runtime_requirements
    )
    return EveRepackResult(
        data=output,
        translated_messages=len(selected),
        translated_pages=sum(candidate.pages for candidate in selected.values()),
        partial_messages=partial_messages,
        layout_fallbacks=layout_fallbacks,
        body_size=rebuilt.body_size_bytes,
        body_capacity=body_capacity,
        runtime_requirements=requirements,
    )
