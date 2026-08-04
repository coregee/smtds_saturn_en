"""Import-safe storage contract for player-entered names."""

from dataclasses import dataclass
from enum import IntEnum

MAX_NAME_LENGTH = 8
ROW_WORDS = MAX_NAME_LENGTH + 1
ROW_STRIDE = ROW_WORDS * 2
TERMINATOR = 0x8000

NAME_FW = 0x0023FDF0
NAME_FW_FULL = 0x0023FE50
CODENAME_BYTES = 0x0023FFD0


class NameField(IntEnum):
    FIRST = 1
    LAST = 2
    CODENAME = 3
    CITY = 4
    WARD = 5


@dataclass(frozen=True)
class NameFieldSpec:
    field: NameField
    key: str
    stage_address: int
    insert_opcode: int

    @property
    def runtime_address(self) -> int:
        return NAME_FW + (self.field - 1) * ROW_STRIDE


NAME_FIELDS = (
    NameFieldSpec(NameField.FIRST, "first", 0x002029E0, 0x8006),
    NameFieldSpec(NameField.LAST, "last", 0x002029E8, 0x8007),
    NameFieldSpec(NameField.CODENAME, "codename", 0x002029D8, 0x8023),
    NameFieldSpec(NameField.CITY, "city", 0x002029F0, 0x801C),
    NameFieldSpec(NameField.WARD, "ward", 0x002029F8, 0x801B),
)
FIELD_BY_KIND = {spec.field: spec for spec in NAME_FIELDS}
FIELD_BY_OPCODE = {spec.insert_opcode: spec for spec in NAME_FIELDS}
