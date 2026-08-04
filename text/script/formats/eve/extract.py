from collections import defaultdict
from pathlib import Path

from text.script.codec.words import decode_words
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.formats.eve.model import EveBank
from text.script.formats.eve.pages import split_pages
from text.script.formats.eve.readers import find_raw_u16_messages
from text.script.profiles import TextReader, profile_for_reader
from text.script.source_models import EveSource


def extract_bank(source: EveSource) -> EveBank:
    data = source.input_path.read_bytes()
    bank = EveBank.parse(
        data,
        table_offset=source.table_offset,
        body_offset=source.body_offset,
    )
    original_body = data[source.body_offset : source.body_offset + bank.body_size_bytes]
    if bank.body_bytes() != original_body:
        raise ValueError(f"{source.path}: parsed messages do not reconstruct the body")
    return bank


PageCoordinates = tuple[int, int, int]


def corpus_record(
    japanese: str,
    state: TranslationState | None = None,
    *,
    note: str | None = None,
) -> dict:
    record = {"locations": [], **translation_pair(japanese, state)}
    if note is not None:
        record["note"] = note
    return record


def page_coordinates(location: dict, context: str) -> PageCoordinates:
    try:
        bank = location["bank"]
        message = location["message"]
        page = location["page"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"{context} has no page coordinates") from error
    coordinates = (bank, message, page)
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in coordinates
    ):
        raise ValueError(f"{context} has invalid page coordinates {coordinates}")
    return coordinates


def page_grounding(location: dict, japanese: str) -> tuple:
    """Identify the complete physical page used to ground a translation."""
    return (
        location.get("page"),
        location.get("content_start_word"),
        location.get("content_end_word"),
        tuple(location.get("boundary_codes", ())),
        location.get("reader"),
        location.get("font"),
        japanese,
    )


def _migrate_flat_rows(path: Path, rows: list[dict]) -> list[dict]:
    """Fold the original one-row-per-page corpus into logical records."""
    pages_by_japanese = defaultdict(list)
    seen = set()
    for index, row in enumerate(rows):
        context = f"{path}: row {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        coordinates = page_coordinates(row, context)
        if coordinates in seen:
            raise ValueError(f"{path}: duplicate page coordinates {coordinates}")
        seen.add(coordinates)
        if not isinstance(row.get("jp"), str):
            raise ValueError(f"{context}.jp must be text")
        load_translation_state(row, context)
        if "note" in row and not isinstance(row["note"], str):
            raise ValueError(f"{context}.note must be a string")
        pages_by_japanese[row["jp"]].append(row)

    groups = []
    for japanese_pages in pages_by_japanese.values():
        variants = list(
            dict.fromkeys(row["tr"] for row in japanese_pages if row["tr"].strip())
        )
        if len(variants) <= 1:
            translation = variants[0] if variants else ""
            variant_pages = [(translation, japanese_pages)]
        else:
            # Existing differences may be contextual. Preserve them as separate
            # logical records instead of choosing one translation arbitrarily.
            variant_pages = [
                (
                    translation,
                    [row for row in japanese_pages if row["tr"] == translation],
                )
                for translation in variants
            ]
            untranslated = [row for row in japanese_pages if not row["tr"].strip()]
            if untranslated:
                variant_pages.append(("", untranslated))

        for translation, pages in variant_pages:
            notes = list(
                dict.fromkeys(
                    row["note"]
                    for row in pages
                    if isinstance(row.get("note"), str) and row["note"].strip()
                )
            )
            if len(notes) > 1:
                raise ValueError(
                    f"{path}: one translation variant has conflicting notes"
                )
            states = [
                load_translation_state(row, f"{path}: migrated page") for row in pages
            ]
            references = list(
                dict.fromkeys(
                    state.english_reference
                    for state in states
                    if state.english_reference is not None
                )
            )
            if len(references) > 1:
                raise ValueError(
                    f"{path}: one translation variant has conflicting English "
                    "references"
                )
            state = TranslationState(
                translation,
                all(existing.reviewed for existing in states),
                all(existing.excluded for existing in states),
                references[0] if references else None,
            )
            record = corpus_record(
                pages[0]["jp"], state, note=notes[0] if notes else None
            )
            record["locations"] = [
                {
                    key: value
                    for key, value in row.items()
                    if key not in ("jp", "en", "tr", "reviewed", "excluded", "note")
                }
                for row in pages
            ]
            groups.append(record)
    return groups


def load_existing(path: Path) -> list[dict]:
    rows = load_json_array(path)
    if not rows:
        return []

    has_locations = [isinstance(row, dict) and "locations" in row for row in rows]
    if not any(has_locations):
        return _migrate_flat_rows(path, rows)
    if not all(has_locations):
        raise ValueError(f"{path}: mixes flat pages and deduplicated records")

    seen = set()
    for index, row in enumerate(rows):
        context = f"{path}: row {index}"
        if not isinstance(row.get("jp"), str):
            raise ValueError(f"{context}.jp must be text")
        load_translation_state(row, context)
        if "note" in row and not isinstance(row["note"], str):
            raise ValueError(f"{context}.note must be a string")
        locations = row["locations"]
        if not isinstance(locations, list) or not locations:
            raise ValueError(f"{context}.locations must be a nonempty array")
        for location_index, location in enumerate(locations):
            coordinates = page_coordinates(
                location,
                f"{context}.locations[{location_index}]",
            )
            if coordinates in seen:
                raise ValueError(f"{path}: duplicate page coordinates {coordinates}")
            seen.add(coordinates)
    return rows


def extract_corpus(source: EveSource, corpus_root: Path) -> list[dict]:
    bank = extract_bank(source)
    source_data = source.input_path.read_bytes()
    raw_u16_messages = find_raw_u16_messages(source_data, source)
    font_overrides = dict(source.font_overrides)
    output_path = corpus_root / source.corpus_path
    existing = load_existing(output_path)
    physical_pages = []

    for message in bank.messages:
        reader = (
            TextReader.RAW_U16
            if message.index in raw_u16_messages
            else source.default_profile.reader
        )
        profile = profile_for_reader(source.default_profile.dialect, reader)
        font = font_overrides.get(message.index, profile.font)
        for page in split_pages(message):
            jp = decode_words(page.words, profile.dialect, font)
            if not jp:
                continue

            location = {
                "bank": 0,
                "message": message.index,
                "page": page.index,
                "file_offset": f"0x{message.file_offset:04x}",
                "content_start_word": page.content_start_word,
                "content_end_word": page.content_end_word,
                "boundary_codes": [f"{word:04x}" for word in page.boundary_codes],
            }
            if profile is not source.default_profile:
                location["reader"] = profile.reader.value
            if font is not profile.font:
                location["font"] = font.value
            physical_pages.append((location, jp))

    existing_by_coordinates = {}
    existing_by_japanese = defaultdict(list)
    existing_grounding = defaultdict(list)
    for group_index, row in enumerate(existing):
        existing_by_japanese[row["jp"]].append(group_index)
        for location in row["locations"]:
            coordinates = page_coordinates(
                location,
                f"{output_path}: existing location",
            )
            existing_by_coordinates[coordinates] = group_index
            existing_grounding[coordinates[:2]].append(
                page_grounding(location, row["jp"])
            )

    current_grounding = defaultdict(list)
    for location, jp in physical_pages:
        coordinates = page_coordinates(location, f"{source.path}: extracted page")
        current_grounding[coordinates[:2]].append(page_grounding(location, jp))
    for pages in existing_grounding.values():
        pages.sort(key=lambda grounding: grounding[0])
    for pages in current_grounding.values():
        pages.sort(key=lambda grounding: grounding[0])
    regrounded_messages = {
        message
        for message in existing_grounding.keys() | current_grounding.keys()
        if existing_grounding[message] != current_grounding[message]
    }

    grouped = {}
    for location, jp in physical_pages:
        coordinates = page_coordinates(location, f"{source.path}: extracted page")
        message = coordinates[:2]
        group_index = existing_by_coordinates.get(coordinates)
        if message in regrounded_messages:
            # A page merge/split changes the source context. Do not attach a
            # line-level draft to the newly grounded page just because its old
            # page number or a fragment of Japanese happens to match.
            key = ("regrounded", jp)
        elif group_index is not None and existing[group_index]["jp"] == jp:
            key = ("existing", group_index)
        else:
            matching_groups = existing_by_japanese[jp]
            if len(matching_groups) == 1:
                key = ("existing", matching_groups[0])
            else:
                # No established group, or an ambiguous context split: make one
                # new untranslated group for all newly discovered occurrences.
                key = ("new", jp)
        if key not in grouped:
            state = (
                load_translation_state(
                    existing[key[1]],
                    f"{output_path}: existing record {key[1]}",
                )
                if key[0] == "existing"
                else None
            )
            note = existing[key[1]].get("note") if key[0] == "existing" else None
            grouped[key] = corpus_record(jp, state, note=note)
        grouped[key]["locations"].append(location)
    return list(grouped.values())
