import struct
from dataclasses import dataclass

from text.script.dialects import TextDialect
from text.script.formats.eve.model import EveBank
from text.script.source_models import EveSource

SCRIPT_TABLE_OFFSET = 0x22
SCRIPT_BODY_OFFSET = 0x800


@dataclass(frozen=True)
class MenuGroup:
    """A script menu, its displayed prompt, and any associated lead text."""

    script_index: int
    word_offset: int
    prompt_message: int | None
    lead_messages: tuple[int, ...]
    option_messages: tuple[int, ...]


def read_script_pointers(data: bytes) -> tuple[int, ...]:
    pointers = []
    cursor = SCRIPT_TABLE_OFFSET
    while cursor + 2 <= SCRIPT_BODY_OFFSET:
        pointer = struct.unpack_from(">H", data, cursor)[0]
        cursor += 2
        if pointer == 0xFFFF:
            break
        pointers.append(pointer)
    else:
        raise ValueError("EVE script table has no 0xffff terminator")
    if not pointers:
        raise ValueError("EVE script table has no script pointers")
    if any(left > right for left, right in zip(pointers, pointers[1:])):
        raise ValueError("EVE script pointers are not monotonically increasing")
    if SCRIPT_BODY_OFFSET + pointers[-1] * 2 >= len(data):
        raise ValueError("EVE script body exceeds the source file")
    return tuple(pointers)


def _script_blocks(
    data: bytes,
    source: EveSource,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    pointers = read_script_pointers(data)
    if not SCRIPT_BODY_OFFSET < source.table_offset <= len(data):
        raise ValueError("EVE script body boundary is outside the source file")
    script_end_word = (source.table_offset - SCRIPT_BODY_OFFSET) // 2
    if pointers[-1] >= script_end_word:
        raise ValueError("EVE script pointer exceeds the script body")

    # Script pointers are starts too.  The text-pointer table is the safe upper
    # bound for the final script; the intervening region is zero-filled.
    end_words = (*pointers[1:], script_end_word)
    blocks = []
    for script_index, (start_word, end_word) in enumerate(zip(pointers, end_words)):
        count = end_word - start_word
        if count <= 0:
            continue
        words = struct.unpack_from(
            f">{count}H",
            data,
            SCRIPT_BODY_OFFSET + start_word * 2,
        )
        blocks.append((script_index, words))
    return tuple(blocks)


def _find_event_menu_groups(
    data: bytes,
    source: EveSource,
) -> tuple[MenuGroup, ...]:
    if not source.detect_menu_readers:
        return ()

    pointers = read_script_pointers(data)
    groups = []
    for script_index, words in _script_blocks(data, source):
        for position, opcode in enumerate(words):
            if opcode != 3:
                continue
            if position != 0 and not (position >= 2 and words[position - 2] == 1):
                continue
            if position + 1 >= len(words):
                continue

            option_count = words[position + 1]
            options_end = position + 2 + option_count * 2
            if not 1 <= option_count <= 4 or options_end > len(words):
                continue

            labels = words[position + 2 : options_end : 2]
            targets = words[position + 3 : options_end : 2]
            if all(target < len(pointers) for target in targets):
                groups.append(
                    MenuGroup(
                        script_index=script_index,
                        word_offset=position,
                        prompt_message=(
                            words[position - 1]
                            if position >= 2 and words[position - 2] == 1
                            else None
                        ),
                        lead_messages=(),
                        option_messages=tuple(labels),
                    )
                )

    return tuple(groups)


def _combat_prompt_sequence(
    words: tuple[int, ...],
    position: int,
    message_count: int,
) -> tuple[int, ...] | None:
    if position >= 5 and (
        words[position - 5] == 0
        and words[position - 3] == 1
        and words[position - 2] == 0
    ):
        prompts = (words[position - 4], words[position - 1])
    elif position >= 2 and words[position - 2] == 0:
        prompts = (words[position - 1],)
    else:
        return ()
    return prompts if all(message < message_count for message in prompts) else None


def _find_combat_menu_groups(
    data: bytes,
    source: EveSource,
) -> tuple[MenuGroup, ...]:
    pointers = read_script_pointers(data)
    message_count = len(
        EveBank.parse(data, source.table_offset, source.body_offset).messages
    )
    menu_arities = {0x10: 2, 0x12: 3, 0x14: 4}
    groups = []
    for script_index, words in _script_blocks(data, source):
        for position, opcode in enumerate(words):
            option_count = menu_arities.get(opcode)
            if option_count is None:
                continue

            separator = position + 1 + option_count
            finish = separator + 1 + option_count
            if finish != len(words) or words[separator] != opcode + 1:
                continue

            labels = words[position + 1 : separator]
            targets = words[separator + 1 : finish]
            if not all(message < message_count for message in labels):
                continue
            if not all(target < len(pointers) for target in targets):
                continue

            prompt_messages = _combat_prompt_sequence(
                words,
                position,
                message_count,
            )
            if prompt_messages is None:
                continue

            groups.append(
                MenuGroup(
                    script_index=script_index,
                    word_offset=position,
                    prompt_message=(prompt_messages[-1] if prompt_messages else None),
                    lead_messages=prompt_messages[:-1],
                    option_messages=tuple(labels),
                )
            )
    return tuple(groups)


def find_menu_groups(data: bytes, source: EveSource) -> tuple[MenuGroup, ...]:
    if source.default_profile.dialect is TextDialect.COMBAT:
        return _find_combat_menu_groups(data, source)
    return _find_event_menu_groups(data, source)


def find_raw_u16_messages(data: bytes, source: EveSource) -> frozenset[int]:
    messages = set(source.forced_raw_messages)
    if source.detect_menu_readers:
        for group in find_menu_groups(data, source):
            messages.update(group.option_messages)

    return frozenset(messages)
