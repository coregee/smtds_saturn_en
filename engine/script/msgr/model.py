"""Static MSGR overlay target contract."""

from pathlib import Path

from engine.script.patching import BinaryTarget

MSGR_BASE = 0x06060000
MSGR_TARGET = BinaryTarget("MSGR.COF", Path("MSGR.COF"), MSGR_BASE)
