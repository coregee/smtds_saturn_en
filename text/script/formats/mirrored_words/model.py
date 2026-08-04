from dataclasses import dataclass
from pathlib import Path

from text.script.profiles import RuntimeCapability


@dataclass(frozen=True)
class MirroredWordLocation:
    path: Path
    table_offset: int
    words_per_record: int
    engine_load_address: int | None = None


@dataclass(frozen=True)
class MirroredWordTable:
    name: str
    record_count: int
    locations: tuple[MirroredWordLocation, ...]
    terminator_mode: str
    zero_mode: str
    require_identical: bool = False
    capacity_fallback_requirements: frozenset[RuntimeCapability] = frozenset()
    capacity_fallback_indices: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if bool(self.capacity_fallback_requirements) != bool(
            self.capacity_fallback_indices
        ):
            raise ValueError(
                "capacity fallback requirements and covered indices must be "
                "declared together"
            )
        if any(
            isinstance(index, bool) or not 0 <= index < self.record_count
            for index in self.capacity_fallback_indices
        ):
            raise ValueError("capacity fallback index is outside the table")

    def runtime_requirements_for_capacity_fallback(
        self,
        index: int,
    ) -> frozenset[RuntimeCapability]:
        if index not in self.capacity_fallback_indices:
            return frozenset()
        return self.capacity_fallback_requirements


@dataclass(frozen=True)
class MirroredWordsOutput:
    path: Path
    data: bytes
    engine_load_address: int | None


@dataclass(frozen=True)
class MirroredWordsResult:
    outputs: tuple[MirroredWordsOutput, ...]
    records: int
    requested_translations: int
    translated_records: int
    capacity_fallbacks: int
    runtime_covered_capacity_fallbacks: int
    runtime_requirements: frozenset[RuntimeCapability]
    longest_words: int
