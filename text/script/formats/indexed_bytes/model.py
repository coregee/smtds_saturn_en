from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedBytesResult:
    data: bytes
    messages: int
    requested_translations: int
    translated_messages: int
    capacity_fallbacks: int
    body_offset: int
    body_size: int
    body_capacity: int
    free_bytes: int
