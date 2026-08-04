from dataclasses import dataclass

from text.script.dialects import TextDialect
from text.script.encoding import EncodingKind
from text.script.encoding.event_codec import EventDictionary, base_token_runs
from text.script.encoding.latin import load_font12_encoding, load_latin_encoding
from text.script.encoding.tokens import normalize_english
from text.script.layouts import (
    encode_combat_translation,
    encode_event_translation,
)
from text.script.profiles import (
    RuntimeCapability,
    TextFont,
    TextProfile,
    TextReader,
    profile_for_reader,
)
from text.script.source_models import EveSource


@dataclass(frozen=True)
class EncodedTranslation:
    words: tuple[int, ...]
    runtime_requirements: frozenset[RuntimeCapability]


def resolve_message_profile(source: EveSource, pages: list[dict]) -> TextProfile:
    readers = {
        TextReader(row.get("reader", source.default_profile.reader.value))
        for row in pages
    }
    if len(readers) != 1:
        raise ValueError(
            f"{source.path} message {pages[0]['message']} mixes text readers"
        )
    return profile_for_reader(source.default_profile.dialect, readers.pop())


def resolve_message_font(profile: TextProfile, pages: list[dict]) -> TextFont:
    fonts = {TextFont(row.get("font", profile.font.value)) for row in pages}
    if len(fonts) != 1:
        raise ValueError(f"EVE message {pages[0]['message']} mixes text fonts")
    return fonts.pop()


def event_dictionary_sequences(
    source: EveSource,
    original_words: tuple[int, ...],
    pages: list[dict],
) -> list[list[int]]:
    """Return unpacked FONT16 runs that will use the shared dictionary."""
    profile = resolve_message_profile(source, pages)
    font = resolve_message_font(profile, pages)
    if font is not TextFont.FONT16:
        return []
    translations = [normalize_english(row["tr"]) for row in pages]
    if profile.dialect is TextDialect.EVENT:
        if (
            profile.reader is not TextReader.TEXT_VM
            or EncodingKind.PACKED_LATIN not in profile.encodings
        ):
            return []
        words = encode_event_translation(
            original_words,
            translations,
            load_latin_encoding(),
            raw_reader=False,
            packed=False,
        )
    else:
        words = encode_combat_translation(
            original_words,
            translations,
            load_latin_encoding(),
        )
        if words is None:
            return []
    return base_token_runs(words)


def encode_translation(
    source: EveSource,
    original_words: tuple[int, ...],
    pages: list[dict],
    *,
    event_dictionary: EventDictionary | None = None,
) -> EncodedTranslation | None:
    profile = resolve_message_profile(source, pages)
    font = resolve_message_font(profile, pages)
    translations = [normalize_english(row["tr"]) for row in pages]
    if any(not text for text in translations):
        raise ValueError(
            f"{source.path} message {pages[0]['message']} has an empty translation page"
        )

    latin = load_font12_encoding() if font is TextFont.FONT12 else load_latin_encoding()
    requirements = set(profile.runtime_requirements)
    if profile.dialect is TextDialect.EVENT:
        raw_reader = profile.reader is TextReader.RAW_U16
        words = encode_event_translation(
            original_words,
            translations,
            latin,
            raw_reader=raw_reader,
            packed=(
                font is TextFont.FONT16
                and EncodingKind.PACKED_LATIN in profile.encodings
            ),
            pack_codes=(
                event_dictionary.encode_codes
                if event_dictionary is not None
                and font is TextFont.FONT16
                and profile.reader is TextReader.TEXT_VM
                else None
            ),
        )
    else:
        words = encode_combat_translation(
            original_words,
            translations,
            latin,
            pack_codes=(
                event_dictionary.encode_codes
                if event_dictionary is not None and font is TextFont.FONT16
                else None
            ),
        )
        if words is None:
            return None

    return EncodedTranslation(
        words=tuple(words),
        runtime_requirements=frozenset(requirements),
    )
