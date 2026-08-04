"""Shared COMBAT overlay identity and runtime scratch addresses."""

from pathlib import Path

from engine.script.patching import BinaryTarget

COMBAT_BASE = 0x06020000
COMBAT_TARGET = BinaryTarget("COMBAT.BIN", Path("COMBAT.BIN"), COMBAT_BASE)

# The packed COMBAT consumers share one copy of the EVENT dictionary.  The
# preceding half of the cave is reserved for the dispatcher and its paced
# dialogue entry.
COMBAT_DICTIONARY_ADDRESS = 0x06021200

# Stock COMBAT insert expansion and the battle-dialogue update loop share this
# word queue.  Index 0 is returned immediately; PENDING_FLAG starts at 1 so
# later updates resume with the second word.
COMBAT_PENDING_BUFFER = 0x06073FA8
COMBAT_PENDING_FLAG = 0x06073FD2
COMBAT_PENDING_WORD_CAPACITY = (COMBAT_PENDING_FLAG - COMBAT_PENDING_BUFFER) // 2
