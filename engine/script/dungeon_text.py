"""Neutral formatting for dungeon labels shared by runtime overlays."""

from collections.abc import Mapping

from engine.script.static_text import StaticTextAsset
from text.script.dungeon_locations import RECORD_COUNT as DUNGEON_RECORD_COUNT
from text.script.dungeon_locations import RECORD_SIZE as DUNGEON_RECORD_SIZE
from text.script.dungeon_locations import TABLE_OFFSET as DUNGEON_TABLE_OFFSET
from text.script.dungeon_locations import TEXT_BYTES as DUNGEON_TEXT_BYTES
from text.script.dungeon_locations import record_kind

SAVELOAD_DUNGEON_CELLS = 24
SAVELOAD_DUNGEON_PIXEL_LIMIT = 144
PADDING_CODE = 0xFFFF


def format_dungeon_location(name: str, floor: int) -> str:
    """Join a canonical dungeon name to the stock signed floor byte."""
    if not -128 <= floor <= 127:
        raise ValueError(f"dungeon floor is outside signed-byte range: {floor}")
    if floor < 0:
        return f"{name} B{-floor}F"
    if floor > 0:
        return f"{name} {floor}F"
    return name


def _asset_text(asset: StaticTextAsset, index: int) -> str:
    name = record_kind(index)
    try:
        block = asset.blocks[name]
    except KeyError as error:
        raise ValueError(f"dungeon-location asset is missing {name}") from error
    if block.storage != "bytes":
        raise ValueError(f"dungeon-location block {name} is not byte text")
    raw = asset.data[block.offset : block.offset + block.size].rstrip(b"\x00")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError(f"dungeon-location block {name} is not ASCII") from error
    if not text:
        raise ValueError(f"dungeon-location block {name} is empty")
    return text


def build_saveload_dungeon_records(
    asset: StaticTextAsset,
    canonical: bytes,
    codes: Mapping[str, int],
    advances: Mapping[str, int],
) -> tuple[tuple[int, ...], ...]:
    """Encode complete one-line save-slot labels from the canonical table."""
    table_end = DUNGEON_TABLE_OFFSET + DUNGEON_RECORD_COUNT * DUNGEON_RECORD_SIZE
    if table_end > len(canonical):
        raise ValueError("canonical dungeon-location table exceeds MAZE.BIN")
    expected_blocks = {record_kind(index) for index in range(DUNGEON_RECORD_COUNT)}
    if set(asset.blocks) != expected_blocks:
        missing = sorted(expected_blocks - set(asset.blocks))
        extra = sorted(set(asset.blocks) - expected_blocks)
        raise ValueError(
            "dungeon-location asset block mismatch: "
            f"missing={missing or 'none'}, extra={extra or 'none'}"
        )

    records = []
    for index in range(DUNGEON_RECORD_COUNT):
        offset = DUNGEON_TABLE_OFFSET + index * DUNGEON_RECORD_SIZE
        floor = int.from_bytes(canonical[offset : offset + 1], "big", signed=True)
        text = format_dungeon_location(_asset_text(asset, index), floor)
        missing = sorted(set(text) - set(codes))
        if missing:
            raise ValueError(
                f"dungeon save label {index} has unsupported characters {missing}"
            )
        width = sum(advances[character] for character in text)
        if width > SAVELOAD_DUNGEON_PIXEL_LIMIT:
            raise ValueError(
                f"dungeon save label {index} is {width}px, limit is "
                f"{SAVELOAD_DUNGEON_PIXEL_LIMIT}px: {text!r}"
            )
        encoded = tuple(codes[character] for character in text)
        if len(encoded) > SAVELOAD_DUNGEON_CELLS:
            raise ValueError(
                f"dungeon save label {index} uses {len(encoded)} cells, limit is "
                f"{SAVELOAD_DUNGEON_CELLS}: {text!r}"
            )
        records.append(
            encoded + (PADDING_CODE,) * (SAVELOAD_DUNGEON_CELLS - len(encoded))
        )
    return tuple(records)


def validate_dungeon_prefix_mirror(
    canonical: bytes,
    mirror: bytes,
    mirror_offset: int,
    mirror_name: str,
) -> None:
    """Require a SAVE/LOAD table to retain MAZE's floor/name index contract."""
    mirror_end = mirror_offset + DUNGEON_RECORD_COUNT * DUNGEON_RECORD_SIZE
    if mirror_offset < 0 or mirror_end > len(mirror):
        raise ValueError(f"{mirror_name}: dungeon-location table is out of bounds")
    for index in range(DUNGEON_RECORD_COUNT):
        canonical_offset = DUNGEON_TABLE_OFFSET + index * DUNGEON_RECORD_SIZE
        target_offset = mirror_offset + index * DUNGEON_RECORD_SIZE
        expected = canonical[canonical_offset : canonical_offset + DUNGEON_TEXT_BYTES]
        actual = mirror[target_offset : target_offset + DUNGEON_TEXT_BYTES]
        if actual != expected:
            raise ValueError(
                f"{mirror_name}: dungeon record {index} does not match MAZE.BIN"
            )
