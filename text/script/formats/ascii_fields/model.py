from dataclasses import dataclass


@dataclass(frozen=True)
class AsciiField:
    kind: str
    file_offset: int
    capacity: int
    runtime_capacity: int | None = None


@dataclass(frozen=True)
class RuntimeAsciiField:
    kind: str
    file_offset: int
    data: bytes


@dataclass(frozen=True)
class AsciiFieldsResult:
    data: bytes
    records: int
    requested_translations: int
    translated_records: int
    capacity_fallbacks: int
    longest_bytes: int
    runtime_fields: tuple[RuntimeAsciiField, ...] = ()
