import json
import struct
from pathlib import Path

from text.script.codec.atlas import FONT16_GLYPHS
from text.script.corpus_io import load_translation_state, translation_pair
from text.script.source_models import DeduplicatedWordsSource

TERMINATOR = 0x8000


def parse_hex(value: object, context: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError(f"{context}: expected 0x-prefixed hexadecimal text")
    try:
        return int(value, 16)
    except ValueError as error:
        raise ValueError(f"{context}: invalid hexadecimal value") from error


def kind_for(first_offset: int) -> str:
    if first_offset < 0x5454E:
        return "battle_test_actor"
    if first_offset <= 0x558C6:
        return "battle_test_or_fallback_message"
    return "battle_debug_field"


def decode_words(words: tuple[int, ...]) -> str:
    return "".join(FONT16_GLYPHS.get(word, f"{{GLYPH:{word:04x}}}") for word in words)


def load_layout(path: Path, source: DeduplicatedWordsSource) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != source.record_count:
        raise ValueError(f"{path}: expected {source.record_count} records")
    physical = 0
    seen_offsets = set()
    previous_first = -1
    for index, row in enumerate(rows):
        context = f"{path}: row {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        if set(row) != {"index", "kind", "locations"}:
            raise ValueError(
                f"{context} must contain exactly index, kind, and locations"
            )
        if row.get("index") != index:
            raise ValueError(f"{context}.index must be {index}")
        locations = row.get("locations")
        if not isinstance(locations, list) or not locations:
            raise ValueError(f"{context}.locations must be a nonempty array")
        parsed_offsets = []
        for location_index, location in enumerate(locations):
            location_context = f"{context}.locations[{location_index}]"
            if not isinstance(location, dict):
                raise ValueError(f"{location_context} must be an object")
            required_location = {"file_offset", "word_count", "boundary_word"}
            if set(location) != required_location:
                raise ValueError(
                    f"{location_context} must contain exactly "
                    "file_offset, word_count, and boundary_word"
                )
            offset = parse_hex(location.get("file_offset"), location_context)
            words = location.get("word_count")
            boundary = parse_hex(location.get("boundary_word"), location_context)
            if not isinstance(words, int) or isinstance(words, bool) or words <= 0:
                raise ValueError(f"{location_context}.word_count must be positive")
            if offset < source.region_start or offset + words * 2 > source.region_end:
                raise ValueError(
                    f"{location_context}: field exceeds the catalog region"
                )
            if offset in seen_offsets:
                raise ValueError(f"{location_context}: duplicate field address")
            seen_offsets.add(offset)
            parsed_offsets.append(offset)
            if boundary < 0 or boundary > 0xFFFF:
                raise ValueError(f"{location_context}: boundary is not a word")
        if parsed_offsets != sorted(parsed_offsets):
            raise ValueError(f"{context}: locations must be address ordered")
        if parsed_offsets[0] <= previous_first:
            raise ValueError(
                f"{context}: logical rows must follow first occurrence order"
            )
        expected_kind = kind_for(parsed_offsets[0])
        if row.get("kind") != expected_kind:
            raise ValueError(f"{context}.kind must be {expected_kind!r}")
        previous_first = parsed_offsets[0]
        physical += len(locations)
    if physical != source.physical_field_count:
        raise ValueError(
            f"{path}: expected {source.physical_field_count} physical fields, got {physical}"
        )
    return rows


def load_existing(path: Path, source: DeduplicatedWordsSource) -> dict[int, dict]:
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a JSON array")
    existing = {}
    for position, row in enumerate(rows):
        context = f"{path}: row {position}"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        index = row.get("index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < source.record_count
        ):
            raise ValueError(f"{context}.index is invalid")
        if index in existing:
            raise ValueError(f"{context}.index is duplicated")
        if not isinstance(row.get("jp"), str):
            raise ValueError(f"{context}.jp must be text")
        load_translation_state(row, context)
        if "note" in row and not isinstance(row["note"], str):
            raise ValueError(f"{context}.note must be text")
        existing[index] = row
    return existing


def extract_corpus(source: DeduplicatedWordsSource, corpus_root: Path) -> list[dict]:
    corpus_path = corpus_root / source.corpus_path
    layout = load_layout(source.layout_input_path, source)
    existing = load_existing(corpus_path, source)
    data = source.input_path.read_bytes()
    output = []
    occupied = []
    for index, row in enumerate(layout):
        decoded = None
        locations = []
        for location_index, location in enumerate(row["locations"]):
            start = parse_hex(location["file_offset"], "file offset")
            word_count = location["word_count"]
            boundary = parse_hex(location["boundary_word"], "boundary word")
            end = start + word_count * 2
            if any(
                start < other_end and other_start < end
                for other_start, other_end in occupied
            ):
                raise ValueError(
                    f"{source.path}:{start:#x}: field overlaps another location"
                )
            occupied.append((start, end))
            words = struct.unpack_from(f">{word_count}H", data, start)
            if boundary == TERMINATOR:
                if words[-1] != TERMINATOR:
                    raise ValueError(
                        f"{source.path}:{start:#x}: missing included terminator"
                    )
                visible = words[:-1]
            else:
                actual = int.from_bytes(data[end : end + 2], "big")
                if actual != boundary:
                    raise ValueError(
                        f"{source.path}:{start:#x}: boundary {actual:#06x} != {boundary:#06x}"
                    )
                visible = words
            text = decode_words(visible)
            if decoded is None:
                decoded = text
            elif text != decoded:
                raise ValueError(
                    f"{source.path}: record {index} mirror {location_index} differs"
                )
            locations.append(
                {
                    "file_offset": f"0x{start:x}",
                    "word_count": word_count,
                    "boundary_word": f"0x{boundary:04x}",
                }
            )
        assert decoded is not None
        prior = existing.get(index)
        retained = prior is not None and prior["jp"] == decoded
        record = {
            "index": index,
            "kind": row["kind"],
            "locations": locations,
            **translation_pair(
                decoded,
                load_translation_state(prior, f"{corpus_path}: row {index}")
                if retained
                else None,
            ),
        }
        if retained and "note" in prior:
            record["note"] = prior["note"]
        output.append(record)
    return output
