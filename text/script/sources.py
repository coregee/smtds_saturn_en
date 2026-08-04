"""Ordered public registry for every translated text source."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from text.script.source_catalog.dialogue import EVE_SOURCES
from text.script.source_catalog.records import (
    ASCII_FIELD_SOURCES,
    DEDUPLICATED_WORDS_SOURCES,
    FIXED_BYTES_SOURCES,
    FIXED_HELP_SOURCES,
    FIXED_WORDS_SOURCES,
    INDEXED_BYTES_SOURCES,
    INDEXED_WORDS_SOURCES,
    MIRRORED_WORDS_SOURCES,
    NAME_DESCRIPTION_SOURCES,
)
from text.script.source_catalog.static import STATIC_SOURCES
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

__all__ = (
    "SOURCES",
    "AsciiFieldsSource",
    "DeduplicatedWordsSource",
    "EveSource",
    "FixedBytesSource",
    "FixedHelpSource",
    "FixedWordsSource",
    "IndexedBytesSource",
    "IndexedWordsSource",
    "MirroredWordsSource",
    "NameDescriptionSource",
    "StaticOverlaySource",
    "TextSource",
    "get_source",
    "select_sources",
)


SOURCES: tuple[TextSource, ...] = (
    EVE_SOURCES
    + FIXED_HELP_SOURCES
    + NAME_DESCRIPTION_SOURCES
    + INDEXED_BYTES_SOURCES
    + INDEXED_WORDS_SOURCES
    + FIXED_BYTES_SOURCES
    + FIXED_WORDS_SOURCES
    + MIRRORED_WORDS_SOURCES
    + DEDUPLICATED_WORDS_SOURCES
    + ASCII_FIELD_SOURCES
    + STATIC_SOURCES
)


def _build_source_indexes(
    sources: tuple[TextSource, ...],
) -> tuple[
    Mapping[str, TextSource],
    Mapping[str, TextSource],
    Mapping[str, tuple[TextSource, ...]],
]:
    canonical: dict[str, TextSource] = {}
    filename_groups: dict[str, list[TextSource]] = defaultdict(list)
    for source in sources:
        key = source.name.casefold()
        if not source.name.strip():
            raise ValueError("registered text source has an empty canonical name")
        previous = canonical.get(key)
        if previous is not None:
            raise ValueError(
                "duplicate canonical text source name "
                f"{source.name!r}: {previous.path} and {source.path}"
            )
        canonical[key] = source
        filename_groups[source.path.name.casefold()].append(source)

    unique_filenames = {
        filename: matches[0]
        for filename, matches in filename_groups.items()
        if len(matches) == 1
    }
    ambiguous_filenames = {
        filename: tuple(matches)
        for filename, matches in filename_groups.items()
        if len(matches) > 1
    }
    return (
        MappingProxyType(canonical),
        MappingProxyType(unique_filenames),
        MappingProxyType(ambiguous_filenames),
    )


(
    _SOURCES_BY_CANONICAL_NAME,
    _SOURCES_BY_UNIQUE_FILENAME,
    _SOURCES_BY_AMBIGUOUS_FILENAME,
) = _build_source_indexes(SOURCES)


def get_source(name: str) -> TextSource:
    key = name.casefold()
    source = _SOURCES_BY_CANONICAL_NAME.get(key)
    if source is not None:
        return source
    source = _SOURCES_BY_UNIQUE_FILENAME.get(key)
    if source is not None:
        return source
    ambiguous = _SOURCES_BY_AMBIGUOUS_FILENAME.get(key)
    if ambiguous is not None:
        choices = ", ".join(source.name for source in ambiguous)
        raise ValueError(
            f"ambiguous text source {name!r}; use a canonical name: {choices}"
        )
    choices = ", ".join(source.name for source in SOURCES)
    raise ValueError(f"unknown text source {name!r}; choose from: {choices}")


def select_sources(names: Sequence[str]) -> tuple[TextSource, ...]:
    if not names:
        return SOURCES
    return tuple(get_source(name) for name in names)
