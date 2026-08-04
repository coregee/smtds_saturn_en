import re
from dataclasses import dataclass

from text.script.dialects import COMBAT_DIALECT
from text.script.encoding.latin import LatinEncoding
from text.script.encoding.tokens import (
    LITERAL_GLYPH_CODES,
    NAMED_GLYPH_CODES,
    normalize_english,
    parse_inline_tokens,
)
from text.script.layouts.model import LayoutSpec, WidthUnit
from text.script.layouts.structure import page_structure, split_skeleton

COMBAT_STRUCTURAL_EDGE_CODES = frozenset(
    {
        0x8000,
        0x8002,
        0x8003,
    }
)
COMBAT_PAUSE_CODES = frozenset(
    {
        0x8003,
        0x8004,
    }
)
# Private raw-glyph marker: below the packed-word 0x0800 boundary, above the
# generated FONT16 code range, and below the text VM's 0x8000 control range.
RUNTIME_SOFT_WRAP_CODE = 0x07FE
RUNTIME_MEASURE_START_CODE = 0x07FC
RUNTIME_MEASURE_END_CODE = 0x07FD
RUNTIME_STATIC_HINT_BASE = 0x0750
RUNTIME_STATIC_HINT_LIMIT = RUNTIME_MEASURE_START_CODE
RUNTIME_STATIC_HINT_MAX = RUNTIME_STATIC_HINT_LIMIT - RUNTIME_STATIC_HINT_BASE - 1


COMBAT_DIALOGUE_LAYOUT = LayoutSpec(
    name="combat_dialogue",
    width=320,
    width_unit=WidthUnit.PIXELS,
    lines_per_page=3,
    surface_width=320,
    insert_widths={
        **{
            code: 16
            for code in (
                *NAMED_GLYPH_CODES.values(),
                *LITERAL_GLYPH_CODES.values(),
            )
        },
        0x8010: 8 * 16,
        0x8011: 8 * 16,
        0x8012: 6 * 16,
        0x8013: 8 * 16,
        0x8014: 8 * 16,
        0x8015: 8 * 16,
        0x8016: 6 * 16,
        0x8017: 2 * 16,
    },
)

# The COMBAT choice renderer keeps one full-width dialogue row for the prompt,
# then addresses the option rows from 0px and 160px.  These are display
# contracts, not repacker wrap rules: ordinary COMBAT records still wrap
# through COMBAT_DIALOGUE_LAYOUT until the script consumes them as a choice.
COMBAT_CHOICE_PROMPT_LAYOUT = LayoutSpec(
    name="combat_choice_prompt",
    width=320,
    width_unit=WidthUnit.PIXELS,
    lines_per_page=1,
    surface_width=320,
    insert_widths=COMBAT_DIALOGUE_LAYOUT.insert_widths,
)

COMBAT_CHOICE_OPTION_LAYOUT = LayoutSpec(
    name="combat_choice_option",
    width=160,
    width_unit=WidthUnit.PIXELS,
    lines_per_page=1,
    surface_width=160,
    insert_widths=COMBAT_DIALOGUE_LAYOUT.insert_widths,
)


def token_code(token: str) -> int:
    parts = parse_inline_tokens(token, COMBAT_DIALECT)
    if len(parts) != 1 or not isinstance(parts[0], int):
        raise ValueError(f"not a single COMBAT token: {token!r}")
    return parts[0]


def normalize_combat_english(text: str) -> str:
    text = normalize_english(text)

    def remove_pause_gap(match) -> str:
        token = match.group(1)
        return token if token_code(token) in COMBAT_PAUSE_CODES else match.group(0)

    return re.sub(
        r" (\{(?:(?:INS|OP):[0-9a-fA-F]{4}|BEAT|WAIT)\})",
        remove_pause_gap,
        text,
    )


def combat_pixel_width(
    text: str,
    encoding: LatinEncoding,
    layout: LayoutSpec = COMBAT_DIALOGUE_LAYOUT,
) -> int:
    advances = {glyph.code: glyph.advance for glyph in encoding.glyphs}

    def runtime_width(code: int) -> int:
        if code in layout.insert_widths:
            return layout.insert_width(code)
        if code < 0x8000:
            return advances.get(code, 16)
        return layout.insert_width(code)

    return encoding.measure(
        text,
        COMBAT_DIALECT,
        runtime_width,
    )


@dataclass(frozen=True)
class CombatLine:
    text: str
    break_after: int | None


def _combat_lines(
    text: str,
    encoding: LatinEncoding,
    layout: LayoutSpec = COMBAT_DIALOGUE_LAYOUT,
) -> list[CombatLine]:
    explicit_lines = normalize_combat_english(text).split("\n")
    lines: list[CombatLine] = []
    for explicit_index, explicit_line in enumerate(explicit_lines):
        words = [word for word in explicit_line.split(" ") if word]
        wrapped: list[str] = []
        current: list[str] = []
        for word in words:
            candidate = " ".join((*current, word))
            if (
                current
                and combat_pixel_width(candidate, encoding, layout) > layout.width
            ):
                wrapped.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            wrapped.append(" ".join(current))
        elif not words:
            wrapped.append("")

        for wrapped_index, line in enumerate(wrapped):
            if wrapped_index < len(wrapped) - 1:
                break_after = RUNTIME_SOFT_WRAP_CODE
            elif explicit_index < len(explicit_lines) - 1:
                break_after = 0x8001
            else:
                break_after = None
            lines.append(CombatLine(line, break_after))
    return lines


def wrap_combat_lines(
    text: str,
    encoding: LatinEncoding,
    layout: LayoutSpec = COMBAT_DIALOGUE_LAYOUT,
) -> list[str]:
    return [line.text for line in _combat_lines(text, encoding, layout)]


def structural_edge_codes(words: list[int]) -> list[int]:
    """Keep record boundaries; translated text owns all movable controls."""
    return [word for word in words if word in COMBAT_STRUCTURAL_EDGE_CODES]


def encode_combat_translation(
    original_words: tuple[int, ...],
    pages: list[str],
    encoding: LatinEncoding,
    *,
    pack_codes=None,
) -> list[int] | None:
    """Encode translated pages while retaining the stock window-clear cadence."""
    _page_sizes, breaks = page_structure(original_words)
    if len(pages) != len(breaks):
        raise ValueError(
            f"translation page count {len(pages)} != source page count {len(breaks)}"
        )

    lead, tail = split_skeleton(
        original_words,
        is_payload=lambda word: word not in COMBAT_STRUCTURAL_EDGE_CODES,
    )
    lead = structural_edge_codes(lead)
    tail = structural_edge_codes(tail)
    encoded_pages = []
    # Each translated page starts at row zero after its source 0x8002 clear, so
    # width-hint state must restart independently for its first word.
    for text in pages:
        lines = _combat_lines(text, encoding)
        if any(
            combat_pixel_width(line.text, encoding) > COMBAT_DIALOGUE_LAYOUT.width
            for line in lines
        ):
            return None

        encoded_lines = []
        for line_position, wrapped in enumerate(lines):
            direct = encoding.encode(
                wrapped.text,
                COMBAT_DIALECT,
                normalized=True,
            )
            widths = {glyph.code: glyph.advance for glyph in encoding.glyphs}
            widths.update(
                {
                    code: 16
                    for code in (
                        *NAMED_GLYPH_CODES.values(),
                        *LITERAL_GLYPH_CODES.values(),
                    )
                }
            )
            staged = []
            run = []
            first_run = True

            def flush_run() -> None:
                nonlocal first_run
                if not run:
                    return
                static_width = sum(widths.get(code, 0) for code in run)
                inserts = [
                    index
                    for index, code in enumerate(run)
                    if code in COMBAT_DIALECT.insert_ops
                ]
                if first_run and line_position == 0:
                    staged.extend(run)
                elif inserts == [0]:
                    staged.extend(
                        (
                            RUNTIME_MEASURE_START_CODE,
                            RUNTIME_MEASURE_START_CODE,
                            static_width + 1,
                        )
                    )
                    staged.extend(run)
                elif inserts or static_width > RUNTIME_STATIC_HINT_MAX:
                    staged.extend((RUNTIME_MEASURE_START_CODE, *run))
                    staged.append(RUNTIME_MEASURE_END_CODE)
                    staged.extend(run)
                else:
                    staged.append(RUNTIME_STATIC_HINT_BASE + static_width)
                    staged.extend(run)
                run.clear()
                first_run = False

            for code in direct:
                if code == 267 or (
                    code >= 0x8000 and code not in COMBAT_DIALECT.insert_ops
                ):
                    flush_run()
                    staged.append(code)
                else:
                    run.append(code)
            flush_run()
            encoded_lines.append(pack_codes(staged) if pack_codes else staged)
        encoded_pages.append((lines, encoded_lines))

    first_translated_word = next(
        (
            word
            for _lines, encoded_lines in encoded_pages
            for line in encoded_lines
            for word in line
            if word
            not in {
                RUNTIME_MEASURE_START_CODE,
                RUNTIME_MEASURE_END_CODE,
            }
            and not RUNTIME_STATIC_HINT_BASE <= word <= (RUNTIME_STATIC_HINT_LIMIT - 1)
        ),
        None,
    )
    if (
        first_translated_word in COMBAT_PAUSE_CODES
        and original_words[0] != first_translated_word
    ):
        raise ValueError(
            "COMBAT translation cannot move a pause before the first glyph"
        )
    output = list(lead)

    for page_index, (lines, encoded_lines) in enumerate(encoded_pages):
        for line_index, line in enumerate(encoded_lines):
            if line_index:
                break_code = lines[line_index - 1].break_after
                if break_code is None:
                    raise ValueError("COMBAT line is missing its runtime break")
                output.append(break_code)
            output.extend(line)

        if page_index < len(encoded_pages) - 1:
            boundary = breaks[page_index]
            if 0x8002 not in boundary:
                raise ValueError("COMBAT source page boundary has no 0x8002 clear")
            output.extend(boundary)

    output.extend(tail)
    if 0x8000 not in tail:
        output.append(0x8000)
    return output
