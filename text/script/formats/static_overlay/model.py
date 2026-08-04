from dataclasses import dataclass

PADDING_CODE = 0xFFFF
ASSET_VERSION = 2


@dataclass(frozen=True)
class TextSpan:
    file_offset: int
    word_count: int


@dataclass(frozen=True)
class FixedRows:
    rows: int
    cells: int
    pixel_limit: int


@dataclass(frozen=True)
class FixedCells:
    cells: int
    pixel_limit: int | None = None
    padding_code: int = 0
    terminator_required: bool = False


@dataclass(frozen=True)
class AsciiString:
    max_bytes: int | None = None


@dataclass(frozen=True)
class SplitLines:
    lines: int
    cells: int
    pixel_limit: int


StaticLayout = FixedRows | FixedCells | AsciiString | SplitLines


@dataclass(frozen=True)
class Font16Words:
    pass


@dataclass(frozen=True)
class IndexedWords:
    glyphs: tuple[str | None, ...]


StaticDecoder = Font16Words | IndexedWords
FONT16_WORDS = Font16Words()


@dataclass(frozen=True)
class StaticRecordSpec:
    kind: str
    spans: tuple[TextSpan, ...]
    layout: StaticLayout
    decoder: StaticDecoder = FONT16_WORDS


@dataclass(frozen=True)
class AssetBlock:
    offset: int
    size: int
    storage: str
    unit_count: int


@dataclass(frozen=True)
class StaticAsset:
    source: str
    source_sha256: str
    corpus_sha256: str
    data: bytes
    blocks: dict[str, AssetBlock]

    def as_json(self) -> dict:
        return {
            "version": ASSET_VERSION,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "corpus_sha256": self.corpus_sha256,
            "padding_code": f"0x{PADDING_CODE:04x}",
            "data_hex": self.data.hex(),
            "blocks": {
                name: {
                    "offset": block.offset,
                    "size": block.size,
                    "storage": block.storage,
                    "unit_count": block.unit_count,
                }
                for name, block in self.blocks.items()
            },
        }
