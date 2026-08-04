from text.script.dialects.model import DialectSpec, TextDialect

COMBAT_DIALECT = DialectSpec(
    kind=TextDialect.COMBAT,
    insert_ops=frozenset(
        {
            0x8010,
            *range(0x8012, 0x8018),
        }
    ),
    named_insert_tokens={
        0x8010: "demon_name",
        0x8012: "race",
        0x8013: "requested_item",
        0x8014: "offered_item",
        0x8015: "codename",
        0x8016: "kyouji_name",
        0x8017: "rei_name",
    },
    inline_pause_tokens={
        0x8003: "{WAIT}",
        0x8004: "{BEAT}",
    },
)
