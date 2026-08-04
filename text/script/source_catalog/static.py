"""Static-overlay and dungeon-location source declarations."""

from pathlib import Path

from text.script.dungeon_locations import (
    ASSET_PATH,
    RECORD_COUNT,
    RECORD_SIZE,
    SOURCE_PATH,
    TABLE_OFFSET,
    TEXT_OFFSET,
    TEXT_WORDS,
    record_kind,
)
from text.script.formats.static_overlay.model import (
    PADDING_CODE,
    AsciiString,
    FixedCells,
    FixedRows,
    IndexedWords,
    SplitLines,
    StaticRecordSpec,
    TextSpan,
)
from text.script.profiles import RuntimeCapability
from text.script.source_models import StaticOverlaySource

CFG_ACTION_GLYPHS = (
    "",
    "オ",
    "ー",
    "ト",
    "マ",
    "ッ",
    "プ",
    "デ",
    "ビ",
    "ル",
    "ア",
    "ナ",
    "ラ",
    "イ",
    "ズ",
    "リ",
    "カ",
    "バ",
    "コ",
    "ン",
    "ド",
    "キ",
    "ャ",
    None,
    "セ",
    "決",
    "定",
    "ヘ",
    "表",
    "示",
    "ジ",
)
CFG_ACTION_DECODER = IndexedWords(CFG_ACTION_GLYPHS)


DUNGEON_LOCATION_RECORDS = tuple(
    StaticRecordSpec(
        kind=record_kind(index),
        spans=(
            TextSpan(
                TABLE_OFFSET + index * RECORD_SIZE + TEXT_OFFSET,
                TEXT_WORDS,
            ),
        ),
        layout=AsciiString(max_bytes=64),
    )
    for index in range(RECORD_COUNT)
)


STATIC_SOURCES = (
    StaticOverlaySource(
        name="fusion_confirmation_static",
        path=Path("EVENT.BIN"),
        corpus_path=Path("static") / "EVENT.fusion_confirmation.json",
        generated_path=Path("static") / "EVENT.fusion_confirmation.json",
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.STATUS_UI,
            }
        ),
        records=(
            StaticRecordSpec(
                "confirm_prompt",
                (TextSpan(0x5458E, 9),),
                FixedCells(
                    cells=20,
                    pixel_limit=320,
                    padding_code=0x8000,
                    terminator_required=True,
                ),
            ),
            StaticRecordSpec(
                "level_too_low",
                (TextSpan(0x545B6, 20),),
                FixedCells(
                    cells=34,
                    pixel_limit=320,
                    padding_code=0x8000,
                    terminator_required=True,
                ),
            ),
            StaticRecordSpec(
                "duplicate_demon",
                (TextSpan(0x545DE, 11),),
                FixedCells(
                    cells=30,
                    pixel_limit=320,
                    padding_code=0x8000,
                    terminator_required=True,
                ),
            ),
            StaticRecordSpec(
                "begin_fusion",
                (TextSpan(0x54606, 8),),
                FixedCells(
                    cells=20,
                    pixel_limit=320,
                    padding_code=0x8000,
                    terminator_required=True,
                ),
            ),
            StaticRecordSpec(
                "label_yes",
                (TextSpan(0x5462E, 3),),
                FixedCells(
                    cells=4,
                    pixel_limit=64,
                    padding_code=0x8000,
                    terminator_required=True,
                ),
            ),
            StaticRecordSpec(
                "label_no",
                (TextSpan(0x54636, 2),),
                FixedCells(
                    cells=4,
                    pixel_limit=64,
                    padding_code=0x8000,
                    terminator_required=True,
                ),
            ),
        ),
    ),
    StaticOverlaySource(
        name="dungeon_locations",
        path=SOURCE_PATH,
        corpus_path=ASSET_PATH,
        generated_path=ASSET_PATH,
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.DUNGEON_LOCATIONS,
            }
        ),
        records=DUNGEON_LOCATION_RECORDS,
        deduplicate_by_jp=True,
    ),
    StaticOverlaySource(
        name="name_static",
        path=Path("NAME.BIN"),
        corpus_path=Path("static") / "NAME.BIN.static.json",
        generated_path=Path("static") / "NAME.BIN.static.json",
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.NAME_RUNTIME,
            }
        ),
        records=(
            StaticRecordSpec(
                kind="prompt_first",
                spans=(TextSpan(0x20B78, 8),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="prompt_last",
                spans=(TextSpan(0x20B78, 8),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="prompt_codename",
                spans=(TextSpan(0x20BA0, 8),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="prompt_city",
                spans=(TextSpan(0x20BC8, 8),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="prompt_ward",
                spans=(TextSpan(0x20BC8, 8),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="prompt_confirm",
                spans=(TextSpan(0x20C18, 10),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="label_yes",
                spans=(TextSpan(0x20C30, 3),),
                layout=FixedCells(cells=3),
            ),
            StaticRecordSpec(
                kind="label_no",
                spans=(TextSpan(0x20C38, 2),),
                layout=FixedCells(cells=2),
            ),
            StaticRecordSpec(
                kind="prompt_occupation",
                spans=(TextSpan(0x20CB8, 8),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="label_occupation",
                spans=(TextSpan(0x20CB8, 8),),
                layout=AsciiString(max_bytes=11),
            ),
            StaticRecordSpec(
                kind="tab_upper",
                spans=(TextSpan(0x20C40, 4),),
                layout=AsciiString(max_bytes=7),
            ),
            StaticRecordSpec(
                kind="tab_lower",
                spans=(TextSpan(0x20C68, 4),),
                layout=AsciiString(max_bytes=7),
            ),
            StaticRecordSpec(
                kind="tab_symbol",
                spans=(TextSpan(0x20DD0, 4),),
                layout=AsciiString(max_bytes=7),
            ),
            StaticRecordSpec(
                kind="occupation_employee",
                spans=(TextSpan(0x20CE0, 3),),
                layout=AsciiString(max_bytes=16),
            ),
            StaticRecordSpec(
                kind="occupation_student",
                spans=(TextSpan(0x20D08, 3),),
                layout=AsciiString(max_bytes=16),
            ),
            StaticRecordSpec(
                kind="occupation_official",
                spans=(TextSpan(0x20D30, 3),),
                layout=AsciiString(max_bytes=16),
            ),
            StaticRecordSpec(
                kind="occupation_part_time",
                spans=(TextSpan(0x20D58, 3),),
                layout=AsciiString(max_bytes=16),
            ),
            StaticRecordSpec(
                kind="occupation_business",
                spans=(TextSpan(0x20D80, 3),),
                layout=AsciiString(max_bytes=16),
            ),
            StaticRecordSpec(
                kind="occupation_jobless",
                spans=(TextSpan(0x20DA8, 3),),
                layout=AsciiString(max_bytes=16),
            ),
        ),
    ),
    StaticOverlaySource(
        name="save_static",
        path=Path("SAVE.BIN"),
        corpus_path=Path("static") / "SAVE.BIN.static.json",
        generated_path=Path("static") / "SAVE.BIN.static.json",
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.SAVELOAD_UI,
            }
        ),
        records=(
            StaticRecordSpec(
                kind="location_home",
                spans=(TextSpan(0x51B2C, 2),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="location_office",
                spans=(TextSpan(0x51B30, 5),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="location_asahi",
                spans=(TextSpan(0x51B3A, 4),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="location_rinkai_park",
                spans=(TextSpan(0x51B42, 4),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="location_mount_kasagi",
                spans=(TextSpan(0x51B4A, 4),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="location_yarai",
                spans=(TextSpan(0x51B52, 4),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="location_chuo",
                spans=(TextSpan(0x51B5A, 4),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="location_hibarigaoka",
                spans=(TextSpan(0x51B62, 4),),
                layout=FixedCells(
                    cells=16,
                    pixel_limit=112,
                    padding_code=PADDING_CODE,
                ),
            ),
            StaticRecordSpec(
                kind="empty",
                spans=(TextSpan(0x50760, 5),),
                layout=FixedCells(cells=5),
            ),
            StaticRecordSpec(
                kind="prompt_overwrite",
                spans=(TextSpan(0x508A4, 11),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="prompt_quit_game",
                spans=(TextSpan(0x508C6, 11),),
                layout=FixedCells(cells=11),
            ),
            StaticRecordSpec(
                kind="save_write_failure",
                spans=(TextSpan(0x50658, 17), TextSpan(0x50684, 10)),
                layout=FixedRows(rows=3, cells=24, pixel_limit=176),
            ),
            StaticRecordSpec(
                kind="save_capacity_error",
                spans=(TextSpan(0x5076A, 15), TextSpan(0x50788, 17)),
                layout=SplitLines(lines=2, cells=0x7F, pixel_limit=272),
            ),
            StaticRecordSpec(
                kind="save_capacity_failure",
                spans=(
                    TextSpan(0x508DC, 11),
                    TextSpan(0x508F2, 11),
                    TextSpan(0x50908, 11),
                ),
                layout=FixedRows(rows=3, cells=24, pixel_limit=176),
            ),
        ),
    ),
    StaticOverlaySource(
        name="load_static",
        path=Path("LOAD.BIN"),
        corpus_path=Path("static") / "LOAD.BIN.static.json",
        generated_path=Path("static") / "LOAD.BIN.static.json",
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.SAVELOAD_UI,
            }
        ),
        records=(
            StaticRecordSpec(
                kind="start_without_save_warning",
                spans=(TextSpan(0xB020, 30), TextSpan(0xB070, 30)),
                layout=FixedRows(rows=4, cells=63, pixel_limit=320),
            ),
            StaticRecordSpec(
                kind="insufficient_free_space_instructions",
                spans=(TextSpan(0xB0C0, 33), TextSpan(0xB110, 65)),
                layout=FixedRows(rows=6, cells=63, pixel_limit=320),
            ),
            StaticRecordSpec(
                kind="save_capacity_error",
                spans=(TextSpan(0xB1BE, 15), TextSpan(0xB1DC, 17)),
                layout=SplitLines(lines=2, cells=0x7F, pixel_limit=272),
            ),
            StaticRecordSpec(
                kind="load_failure",
                spans=(TextSpan(0xB1FE, 20), TextSpan(0xB22A, 10)),
                layout=FixedRows(rows=3, cells=24, pixel_limit=176),
            ),
        ),
    ),
    StaticOverlaySource(
        name="config_static",
        path=Path("CFG_SET.BIN"),
        corpus_path=Path("static") / "CFG_SET.BIN.static.json",
        generated_path=Path("static") / "CFG_SET.BIN.static.json",
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.CONFIG_UI,
            }
        ),
        records=(
            StaticRecordSpec("battle_messages", (TextSpan(0x9E3A, 8),), FixedCells(16)),
            StaticRecordSpec("auto_map", (TextSpan(0x9E4A, 8),), FixedCells(16)),
            StaticRecordSpec("party_panel", (TextSpan(0x9E5A, 8),), FixedCells(16)),
            StaticRecordSpec("demon_analyze", (TextSpan(0x9E6A, 8),), FixedCells(16)),
            StaticRecordSpec("sound", (TextSpan(0x9E7A, 8),), FixedCells(16)),
            StaticRecordSpec("magic_order", (TextSpan(0x9E8A, 8),), FixedCells(16)),
            StaticRecordSpec("item_order", (TextSpan(0x9E9A, 8),), FixedCells(16)),
            StaticRecordSpec("speed_fast", (TextSpan(0x9EAA, 8),), FixedCells(16)),
            StaticRecordSpec("speed_normal", (TextSpan(0x9EBA, 8),), FixedCells(16)),
            StaticRecordSpec("speed_slow", (TextSpan(0x9ECA, 8),), FixedCells(16)),
            StaticRecordSpec("party_fixed", (TextSpan(0x9EDA, 8),), FixedCells(16)),
            StaticRecordSpec("party_free", (TextSpan(0x9EEA, 8),), FixedCells(16)),
            StaticRecordSpec("graph", (TextSpan(0x9EFA, 8),), FixedCells(16)),
            StaticRecordSpec("max", (TextSpan(0x9F0A, 8),), FixedCells(16)),
            StaticRecordSpec("display_normal", (TextSpan(0x9F1A, 8),), FixedCells(16)),
            StaticRecordSpec("display_reverse", (TextSpan(0x9F2A, 8),), FixedCells(16)),
            StaticRecordSpec("stereo", (TextSpan(0x9F3A, 8),), FixedCells(16)),
            StaticRecordSpec("mono", (TextSpan(0x9F4A, 8),), FixedCells(16)),
            StaticRecordSpec("controls", (TextSpan(0x9F6A, 9),), FixedCells(9)),
            StaticRecordSpec("mode_normal", (TextSpan(0x9F7C, 9),), FixedCells(9)),
            StaticRecordSpec("mode_custom", (TextSpan(0x9F8E, 6),), FixedCells(6)),
            StaticRecordSpec(
                "assist_heal",
                (TextSpan(0x9FA0, 5),),
                FixedCells(16, pixel_limit=80, padding_code=PADDING_CODE),
            ),
            StaticRecordSpec(
                "assist_skill",
                (TextSpan(0x9FAA, 5),),
                FixedCells(16, pixel_limit=80, padding_code=PADDING_CODE),
            ),
            StaticRecordSpec(
                "assist_buff",
                (TextSpan(0x9FB4, 5),),
                FixedCells(16, pixel_limit=80, padding_code=PADDING_CODE),
            ),
            StaticRecordSpec(
                "assist_attack_support",
                (TextSpan(0x9FBE, 5),),
                FixedCells(16, pixel_limit=80, padding_code=PADDING_CODE),
            ),
            StaticRecordSpec(
                "assist_item",
                (TextSpan(0x9FC8, 5),),
                FixedCells(16, pixel_limit=80, padding_code=PADDING_CODE),
            ),
            StaticRecordSpec(
                "assist_gem",
                (TextSpan(0x9FD2, 5),),
                FixedCells(16, pixel_limit=80, padding_code=PADDING_CODE),
            ),
            StaticRecordSpec(
                "assist_equip",
                (TextSpan(0x9FDC, 5),),
                FixedCells(16, pixel_limit=80, padding_code=PADDING_CODE),
            ),
            StaticRecordSpec(
                "action_full_cancel",
                (TextSpan(0x42B46, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "action_cancel",
                (TextSpan(0x42B56, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "action_confirm",
                (TextSpan(0x42B66, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "action_help",
                (TextSpan(0x42B76, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "action_recover",
                (TextSpan(0x42B86, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "action_command",
                (TextSpan(0x42B96, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "action_auto_map",
                (TextSpan(0x42BA6, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "action_analyze",
                (TextSpan(0x42BB6, 8),),
                AsciiString(max_bytes=32),
                CFG_ACTION_DECODER,
            ),
            StaticRecordSpec(
                "footer_assign",
                (TextSpan(0x42BD6, 9),),
                AsciiString(max_bytes=32),
            ),
            StaticRecordSpec(
                "footer_finish",
                (TextSpan(0x42BE8, 9),),
                AsciiString(max_bytes=32),
            ),
        ),
    ),
    StaticOverlaySource(
        name="map_static",
        path=Path("MAP2D.BIN"),
        corpus_path=Path("static") / "MAP2D.BIN.static.json",
        generated_path=Path("static") / "MAP2D.BIN.static.json",
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.NAME_RUNTIME,
                RuntimeCapability.MAP_UI,
            }
        ),
        records=(
            StaticRecordSpec(
                "location_rinkai_park",
                (TextSpan(0x1E68E, 4),),
                AsciiString(max_bytes=32),
            ),
            StaticRecordSpec(
                "location_mount_kasagi",
                (TextSpan(0x1E698, 3),),
                AsciiString(max_bytes=32),
            ),
            StaticRecordSpec(
                "location_yarai",
                (TextSpan(0x1E6A2, 3),),
                AsciiString(max_bytes=32),
            ),
            StaticRecordSpec(
                "location_chuo",
                (TextSpan(0x1E6AC, 3),),
                AsciiString(max_bytes=32),
            ),
            StaticRecordSpec(
                "location_hibarigaoka",
                (TextSpan(0x1E6B6, 4),),
                AsciiString(max_bytes=32),
            ),
            StaticRecordSpec(
                "talk_prompt",
                (TextSpan(0x1E756, 14),),
                AsciiString(max_bytes=64),
            ),
            StaticRecordSpec(
                "label_yes",
                (TextSpan(0x1E774, 3),),
                FixedCells(cells=3),
            ),
            StaticRecordSpec(
                "label_no",
                (TextSpan(0x1E77C, 2),),
                FixedCells(cells=2),
            ),
        ),
    ),
)
