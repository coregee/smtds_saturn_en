"""Immutable text-source records shared by catalogs and format handlers."""

from dataclasses import dataclass
from pathlib import Path

from project_paths import EXTRACTED_ROOT, TEXT_LAYOUT_ROOT
from text.script.dialects import TextDialect
from text.script.formats.ascii_fields.model import AsciiField
from text.script.formats.fixed_bytes.model import FixedBytesRuntimeCoverage
from text.script.formats.fixed_words.model import FixedWordField
from text.script.formats.mirrored_words.model import MirroredWordTable
from text.script.formats.static_overlay.model import StaticRecordSpec
from text.script.profiles import RuntimeCapability, TextFont, TextProfile

EXTRACTED_PATH = EXTRACTED_ROOT


@dataclass(frozen=True)
class EveSource:
    name: str
    path: Path
    default_profile: TextProfile
    table_offset: int
    body_offset: int
    corpus_path: Path
    detect_menu_readers: bool = False
    forced_raw_messages: frozenset[int] = frozenset()
    font_overrides: tuple[tuple[int, TextFont], ...] = ()

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class StaticOverlaySource:
    name: str
    path: Path
    corpus_path: Path
    generated_path: Path
    records: tuple[StaticRecordSpec, ...]
    runtime_requirements: frozenset[RuntimeCapability]
    deduplicate_by_jp: bool = False

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class FixedHelpSource:
    name: str
    path: Path
    corpus_path: Path
    record_words: int
    record_count: int
    max_lines: int
    packed: bool
    dialect: TextDialect
    runtime_requirements: frozenset[RuntimeCapability]

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class NameDescriptionSource:
    name: str
    path: Path
    corpus_path: Path
    record_size: int
    record_count: int
    name_offset: int
    name_bytes: int
    description_offset: int
    description_words: int
    pointer_offset: int
    max_full_name_bytes: int
    max_full_name_pixels: int
    dialect: TextDialect
    runtime_requirements: frozenset[RuntimeCapability]

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class IndexedBytesSource:
    name: str
    path: Path
    corpus_path: Path
    table_size: int
    table_sentinel: int
    terminator: int
    primary_atlas: str
    secondary_atlas: str
    secondary_base: int
    secondary_glyphs: int
    named_controls: tuple[tuple[int, str], ...]
    runtime_requirements: frozenset[RuntimeCapability]
    repacked_body_offset: int | None = None
    engine_load_address: int | None = None

    @property
    def output_body_offset(self) -> int:
        return (
            self.table_size
            if self.repacked_body_offset is None
            else self.repacked_body_offset
        )

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class IndexedWordsSource:
    name: str
    path: Path
    corpus_path: Path
    body_offset: int
    table_sentinel: int
    terminator: int
    dialect: TextDialect
    runtime_requirements: frozenset[RuntimeCapability]
    layout_width_pixels: int | None = None
    layout_lines: int | None = None

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class FixedBytesSource:
    name: str
    path: Path
    corpus_path: Path
    record_size: int
    record_count: int
    field_offset: int
    field_size: int
    padding: int
    pixel_limit: int
    atlas: str
    runtime_requirements: frozenset[RuntimeCapability]
    capacity_fallback_coverage: tuple[FixedBytesRuntimeCoverage, ...] = ()

    def __post_init__(self) -> None:
        covered: set[int] = set()
        for coverage in self.capacity_fallback_coverage:
            if any(
                isinstance(index, bool) or not 0 <= index < self.record_count
                for index in coverage.record_indices
            ):
                raise ValueError("capacity fallback index is outside the source")
            overlap = covered & coverage.record_indices
            if overlap:
                indices = ", ".join(str(index) for index in sorted(overlap))
                raise ValueError(
                    f"capacity fallback coverage overlaps at record(s): {indices}"
                )
            covered.update(coverage.record_indices)

    def runtime_requirements_for_capacity_fallback(
        self,
        index: int,
    ) -> frozenset[RuntimeCapability]:
        for coverage in self.capacity_fallback_coverage:
            if index in coverage.record_indices:
                return coverage.requirements
        return frozenset()

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class FixedWordsSource:
    name: str
    path: Path
    corpus_path: Path
    fields: tuple[FixedWordField, ...]
    runtime_requirements: frozenset[RuntimeCapability]
    engine_load_address: int | None = None
    packed: bool = False
    dialect: TextDialect | None = None

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class AsciiFieldsSource:
    name: str
    path: Path
    corpus_path: Path
    fields: tuple[AsciiField, ...]
    runtime_requirements: frozenset[RuntimeCapability]
    engine_load_address: int | None = None

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path


@dataclass(frozen=True)
class MirroredWordsSource:
    name: str
    corpus_path: Path
    tables: tuple[MirroredWordTable, ...]
    runtime_requirements: frozenset[RuntimeCapability]

    @property
    def path(self) -> Path:
        return self.tables[0].locations[0].path

    @property
    def extracted_root(self) -> Path:
        return EXTRACTED_PATH


@dataclass(frozen=True)
class DeduplicatedWordsSource:
    name: str
    path: Path
    corpus_path: Path
    layout_path: Path
    region_start: int
    region_end: int
    record_count: int
    physical_field_count: int
    engine_load_address: int
    runtime_requirements: frozenset[RuntimeCapability]
    packed: bool = False

    @property
    def input_path(self) -> Path:
        return EXTRACTED_PATH / self.path

    @property
    def layout_input_path(self) -> Path:
        return TEXT_LAYOUT_ROOT / self.layout_path


TextSource = (
    EveSource
    | StaticOverlaySource
    | FixedHelpSource
    | NameDescriptionSource
    | IndexedBytesSource
    | IndexedWordsSource
    | FixedBytesSource
    | FixedWordsSource
    | AsciiFieldsSource
    | MirroredWordsSource
    | DeduplicatedWordsSource
)
