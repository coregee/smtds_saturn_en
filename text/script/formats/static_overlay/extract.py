import struct
from pathlib import Path

from text.script.codec.atlas import FONT16_GLYPHS
from text.script.corpus_io import (
    TranslationState,
    load_json_array,
    load_translation_state,
    translation_pair,
)
from text.script.formats.static_overlay.model import (
    Font16Words,
    IndexedWords,
    StaticDecoder,
)
from text.script.source_models import StaticOverlaySource


def load_existing(
    path: Path,
    identity_field: str,
    *,
    allow_matching_duplicates: bool = False,
) -> dict[str, TranslationState]:
    rows = load_json_array(path)

    existing = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index} must be an object")
        identity = row.get(identity_field)
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"{path}: row {index} has no {identity_field!r} identity")
        state = load_translation_state(row, f"{path}: row {index}")
        if identity in existing:
            if allow_matching_duplicates and existing[identity] == state:
                continue
            raise ValueError(
                f"{path}: duplicate {identity_field} {identity!r} has "
                "conflicting definitions"
            )
        existing[identity] = state
    return existing


def decode_span(
    data: bytes,
    offset: int,
    word_count: int,
    context: str,
    decoder: StaticDecoder,
) -> str:
    end = offset + word_count * 2
    if offset < 0 or end > len(data):
        raise ValueError(f"{context}: span exceeds the source file")
    words = struct.unpack_from(f">{word_count}H", data, offset)
    output = []
    for word in words:
        if word == 0:
            continue
        if isinstance(decoder, Font16Words):
            output.append(FONT16_GLYPHS.get(word, f"{{0x{word:04x}}}"))
        elif isinstance(decoder, IndexedWords):
            glyph = decoder.glyphs[word] if word < len(decoder.glyphs) else None
            output.append(glyph if glyph is not None else f"{{index:{word}}}")
        else:
            raise TypeError(f"{context}: unknown static decoder")
    return "".join(output)


def extract_records(source: StaticOverlaySource) -> list[dict]:
    data = source.input_path.read_bytes()
    rows = []

    for record in source.records:
        rows.append(
            {
                "kind": record.kind,
                "spans": [
                    {
                        "file_offset": f"0x{span.file_offset:x}",
                        "word_count": span.word_count,
                    }
                    for span in record.spans
                ],
                "jp": "{n}".join(
                    decode_span(
                        data,
                        span.file_offset,
                        span.word_count,
                        f"{source.path}:{record.kind}",
                        record.decoder,
                    )
                    for span in record.spans
                ),
            }
        )
    return rows


def extract_corpus(source: StaticOverlaySource, corpus_root: Path) -> list[dict]:
    output_path = corpus_root / source.corpus_path
    records = extract_records(source)
    if source.deduplicate_by_jp:
        existing = load_existing(
            output_path,
            "jp",
            allow_matching_duplicates=True,
        )
        rows = []
        seen = set()
        for record in records:
            japanese = record["jp"]
            if not japanese:
                raise ValueError(
                    f"{source.path}:{record['kind']}: shared source text is empty"
                )
            if japanese in seen:
                continue
            seen.add(japanese)
            rows.append(translation_pair(japanese, existing.get(japanese)))
        return rows

    existing = load_existing(output_path, "kind")
    return [
        {
            **record,
            **translation_pair(
                record["jp"],
                existing.get(record["kind"]),
            ),
        }
        for record in records
    ]
