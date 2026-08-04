"""Corpus and generated-table preparation for detailed status UI."""

import json
import re
import struct
from functools import cache

from engine.script.status_ui.model import (
    BASE,
    BUILT_CHARNAME_PATH,
    BUILT_DVLNAME_PATH,
    CHARACTER_NAMES_PATH,
    CHARNAME_PATH,
    DEMON_NAMES_PATH,
    DVLNAME_PATH,
    EVENT_BAR_DRINK_COUNT,
    EVENT_BAR_DRINK_SOURCE,
    EVENT_BAR_DRINK_STRIDE,
    EVENT_BAR_TALK_ROLE_COUNT,
    EVENT_BAR_TALK_ROLE_SOURCE,
    EVENT_BAR_TALK_ROLE_STRIDE,
    EVENT_HEALING_ALL_SOURCE_SITES,
    EVENT_PATH,
    FONT8_PATH,
    FONT16_PATH,
    HEALING_UI_PATH,
    MAGIC_NAMES_PATH,
    RUNTIME_DATA_FILE,
    SATURN_ROOT,
    SHOP_UI_PATH,
    STATUS_TABLES_PATH,
)
from engine.script.status_ui.name_lookup import NAME_LOOKUP_STRIDE, build_name_lookup
from engine.script.text_render.font8_metrics import font8_metrics
from engine.script.text_render.font_metrics import font16_metrics


def validate_shiftable_bitmap(
    bitmap: bytes,
    widths: bytes,
    glyph_stride: int,
    row_stride: int,
    context: str,
) -> None:
    """Prove odd-X shift/draw/restore cannot discard a glyph's trailing bit."""
    if (
        glyph_stride <= 0
        or row_stride <= 0
        or glyph_stride % row_stride
        or len(bitmap) % glyph_stride
    ):
        raise ValueError(f"{context}: invalid font bitmap layout")
    glyph_count = len(bitmap) // glyph_stride
    for code, width in enumerate(widths):
        if not width:
            continue
        if code >= glyph_count:
            raise ValueError(f"{context}: glyph {code} exceeds the font bitmap")
        record = bitmap[code * glyph_stride : (code + 1) * glyph_stride]
        if any(
            record[offset] & 1
            for offset in range(row_stride - 1, glyph_stride, row_stride)
        ):
            raise ValueError(
                f"{context}: glyph {code} uses the trailing bit required "
                "for exact odd-pixel placement"
            )


@cache
def status_labels():
    """Load the shared equipment/status terminology without building patches."""
    from engine.script.equipment_ui.model import load_config

    return load_config().labels


def derived_rows(labels=None) -> tuple[tuple[str, ...], ...]:
    labels = status_labels() if labels is None else labels
    rows = tuple(tuple(label.split()) for label in labels.derived)
    if any(not row or len(row) > 4 for row in rows):
        raise ValueError("derived status labels must contain one to four chunks")
    return rows


def load_font16_metrics() -> tuple[bytes, dict[str, int]]:
    document = font16_metrics()
    table = document.get("width_table", {})
    limit = table.get("code_limit")
    if document.get("version") != 2 or not document.get("complete") or limit != 268:
        raise ValueError("incomplete FONT16 metrics for status UI")
    widths = bytearray(limit)
    codes = {}
    for row in document.get("glyphs", ()):
        code, advance = row.get("code"), row.get("advance")
        if not isinstance(code, int) or not 0 <= code < limit:
            raise ValueError("invalid FONT16 status glyph code")
        if not isinstance(advance, int) or not 1 <= advance <= 16:
            raise ValueError("invalid FONT16 status glyph advance")
        widths[code] = advance
        for text in (row.get("text"), *row.get("aliases", ())):
            if isinstance(text, str) and len(text) == 1:
                codes.setdefault(text, code)
    return bytes(widths), codes


def load_status_terms(
    context: str,
) -> tuple[list[str], list[str], list[str]]:
    tables = json.loads(STATUS_TABLES_PATH.read_text(encoding="utf-8"))
    races = [row["tr"] for row in tables if row["table"] == "races"]
    affinities = [row["tr"] for row in tables if row["table"] == "affinities"][:66]
    names = json.loads(DEMON_NAMES_PATH.read_text(encoding="utf-8"))
    demon_names = [row["tr"] for row in names]
    if len(races) != 43 or len(affinities) != 66:
        raise ValueError(f"{context} needs 43 races and 66 affinities")
    if len(demon_names) != 319:
        raise ValueError(f"{context} needs 319 demon names")
    if any(not text for text in (*races, *affinities, *demon_names)):
        raise ValueError(f"{context} terminology contains untranslated rows")
    return races, affinities, demon_names


def add_name_hashes(
    hashes: dict[int, str],
    assets: tuple[bytes, ...],
    translated: list[str],
    context: str,
) -> None:
    for asset in assets:
        for index, name in enumerate(translated):
            first, second = struct.unpack_from(">II", asset, index * 8)
            key = first ^ second
            previous = hashes.get(key)
            if previous is not None and previous != name:
                raise ValueError(
                    f"{context} name XOR collision has different translations: "
                    f"{previous!r} and {name!r}"
                )
            hashes[key] = name


def encode_font16_glyphs(
    text: str,
    codes: dict[str, int],
    widths: bytes,
    context: str,
) -> list[int]:
    try:
        glyphs = [codes[character] for character in text]
    except KeyError as error:
        raise ValueError(
            f"unsupported {context} FONT16 character in {text!r}: {error.args[0]!r}"
        ) from error
    if sum(widths[glyph] for glyph in glyphs) > 224:
        raise ValueError(f"{context} text exceeds 224px: {text!r}")
    return glyphs


def populate_term_tables(
    data: bytearray,
    race_offset: int,
    affinity_offset: int,
    races: list[str],
    affinities: list[str],
    encode,
    context: str,
) -> None:
    for index, text in enumerate(races):
        struct.pack_into(">I", data, race_offset + index * 4, encode(text))
    encode("")
    for index, text in enumerate(affinities):
        lines = text.split("{n}")
        if len(lines) > 2:
            raise ValueError(f"{context} affinity {index} needs more than two rows")
        lines += [""] * (2 - len(lines))
        struct.pack_into(
            ">II",
            data,
            affinity_offset + index * 8,
            *(encode(line) for line in lines),
        )


def status_english_data() -> tuple[bytes, int, int, int, int, int, int]:
    """Build compact pointer tables and an interned FONT16 string pool."""
    widths8, _ = font8_metrics()
    widths16, codes16 = load_font16_metrics()
    validate_shiftable_bitmap(
        FONT16_PATH.read_bytes(), widths16, 32, 2, "status FONT16"
    )
    validate_shiftable_bitmap(FONT8_PATH.read_bytes(), widths8, 8, 1, "status FONT8")
    races, affinities, demon_names = load_status_terms("status terminology")
    original_names = DVLNAME_PATH.read_bytes()
    built_names = BUILT_DVLNAME_PATH.read_bytes()
    characters = json.loads(CHARACTER_NAMES_PATH.read_text(encoding="utf-8"))
    character_names = [row["tr"] for row in characters]
    original_characters = CHARNAME_PATH.read_bytes()
    built_characters = BUILT_CHARNAME_PATH.read_bytes()
    if any(len(asset) != 319 * 8 for asset in (original_names, built_names)):
        raise ValueError("status demon-name lookup needs 319 records")
    if len(character_names) != 6 or any(
        len(asset) != 6 * 8 for asset in (original_characters, built_characters)
    ):
        raise ValueError("status character-name lookup needs six records")
    if any(not text for text in character_names):
        raise ValueError("status character terminology contains untranslated rows")

    data = bytearray()

    def align(alignment: int = 4) -> None:
        while (RUNTIME_DATA_FILE + len(data)) % alignment:
            data.append(0)

    def reserve(size: int) -> tuple[int, int]:
        align()
        offset = len(data)
        data.extend(bytes(size))
        return offset, BASE + RUNTIME_DATA_FILE + offset

    widths_offset, widths_address = reserve(len(widths16))
    data[widths_offset : widths_offset + len(widths16)] = widths16
    widths8_offset, widths8_address = reserve(len(widths8))
    data[widths8_offset : widths8_offset + len(widths8)] = widths8
    race_offset, race_address = reserve(len(races) * 4)
    affinity_offset, affinity_address = reserve(len(affinities) * 8)

    hashes = {}
    add_name_hashes(
        hashes,
        (original_names, built_names),
        demon_names,
        "status",
    )
    add_name_hashes(
        hashes,
        (original_characters, built_characters),
        character_names,
        "status",
    )
    lookup_offset, lookup_address = reserve(len(hashes) * NAME_LOOKUP_STRIDE)
    if lookup_address & 3:
        raise ValueError("fusion-status hash lookup is not longword-aligned")

    texts: list[str] = []

    def remember(text: str) -> None:
        if text not in texts:
            texts.append(text)

    for text in races:
        remember(text)
    remember("")
    for text in affinities:
        lines = text.split("{n}")
        lines += [""] * (2 - len(lines))
        for line in lines:
            remember(line)
    for text in hashes.values():
        remember(text)

    blobs = {}
    for text in texts:
        glyphs = encode_font16_glyphs(text, codes16, widths16, "status")
        blobs[text] = struct.pack(f">{len(glyphs) + 1}H", *glyphs, 0x8000)

    align(2)
    pool_address = BASE + RUNTIME_DATA_FILE + len(data)
    pool = bytearray()
    offsets: dict[str, int] = {}
    owners: list[str] = []
    for text in sorted(texts, key=lambda value: (-len(blobs[value]), value)):
        blob = blobs[text]
        offset = next(
            (
                offsets[owner] + len(blobs[owner]) - len(blob)
                for owner in owners
                if blobs[owner].endswith(blob)
            ),
            None,
        )
        if offset is None:
            offset = len(pool)
            pool.extend(blob)
            owners.append(text)
        offsets[text] = offset
    data.extend(pool)

    def encode(text: str) -> int:
        return pool_address + offsets[text]

    populate_term_tables(
        data,
        race_offset,
        affinity_offset,
        races,
        affinities,
        encode,
        "status",
    )
    lookup = build_name_lookup(hashes, encode)
    data[lookup_offset : lookup_offset + len(lookup)] = lookup

    return (
        bytes(data),
        widths_address,
        widths8_address,
        race_address,
        affinity_address,
        lookup_address,
        len(hashes),
    )


def event_status_english_data(
    address: int,
) -> tuple[bytes, int, int, int, int, int, int, int, int, int, int, int, int, int]:
    """Build compact fusion-status and bar/shop text tables."""
    return _event_status_english_data(address, "fusion status")


def da3d_compact_status_data(
    address: int,
) -> tuple[bytes, bytes, int, int, int, int, int, int, int, int]:
    """Pack DA_3D terms without retaining either stock fixed-width limit."""
    widths8, codes8 = font8_metrics()
    widths16, codes16 = load_font16_metrics()
    races, affinities, demon_names = load_status_terms("DA_3D status")
    data = bytearray()

    def append(payload: bytes, alignment: int = 1) -> int:
        data.extend(bytes((-(address + len(data))) % alignment))
        result = address + len(data)
        data.extend(payload)
        return result

    def encode_font8(text: str, context: str, terminator: int) -> bytes:
        result = bytearray()
        for character in text:
            try:
                result.append(codes8[character])
            except KeyError as error:
                raise ValueError(
                    f"unsupported {context} FONT8 character {character!r} in {text!r}"
                ) from error
        result.append(terminator)
        return bytes(result)

    # The FONT16 renderer consumes FONT8-coded source strings.  Store its
    # advances by source code so the runtime does not need a 512-byte glyph map.
    font16_advances = bytearray(229 - 63 + 1)
    source_characters = set(
        "".join(
            (*races, *(text.replace("{n}", "") for text in affinities), *demon_names)
        )
    )
    for character in source_characters:
        try:
            source_code = codes8[character]
            target_code = codes16[character]
        except KeyError as error:
            raise ValueError(
                f"DA_3D FONT16 source mapping is missing {error.args[0]!r}"
            ) from error
        if not 63 <= source_code <= 229:
            raise ValueError(f"DA_3D FONT16 source code {source_code} is out of range")
        font16_advances[source_code - 63] = widths16[target_code]
    compact_font16_advances = font16_advances[: 118 - 63] + font16_advances[205 - 63 :]
    if len(compact_font16_advances) != 80:
        raise ValueError("DA_3D compact FONT16 width table must be 80 bytes")
    font16_widths_address = append(bytes(compact_font16_advances))

    race_pool = bytearray()
    race_offsets = bytearray()
    for index, race in enumerate(races):
        race_offsets.extend(struct.pack(">H", len(race_pool)))
        race_pool.extend(encode_font8(race, f"DA_3D race {index}", 0xFF))
    race_pool_address = append(bytes(race_pool))
    race_offsets_address = append(bytes(race_offsets), 2)

    # Demon names use five-bit title-case tokens packed three per word.  Token
    # 30 inverts the inferred case of the next letter; token 31 represents 8.
    built_names = BUILT_DVLNAME_PATH.read_bytes()
    if len(built_names) != len(demon_names) * 8:
        raise ValueError("DA_3D status needs 319 built demon-name records")
    long_name_bits = bytearray((len(demon_names) + 7) // 8)
    encoded_names = []
    for index, name in enumerate(demon_names):
        encoded = encode_font8(name, f"DA_3D demon name {index}", 0)[:-1]
        direct = len(encoded) <= 8 and sum(widths8[code] for code in encoded) <= 64
        if direct:
            expected = encoded.ljust(8, b"\0")
            actual = built_names[index * 8 : (index + 1) * 8]
            if actual != expected:
                raise ValueError(
                    f"DA_3D direct demon name {index} is stale in built DVLNAME.DAT"
                )
        else:
            long_name_bits[index // 8] |= 1 << (index & 7)
        encoded_names.append((name, direct))

    long_name_bits_address = append(bytes(long_name_bits))
    name_pool_address = address + len(data)
    for index, (name, direct) in enumerate(encoded_names):
        if direct:
            continue
        tokens = []
        uppercase = True
        for character in name:
            if character.isalpha() and character.isascii():
                wanted_uppercase = character.isupper()
                if wanted_uppercase != uppercase:
                    tokens.append(30)
                tokens.append(ord(character.lower()) - ord("a") + 1)
                uppercase = False
            elif character == " ":
                tokens.append(27)
                uppercase = True
            elif character == "-":
                tokens.append(28)
                uppercase = True
            elif character == "'":
                tokens.append(29)
                uppercase = True
            elif character == "8":
                tokens.append(31)
                uppercase = False
            else:
                raise ValueError(
                    f"unsupported DA_3D demon-name character "
                    f"{character!r} in record {index}: {name!r}"
                )
        while len(tokens) % 3:
            tokens.append(0)
        for offset in range(0, len(tokens), 3):
            first, second, third = tokens[offset : offset + 3]
            final = offset + 3 == len(tokens)
            data.extend(
                struct.pack(
                    ">H",
                    (0x8000 if final else 0) | (first << 10) | (second << 5) | third,
                )
            )

    # Affinities consist of a small repeated vocabulary.  Byte tokens 1..28
    # select a null-terminated word or repeated phrase; 29 is comma, 30
    # newline, 31 colon, and zero terminates the record.  Keep the most common
    # complete clause in the dictionary so the redirected DA_3D mirrors retain
    # full demon names without abbreviating either table.
    affinity_phrases = (
        "Nulls: Expel",
        "Demon attacks",
        "Demon Atk",
        "Other magic",
    )
    affinity_pattern = re.compile(
        "("
        + "|".join(re.escape(phrase) for phrase in affinity_phrases)
        + r"|[,:]|\{n\}|[A-Za-z]+)"
    )
    words = []
    affinity_tokens = bytearray()
    for affinity_index, affinity in enumerate(affinities):
        # The runtime copies dictionary strings verbatim, including spaces and
        # the colon in the repeated nullification clause.
        parts = affinity_pattern.split(affinity)
        for part in parts:
            if not part or part.isspace():
                continue
            if part == ",":
                affinity_tokens.append(29)
            elif part == "{n}":
                affinity_tokens.append(30)
            elif part == ":":
                affinity_tokens.append(31)
            elif part in affinity_phrases or all(
                word.isalpha() and word.isascii() for word in part.split()
            ):
                if part not in words:
                    words.append(part)
                affinity_tokens.append(words.index(part) + 1)
            else:
                raise ValueError(
                    f"unsupported DA_3D affinity token {part!r} "
                    f"in record {affinity_index}"
                )
        affinity_tokens.append(0)
    if len(words) > 28:
        raise ValueError("DA_3D affinity vocabulary exceeds 28 words")

    word_offsets = bytearray()
    word_pool = bytearray()
    for index, word in enumerate(words):
        if len(word_pool) > 0xFF:
            raise ValueError("DA_3D affinity word pool exceeds byte offsets")
        word_offsets.append(len(word_pool))
        word_pool.extend(encode_font8(word, f"DA_3D affinity word {index}", 0))
    affinity_word_offsets_address = append(bytes(word_offsets))
    affinity_word_pool_address = append(bytes(word_pool))
    affinity_tokens_address = append(bytes(affinity_tokens))

    compact_widths8 = widths8[63:118] + widths8[205:230]
    if len(compact_widths8) != 80:
        raise ValueError("DA_3D compact FONT8 width table must be 80 bytes")

    return (
        bytes(data),
        compact_widths8,
        font16_widths_address,
        race_pool_address,
        race_offsets_address,
        long_name_bits_address,
        name_pool_address,
        affinity_word_offsets_address,
        affinity_word_pool_address,
        affinity_tokens_address,
    )


def _event_status_english_data(
    address: int,
    context: str,
) -> tuple[
    bytes,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
]:
    """Pack EVENT status names once for both FONT16 and bar FONT8 consumers."""
    widths8, codes8 = font8_metrics()
    widths16, codes16 = load_font16_metrics()
    validate_shiftable_bitmap(
        FONT16_PATH.read_bytes(), widths16, 32, 2, f"{context} FONT16"
    )
    validate_shiftable_bitmap(
        FONT8_PATH.read_bytes(), widths8, 8, 1, f"{context} FONT8"
    )
    races, affinities, demon_names = load_status_terms(context)
    characters = json.loads(CHARACTER_NAMES_PATH.read_text(encoding="utf-8"))
    character_names = [row["tr"] for row in characters]
    built_names = BUILT_DVLNAME_PATH.read_bytes()
    original_characters = CHARNAME_PATH.read_bytes()
    built_characters = BUILT_CHARNAME_PATH.read_bytes()
    if len(built_names) != 319 * 8:
        raise ValueError(f"{context} needs 319 built demon-name records")
    if len(character_names) != 6 or any(
        len(asset) != 6 * 8 for asset in (original_characters, built_characters)
    ):
        raise ValueError(f"{context} needs six built character-name records")
    if any(not name for name in character_names):
        raise ValueError(f"{context} character names contain untranslated rows")

    hashes = {}
    add_name_hashes(hashes, (built_names,), demon_names, context)
    add_name_hashes(
        hashes,
        (original_characters, built_characters),
        character_names,
        context,
    )

    data = bytearray()

    def align(alignment: int = 4) -> None:
        data.extend(bytes((-(address + len(data))) % alignment))

    def reserve(size: int, alignment: int = 4) -> tuple[int, int]:
        align(alignment)
        offset = len(data)
        data.extend(bytes(size))
        return offset, address + offset

    def encode_font8(text: str, label: str, max_width: int) -> bytes:
        try:
            encoded = bytes(codes8[character] for character in text)
        except KeyError as error:
            raise ValueError(
                f"unsupported {label} FONT8 character {error.args[0]!r} in {text!r}"
            ) from error
        pixel_width = sum(widths8[code] for code in encoded) + max(0, len(encoded) - 1)
        if pixel_width > max_width:
            raise ValueError(
                f"{label} exceeds {max_width}px ({pixel_width}px): {text!r}"
            )
        return encoded + b"\0"

    widths16_offset, widths16_address = reserve(len(widths16))
    data[widths16_offset : widths16_offset + len(widths16)] = widths16
    widths8_offset, widths8_address = reserve(len(widths8))
    data[widths8_offset : widths8_offset + len(widths8)] = widths8

    # Detailed status still draws race and affinity strings with FONT16.  Demon
    # and character names are stored as FONT8 source bytes and converted to
    # FONT16 by the event-only name renderer, halving the shared name pool.
    font16_advances = bytearray(229 - 63 + 1)
    for character in set("".join((*demon_names, *character_names))):
        try:
            source_code = codes8[character]
            target_code = codes16[character]
        except KeyError as error:
            raise ValueError(
                f"{context} FONT16 name mapping is missing {error.args[0]!r}"
            ) from error
        if not 63 <= source_code <= 229:
            raise ValueError(f"{context} FONT8 name code {source_code} is out of range")
        font16_advances[source_code - 63] = widths16[target_code]
    compact_font16_advances = font16_advances[: 118 - 63] + font16_advances[205 - 63 :]
    if len(compact_font16_advances) != 80:
        raise ValueError(f"{context} compact FONT16 table must be 80 bytes")
    compact16_offset, compact16_address = reserve(len(compact_font16_advances))
    data[compact16_offset : compact16_offset + len(compact_font16_advances)] = (
        compact_font16_advances
    )

    race_offset, race_address = reserve(len(races) * 4)
    affinity_offset, affinity_address = reserve(len(affinities) * 8)
    lookup_offset, lookup_address = reserve(len(hashes) * NAME_LOOKUP_STRIDE)

    font16_pool = {}

    def encode_font16(text: str) -> int:
        cached = font16_pool.get(text)
        if cached is not None:
            return cached
        align(2)
        pointer = address + len(data)
        glyphs = encode_font16_glyphs(text, codes16, widths16, context)
        data.extend(struct.pack(f">{len(glyphs) + 1}H", *glyphs, 0x8000))
        font16_pool[text] = pointer
        return pointer

    populate_term_tables(
        data,
        race_offset,
        affinity_offset,
        races,
        affinities,
        encode_font16,
        "fusion",
    )

    name_pool = bytearray()
    name_offsets = {}
    for name in hashes.values():
        if name in name_offsets:
            continue
        name_offsets[name] = len(name_pool)
        name_pool.extend(encode_font8(name, f"{context} name", 104))
    record_offsets = bytearray()
    for name in (*demon_names, *character_names):
        offset = name_offsets[name]
        if offset > 0xFFFF:
            raise ValueError(f"{context} name pool exceeds 16-bit offsets")
        record_offsets.extend(struct.pack(">H", offset))
    record_offsets_address = address + len(data)
    data.extend(record_offsets)
    name_pool_address = address + len(data)
    data.extend(name_pool)
    lookup = build_name_lookup(
        hashes,
        lambda name: name_pool_address + name_offsets[name],
    )
    data[lookup_offset : lookup_offset + len(lookup)] = lookup

    shop = json.loads(SHOP_UI_PATH.read_text(encoding="utf-8"))
    drinks = shop.get("drinks")
    if not isinstance(drinks, list) or len(drinks) != EVENT_BAR_DRINK_COUNT:
        raise ValueError(f"shop UI needs {EVENT_BAR_DRINK_COUNT} drink records")
    event = EVENT_PATH.read_bytes()
    source_offset = EVENT_BAR_DRINK_SOURCE - BASE
    drink_pool = bytearray()
    drink_offsets = bytearray()
    for index, row in enumerate(drinks):
        if not isinstance(row, dict):
            raise ValueError(f"shop drink {index} must be an object")
        try:
            source = bytes.fromhex(row["source_hex"])
            price = row["price"]
            translation = row["tr"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid shop drink {index}") from error
        if len(source) != 8 or not isinstance(price, int):
            raise ValueError(f"invalid shop drink source record {index}")
        record = event[
            source_offset + index * EVENT_BAR_DRINK_STRIDE : source_offset
            + (index + 1) * EVENT_BAR_DRINK_STRIDE
        ]
        if len(record) != EVENT_BAR_DRINK_STRIDE:
            raise ValueError(f"shop drink source record {index} is truncated")
        if record[:8] != source or struct.unpack_from(">H", record, 8)[0] != price:
            raise ValueError(
                f"shop drink {index} no longer matches EVENT.BIN source data"
            )
        if len(drink_pool) > 0xFFFF:
            raise ValueError("shop drink string pool exceeds 16-bit offsets")
        drink_offsets.extend(struct.pack(">H", len(drink_pool)))
        drink_pool.extend(encode_font8(translation, f"shop drink {index}", 64))
    # The drawer indexes this table with mov.w.  The shared name pool before it
    # is variable-sized, so the table must not inherit an odd end address.
    align(2)
    drink_offsets_address = address + len(data)
    data.extend(drink_offsets)
    drink_pool_address = address + len(data)
    data.extend(drink_pool)

    talk_labels = shop.get("talk_labels")
    if (
        not isinstance(talk_labels, list)
        or len(talk_labels) != EVENT_BAR_TALK_ROLE_COUNT
    ):
        raise ValueError(f"shop UI needs {EVENT_BAR_TALK_ROLE_COUNT} Talk role records")
    talk_pool = bytearray(b"\0")
    talk_offsets = bytearray(b"\0\0")  # record zero is the stock blank row
    source_offset = EVENT_BAR_TALK_ROLE_SOURCE - BASE
    for expected_record, row in enumerate(talk_labels, 1):
        if not isinstance(row, dict) or row.get("record") != expected_record:
            raise ValueError(f"invalid Talk role record {expected_record}")
        try:
            source = bytes.fromhex(row["source_hex"])
            translation = row["tr"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid Talk role record {expected_record}") from error
        record = event[
            source_offset
            + (expected_record - 1) * EVENT_BAR_TALK_ROLE_STRIDE : source_offset
            + (expected_record - 1) * EVENT_BAR_TALK_ROLE_STRIDE
            + 8
        ]
        if len(source) != 8 or record != source:
            raise ValueError(
                f"Talk role {expected_record} no longer matches EVENT.BIN source data"
            )
        if len(talk_pool) > 0xFFFF:
            raise ValueError("Talk role string pool exceeds 16-bit offsets")
        talk_offsets.extend(struct.pack(">H", len(talk_pool)))
        talk_pool.extend(
            encode_font8(
                translation,
                f"Talk role {expected_record}",
                64,
            )
        )
    # The runtime consumes this table with SH-2 mov.w loads.  The preceding
    # byte-string pool is variable-sized, so explicitly restore halfword
    # alignment before binding the table address.
    if (address + len(data)) & 1:
        data.append(0)
    talk_offsets_address = address + len(data)
    data.extend(talk_offsets)
    talk_pool_address = address + len(data)
    data.extend(talk_pool)

    healing = json.loads(HEALING_UI_PATH.read_text(encoding="utf-8"))
    all_members = healing.get("all_members")
    if not isinstance(all_members, dict):
        raise ValueError("healing UI needs an all_members record")
    try:
        source = bytes.fromhex(all_members["source_hex"])
        translation = all_members["tr"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid healing all-members record") from error
    bound_source = bytearray()
    for site, expected in EVENT_HEALING_ALL_SOURCE_SITES:
        actual = event[site - BASE : site - BASE + len(expected)]
        if actual != expected:
            raise ValueError(f"healing all-members source changed at {site:#010x}")
        if len(expected) == 2 and expected[0] == 0xE2:
            bound_source.extend((0, expected[1]))
        else:
            bound_source.extend(expected)
    if bytes(bound_source) != source:
        raise ValueError("healing all-members source no longer matches healing_ui.json")
    healing_all_address = address + len(data)
    data.extend(encode_font8(translation, "healing all-members", 144))

    return (
        bytes(data),
        widths16_address,
        widths8_address,
        compact16_address,
        race_address,
        affinity_address,
        lookup_address,
        len(hashes),
        record_offsets_address,
        name_pool_address,
        drink_offsets_address,
        drink_pool_address,
        talk_offsets_address,
        talk_pool_address,
        healing_all_address,
    )


def ambiguous_magname_fallbacks() -> tuple[bytes, ...]:
    """Return eight-byte fallbacks shared by different English skill names."""
    names = json.loads(MAGIC_NAMES_PATH.read_text(encoding="utf-8"))
    built = (SATURN_ROOT / "rom" / "build" / "MAGNAME.DAT").read_bytes()
    if len(names) != 255 or len(built) != 255 * 96:
        raise ValueError("fusion status needs 255 MAGNAME records")
    seen = {}
    ambiguous = set()
    for index, row in enumerate(names):
        fallback = built[index * 96 + 4 : index * 96 + 12]
        name = row["name"]["tr"]
        previous = seen.get(fallback)
        if previous is not None and previous != name:
            ambiguous.add(fallback)
        seen[fallback] = name
    result = tuple(sorted(ambiguous))
    if len(result) != 4:
        raise ValueError(
            "fusion status expected four ambiguous MAGNAME fallbacks, found "
            f"{len(result)}"
        )
    return result
