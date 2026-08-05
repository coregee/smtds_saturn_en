from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class WidthUnit(Enum):
    NONE = "none"
    PIXELS = "pixels"


@dataclass(frozen=True)
class LayoutSpec:
    name: str
    width: int | None
    width_unit: WidthUnit
    lines_per_page: int
    surface_width: int | None = None
    left_margin: int = 0
    right_margin: int = 0
    default_insert_width: int = 0
    insert_widths: Mapping[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.surface_width is None:
            if self.left_margin or self.right_margin:
                raise ValueError("layout margins require a surface width")
            return
        if self.surface_width <= 0:
            raise ValueError("layout surface width must be positive")
        if self.left_margin < 0 or self.right_margin < 0:
            raise ValueError("layout margins cannot be negative")
        if (
            self.width is not None
            and self.width_unit is WidthUnit.PIXELS
            and self.left_margin + self.width + self.right_margin != self.surface_width
        ):
            raise ValueError(
                "pixel layout width and margins must fill the declared surface"
            )

    def insert_width(self, operation: int) -> int:
        return self.insert_widths.get(operation, self.default_insert_width)
