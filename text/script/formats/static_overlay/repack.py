import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from text.script.encoding.latin import LatinEncoding, load_latin_encoding
from text.script.formats.static_overlay.extract import extract_corpus, extract_records
from text.script.formats.static_overlay.model import (
    PADDING_CODE,
    AsciiString,
    AssetBlock,
    FixedCells,
    FixedRows,
    SplitLines,
    StaticAsset,
)
from text.script.source_models import StaticOverlaySource


@dataclass(frozen=True)
class StaticRepackResult:
    asset: StaticAsset
    translated_records: int

    def json_text(self) -> str:
        return json.dumps(self.asset.as_json(), ensure_ascii=False, indent=2) + "\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_validated_corpus(
    source: StaticOverlaySource,
    corpus_root: Path,
) -> tuple[list[dict], bytes]:
    corpus_path = corpus_root / source.corpus_path
    corpus_bytes = corpus_path.read_bytes()
    rows = json.loads(corpus_bytes.decode("utf-8"))
    if rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )
    return rows, corpus_bytes


def wrap_paragraph(
    paragraph: str,
    pixel_limit: int,
    encoding: LatinEncoding,
) -> list[str]:
    words = paragraph.split()
    if not words:
        return [""]
    lines = []
    line = words[0]
    if encoding.measure_segment(line) > pixel_limit:
        raise ValueError(f"static-text word exceeds {pixel_limit}px: {line!r}")
    for word in words[1:]:
        candidate = f"{line} {word}"
        if encoding.measure_segment(candidate) <= pixel_limit:
            line = candidate
        else:
            lines.append(line)
            line = word
            if encoding.measure_segment(line) > pixel_limit:
                raise ValueError(f"static-text word exceeds {pixel_limit}px: {line!r}")
    lines.append(line)
    return lines


def wrap_message(
    text: str,
    pixel_limit: int,
    row_limit: int,
    encoding: LatinEncoding,
) -> tuple[str, ...]:
    lines = []
    for paragraph in text.split("{n}"):
        lines.extend(wrap_paragraph(paragraph, pixel_limit, encoding))
    if len(lines) > row_limit:
        raise ValueError(
            f"static text needs {len(lines)} rows; limit is {row_limit}: {text!r}"
        )
    return tuple(lines)


def build_fixed_rows(
    text: str,
    layout: FixedRows,
    encoding: LatinEncoding,
) -> bytes:
    lines = wrap_message(text, layout.pixel_limit, layout.rows, encoding)
    words = []
    for line in lines:
        codes = tuple(encoding.encode_segment(line))
        if len(codes) > layout.cells:
            raise ValueError(f"static-text line exceeds {layout.cells} cells: {line!r}")
        words.extend(codes + (PADDING_CODE,) * (layout.cells - len(codes)))
    words.extend((PADDING_CODE,) * ((layout.rows - len(lines)) * layout.cells))
    return struct.pack(f">{len(words)}H", *words)


def build_fixed_cells(
    text: str,
    layout: FixedCells,
    encoding: LatinEncoding,
) -> bytes:
    codes = tuple(encoding.encode_segment(text))
    visible_cells = layout.cells - int(layout.terminator_required)
    if visible_cells < 0:
        raise ValueError("static-text layout cannot reserve a terminator")
    if len(codes) > visible_cells:
        raise ValueError(f"static text exceeds {visible_cells} cells: {text!r}")
    if (
        layout.pixel_limit is not None
        and encoding.measure_segment(text) > layout.pixel_limit
    ):
        raise ValueError(f"static text exceeds {layout.pixel_limit}px: {text!r}")
    if not 0 <= layout.padding_code <= 0xFFFF:
        raise ValueError("static-text padding code must be a u16 value")
    if layout.terminator_required and not layout.padding_code & 0x8000:
        raise ValueError("static-text terminator must have its high bit set")
    words = codes + (layout.padding_code,) * (layout.cells - len(codes))
    return struct.pack(f">{len(words)}H", *words)


def build_ascii_string(text: str, layout: AsciiString) -> bytes:
    try:
        data = text.encode("ascii") + b"\x00"
    except UnicodeEncodeError as error:
        raise ValueError(
            f"static ASCII text contains a non-ASCII character: {text!r}"
        ) from error
    if layout.max_bytes is not None and len(data) > layout.max_bytes:
        raise ValueError(
            f"static ASCII text needs {len(data)} bytes; limit is {layout.max_bytes}: "
            f"{text!r}"
        )
    return data


def build_split_lines(
    text: str,
    layout: SplitLines,
    encoding: LatinEncoding,
) -> tuple[bytes, ...]:
    lines = tuple(text.split("{n}"))
    if len(lines) != layout.lines or any(not line for line in lines):
        raise ValueError(
            f"static text must contain {layout.lines} nonempty explicit lines"
        )
    output = []
    for line in lines:
        codes = encoding.encode_segment(line)
        if len(codes) > layout.cells:
            raise ValueError(f"static-text line exceeds {layout.cells} cells: {line!r}")
        if encoding.measure_segment(line) > layout.pixel_limit:
            raise ValueError(
                f"static-text line exceeds {layout.pixel_limit}px: {line!r}"
            )
        output.append(struct.pack(f">{len(codes)}H", *codes))
    return tuple(output)


def append_block(
    buffer: bytearray,
    blocks: dict[str, AssetBlock],
    name: str,
    data: bytes,
    *,
    storage: str = "u16be",
) -> None:
    if name in blocks:
        raise ValueError(f"duplicate static-text block {name!r}")
    if storage == "u16be":
        if len(data) % 2:
            raise ValueError(f"u16 block {name!r} has an odd byte size")
        unit_count = len(data) // 2
    elif storage == "bytes":
        unit_count = len(data)
    else:
        raise ValueError(f"unknown static-text storage {storage!r}")
    blocks[name] = AssetBlock(len(buffer), len(data), storage, unit_count)
    buffer.extend(data)
    buffer.extend(bytes((-len(buffer)) % 4))


def repack_static(
    source: StaticOverlaySource,
    corpus_root: Path,
) -> StaticRepackResult:
    rows, corpus_bytes = load_validated_corpus(source, corpus_root)
    if source.deduplicate_by_jp:
        translations = {row["jp"]: row["tr"] for row in rows}
        rows_by_kind = {
            row["kind"]: translations[row["jp"]] for row in extract_records(source)
        }
    else:
        rows_by_kind = {row["kind"]: row["tr"] for row in rows}
    encoding = load_latin_encoding()
    buffer = bytearray()
    blocks = {}

    for record in source.records:
        translation = rows_by_kind[record.kind].strip()
        if not translation:
            raise ValueError(
                f"{source.corpus_path}: {record.kind}.tr must be translated"
            )
        if isinstance(record.layout, FixedRows):
            append_block(
                buffer,
                blocks,
                record.kind,
                build_fixed_rows(translation, record.layout, encoding),
            )
        elif isinstance(record.layout, FixedCells):
            append_block(
                buffer,
                blocks,
                record.kind,
                build_fixed_cells(translation, record.layout, encoding),
            )
        elif isinstance(record.layout, AsciiString):
            append_block(
                buffer,
                blocks,
                record.kind,
                build_ascii_string(translation, record.layout),
                storage="bytes",
            )
        elif isinstance(record.layout, SplitLines):
            for index, data in enumerate(
                build_split_lines(translation, record.layout, encoding)
            ):
                append_block(buffer, blocks, f"{record.kind}_{index}", data)
        else:
            raise TypeError(f"unknown static layout for {record.kind}")

    source_data = source.input_path.read_bytes()
    return StaticRepackResult(
        asset=StaticAsset(
            source=source.path.as_posix(),
            source_sha256=sha256(source_data),
            corpus_sha256=sha256(corpus_bytes),
            data=bytes(buffer),
            blocks=blocks,
        ),
        translated_records=len(source.records),
    )
