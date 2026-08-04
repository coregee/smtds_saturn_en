"""Validate CLI source/message selections for the text repacker."""

from dataclasses import dataclass

from text.script.source_models import EveSource, TextSource
from text.script.sources import get_source, select_sources


@dataclass(frozen=True)
class RepackSelection:
    sources: tuple[TextSource, ...]
    messages_by_source: dict[str, frozenset[int]] | None
    message_indices: frozenset[int] | None


def parse_selection(
    values: list[str] | None,
) -> dict[str, frozenset[int]] | None:
    if values is None:
        return None
    selection = {}
    for value in values:
        name, separator, raw_indices = value.partition(":")
        if not separator or not name or not raw_indices:
            raise ValueError(
                f"invalid selection {value!r}; expected SOURCE:INDEX[,INDEX...]"
            )
        source = get_source(name)
        if not isinstance(source, EveSource):
            raise ValueError(f"selection source {name!r} is not an EVE bank")
        key = source.name.casefold()
        if key in selection:
            raise ValueError(f"duplicate selection source {name!r}")
        try:
            indices = tuple(int(index, 10) for index in raw_indices.split(","))
        except ValueError as error:
            raise ValueError(f"selection {value!r} has a non-decimal index") from error
        if any(index < 0 for index in indices):
            raise ValueError(f"selection {value!r} has a negative index")
        if len(set(indices)) != len(indices):
            raise ValueError(f"selection {value!r} repeats a message index")
        selection[key] = frozenset(indices)
    return selection


def selected_message_indices(
    source: EveSource,
    selection: dict[str, frozenset[int]] | None,
    message_indices: frozenset[int] | None,
) -> frozenset[int] | None:
    return (
        selection.get(source.name.casefold(), frozenset())
        if selection is not None
        else message_indices
    )


def resolve_selection(
    source_names: list[str],
    messages: list[int] | None,
    selections: list[str] | None,
) -> RepackSelection:
    messages_by_source = parse_selection(selections)
    if messages_by_source is not None and (source_names or messages is not None):
        raise ValueError("--select cannot be combined with sources or --message")
    sources = (
        select_sources(())
        if messages_by_source is not None
        else select_sources(source_names)
    )
    if messages is not None and len(sources) != 1:
        raise ValueError("--message requires exactly one text source")
    if messages is not None and not isinstance(sources[0], EveSource):
        raise ValueError("--message is only valid for EVE sources")
    return RepackSelection(
        sources,
        messages_by_source,
        frozenset(messages) if messages is not None else None,
    )
