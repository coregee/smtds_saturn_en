"""Fixed, indexed, mirrored, and diagnostic source declarations."""

from pathlib import Path

from text.script.dialects import TextDialect
from text.script.formats.ascii_fields.model import AsciiField
from text.script.formats.fixed_bytes.model import FixedBytesRuntimeCoverage
from text.script.formats.fixed_words.model import FixedWordField
from text.script.formats.mirrored_words.model import (
    MirroredWordLocation,
    MirroredWordTable,
)
from text.script.profiles import RuntimeCapability
from text.script.source_models import (
    AsciiFieldsSource,
    DeduplicatedWordsSource,
    FixedBytesSource,
    FixedHelpSource,
    FixedWordsSource,
    IndexedBytesSource,
    IndexedWordsSource,
    MirroredWordsSource,
    NameDescriptionSource,
)

FIXED_HELP_SOURCES = (
    FixedHelpSource(
        name="btl_help",
        path=Path("BTL_HELP.DAT"),
        corpus_path=Path("fixed_help") / "BTL_HELP.DAT.json",
        record_words=22,
        record_count=19,
        max_lines=1,
        packed=True,
        dialect=TextDialect.COMBAT,
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.SMALLFONT_VWF,
            }
        ),
    ),
    FixedHelpSource(
        name="normhelp",
        path=Path("NORMHELP.DAT"),
        corpus_path=Path("fixed_help") / "NORMHELP.DAT.json",
        record_words=42,
        record_count=24,
        max_lines=2,
        packed=True,
        dialect=TextDialect.EVENT,
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.NORMCOM_HELP,
            }
        ),
    ),
)


NAME_DESCRIPTION_SOURCES = (
    NameDescriptionSource(
        name="itemname",
        path=Path("ITEMNAME.DAT"),
        corpus_path=Path("name_description") / "ITEMNAME.DAT.json",
        record_size=0x60,
        record_count=287,
        name_offset=4,
        name_bytes=8,
        description_offset=0x0C,
        description_words=42,
        pointer_offset=0x5E,
        max_full_name_bytes=32,
        max_full_name_pixels=80,
        dialect=TextDialect.EVENT,
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT8_LATIN,
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.EVENT_VWF,
                RuntimeCapability.EVENT_PACKED_FETCH,
                RuntimeCapability.NORMCOM_HELP,
                RuntimeCapability.SMALLFONT_VWF,
                RuntimeCapability.ITEMNAME_RUNTIME,
            }
        ),
    ),
    NameDescriptionSource(
        name="magname",
        path=Path("MAGNAME.DAT"),
        corpus_path=Path("name_description") / "MAGNAME.DAT.json",
        record_size=0x60,
        record_count=255,
        name_offset=4,
        name_bytes=8,
        description_offset=0x0C,
        description_words=42,
        pointer_offset=0x5E,
        max_full_name_bytes=32,
        max_full_name_pixels=80,
        dialect=TextDialect.EVENT,
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT8_LATIN,
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.NORMCOM_HELP,
                RuntimeCapability.SMALLFONT_VWF,
            }
        ),
    ),
)


INDEXED_BYTES_SOURCES = (
    IndexedBytesSource(
        name="btl_mes",
        path=Path("BTL_MES.MD8"),
        corpus_path=Path("indexed_bytes") / "BTL_MES.MD8.json",
        table_size=0x800,
        table_sentinel=0xFFFF,
        terminator=0x80,
        primary_atlas="fnt8x12.json",
        secondary_atlas="fnt12x12.json",
        secondary_base=0x48,
        secondary_glyphs=0x38,
        named_controls=((0xA5, "NUM"),),
        runtime_requirements=frozenset({RuntimeCapability.SMALLFONT_VWF}),
        repacked_body_offset=0x400,
        engine_load_address=0x002FA000,
    ),
)


INDEXED_WORDS_SOURCES = tuple(
    IndexedWordsSource(
        name=name,
        path=Path(filename),
        corpus_path=Path("indexed_words") / f"{filename}.json",
        body_offset=0x400,
        table_sentinel=0xFFFF,
        terminator=0x8000,
        dialect=TextDialect.COMBAT,
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.COMBAT_PACKED_FETCH,
            }
        ),
        layout_width_pixels=176 if name == "btl_srf" else None,
        layout_lines=2 if name == "btl_srf" else None,
    )
    for name, filename in (
        ("btl_srf", "BTL_SRF.MDT"),
        ("butu_srf", "BUTU_SRF.MDT"),
    )
)


CHARACTER_DIALOGUE_REQUIREMENTS = frozenset(
    {
        RuntimeCapability.MSGR_TEXT,
        RuntimeCapability.STATUS_UI,
    }
)
CHARACTER_VISIBLE_REQUIREMENTS = CHARACTER_DIALOGUE_REQUIREMENTS | {
    RuntimeCapability.FUSION_MENU,
    RuntimeCapability.ITEMNAME_RUNTIME,
    RuntimeCapability.SMALLFONT_VWF,
}
DEMON_VISIBLE_REQUIREMENTS = frozenset(
    {
        RuntimeCapability.COMBAT_VWF,
        RuntimeCapability.FUSION_MENU,
        RuntimeCapability.MSGR_TEXT,
        RuntimeCapability.SMALLFONT_VWF,
        RuntimeCapability.STATUS_UI,
    }
)


FIXED_BYTES_SOURCES = (
    FixedBytesSource(
        name="charname",
        path=Path("CHARNAME.DAT"),
        corpus_path=Path("fixed_bytes/CHARNAME.DAT.json"),
        record_size=8,
        record_count=6,
        field_offset=0,
        field_size=8,
        padding=0,
        pixel_limit=64,
        atlas="font8.json",
        runtime_requirements=frozenset({RuntimeCapability.FONT8_LATIN})
        | CHARACTER_VISIBLE_REQUIREMENTS,
        capacity_fallback_coverage=(
            # Record zero is a fixed dialogue term when explicitly inserted,
            # but party/fusion/level-up selectors keep their live player-name
            # meaning.  The other five records are fixed characters everywhere.
            FixedBytesRuntimeCoverage(
                frozenset({0}),
                CHARACTER_DIALOGUE_REQUIREMENTS,
            ),
            FixedBytesRuntimeCoverage(
                frozenset(range(1, 6)),
                CHARACTER_VISIBLE_REQUIREMENTS,
            ),
        ),
    ),
    FixedBytesSource(
        name="dvlname",
        path=Path("DVLNAME.DAT"),
        corpus_path=Path("fixed_bytes/DVLNAME.DAT.json"),
        record_size=8,
        record_count=319,
        field_offset=0,
        field_size=8,
        padding=0,
        pixel_limit=64,
        atlas="font8.json",
        runtime_requirements=frozenset({RuntimeCapability.FONT8_LATIN})
        | DEMON_VISIBLE_REQUIREMENTS,
        # The Zoma editor mutates records 255..259 in-place through the stock
        # eight-byte ABI.  They all fit and deliberately remain strict if their
        # wording ever grows.  Every other visible record is runtime-resolved.
        capacity_fallback_coverage=(
            FixedBytesRuntimeCoverage(
                frozenset(set(range(319)) - set(range(255, 260))),
                DEMON_VISIBLE_REQUIREMENTS,
            ),
        ),
    ),
)


END_ROLL_MAIN_COUNTS = (
    5,
    5,
    5,
    4,
    4,
    5,
    5,
    5,
    4,
    6,
    5,
    5,
    4,
    4,
    4,
    4,
    6,
    5,
    4,
    5,
    5,
    6,
    4,
    6,
    5,
    4,
    4,
    5,
)
END_ROLL_TEST_FIELDS = (
    (0x20304, 5),
    (0x20312, 5),
    (0x20320, 5),
    (0x2032E, 4),
    (0x2033C, 5),
    (0x2034A, 5),
    (0x20358, 5),
    (0x20366, 5),
    (0x20374, 5),
    (0x20382, 5),
    (0x203AC, 5),
    (0x203BA, 5),
)


COMBAT_CONDITION_BLOCKS = (
    ("charmed", 0x5455C),
    ("happy", 0x5481C),
    ("confused", 0x54ADC),
    ("enraged", 0x54D9C),
    ("talk_blocked", 0x5505C),
    ("ally_veto", 0x5531C),
    ("full_moon", 0x555DC),
)
COMBAT_DIALOGUE_VOICES = (
    "tlk_bst",
    "kemo",
    "tlk_kofu",
    "nbl_m",
    "tlk_hirk",
    "tlk_yngm",
    "grl",
    "tlk_boy",
    "cld_f",
    "tlk_lady",
    "tlk_crzy",
    "jijy",
    "cyni",
    "tlk_west",
    "slm",
    "fallback",
)


FIXED_WORDS_SOURCES = (
    FixedWordsSource(
        name="end_roll_names",
        path=Path("END_ROLL.BIN"),
        corpus_path=Path("fixed_words") / "END_ROLL.BIN.names.json",
        fields=tuple(
            FixedWordField(
                kind=f"main_staff_{index:02d}",
                file_offset=0x19FA8 + index * 0x0C,
                word_count=count,
                runtime_word_count=18,
            )
            for index, count in enumerate(END_ROLL_MAIN_COUNTS)
        )
        + tuple(
            FixedWordField(
                kind=f"test_staff_{index:02d}",
                file_offset=offset,
                word_count=count,
                runtime_word_count=18,
            )
            for index, (offset, count) in enumerate(END_ROLL_TEST_FIELDS)
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.FIXED_TEXT_FIELDS,
            }
        ),
        engine_load_address=0x06020000,
    ),
    FixedWordsSource(
        name="automap_system",
        path=Path("AUTOMAPC.BIN"),
        corpus_path=Path("fixed_words") / "AUTOMAPC.BIN.system.json",
        fields=(
            FixedWordField(
                "marker_delete",
                0xA69C,
                6,
                zero_mode="skip",
                runtime_word_count=7,
            ),
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.DUNGEON_LOCATIONS,
                RuntimeCapability.FIXED_TEXT_FIELDS,
            }
        ),
        engine_load_address=0x06020000,
    ),
    FixedWordsSource(
        name="combat_system",
        path=Path("COMBAT.BIN"),
        corpus_path=Path("fixed_words") / "COMBAT.BIN.system.json",
        fields=tuple(
            FixedWordField(kind, offset, words, terminator=0x8000, zero_mode="skip")
            for kind, offset, words in (
                ("cash", 0x528F4, 3),
                ("magnetite", 0x5291C, 7),
                ("item", 0x52944, 5),
                ("give_nothing", 0x5454E, 7),
            )
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.COMBAT_PACKED_FETCH,
                RuntimeCapability.COMBAT_VWF,
                RuntimeCapability.FIXED_TEXT_FIELDS,
            }
        ),
        engine_load_address=0x06020000,
        packed=True,
        dialect=TextDialect.COMBAT,
    ),
    FixedWordsSource(
        name="combat_condition_messages",
        path=Path("COMBAT.BIN"),
        corpus_path=Path("fixed_words") / "COMBAT.BIN.condition_messages.json",
        fields=tuple(
            FixedWordField(
                kind=f"{condition}_{voice}",
                file_offset=base + voice_index * 0x2C,
                word_count=22,
                terminator=0x8000,
                zero_mode="space",
            )
            for condition, base in COMBAT_CONDITION_BLOCKS
            for voice_index, voice in enumerate(COMBAT_DIALOGUE_VOICES)
        )
        + (
            FixedWordField(
                kind="comp_signal_happy",
                file_offset=0x5589C,
                word_count=22,
                terminator=0x8000,
                zero_mode="space",
            ),
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.COMBAT_PACKED_FETCH,
                RuntimeCapability.COMBAT_VWF,
                RuntimeCapability.FIXED_TEXT_FIELDS,
            }
        ),
        engine_load_address=0x06020000,
        packed=True,
        dialect=TextDialect.COMBAT,
    ),
    FixedWordsSource(
        name="hosi_messages",
        path=Path("HOSI.BIN"),
        corpus_path=Path("fixed_words") / "HOSI.BIN.json",
        fields=tuple(
            FixedWordField(
                f"horoscope_{index:02d}",
                0x10F62 + index * 42,
                21,
                terminator=0x8000,
                zero_mode="skip",
                runtime_word_count=64,
            )
            for index in range(8)
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.HOSI_MESSAGES,
            }
        ),
        engine_load_address=0x06020000,
    ),
    FixedWordsSource(
        name="level_up_system",
        path=Path("LEVEL_UP.BIN"),
        corpus_path=Path("fixed_words") / "LEVEL_UP.BIN.json",
        fields=(
            FixedWordField(
                "learned_magic",
                0x8F2C,
                6,
                terminator=0x8000,
                zero_mode="skip",
                runtime_word_count=18,
            ),
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.FIXED_TEXT_FIELDS,
                RuntimeCapability.STATUS_UI,
            }
        ),
        engine_load_address=0x06020000,
    ),
    FixedWordsSource(
        name="load_capacity",
        path=Path("LOAD.BIN"),
        corpus_path=Path("fixed_words") / "LOAD.BIN.capacity.json",
        fields=(FixedWordField("capacity_number", 0xB1AE, 3, zero_mode="skip"),),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.FIXED_TEXT_FIELDS,
            }
        ),
        engine_load_address=0x06020000,
    ),
    FixedWordsSource(
        name="maze_messages",
        path=Path("MAZE.BIN"),
        corpus_path=Path("fixed_words") / "MAZE.BIN.messages.json",
        fields=tuple(
            FixedWordField(
                kind,
                offset,
                words,
                zero_mode="skip",
                runtime_word_count=18,
            )
            for kind, offset, words in (
                ("talk_prompt", 0x250E4, 14),
                ("operation_disabled", 0x25124, 14),
                ("nothing_notable", 0x25150, 14),
                ("nothing_found", 0x2516C, 14),
                ("items_full", 0x25188, 14),
                ("already_searched", 0x251A4, 14),
                ("obtained_suffix_a", 0x251D0, 6),
                ("obtained_suffix_b", 0x251DC, 6),
                ("full_suffix", 0x251E8, 6),
                ("found_suffix", 0x251F4, 6),
                ("enemy_surprise", 0x25234, 14),
                ("enemy_behind", 0x25250, 14),
                ("preemptive_chance", 0x2526C, 14),
                ("auto_recover_on", 0x252B4, 10),
                ("no_effect", 0x252D0, 14),
            )
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.FIXED_TEXT_FIELDS,
            }
        ),
        engine_load_address=0x06020000,
        packed=True,
    ),
)


MIRRORED_WORDS_SOURCES = (
    MirroredWordsSource(
        name="normcom_tables",
        corpus_path=Path("mirrored_words") / "NORMCOM.tables.json",
        tables=(
            MirroredWordTable(
                name="races",
                record_count=43,
                terminator_mode="optional_full",
                zero_mode="skip",
                # Every live selector is redirected to the same generated
                # 43-entry corpus in all five overlays.  The three status
                # copies are owned atomically by status_ui; COMBAT and MSGR
                # use their dialogue-specific full-word insertion adapters.
                capacity_fallback_requirements=frozenset(
                    {
                        RuntimeCapability.STATUS_UI,
                        RuntimeCapability.COMBAT_VWF,
                        RuntimeCapability.MSGR_TEXT,
                    }
                ),
                capacity_fallback_indices=frozenset(range(43)),
                locations=(
                    MirroredWordLocation(Path("NORMCOM.BIN"), 0x1F974, 3, 0x06020000),
                    MirroredWordLocation(Path("DA_3D.BIN"), 0x44386, 3, 0x06020000),
                    MirroredWordLocation(Path("EVENT.BIN"), 0x54828, 3, 0x06020000),
                    MirroredWordLocation(Path("COMBAT.BIN"), 0x543C0, 4, 0x06020000),
                    MirroredWordLocation(Path("MSGR.COF"), 0x18D90, 4, 0x06060000),
                ),
            ),
            MirroredWordTable(
                name="affinities",
                record_count=96,
                terminator_mode="required",
                zero_mode="newline",
                require_identical=True,
                # All 66 live selectors are redirected in the three overlays by
                # one atomic status_ui capability.  The 30-record reserve tail
                # remains physical and every current translation in it fits.
                capacity_fallback_requirements=frozenset({RuntimeCapability.STATUS_UI}),
                capacity_fallback_indices=frozenset(range(66)),
                locations=(
                    MirroredWordLocation(Path("NORMCOM.BIN"), 0x1FA76, 17, 0x06020000),
                    MirroredWordLocation(Path("DA_3D.BIN"), 0x44488, 17, 0x06020000),
                    MirroredWordLocation(Path("EVENT.BIN"), 0x5492A, 17, 0x06020000),
                ),
            ),
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.FIXED_TEXT_FIELDS,
                RuntimeCapability.COMBAT_VWF,
                RuntimeCapability.MSGR_TEXT,
                RuntimeCapability.STATUS_UI,
            }
        ),
    ),
)


DEDUPLICATED_WORDS_SOURCES = (
    DeduplicatedWordsSource(
        name="combat_debug",
        path=Path("COMBAT.BIN"),
        corpus_path=Path("deduplicated_words") / "COMBAT.BIN.debug_text.json",
        layout_path=Path("deduplicated_words") / "COMBAT.BIN.debug_text.json",
        region_start=0x5451C,
        region_end=0x55B56,
        record_count=14,
        physical_field_count=20,
        engine_load_address=0x06020000,
        packed=True,
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.FIXED_TEXT_FIELDS,
                RuntimeCapability.COMBAT_PACKED_FETCH,
            }
        ),
    ),
)


ASCII_FIELD_SOURCES = (
    AsciiFieldsSource(
        name="automap_marker_ui",
        path=Path("AUTOMAPC.BIN"),
        corpus_path=Path("ascii_fields") / "AUTOMAPC.BIN.marker_ui.json",
        fields=(
            AsciiField("marker_no_data", 0x9AA8, 8, runtime_capacity=10),
            AsciiField("marker_yes", 0xA5E0, 4, runtime_capacity=4),
            AsciiField("marker_no", 0xA5E4, 4, runtime_capacity=4),
        ),
        runtime_requirements=frozenset(
            {
                RuntimeCapability.FONT16_LATIN,
                RuntimeCapability.DUNGEON_LOCATIONS,
                RuntimeCapability.FIXED_TEXT_FIELDS,
            }
        ),
        engine_load_address=0x06020000,
    ),
    AsciiFieldsSource(
        name="sndtest_fields",
        path=Path("SNDTEST.BIN"),
        corpus_path=Path("ascii_fields") / "SNDTEST.BIN.json",
        fields=tuple(
            AsciiField(kind, offset, capacity)
            for kind, offset, capacity in (
                ("title", 0x6FAC, 20),
                ("request_number", 0x6FC0, 8),
                ("sound_effect_request_number", 0x6FC8, 12),
                ("exit_message", 0x6FD4, 18),
            )
        ),
        runtime_requirements=frozenset(),
    ),
    AsciiFieldsSource(
        name="test3d_fields",
        path=Path("TEST3D.BIN"),
        corpus_path=Path("ascii_fields") / "TEST3D.BIN.json",
        fields=tuple(
            AsciiField(kind, offset, capacity)
            for kind, offset, capacity in (
                ("title", 0x695C, 20),
                ("control", 0x6970, 8),
                ("map_number", 0x6978, 8),
                ("direction", 0x6980, 8),
                ("x_position", 0x6988, 8),
                ("y_position", 0x6990, 8),
                ("launch", 0x69A0, 20),
            )
        ),
        runtime_requirements=frozenset(),
    ),
)
