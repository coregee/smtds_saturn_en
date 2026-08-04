from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class TextDialect(Enum):
    EVENT = "event"
    COMBAT = "combat"


@dataclass(frozen=True)
class DialectSpec:
    kind: TextDialect
    insert_ops: frozenset[int]
    named_insert_tokens: Mapping[int, str]
    inline_pause_tokens: dict[int, str]

    def __post_init__(self) -> None:
        unknown_codes = set(self.named_insert_tokens) - self.insert_ops
        if unknown_codes:
            rendered = ", ".join(f"{code:#06x}" for code in sorted(unknown_codes))
            raise ValueError(f"named tokens are not insert operations: {rendered}")
        names = tuple(self.named_insert_tokens.values())
        if len(set(names)) != len(names):
            raise ValueError(
                f"duplicate named insert token in {self.kind.value} dialect"
            )

    @property
    def named_insert_codes(self) -> dict[str, int]:
        return {name: code for code, name in self.named_insert_tokens.items()}

    def decode_control(self, word: int) -> str:
        if word in self.insert_ops:
            if name := self.named_insert_tokens.get(word):
                return f"{{{name}}}"
            return f"{{INS:{word:04x}}}"
        if word == 0x8001:
            return "{n}"
        if word in self.inline_pause_tokens:
            return self.inline_pause_tokens[word]
        if word in (0x8000, 0x8002, 0x8003):
            return ""
        return f"{{OP:{word:04x}}}"
