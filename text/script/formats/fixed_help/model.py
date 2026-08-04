from dataclasses import dataclass


@dataclass(frozen=True)
class FixedHelpResult:
    data: bytes
    records: int
    translated_records: int
    longest_words: int
    capacity_words: int
