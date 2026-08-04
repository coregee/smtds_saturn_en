"""Static EVENT target and reserved runtime-address contract."""

from pathlib import Path

from engine.script.patching import BinaryTarget

EVENT_BASE = 0x06020000
EVENT_TARGET = BinaryTarget("EVENT.BIN", Path("EVENT.BIN"), EVENT_BASE)
# The fusion-menu runtime grows upward from 0x06021800.  Reserve the final
# 68-byte zero tail for the only fusion-confirmation record that cannot fit in
# the stock table after it is converted to pointer-based storage.
FUSION_CONFIRMATION_OVERFLOW_ADDRESS = 0x06022FBC
PACKED_FETCH_ADDRESS = 0x06023000
