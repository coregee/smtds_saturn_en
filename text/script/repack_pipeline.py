"""Per-source text repacking and generated-output orchestration."""

from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from project_paths import BUILD_ROOT, TEXT_CORPUS_ROOT, TEXT_GENERATED_ROOT
from text.script.formats.ascii_fields.repack import (
    asset_json as ascii_asset_json,
)
from text.script.formats.ascii_fields.repack import repack_ascii_fields
from text.script.formats.deduplicated_words.repack import (
    asset_json as deduplicated_asset_json,
)
from text.script.formats.deduplicated_words.repack import (
    repack_deduplicated_words,
)
from text.script.formats.eve.repack import repack_eve
from text.script.formats.fixed_bytes.repack import repack_fixed_bytes
from text.script.formats.fixed_help.repack import repack_help
from text.script.formats.fixed_words.repack import asset_json, repack_fixed_words
from text.script.formats.indexed_bytes.repack import repack_indexed_bytes
from text.script.formats.indexed_words.repack import repack_indexed_words
from text.script.formats.mirrored_words.repack import (
    asset_json as mirrored_asset_json,
)
from text.script.formats.mirrored_words.repack import (
    asset_path as mirrored_asset_path,
)
from text.script.formats.mirrored_words.repack import (
    repack_mirrored_words,
)
from text.script.formats.name_description.repack import repack_name_descriptions
from text.script.formats.static_overlay.repack import repack_static
from text.script.message import encode_translation
from text.script.output_files import OutputFiles
from text.script.profiles import RuntimeCapability
from text.script.repack_codec import (
    build_event_dictionary,
    codec_output_paths,
    event_codec_binding_json,
    event_codec_json,
)
from text.script.repack_selection import RepackSelection, selected_message_indices
from text.script.runtime_ui import write_runtime_ui_contract
from text.script.source_models import (
    AsciiFieldsSource,
    DeduplicatedWordsSource,
    EveSource,
    FixedBytesSource,
    FixedHelpSource,
    FixedWordsSource,
    IndexedBytesSource,
    IndexedWordsSource,
    MirroredWordsSource,
    NameDescriptionSource,
    StaticOverlaySource,
    TextSource,
)
from text.script.sources import select_sources

CORPUS_ROOT = TEXT_CORPUS_ROOT
GENERATED_ROOT = TEXT_GENERATED_ROOT
EVENT_CODEC_PATH = GENERATED_ROOT / "event_codec.json"
EVENT_CODEC_BINDING_PATH = GENERATED_ROOT / "event_codec_binding.json"


@dataclass
class RepackContext:
    selection: RepackSelection
    outputs: OutputFiles
    event_dictionary: object | None = None
    codec_text: str | None = None
    codec_outputs: dict[str, bytes] = field(default_factory=dict)
    requirements: set[RuntimeCapability] = field(default_factory=set)
    jp_fallbacks: list[str] = field(default_factory=list)


def prepare_event_codec(context: RepackContext) -> tuple[str, ...]:
    registered_outputs = codec_output_paths(select_sources(()))
    codec_sources = tuple(
        source
        for source in context.selection.sources
        if isinstance(source, (EveSource, IndexedWordsSource))
    )
    if not codec_sources:
        return registered_outputs
    context.event_dictionary = build_event_dictionary(
        context.selection.sources,
        CORPUS_ROOT,
        context.selection.messages_by_source,
        context.selection.message_indices,
    )
    context.codec_text = event_codec_json(context.event_dictionary)
    context.outputs.text(EVENT_CODEC_PATH, context.codec_text)
    print(
        f"EVENT dictionary: {len(context.event_dictionary.merges)}/57 tokens -> "
        f"{EVENT_CODEC_PATH}"
    )
    return registered_outputs


def write_binary_result(context: RepackContext, source, data: bytes) -> Path:
    output_path = BUILD_ROOT / source.path
    context.outputs.bytes(output_path, data)
    return output_path


def record_fallback(
    context: RepackContext,
    source: TextSource,
    count: int,
    reason: str,
) -> None:
    if count:
        detail = f"{source.name}: {count} {reason}"
        context.jp_fallbacks.append(detail)
        print(f"  JP fallbacks: {count} {reason}")


def require_no_fallbacks(fallbacks: list[str]) -> None:
    if fallbacks:
        details = "\n  ".join(fallbacks)
        raise ValueError(
            "unresolved Japanese fallbacks remain; shorten the translation or "
            f"add a verified runtime consumer:\n  {details}"
        )


def _repack_source_kind(source: TextSource, context: RepackContext, kind: str) -> None:
    if kind == "eve":
        selected_messages = selected_message_indices(
            source,
            context.selection.messages_by_source,
            context.selection.message_indices,
        )
        result = repack_eve(
            source,
            CORPUS_ROOT,
            partial(
                encode_translation,
                event_dictionary=context.event_dictionary,
            ),
            selected_messages,
        )
        output_path = write_binary_result(context, source, result.data)
        context.codec_outputs[source.path.as_posix()] = result.data
        context.requirements.update(result.runtime_requirements)
        print(
            f"{source.path}: {result.translated_messages} messages / "
            f"{result.translated_pages} pages translated; "
            f"body {result.body_size}/{result.body_capacity} bytes -> "
            f"{output_path}"
        )
        fallbacks = []
        if result.partial_messages:
            fallbacks.append(f"{result.partial_messages} partial")
            record_fallback(
                context,
                source,
                result.partial_messages,
                "partial messages",
            )
        if result.layout_fallbacks:
            fallbacks.append(f"{result.layout_fallbacks} layout")
            record_fallback(
                context,
                source,
                result.layout_fallbacks,
                "layout failures",
            )
        if fallbacks:
            # ``record_fallback`` already prints the actionable per-kind rows.
            pass
        return

    if kind == "ascii_fields":
        result = repack_ascii_fields(source, CORPUS_ROOT)
        if source.engine_load_address is not None:
            output_path = GENERATED_ROOT / source.corpus_path
            text = ascii_asset_json(
                source,
                CORPUS_ROOT / source.corpus_path,
                result,
            )
            context.outputs.text(output_path, text)
            destination = f"asset {output_path}"
        else:
            output_path = write_binary_result(context, source, result.data)
            destination = str(output_path)
        print(
            f"{source.path}: {result.translated_records}/"
            f"{result.requested_translations} requested ASCII fields translated "
            f"across {result.records} records; longest "
            f"{result.longest_bytes} bytes -> {destination}"
        )
        record_fallback(context, source, result.capacity_fallbacks, "capacity")
    elif kind == "fixed_bytes":
        result = repack_fixed_bytes(source, CORPUS_ROOT)
        output_path = write_binary_result(context, source, result.data)
        print(
            f"{source.path}: {result.translated_records}/"
            f"{result.requested_translations} requested names translated "
            f"across {result.records} records; longest "
            f"{result.longest_bytes}/{source.field_size} bytes, "
            f"{result.longest_pixels}/{source.pixel_limit} pixels -> "
            f"{output_path}"
        )
        if result.runtime_covered_capacity_fallbacks:
            capabilities = ", ".join(
                sorted(requirement.value for requirement in result.runtime_requirements)
            )
            print(
                "  Runtime-covered physical fallbacks: "
                f"{result.runtime_covered_capacity_fallbacks} capacity "
                f"({capabilities})"
            )
            context.requirements.update(result.runtime_requirements)
        record_fallback(context, source, result.capacity_fallbacks, "capacity")
    elif kind == "fixed_words":
        result = repack_fixed_words(source, CORPUS_ROOT)
        if source.engine_load_address is not None:
            output_path = GENERATED_ROOT / source.corpus_path
            text = asset_json(
                source,
                CORPUS_ROOT / source.corpus_path,
                result,
            )
            context.outputs.text(output_path, text)
            destination = f"asset {output_path}"
        else:
            output_path = write_binary_result(context, source, result.data)
            destination = str(output_path)
        print(
            f"{source.path}: {result.translated_records}/"
            f"{result.requested_translations} requested fields translated "
            f"across {result.records} records; longest "
            f"{result.longest_words} words -> {destination}"
        )
        record_fallback(context, source, result.capacity_fallbacks, "capacity")
    elif kind == "mirrored_words":
        result = repack_mirrored_words(source, CORPUS_ROOT)
        destinations = []
        for output in result.outputs:
            if output.engine_load_address is not None:
                relative = mirrored_asset_path(source, output)
                output_path = GENERATED_ROOT / relative
                text = mirrored_asset_json(
                    source,
                    output,
                    CORPUS_ROOT / source.corpus_path,
                )
                context.outputs.text(output_path, text)
                destinations.append(f"asset {output_path}")
            else:
                output_path = BUILD_ROOT / output.path
                context.outputs.bytes(output_path, output.data)
                destinations.append(str(output_path))
        print(
            f"{source.path}: {result.translated_records}/"
            f"{result.requested_translations} requested mirrored records "
            f"translated across {result.records} logical records and "
            f"{len(result.outputs)} files; longest "
            f"{result.longest_words} words -> {', '.join(destinations)}"
        )
        if result.runtime_covered_capacity_fallbacks:
            capabilities = ", ".join(
                sorted(requirement.value for requirement in result.runtime_requirements)
            )
            print(
                "  Runtime-covered physical fallbacks: "
                f"{result.runtime_covered_capacity_fallbacks} capacity "
                f"({capabilities})"
            )
            context.requirements.update(result.runtime_requirements)
        record_fallback(context, source, result.capacity_fallbacks, "capacity")
    elif kind == "deduplicated_words":
        result = repack_deduplicated_words(source, CORPUS_ROOT)
        output_path = GENERATED_ROOT / source.corpus_path
        text = deduplicated_asset_json(
            source,
            CORPUS_ROOT / source.corpus_path,
            result,
        )
        context.outputs.text(output_path, text)
        print(
            f"{source.path}: {result.translated_records}/"
            f"{result.requested_translations} requested fallback records "
            f"translated across {result.records} logical records and "
            f"{result.physical_fields} physical fields; longest "
            f"{result.longest_words} words -> asset {output_path}"
        )
        record_fallback(context, source, result.capacity_fallbacks, "capacity")
    elif kind == "static_overlay":
        result = repack_static(source, CORPUS_ROOT)
        output_path = GENERATED_ROOT / source.generated_path
        context.outputs.text(output_path, result.json_text())
        print(
            f"{source.path}: {result.translated_records} static records / "
            f"{len(result.asset.blocks)} blocks, "
            f"{len(result.asset.data)} bytes -> {output_path}"
        )
    elif kind == "fixed_help":
        result = repack_help(source, CORPUS_ROOT)
        output_path = write_binary_result(context, source, result.data)
        print(
            f"{source.path}: {result.translated_records}/"
            f"{result.records} fixed help records; longest "
            f"{result.longest_words}/{result.capacity_words} words -> "
            f"{output_path}"
        )
    elif kind == "name_description":
        result = repack_name_descriptions(source, CORPUS_ROOT)
        output_path = write_binary_result(context, source, result.data)
        print(
            f"{source.path}: {result.translated_names}/"
            f"{result.requested_names} requested names, "
            f"{result.translated_descriptions}/"
            f"{result.requested_descriptions} requested descriptions; "
            f"longest name {result.longest_name_bytes} bytes / "
            f"{result.longest_name_pixels} pixels; description "
            f"{result.longest_description_words}/"
            f"{result.description_capacity_words} words; "
            f"{result.free_bytes} padding bytes free -> {output_path}"
        )
        if result.name_capacity_fallbacks or result.description_capacity_fallbacks:
            print(
                "  JP fallbacks: "
                f"{result.name_capacity_fallbacks} names, "
                f"{result.description_capacity_fallbacks} descriptions"
            )
            if result.name_capacity_fallbacks:
                context.jp_fallbacks.append(
                    f"{source.name}: {result.name_capacity_fallbacks} name capacity"
                )
            if result.description_capacity_fallbacks:
                context.jp_fallbacks.append(
                    f"{source.name}: {result.description_capacity_fallbacks} "
                    "description capacity"
                )
    elif kind == "indexed_bytes":
        result = repack_indexed_bytes(source, CORPUS_ROOT)
        output_path = write_binary_result(context, source, result.data)
        print(
            f"{source.path}: {result.translated_messages}/"
            f"{result.requested_translations} requested indexed messages; body "
            f"at {result.body_offset:#x}, {result.body_size}/"
            f"{result.body_capacity} bytes, "
            f"{result.free_bytes} free -> {output_path}"
        )
        record_fallback(context, source, result.capacity_fallbacks, "capacity")
    elif kind == "indexed_words":
        result = repack_indexed_words(
            source,
            CORPUS_ROOT,
            context.event_dictionary,
        )
        output_path = write_binary_result(context, source, result.data)
        context.codec_outputs[source.path.as_posix()] = result.data
        print(
            f"{source.path}: {result.translated_messages}/"
            f"{result.messages} indexed messages; body "
            f"{result.body_words}/{result.body_capacity_words} words, "
            f"{result.free_words} free -> {output_path}"
        )
    else:
        raise TypeError(f"unknown text source type: {type(source).__name__}")

    context.requirements.update(source.runtime_requirements)


FORMAT_HANDLERS = {
    EveSource: partial(_repack_source_kind, kind="eve"),
    AsciiFieldsSource: partial(_repack_source_kind, kind="ascii_fields"),
    FixedBytesSource: partial(_repack_source_kind, kind="fixed_bytes"),
    FixedWordsSource: partial(_repack_source_kind, kind="fixed_words"),
    MirroredWordsSource: partial(_repack_source_kind, kind="mirrored_words"),
    DeduplicatedWordsSource: partial(_repack_source_kind, kind="deduplicated_words"),
    StaticOverlaySource: partial(_repack_source_kind, kind="static_overlay"),
    FixedHelpSource: partial(_repack_source_kind, kind="fixed_help"),
    NameDescriptionSource: partial(_repack_source_kind, kind="name_description"),
    IndexedBytesSource: partial(_repack_source_kind, kind="indexed_bytes"),
    IndexedWordsSource: partial(_repack_source_kind, kind="indexed_words"),
}


def repack_source(source: TextSource, context: RepackContext) -> None:
    try:
        handler = FORMAT_HANDLERS[type(source)]
    except KeyError as error:
        raise TypeError(f"unknown text source type: {type(source).__name__}") from error
    handler(source=source, context=context)


def finish_event_codec(
    context: RepackContext,
    registered_outputs: tuple[str, ...],
) -> None:
    if context.event_dictionary is None:
        return
    binding_text = event_codec_binding_json(
        context.codec_text,
        registered_outputs,
        context.codec_outputs,
    )
    if not context.outputs.check:
        selected_outputs = set(context.codec_outputs)
        for relative_path in registered_outputs:
            if relative_path in selected_outputs:
                continue
            stale_output = BUILD_ROOT / relative_path
            if stale_output.exists():
                stale_output.unlink()
                print(
                    "removed output encoded with a different dictionary: "
                    f"{stale_output}"
                )
    context.outputs.text(EVENT_CODEC_BINDING_PATH, binding_text)
    print(f"EVENT dictionary binding -> {EVENT_CODEC_BINDING_PATH}")


def run_repack(
    selection: RepackSelection,
    check: bool,
    *,
    fail_on_fallbacks: bool = False,
) -> None:
    context = RepackContext(selection, OutputFiles(check))
    write_runtime_ui_contract(context.outputs)
    registered_outputs = prepare_event_codec(context)
    for source in selection.sources:
        repack_source(source, context)
    finish_event_codec(context, registered_outputs)
    if fail_on_fallbacks:
        require_no_fallbacks(context.jp_fallbacks)
    if context.requirements:
        names = ", ".join(
            sorted(requirement.value for requirement in context.requirements)
        )
        print(f"Runtime requirements: {names}")
    context.outputs.require_current("stale text build files")
