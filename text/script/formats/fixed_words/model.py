from dataclasses import dataclass


@dataclass(frozen=True)
class FixedWordField:
    kind: str
    file_offset: int
    word_count: int
    terminator: int | None = None
    zero_mode: str = "space"
    runtime_word_count: int | None = None


@dataclass(frozen=True)
class RuntimeFixedWords:
    kind: str
    file_offset: int
    words: tuple[int, ...]


@dataclass(frozen=True)
class FixedWordsResult:
    data: bytes
    records: int
    requested_translations: int
    translated_records: int
    capacity_fallbacks: int
    longest_words: int
    runtime_fields: tuple[RuntimeFixedWords, ...] = ()
