"""Immutable CONFIG target, layout, and table definitions."""

from pathlib import Path

from engine.script.config_menu.sort_order import SORT_COMPOUNDS
from engine.script.patching import BinaryTarget

BASE = 0x06020000

TARGET = BinaryTarget("CFG_SET.BIN", Path("CFG_SET.BIN"), BASE)

ORIGINAL_SHA256 = "9a07600dd73031c3e95ece81e1d7dc108b4fce35bcea565402006bb9d6cad0da"

CAVE_FILE = 0x1900

CAVE_ADDR = BASE + CAVE_FILE

LABEL_TABLE_FILE = 0x0400

LABEL_TABLE_ADDR = BASE + LABEL_TABLE_FILE

ACTIVE_RENDER_FILE = 0x0700

ACTIVE_RENDER_ADDR = BASE + ACTIVE_RENDER_FILE

ACTIVE_CACHE_FILE = 0x0900

ACTIVE_CACHE_ADDR = BASE + ACTIVE_CACHE_FILE

MAGIC_SORT_TABLE_FILE = 0x0904

MAGIC_SORT_TABLE_ADDR = BASE + MAGIC_SORT_TABLE_FILE

ITEM_SORT_TABLE_FILE = 0x0984

ITEM_SORT_TABLE_ADDR = BASE + ITEM_SORT_TABLE_FILE

ACTION_VWF_FILE = 0x0A00

ACTION_VWF_ADDR = BASE + ACTION_VWF_FILE

COMPOUND_GLYPH_FILE = 0x2000

COMPOUND_GLYPH_ADDR = BASE + COMPOUND_GLYPH_FILE

LABEL_RECORDS = 19

LABEL_CELLS = 16

STOCK_LABEL_TABLE_FILE = 0x9E2A

LABEL_STRIDE_SITES = (0x6C58, 0x6D0A, 0x6D7E, 0x76B2)

LABEL_TABLE_POINTERS = (0x6CC8, 0x6D40, 0x6DB4, 0x77CC)

ITEM_SORT_POINTER = 0x7504

ROW_RENDER_POINTERS = (0x7400,)

ACTIVE_RENDER_POINTERS = (0x7624,)

STOCK_GLYPH = 0x06027B64

GLYPH_POOL_FILE = 0x7ED4

ADVANCE_SITE_FILE = 0x7EB0

ACTION_GLYPH = 0x06027C20

ACTION_GLYPH_POOL_FILE = 0x7F38

ACTION_ADVANCE_SITE_FILE = 0x7F14

ACTION_ATLAS_FILE = 0x1000

ACTION_ATLAS_ADDR = BASE + ACTION_ATLAS_FILE

STOCK_ACTION_ATLAS_ADDR = BASE + 0xA048

ACTION_ATLAS_POINTER = 0x7CC8

ACTION_CAPACITY = 64

COMPOUND_TEXT = ("AR", " A", "ign", *SORT_COMPOUNDS)

COMPOUND_CODES = {text: 1848 + index for index, text in enumerate(COMPOUND_TEXT)}

LABEL_BLOCKS = (
    (0x9E3A, "battle_messages"),
    (0x9E4A, "auto_map"),
    (0x9E5A, "party_panel"),
    (0x9E6A, "demon_analyze"),
    (0x9E7A, "sound"),
    (0x9E8A, "magic_order"),
    (0x9E9A, "item_order"),
    (0x9EAA, "speed_fast"),
    (0x9EBA, "speed_normal"),
    (0x9ECA, "speed_slow"),
    (0x9EDA, "party_fixed"),
    (0x9EEA, "party_free"),
    (0x9EFA, "graph"),
    (0x9F0A, "max"),
    (0x9F1A, "display_normal"),
    (0x9F2A, "display_reverse"),
    (0x9F3A, "stereo"),
    (0x9F4A, "mono"),
)

PAGE2_BLOCKS = (
    (0x9F6A, "controls"),
    (0x9F7C, "mode_normal"),
    (0x9F8E, "mode_custom"),
)

ASSIST_BLOCKS = (
    "assist_item",
    "assist_gem",
    "assist_equip",
)

SORT_RECORD_CELLS = 16

ACTION_BLOCKS = (
    (0x42B46, "action_full_cancel"),
    (0x42B56, "action_cancel"),
    (0x42B66, "action_confirm"),
    (0x42B76, "action_help"),
    (0x42B86, "action_recover"),
    (0x42B96, "action_command"),
    (0x42BA6, "action_auto_map"),
    (0x42BB6, "action_analyze"),
)

FOOTER_BLOCKS = (
    (0x42BD6, "footer_assign"),
    (0x42BE8, "footer_finish"),
)

MODE_COUNT_SITES = (
    0x8A08,
    0x8A2A,
    0x8A44,
    0x8AA2,
    0x8ABC,
    0x8AF2,
    0x8B0A,
    0x8B58,
    0x8B74,
)
