from dataclasses import dataclass

from text.script.profiles import RuntimeCapability


@dataclass(frozen=True)
class FixedBytesRuntimeCoverage:
    """Records whose complete text is supplied by a set of runtime patches."""

    record_indices: frozenset[int]
    requirements: frozenset[RuntimeCapability]

    def __post_init__(self) -> None:
        if not self.record_indices or not self.requirements:
            raise ValueError(
                "runtime-covered record indices and requirements must be nonempty"
            )


@dataclass(frozen=True)
class FixedBytesResult:
    data: bytes
    records: int
    requested_translations: int
    translated_records: int
    capacity_fallbacks: int
    runtime_covered_capacity_fallbacks: int
    runtime_requirements: frozenset[RuntimeCapability]
    longest_bytes: int
    longest_pixels: int
