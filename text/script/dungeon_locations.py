"""Schema for the generated dungeon-location contract consumed by the engine."""

from pathlib import Path

SOURCE_PATH = Path("MAZE.BIN")
ASSET_PATH = Path("locations") / "MAZE_AUTOMAP.json"
RECORD_COUNT = 144
RECORD_SIZE = 0x20
TABLE_OFFSET = 0x2532C
TEXT_OFFSET = 2
TEXT_WORDS = 5
TEXT_BYTES = TEXT_OFFSET + TEXT_WORDS * 2


def record_kind(index: int) -> str:
    if not 0 <= index < RECORD_COUNT:
        raise ValueError(f"dungeon-location record index is out of range: {index}")
    return f"location_{index:03d}"
