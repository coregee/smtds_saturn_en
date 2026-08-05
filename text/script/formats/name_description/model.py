from dataclasses import dataclass


@dataclass(frozen=True)
class NameDescriptionResult:
    data: bytes
    records: int
    requested_names: int
    translated_names: int
    name_capacity_fallbacks: int
    requested_descriptions: int
    translated_descriptions: int
    description_capacity_fallbacks: int
    longest_name_bytes: int
    longest_name_pixels: int
    longest_description_words: int
    description_capacity_words: int
    free_bytes: int
