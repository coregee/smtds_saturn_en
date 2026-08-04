"""Immutable dungeon-location targets, layout, and mirror inventory."""

from dataclasses import dataclass
from pathlib import Path

from engine.script.patching import BinaryTarget
from text.script.dungeon_locations import (
    SOURCE_PATH as MAZE_SOURCE_PATH,
)
from text.script.dungeon_locations import (
    TABLE_OFFSET as MAZE_TABLE_OFFSET,
)

BASE = 0x06020000

FONT16_BASE = 0x0021A000

TOP_CODE = 0x0740

BOTTOM_CODE = 0x0744

AUTOMAP_ASCII_DRAWER = 0x06026C28

AUTOMAP_RAW_DRAWER = 0x06026CD0

AUTOMAP_NO_DATA_POINTER = 0x06029AA8

AUTOMAP_YES_POINTER = 0x0602A5E0

AUTOMAP_NO_POINTER = 0x0602A5E4

AUTOMAP_ASCII_NO_DATA_DRAWER_SITE = 0x06029BD8

AUTOMAP_ASCII_CHOICES_DRAWER_SITE = 0x0602A694

AUTOMAP_DELETE_DRAWER = 0x0602A6A8

AUTOMAP_DELETE_DRAWER_SITE = 0x0602ACC8

AUTOMAP_DRAW_DESCRIPTOR = 0x06059E70

AUTOMAP_DELETE_SURFACE = 66

LABEL_SENTINEL = 0x7E00

LABEL_GAP = 2

AUTOMAP_MARKER_PIXEL_LIMIT = 112


@dataclass(frozen=True)
class LocationSpec:
    target: BinaryTarget
    source_sha256: str
    table_file: int
    cave_file: int
    cave_limit: int
    hook_file: int
    pool_file: int
    return_address: int
    name_pointer_file: int
    stock_name_drawer: int
    automap: bool


@dataclass(frozen=True)
class LandingSpec:
    path: Path
    source_sha256: str
    record_count: int


@dataclass(frozen=True)
class KaiSpec:
    path: Path
    source_sha256: str
    name_offsets: tuple[int, ...]


SPECS = (
    LocationSpec(
        BinaryTarget(MAZE_SOURCE_PATH.name, MAZE_SOURCE_PATH, BASE),
        "38d8a919d2d17461fc2c2ee8b41093efc893fc72d4e7eb5db243fe84560cc229",
        MAZE_TABLE_OFFSET,
        0x0400,
        0x2800,
        0x20062,
        0x200E0,
        0x0604010C,
        0x1FD34,
        0x0603FEA0,
        False,
    ),
    LocationSpec(
        BinaryTarget("AUTOMAPC.BIN", Path("AUTOMAPC.BIN"), BASE),
        "093b6e57f5c91d4c0b6b3cac428a4e5e15d51d29a6e2f2a5a93c9cc0af329593",
        0x3A418,
        0x0400,
        0x6500,
        0x09B36,
        0x09BD4,
        0x06029B98,
        0x09BCC,
        0x06026CD0,
        True,
    ),
)

LANDING_RECORD_START = 0x5C

KAI_NAME_START = 0x12

KAI_RECORD_SIZE = 0x28

KAI_FILE_COUNT = 98

KAI_RECORD_COUNT = 232

KAI_SOURCE_CATALOG_SHA256 = (
    "48eb224fbd6cccbdcb182099485116c4c92b3f85c4f0d44fb92039e1593ffd6a"
)

LANDING_SPECS = (
    LandingSpec(
        Path("MAZEDATA/HDENELV0.BIN"),
        "b9fac939fad6b48d97eb75f3ac48f27b03eaf10235b9318e8b807cd4e752d56d",
        2,
    ),
    LandingSpec(
        Path("MAZEDATA/IDENELV0.BIN"),
        "8825527a84f68aa44372f20df46d3c78885ea420676f79594aecc905c75a2914",
        5,
    ),
    LandingSpec(
        Path("MAZEDATA/IDENELV1.BIN"),
        "460075617dd2ff14f6eb9b6e7a9b7d2af2eac13d08452247ce2ec4fed46bc1e3",
        5,
    ),
    LandingSpec(
        Path("MAZEDATA/IDENELV2.BIN"),
        "9ff5f1739af2991c5ee2e1c938296e74d94716a639e46737d5edb649fff15612",
        3,
    ),
    LandingSpec(
        Path("MAZEDATA/IDENELV3.BIN"),
        "ccdeecaac20ef6688d8fc95ccb5cfe13ab9715c767df0151c619cea47453c0ea",
        3,
    ),
    LandingSpec(
        Path("MAZEDATA/IMANELV0.BIN"),
        "655d4b0443bf7c08122a8081bb6680adb25be07421c9720dd92175e4e9bb3791",
        4,
    ),
    LandingSpec(
        Path("MAZEDATA/IMANELV1.BIN"),
        "3383ecd56d52d5f658033c5f7c71d9722977bc75ad3a2b753cb002077422afbe",
        2,
    ),
    LandingSpec(
        Path("MAZEDATA/ISTELV0.BIN"),
        "18491db357191c46703407ad48a6353bb5ea966dc095a4984c8ecdc69cc1d344",
        4,
    ),
    LandingSpec(
        Path("MAZEDATA/ITOSELV.BIN"),
        "cdca74c1be78f136fb523df1a904ceed271fb6baebc6962bdea6de9d23bb7934",
        5,
    ),
    LandingSpec(
        Path("MAZEDATA/ITVELV0.BIN"),
        "8c72178aaf9084715a77e6af522d8f240d56f9551343ee982dec8f9bc0e44b15",
        3,
    ),
    LandingSpec(
        Path("MAZEDATA/ITVELV1.BIN"),
        "f24300805a92d1d314ea26be6def833edcb07788123fe1578f214f0e8b1362f2",
        3,
    ),
    LandingSpec(
        Path("MAZEDATA/KUMIELV0.BIN"),
        "20b0374f444f00a45b85f066a43db3dd425614c23ffe4222ad015731dbe5ee60",
        3,
    ),
    LandingSpec(
        Path("MAZEDATA/SHIELV0.BIN"),
        "8a3b116c424d4aa30774236f1dd3e1d8d0df8a23ec1d51cb9aba5649f06162be",
        5,
    ),
    LandingSpec(
        Path("MAZEDATA/SHIELV1.BIN"),
        "690618fd69f8e6045c09b26ee2dce47d383feb05c83368194dfbbc8b8b407fe2",
        3,
    ),
    LandingSpec(
        Path("MAZEDATA/SHIELV2.BIN"),
        "8a18877199f4b35c8a77c3641d5cfae669066682b40eeff57f3f4740f73646b3",
        2,
    ),
    LandingSpec(
        Path("MAZEDATA/SHIELV3.BIN"),
        "9199078a70da4bf7b1e3158bc5bd4df14fc1f073ef84dc444e2c853ff704468f",
        2,
    ),
    LandingSpec(
        Path("MAZEDATA/SHIELV4.BIN"),
        "ee446776cde04c15ff3c14648a0a6ae40debbcf3f8e872dd2d35033075c2c0b0",
        2,
    ),
)
