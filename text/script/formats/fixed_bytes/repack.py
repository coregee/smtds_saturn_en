import json
from pathlib import Path

from project_paths import FONT_GENERATED_ROOT
from text.script.encoding.latin import load_latin_encoding
from text.script.formats.fixed_bytes.extract import extract_corpus
from text.script.formats.fixed_bytes.model import FixedBytesResult
from text.script.profiles import RuntimeCapability
from text.script.source_models import FixedBytesSource

FONT8_METRICS_PATH = FONT_GENERATED_ROOT / "font8_metrics.json"


def repack_fixed_bytes(
    source: FixedBytesSource,
    corpus_root: Path,
) -> FixedBytesResult:
    corpus_path = corpus_root / source.corpus_path
    rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )

    output = bytearray(source.input_path.read_bytes())
    latin = load_latin_encoding(FONT8_METRICS_PATH)
    requested = 0
    translated = 0
    fallbacks = 0
    runtime_fallbacks = 0
    runtime_requirements: set[RuntimeCapability] = set()
    longest_bytes = 0
    longest_pixels = 0

    for record, row in enumerate(rows):
        translation = row["tr"].strip()
        if not translation:
            continue
        requested += 1
        try:
            encoded = bytes(latin.encode_segment(translation))
            pixels = latin.measure_segment(translation)
        except ValueError as error:
            raise ValueError(
                f"{source.path}: record {record}: {error}; text {translation!r}"
            ) from error

        longest_bytes = max(longest_bytes, len(encoded))
        longest_pixels = max(longest_pixels, pixels)
        if len(encoded) > source.field_size or pixels > source.pixel_limit:
            requirements = source.runtime_requirements_for_capacity_fallback(record)
            if not requirements:
                fallbacks += 1
            else:
                missing = requirements - source.runtime_requirements
                if missing:
                    names = ", ".join(sorted(item.value for item in missing))
                    raise ValueError(
                        f"{source.name}[{record}]: runtime-covered capacity "
                        "fallback requirements are not emitted by the source: "
                        f"{names}"
                    )
                runtime_fallbacks += 1
                runtime_requirements.update(requirements)
            continue

        offset = record * source.record_size + source.field_offset
        output[offset : offset + source.field_size] = encoded.ljust(
            source.field_size,
            bytes([source.padding]),
        )
        translated += 1

    if len(output) != len(source.input_path.read_bytes()):
        raise ValueError(f"{source.path}: rebuilt file size changed")
    return FixedBytesResult(
        data=bytes(output),
        records=source.record_count,
        requested_translations=requested,
        translated_records=translated,
        capacity_fallbacks=fallbacks,
        runtime_covered_capacity_fallbacks=runtime_fallbacks,
        runtime_requirements=frozenset(runtime_requirements),
        longest_bytes=longest_bytes,
        longest_pixels=longest_pixels,
    )
