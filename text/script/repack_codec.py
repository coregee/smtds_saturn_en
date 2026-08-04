"""Shared EVENT dictionary preparation and binding manifests."""

import hashlib
import json

from text.script.encoding.event_codec import train_event_dictionary
from text.script.formats.eve.extract import extract_bank
from text.script.formats.eve.repack import group_corpus_pages, load_validated_corpus
from text.script.formats.indexed_words.repack import indexed_words_dictionary_sequences
from text.script.message import event_dictionary_sequences
from text.script.repack_selection import selected_message_indices
from text.script.source_models import EveSource, IndexedWordsSource, TextSource


def build_event_dictionary(
    sources: tuple[TextSource, ...],
    corpus_root,
    selection: dict[str, frozenset[int]] | None,
    message_indices: frozenset[int] | None,
):
    sequences = []
    for source in sources:
        if isinstance(source, IndexedWordsSource):
            sequences.extend(indexed_words_dictionary_sequences(source, corpus_root))
            continue
        if not isinstance(source, EveSource):
            continue
        selected = selected_message_indices(source, selection, message_indices)
        bank = extract_bank(source)
        grouped = group_corpus_pages(load_validated_corpus(source, corpus_root))
        for message in bank.messages:
            if selected is not None and message.index not in selected:
                continue
            pages = grouped.get(message.index, [])
            translations = [row["tr"].strip() for row in pages]
            if not translations or not all(translations):
                continue
            sequences.extend(event_dictionary_sequences(source, message.words, pages))
    return train_event_dictionary(sequences)


def event_codec_json(dictionary) -> str:
    return (
        json.dumps(
            dictionary.manifest(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def event_codec_binding_json(
    codec_text: str,
    registered_outputs: tuple[str, ...],
    outputs: dict[str, bytes],
) -> str:
    document = {
        "version": 1,
        "codec_sha256": hashlib.sha256(codec_text.encode("utf-8")).hexdigest(),
        "registered_outputs": list(registered_outputs),
        "outputs": {
            path: hashlib.sha256(data).hexdigest()
            for path, data in sorted(outputs.items())
        },
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def codec_output_paths(sources: tuple[TextSource, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            source.path.as_posix()
            for source in sources
            if isinstance(source, (EveSource, IndexedWordsSource))
        )
    )
