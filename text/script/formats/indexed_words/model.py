from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedWordsResult:
    data: bytes
    messages: int
    translated_messages: int
    body_words: int
    body_capacity_words: int
    free_words: int
