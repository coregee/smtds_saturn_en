from text.script.dialects.combat import COMBAT_DIALECT
from text.script.dialects.event import EVENT_DIALECT
from text.script.dialects.model import DialectSpec, TextDialect

DIALECTS = {
    TextDialect.EVENT: EVENT_DIALECT,
    TextDialect.COMBAT: COMBAT_DIALECT,
}
NAMED_INSERT_TOKENS = frozenset(
    name
    for dialect in DIALECTS.values()
    for name in dialect.named_insert_tokens.values()
)


def get_dialect(kind: TextDialect) -> DialectSpec:
    return DIALECTS[kind]


__all__ = [
    "COMBAT_DIALECT",
    "DIALECTS",
    "EVENT_DIALECT",
    "NAMED_INSERT_TOKENS",
    "DialectSpec",
    "TextDialect",
    "get_dialect",
]
