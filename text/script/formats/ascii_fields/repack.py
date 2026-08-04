import json
from pathlib import Path

from text.script.formats.ascii_fields.extract import extract_corpus
from text.script.formats.ascii_fields.model import (
    AsciiFieldsResult,
    RuntimeAsciiField,
)
from text.script.patch_assets import PatchSpan, build_asset_json
from text.script.source_models import AsciiFieldsSource


def asset_json(
    source: AsciiFieldsSource,
    corpus_path: Path,
    result: AsciiFieldsResult,
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
            PatchSpan(field.kind, field.file_offset, field.capacity)
            for field in source.fields
        ),
        extra={
            "runtime_fields": [
                {
                    "name": field.kind,
                    "file_offset": f"0x{field.file_offset:x}",
                    "byte_count": len(field.data),
                    "bytes_hex": field.data.hex(),
                }
                for field in result.runtime_fields
            ],
        }
        if result.runtime_fields
        else None,
    )


def repack_ascii_fields(
    source: AsciiFieldsSource,
    corpus_root: Path,
) -> AsciiFieldsResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )
    output = bytearray(source.input_path.read_bytes())
    rows_by_kind = {row["kind"]: row for row in rows}
    requested = translated = fallbacks = longest = 0
    runtime_fields = []
    for field in source.fields:
        if (
            field.runtime_capacity is not None
            and field.runtime_capacity < field.capacity
        ):
            raise ValueError(
                f"{source.path}:{field.kind}: runtime capacity "
                f"{field.runtime_capacity} is smaller than native capacity "
                f"{field.capacity}"
            )
        translation = rows_by_kind[field.kind]["tr"]
        if not translation:
            continue
        requested += 1
        try:
            payload = translation.encode("ascii") + b"\x00"
        except UnicodeEncodeError as error:
            raise ValueError(
                f"{source.path}:{field.kind}: translation field is not ASCII"
            ) from error
        longest = max(longest, len(payload))
        capacity = field.runtime_capacity or field.capacity
        if len(payload) > capacity:
            fallbacks += 1
            continue
        if field.runtime_capacity is not None:
            runtime_fields.append(
                RuntimeAsciiField(
                    kind=field.kind,
                    file_offset=field.file_offset,
                    data=payload,
                )
            )
        if len(payload) <= field.capacity:
            output[field.file_offset : field.file_offset + field.capacity] = (
                payload.ljust(field.capacity, b"\x00")
            )
        translated += 1
    return AsciiFieldsResult(
        data=bytes(output),
        records=len(source.fields),
        requested_translations=requested,
        translated_records=translated,
        capacity_fallbacks=fallbacks,
        longest_bytes=longest,
        runtime_fields=tuple(runtime_fields),
    )
