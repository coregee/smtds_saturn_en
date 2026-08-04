import argparse
import json

from project_paths import TEXT_CORPUS_ROOT as CORPUS_ROOT
from text.script.formats.ascii_fields.extract import (
    extract_corpus as extract_ascii_fields,
)
from text.script.formats.deduplicated_words.extract import (
    extract_corpus as extract_deduplicated_words,
)
from text.script.formats.eve.extract import extract_corpus as extract_eve
from text.script.formats.fixed_bytes.extract import (
    extract_corpus as extract_fixed_bytes,
)
from text.script.formats.fixed_help.extract import extract_corpus as extract_help
from text.script.formats.fixed_words.extract import (
    extract_corpus as extract_fixed_words,
)
from text.script.formats.indexed_bytes.extract import (
    extract_corpus as extract_indexed_bytes,
)
from text.script.formats.indexed_words.extract import (
    extract_corpus as extract_indexed_words,
)
from text.script.formats.mirrored_words.extract import (
    extract_corpus as extract_mirrored_words,
)
from text.script.formats.name_description.extract import (
    extract_corpus as extract_name_description,
)
from text.script.formats.static_overlay.extract import extract_corpus as extract_static
from text.script.output_files import OutputFiles
from text.script.source_cli import add_source_arguments, print_source_list
from text.script.sources import (
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
    select_sources,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract registered text sources into self-contained corpus JSON."
    )
    add_source_arguments(
        parser,
        omitted_action="inspects every source",
        check_help="verify that corpus files match extraction without rewriting them",
    )
    arguments = parser.parse_args()

    if arguments.list_sources:
        print_source_list()
        return

    try:
        outputs = OutputFiles(arguments.check)
        for source in select_sources(arguments.sources):
            if isinstance(source, EveSource):
                rows = extract_eve(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, AsciiFieldsSource):
                rows = extract_ascii_fields(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, FixedBytesSource):
                rows = extract_fixed_bytes(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, FixedWordsSource):
                rows = extract_fixed_words(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, MirroredWordsSource):
                rows = extract_mirrored_words(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, DeduplicatedWordsSource):
                rows = extract_deduplicated_words(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, FixedHelpSource):
                rows = extract_help(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, NameDescriptionSource):
                rows = extract_name_description(source, CORPUS_ROOT)
                unit = "records"
            elif isinstance(source, IndexedBytesSource):
                rows = extract_indexed_bytes(source, CORPUS_ROOT)
                unit = "messages"
            elif isinstance(source, IndexedWordsSource):
                rows = extract_indexed_words(source, CORPUS_ROOT)
                unit = "messages"
            elif isinstance(source, StaticOverlaySource):
                rows = extract_static(source, CORPUS_ROOT)
                unit = (
                    f"shared translations / {len(source.records)} physical records"
                    if source.deduplicate_by_jp
                    else "records"
                )
            else:
                raise TypeError(f"unknown text source type: {type(source).__name__}")
            output_path = CORPUS_ROOT / source.corpus_path
            text = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"

            outputs.text(output_path, text)

            if isinstance(source, NameDescriptionSource):
                translated = sum(
                    bool(row["name"]["tr"]) + bool(row["description"]["tr"])
                    for row in rows
                )
                translation_unit = "translated fields"
            else:
                translated = sum(bool(row["tr"]) for row in rows)
                translation_unit = "translated"
            detail = ""
            if isinstance(source, EveSource):
                physical = sum(len(row["locations"]) for row in rows)
                detail = f" / {physical} physical pages"
            print(
                f"{source.path}: {len(rows)} {unit}{detail}, "
                f"{translated} {translation_unit} -> {output_path}"
            )

        outputs.require_current("stale corpus files")
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
