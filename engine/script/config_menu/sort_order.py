"""Import-safe CONFIG magic-sort labels and stock preset order."""

MAGIC_SORT_BLOCKS = (
    "assist_heal",
    "assist_skill",
    "assist_buff",
    "assist_attack_support",
)

MAGIC_SORT_ORDERS = (
    (0, 1, 2, 3),
    (2, 3, 0, 1),
    (0, 2, 1, 3),
)

# The stock CONFIG popup has a five-cell draw budget per row.  These pairs
# compact the translated labels back into that budget; the engine rasterizes
# them into CONFIG-local 16x16 cells rather than consuming global FONT16 slots.
SORT_COMPOUNDS = (
    "Re",
    "co",
    "ve",
    "Sp",
    "ec",
    "At",
    "De",
    "Co",
    "ns",
    "um",
    "ab",
    "le",
    "Eq",
    "ui",
    "pm",
    "en",
)
