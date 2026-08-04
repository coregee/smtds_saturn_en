"""Recovered Gouma-den fusion-screen data contracts."""

from collections.abc import Mapping

LIST_ROW_WIDTH = 96
PREVIEW_NAME_WIDTH = 96
PREVIEW_RACE_WIDTH = 24
TABLE_NAME_WIDTH = 96
TABLE_RACE_WIDTH = 40
CHART_CELL_WIDTH = 26
TABLE_FONT8_Y_OFFSET = 2
TABLE_FONT8_MODE = 4
GUIDE_FIRST_MESSAGE = 139
GUIDE_LAST_MESSAGE = 151
GUIDE_STOCK_ROWS = 10
GUIDE_ROW_HEIGHT = 15
GUIDE_DESCRIPTION_Y = GUIDE_STOCK_ROWS * GUIDE_ROW_HEIGHT
GUIDE_LINE_WIDTH = 320
# The narrowest configured FONT8 advance is three pixels. This guard therefore
# permits every glyph that can fit on the 320-pixel Guide surface while keeping
# a finite bound if a malformed direct record lacks its 0x8000 terminator.
GUIDE_GLYPH_LIMIT = GUIDE_LINE_WIDTH // 3
HELP_FIRST_MESSAGE = 152
HELP_LAST_MESSAGE = 160
HELP_START_X = 36
HELP_LINE_WIDTH = 320 - HELP_START_X
# Help uses the same three-pixel minimum FONT8 advance as Guide, but its direct
# reader starts at x=36 rather than the left edge of the 320-pixel surface.
HELP_GLYPH_LIMIT = HELP_LINE_WIDTH // 3
RACE_WORD_BASE = 219
PLAYER_NAME_ID = 0x8000

# The result preview places the race at x=72 and the demon name at x=96.
# These unique screen-local abbreviations retain the stock 24-pixel field.
FUSION_RACE_LABELS = (
    "DE",
    "MG",
    "HR",
    "AV",
    "TR",
    "EN",
    "GE",
    "AT",
    "HO",
    "EL",
    "MI",
    "HE",
    "FU",
    "LA",
    "KI",
    "DG",
    "DV",
    "FL",
    "YO",
    "FY",
    "SN",
    "BE",
    "UM",
    "JI",
    "NI",
    "FA",
    "BR",
    "FE",
    "VI",
    "RA",
    "WO",
    "RE",
    "WI",
    "JA",
    "HA",
    "VE",
    "TY",
    "DR",
    "GH",
    "SP",
    "FO",
    "ZO",
    "HU",
)


def measure_font12(text: str, codes: Mapping[str, int], widths: bytes) -> int:
    """Measure a fusion-screen string with the runtime FONT12 advances."""
    try:
        return sum(widths[codes[character]] for character in text)
    except KeyError as error:
        raise ValueError(
            f"unsupported FONT12 character {error.args[0]!r} in {text!r}"
        ) from error


def truncate_font8(
    text: str,
    codes: Mapping[str, int],
    widths: bytes,
    maximum: int,
) -> tuple[str, int]:
    """Return the longest prefix whose generated FONT8 advance fits."""
    output = []
    width = 0
    for character in text:
        try:
            advance = widths[codes[character]] + (character != " ")
        except KeyError as error:
            raise ValueError(
                f"unsupported FONT8 character {error.args[0]!r} in {text!r}"
            ) from error
        if width + advance > maximum:
            break
        output.append(character)
        width += advance
    return "".join(output), width
