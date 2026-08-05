"""Full generated character, demon, and race insertions for MSGR.COF."""

import struct

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.generated_asset import load_runtime_ui
from engine.script.msgr.model import MSGR_TARGET
from engine.script.patching import BytePatch, PatchGroup
from engine.script.status_ui.runtime import (
    build_dialogue_character_insert,
    build_dialogue_inserts,
)
from engine.script.text_render.font8_metrics import font8_metrics
from engine.script.text_render.font_metrics import font16_metrics

RUNTIME_ADDRESS = 0x06065000
RUNTIME_LIMIT = 0x06066500

CHARACTER_INSERT_POINTER = 0x0606F17C
CHARACTER_INSERT_STOCK = 0x0606F454
DEMON_INSERT_POINTER = 0x0606F188
DEMON_INSERT_STOCK = 0x0606F8F8
RACE_INSERT_POINTER = 0x0606F198
RACE_INSERT_STOCK = 0x0606FA9C

CURRENT_DEMON_IDS = 0x0607A8C8
RACE_ID_HELPER = 0x0606B680
INSERT_STATE = 0x0607A434
INSERT_ACTIVE = 0x0607959C
STREAM_PUSH = 0x0606EF54
STREAM_POINTER = 0x0607A450
STREAM_STATUS = 0x0607A8D0
TEXT_FLAGS = 0x06079894


def _indexed_terms(rows: object, count: int, label: str) -> tuple[str, ...]:
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError(f"MSGR needs {count} {label} rows")
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("record") != index:
            raise ValueError(f"MSGR {label} row {index} is invalid")
        text = row.get("tr")
        if not isinstance(text, str) or not text:
            raise ValueError(f"MSGR {label} row {index} is untranslated")
        result.append(text)
    return tuple(result)


def _race_terms(rows: object) -> tuple[str, ...]:
    if not isinstance(rows, list):
        raise ValueError("MSGR status table section is invalid")
    races = tuple(
        row.get("tr")
        for row in rows
        if isinstance(row, dict) and row.get("table") == "races"
    )
    if len(races) != 43 or not all(isinstance(text, str) and text for text in races):
        raise ValueError("MSGR needs 43 translated race rows")
    return races  # type: ignore[return-value]


def build_runtime(
    demon_names: tuple[str, ...],
    character_names: tuple[str, ...],
    races: tuple[str, ...],
    codes8: dict[str, int] | None = None,
    codes16: dict[str, int] | None = None,
    engine_context: EngineBuildContext = DEFAULT_CONTEXT,
) -> tuple[bytes, dict[str, int]]:
    """Pack the source-bound tables and shared VM adapters into one cave."""
    if codes8 is None:
        _widths8, codes8 = font8_metrics()
    if codes16 is None:
        metrics = font16_metrics()
        codes16 = {}
        for row in metrics["glyphs"]:
            for text in (row["text"], *row.get("aliases", ())):
                if len(text) == 1:
                    codes16.setdefault(text, row["code"])
    names = (*demon_names, *character_names)
    data = bytearray(2 * len(names))
    name_pool_address = RUNTIME_ADDRESS + len(data)
    name_pool = bytearray()
    offsets: dict[str, int] = {}
    for index, name in enumerate(names):
        offset = offsets.get(name)
        if offset is None:
            offset = len(name_pool)
            offsets[name] = offset
            try:
                name_pool.extend(codes8[character] for character in name)
            except KeyError as error:
                raise ValueError(
                    f"MSGR name {name!r} uses unsupported FONT8 character "
                    f"{error.args[0]!r}"
                ) from error
            name_pool.append(0)
        if offset > 0xFFFF:
            raise ValueError("MSGR name pool exceeds 16-bit offsets")
        struct.pack_into(">H", data, index * 2, offset)
    data.extend(name_pool)
    data.extend(bytes((-(RUNTIME_ADDRESS + len(data))) % 4))

    race_table_address = RUNTIME_ADDRESS + len(data)
    race_table_offset = len(data)
    data.extend(bytes(4 * len(races)))
    for index, race in enumerate(races):
        pointer = RUNTIME_ADDRESS + len(data)
        struct.pack_into(">I", data, race_table_offset + index * 4, pointer)
        try:
            glyphs = tuple(codes16[character] for character in race)
        except KeyError as error:
            raise ValueError(
                f"MSGR race {race!r} uses unsupported FONT16 character "
                f"{error.args[0]!r}"
            ) from error
        data.extend(struct.pack(f">{len(glyphs) + 1}H", *glyphs, 0x8000))
    data.extend(bytes((-(RUNTIME_ADDRESS + len(data))) % 4))

    code_address = RUNTIME_ADDRESS + len(data)
    code, labels = build_dialogue_inserts(
        code_address,
        RUNTIME_ADDRESS,
        name_pool_address,
        race_table_address,
        demon_names=demon_names,
        character_names=character_names,
        current_demon_ids=CURRENT_DEMON_IDS,
        race_id_helper=RACE_ID_HELPER,
        insert_state=INSERT_STATE,
        insert_active=INSERT_ACTIVE,
        stream_push=STREAM_PUSH,
        stream_pointer=STREAM_POINTER,
        stream_status=STREAM_STATUS,
        text_flags=TEXT_FLAGS,
        stock_demon_insert=DEMON_INSERT_STOCK,
        stock_race_insert=RACE_INSERT_STOCK,
        insert_buffer=None,
        context="MSGR dialogue inserts",
        engine_context=engine_context,
    )
    data.extend(code)
    data.extend(bytes((-(RUNTIME_ADDRESS + len(data))) % 4))
    character_address = RUNTIME_ADDRESS + len(data)
    character_code, character_labels = build_dialogue_character_insert(
        character_address,
        character_offsets=RUNTIME_ADDRESS + len(demon_names) * 2,
        name_pool=name_pool_address,
        insert_state=INSERT_STATE,
        insert_buffer=labels["insert_buffer"],
        name_copy=labels["name_copy"],
        name_cleanup=labels["name_cleanup"],
        context="MSGR dialogue character insert",
    )
    data.extend(character_code)
    labels.update(character_labels)
    if RUNTIME_ADDRESS + len(data) > RUNTIME_LIMIT:
        raise ValueError(
            "MSGR dialogue insertion runtime exceeds its verified zero window"
        )
    return bytes(data), labels


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    contract = load_runtime_ui(context)
    demon_names = _indexed_terms(contract.section("demon_names"), 319, "demon")
    character_names = _indexed_terms(
        contract.section("character_names"), 6, "character"
    )
    races = _race_terms(contract.section("status_tables"))
    _widths8, codes8 = font8_metrics(context.font_generated_root / "font8_metrics.json")
    metrics16 = font16_metrics(context.font_generated_root / "font16_metrics.json")
    codes16 = {}
    for row in metrics16["glyphs"]:
        for text in (row["text"], *row.get("aliases", ())):
            if len(text) == 1:
                codes16.setdefault(text, row["code"])
    runtime, labels = build_runtime(
        demon_names,
        character_names,
        races,
        codes8,
        codes16,
        context,
    )
    return PatchGroup(
        "msgr_text",
        MSGR_TARGET,
        (
            BytePatch(
                "dialogue_full_term_runtime",
                RUNTIME_ADDRESS,
                bytes(len(runtime)),
                runtime,
            ),
            BytePatch(
                "dialogue_character_name_insert",
                CHARACTER_INSERT_POINTER,
                struct.pack(">I", CHARACTER_INSERT_STOCK),
                struct.pack(">I", labels["dialogue_character_name_insert"]),
            ),
            BytePatch(
                "dialogue_demon_name_insert",
                DEMON_INSERT_POINTER,
                struct.pack(">I", DEMON_INSERT_STOCK),
                struct.pack(">I", labels["dialogue_demon_name_insert"]),
            ),
            BytePatch(
                "dialogue_race_insert",
                RACE_INSERT_POINTER,
                struct.pack(">I", RACE_INSERT_STOCK),
                struct.pack(">I", labels["dialogue_race_insert"]),
            ),
        ),
    )
