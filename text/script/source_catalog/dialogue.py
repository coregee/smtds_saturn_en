"""EVENT and combat-dialogue source declarations."""

from pathlib import Path

from text.script.profiles import COMBAT_DIALOGUE, EVENT_DIALOGUE, TextFont
from text.script.source_models import EveSource

EVFILE0_FORCED_RAW = frozenset(
    {
        33,
        34,
        35,
        57,
        58,
        60,
        240,
        258,
        259,
        272,
    }
)
SHOPSMP_FUSION_MENU = frozenset(range(68, 79)) | frozenset(range(105, 109))
# The outer Gouma-den choice reads Talk, Demon Fusion, and Exit directly as
# FONT16 words. Keep all three explicit because the script-menu heuristic does
# not discover message 274 (Talk).
SHOPSMP_GOMADEN_MENU = frozenset(range(272, 275))
# The Bioenergy Association's MAG exchange controller reads these three option
# records directly as FONT16 words rather than through the EVENT text VM.
SHOPSMP_MAG_EXCHANGE_MENU = frozenset({773, 774, 779})
SHOPSMP_FUSION_CHART_TITLES = frozenset(range(83, 87))
# Search's three option panes pass UI codes through the stock lookup at
# 0x06067cb4, then read these SHOPSMP records as literal FONT12 words:
#   0x0e-0x10 -> messages 81, 82, 78
#   0x11-0x16 -> messages 83-87, 78
#   0x17-0x19 -> messages 88, 89, 78
# The chart titles are declared separately above; these are the remaining
# Search-only labels that must never enter EVENT compression. Messages 90-97
# are the sort choices rendered by 0x06044b70, while 102-104 are the literal
# Sort Order, Fusion Type, and Result Demon headings used by 0x06044f40,
# 0x0604588c, and 0x06045dac.
SHOPSMP_FUSION_SEARCH = (
    frozenset({81, 82}) | frozenset(range(87, 98)) | frozenset(range(102, 105))
)
# The triad preview passes demon ID zero when the selected demons have no valid
# result. Its name drawer falls back to the stock path, which selects local
# record 100. The runtime table base makes that SHOPSMP message 101, read as
# literal FONT12 words; compression turns packed Latin pairs into glyph IDs.
SHOPSMP_FUSION_RESULT_STATUS = frozenset({101})
# Messages 138-266 are not EVENT-VM dialogue. Gouma-den indexes them directly
# as Guide lines, compact race labels, and Search/chart cells. Packing those
# words makes the direct readers interpret compression tokens as glyph IDs.
SHOPSMP_FUSION_DIRECT = frozenset(range(138, 267))
SHOPSMP_FONT12_MESSAGES = (
    SHOPSMP_FUSION_MENU
    | SHOPSMP_FUSION_CHART_TITLES
    | SHOPSMP_FUSION_SEARCH
    | SHOPSMP_FUSION_RESULT_STATUS
    | frozenset(range(109, 138))
    | SHOPSMP_FUSION_DIRECT
)


def event_source(
    filename: str,
    *,
    table_offset: int = 0x4800,
    forced_raw_messages: frozenset[int] = frozenset(),
    font_overrides: tuple[tuple[int, TextFont], ...] = (),
) -> EveSource:
    return EveSource(
        name=Path(filename).stem.casefold(),
        path=Path(filename),
        default_profile=EVENT_DIALOGUE,
        table_offset=table_offset,
        body_offset=0x5000,
        corpus_path=Path("eve") / f"{filename}.json",
        detect_menu_readers=True,
        forced_raw_messages=forced_raw_messages,
        font_overrides=font_overrides,
    )


def combat_source(filename: str) -> EveSource:
    return EveSource(
        name=Path(filename).stem.casefold(),
        path=Path("COMBDATA") / filename,
        default_profile=COMBAT_DIALOGUE,
        table_offset=0x4800,
        body_offset=0x5000,
        corpus_path=Path("eve") / f"{filename}.json",
    )


EVE_SOURCES = (
    event_source("MESFILE.EVE"),
    event_source("EVFILE_0.EVE", forced_raw_messages=EVFILE0_FORCED_RAW),
    event_source("EVFILE_1.EVE"),
    event_source("EVFILE_2.EVE"),
    event_source(
        "SHOPSMP.EVE",
        table_offset=0x47FE,
        forced_raw_messages=(
            SHOPSMP_FUSION_MENU
            | SHOPSMP_GOMADEN_MENU
            | SHOPSMP_MAG_EXCHANGE_MENU
            | SHOPSMP_FUSION_CHART_TITLES
            | SHOPSMP_FUSION_SEARCH
            | SHOPSMP_FUSION_RESULT_STATUS
            | SHOPSMP_FUSION_DIRECT
        ),
        font_overrides=tuple(
            (message, TextFont.FONT12) for message in SHOPSMP_FONT12_MESSAGES
        ),
    ),
    combat_source("BOSSTALK.EVE"),
    combat_source("TLK_BST.EVE"),
    combat_source("KEMO.EVE"),
    combat_source("TLK_KOFU.EVE"),
    combat_source("NBL_M.EVE"),
    combat_source("TLK_HIRK.EVE"),
    combat_source("TLK_YNGM.EVE"),
    combat_source("GRL.EVE"),
    combat_source("TLK_BOY.EVE"),
    combat_source("CLD_F.EVE"),
    combat_source("TLK_LADY.EVE"),
    combat_source("TLK_CRZY.EVE"),
    combat_source("JIJY.EVE"),
    combat_source("CYNI.EVE"),
    combat_source("TLK_WEST.EVE"),
    combat_source("SLM.EVE"),
)
