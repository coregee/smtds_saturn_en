from dataclasses import dataclass
from enum import Enum

from text.script.dialects import TextDialect
from text.script.encoding import EncodingKind
from text.script.layouts import (
    COMBAT_DIALOGUE_LAYOUT,
    EVENT_DIALOGUE_LAYOUT,
    EVENT_MENU_LAYOUT,
    LayoutSpec,
)


class TextReader(Enum):
    TEXT_VM = "text_vm"
    RAW_U16 = "raw_u16"


class TextFont(Enum):
    FONT12 = "font12"
    FONT16 = "font16"


class RuntimeCapability(Enum):
    FONT16_LATIN = "font16_latin"
    FONT8_LATIN = "font8_latin"
    EVENT_VWF = "event_vwf"
    EVENT_PACKED_FETCH = "event_packed_fetch"
    COMBAT_PACKED_FETCH = "combat_packed_fetch"
    COMBAT_VWF = "combat_vwf"
    MSGR_TEXT = "msgr_text"
    NAME_RUNTIME = "name_runtime"
    SAVELOAD_UI = "saveload_ui"
    CONFIG_UI = "config_ui"
    MAP_UI = "map_ui"
    SMALLFONT_VWF = "smallfont_vwf"
    NORMCOM_HELP = "normcom_help"
    ITEMNAME_RUNTIME = "itemname_runtime"
    DUNGEON_LOCATIONS = "dungeon_locations"
    FIXED_TEXT_FIELDS = "fixed_text_fields"
    STATUS_UI = "status_ui"
    HOSI_MESSAGES = "hosi_messages"
    FUSION_MENU = "fusion_menu"


@dataclass(frozen=True)
class TextProfile:
    name: str
    dialect: TextDialect
    reader: TextReader
    font: TextFont
    encodings: tuple[EncodingKind, ...]
    layout: LayoutSpec
    runtime_requirements: frozenset[RuntimeCapability]


EVENT_DIALOGUE = TextProfile(
    name="event_dialogue",
    dialect=TextDialect.EVENT,
    reader=TextReader.TEXT_VM,
    font=TextFont.FONT16,
    encodings=(EncodingKind.PACKED_LATIN,),
    layout=EVENT_DIALOGUE_LAYOUT,
    runtime_requirements=frozenset(
        {
            RuntimeCapability.FONT16_LATIN,
            RuntimeCapability.EVENT_VWF,
            RuntimeCapability.EVENT_PACKED_FETCH,
            RuntimeCapability.MSGR_TEXT,
            RuntimeCapability.NAME_RUNTIME,
        }
    ),
)

EVENT_MENU = TextProfile(
    name="event_menu",
    dialect=TextDialect.EVENT,
    reader=TextReader.RAW_U16,
    font=TextFont.FONT16,
    encodings=(EncodingKind.LATIN_U16,),
    layout=EVENT_MENU_LAYOUT,
    runtime_requirements=frozenset(
        {
            RuntimeCapability.FONT16_LATIN,
            RuntimeCapability.EVENT_VWF,
            RuntimeCapability.MSGR_TEXT,
            RuntimeCapability.NAME_RUNTIME,
        }
    ),
)

COMBAT_DIALOGUE = TextProfile(
    name="combat_dialogue",
    dialect=TextDialect.COMBAT,
    reader=TextReader.RAW_U16,
    font=TextFont.FONT16,
    encodings=(EncodingKind.PACKED_LATIN,),
    layout=COMBAT_DIALOGUE_LAYOUT,
    runtime_requirements=frozenset(
        {
            RuntimeCapability.FONT16_LATIN,
            RuntimeCapability.COMBAT_PACKED_FETCH,
            RuntimeCapability.COMBAT_VWF,
            RuntimeCapability.NAME_RUNTIME,
        }
    ),
)

PROFILE_BY_READER = {
    (profile.dialect, profile.reader): profile
    for profile in (EVENT_DIALOGUE, EVENT_MENU, COMBAT_DIALOGUE)
}


def profile_for_reader(
    dialect: TextDialect,
    reader: TextReader,
) -> TextProfile:
    try:
        return PROFILE_BY_READER[dialect, reader]
    except KeyError as error:
        raise ValueError(
            f"no text profile for {dialect.value}/{reader.value}"
        ) from error
