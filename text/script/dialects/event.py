from text.script.dialects.model import DialectSpec, TextDialect

EVENT_DIALECT = DialectSpec(
    kind=TextDialect.EVENT,
    insert_ops=frozenset(
        {
            0x8006,
            0x8007,
            *range(0x8017, 0x8024),
        }
    ),
    named_insert_tokens={
        0x8006: "first_name",
        0x8007: "last_name",
        0x8017: "drink_name",
        0x8018: "item_name",
        0x8019: "demon_name",
        0x801B: "ward",
        0x801C: "city",
        0x801F: "race",
        0x8022: "event_id",
        0x8023: "codename",
    },
    inline_pause_tokens={
        0x8003: "{WAIT}",
        0x8004: "{NL}",
    },
)
