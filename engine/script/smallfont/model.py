"""Immutable target and drawer contracts for the shared small-font runtime."""

from dataclasses import dataclass
from pathlib import Path

from engine.script.patching import BinaryTarget

BASE = 0x06020000
NORMCOM_PANEL_CAVE_OFFSET = 0x5F34
NORMCOM_PANEL_CAVE_LIMIT = 0x6500


@dataclass(frozen=True)
class DrawerSpec:
    name: str
    stride: int
    string_first: bool
    pointer_sites: tuple[int, ...]
    stock_drawer: int
    packed_full_names: bool = False


@dataclass(frozen=True)
class OverlaySpec:
    target: BinaryTarget
    cave_offset: int
    stock_wrapper: int
    drawers: tuple[DrawerSpec, ...]


OVERLAYS = (
    OverlaySpec(
        BinaryTarget("NORMCOM.BIN", Path("NORMCOM.BIN"), BASE),
        0x0400,
        0x06027A08,
        (
            DrawerSpec(
                "panel",
                0x0200,
                True,
                (0x06029064, 0x06029360, 0x060295E4),
                0x060298B4,
            ),
            DrawerSpec(
                "mag_grid",
                0x0140,
                False,
                (0x0602DD6C, 0x0602DE48),
                0x0602DE50,
                True,
            ),
        ),
    ),
    OverlaySpec(
        BinaryTarget("COMBAT.BIN", Path("COMBAT.BIN"), BASE),
        0x0400,
        0x06046BD0,
        (
            DrawerSpec(
                "panel",
                0x0200,
                True,
                (0x0604C530, 0x0604CAB0, 0x0604C82C),
                0x0604CD80,
            ),
        ),
    ),
    OverlaySpec(
        BinaryTarget("MAZE.BIN", Path("MAZE.BIN"), BASE),
        0x2800,
        0x0603E5E0,
        (
            DrawerSpec(
                "panel",
                0x0200,
                True,
                (0x0603F364, 0x0603F660, 0x0603F8E4),
                0x0603FBB4,
            ),
        ),
    ),
)
