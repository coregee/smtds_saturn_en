from dataclasses import dataclass


@dataclass(frozen=True)
class DeduplicatedWordsResult:
    data: bytes
    records: int
    physical_fields: int
    requested_translations: int
    translated_records: int
    capacity_fallbacks: int
    longest_words: int
