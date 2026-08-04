from text.script.dialects import EVENT_DIALECT
from text.script.encoding.latin import LatinEncoding
from text.script.encoding.tokens import (
    LITERAL_GLYPH_CODES,
    NAMED_GLYPH_CODES,
    normalize_english,
)
from text.script.layouts.model import LayoutSpec, WidthUnit
from text.script.layouts.structure import (
    page_structure,
    terminator_suffix,
    with_terminator,
)

EVENT_DIALOGUE_LAYOUT = LayoutSpec(
    name="event_dialogue",
    width=314,
    width_unit=WidthUnit.PIXELS,
    lines_per_page=3,
    surface_width=320,
    left_margin=3,
    right_margin=3,
    # Runtime name fields accept eight characters.  Reserve the widest
    # possible configured value ("WWWWWWWW", 8 * 10px) so wrapping remains
    # valid after EVENT/MSGR substitutes the live value.
    default_insert_width=80,
    insert_widths={
        code: 16
        for code in (*NAMED_GLYPH_CODES.values(), *LITERAL_GLYPH_CODES.values())
    },
)

EVENT_MENU_LAYOUT = LayoutSpec(
    name="event_menu",
    width=None,
    width_unit=WidthUnit.NONE,
    lines_per_page=1,
)


def wrap_event_lines(
    text: str,
    encoding: LatinEncoding,
    layout: LayoutSpec = EVENT_DIALOGUE_LAYOUT,
) -> list[str]:
    if layout.width is None:
        return [normalize_english(text)]

    lines = []
    for explicit_line in normalize_english(text).split("\n"):
        words = [word for word in explicit_line.split(" ") if word]
        current = []
        for word in words:
            candidate = " ".join((*current, word))
            width = encoding.measure(
                candidate,
                EVENT_DIALECT,
                layout.insert_width,
            )
            if current and width > layout.width:
                lines.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(" ".join(current))
        elif not words:
            lines.append("")
    return lines


def layout_event_message(
    original_words: tuple[int, ...],
    text: str,
    encoding: LatinEncoding,
    *,
    wrap: bool,
    packed: bool,
    pack_codes=None,
) -> list[int]:
    _page_sizes, breaks = page_structure(original_words)
    final_break = list(breaks[-1])

    if not wrap:
        output = encoding.encode(
            text,
            EVENT_DIALECT,
            packed=packed,
            pack_codes=pack_codes,
        )
    else:
        lines = wrap_event_lines(text, encoding)
        interior = breaks[:-1]
        separator_template = (
            list(interior[-1])
            if interior
            else ([0x8003, 0x8002] if 0x8003 in final_break else [0x8002])
        )
        capacity_pages = max(
            1,
            -(-len(lines) // EVENT_DIALOGUE_LAYOUT.lines_per_page),
        )
        original_page_count = len(interior) + 1
        page_count = min(
            len(lines),
            max(capacity_pages, original_page_count),
        )

        output = []
        line_position = 0
        for page_index in range(page_count):
            remaining = len(lines) - line_position
            pages_left = page_count - page_index
            line_count = -(-remaining // pages_left)
            if not 1 <= line_count <= EVENT_DIALOGUE_LAYOUT.lines_per_page:
                raise ValueError("EVENT page exceeds its line capacity")
            page_lines = lines[line_position : line_position + line_count]
            line_position += line_count

            for line_index, line in enumerate(page_lines):
                if line_index:
                    output.append(0x8001)
                output.extend(
                    encoding.encode(
                        line,
                        EVENT_DIALECT,
                        packed=packed,
                        pack_codes=pack_codes,
                    )
                )

            if page_index < page_count - 1:
                separator = list(
                    interior[page_index]
                    if page_index < len(interior)
                    else separator_template
                )
                if 0x8002 not in separator:
                    separator.append(0x8002)
                output.extend(separator)

    output.extend(final_break)
    return with_terminator(output, terminator_suffix(original_words))


def layout_event_pages(
    original_words: tuple[int, ...],
    pages: list[str],
    encoding: LatinEncoding,
    *,
    packed: bool,
    pack_codes=None,
) -> list[int]:
    _page_sizes, breaks = page_structure(original_words)
    if len(pages) != len(breaks):
        raise ValueError(
            f"translation page count {len(pages)} != source page count {len(breaks)}"
        )

    final_break = list(breaks[-1])
    interior = breaks[:-1]
    output = []

    for group_index, text in enumerate(pages):
        lines = wrap_event_lines(text, encoding)
        subpage_count = max(
            1,
            -(-len(lines) // EVENT_DIALOGUE_LAYOUT.lines_per_page),
        )
        line_position = 0
        for subpage_index in range(subpage_count):
            remaining = len(lines) - line_position
            pages_left = subpage_count - subpage_index
            line_count = -(-remaining // pages_left)
            page_lines = lines[line_position : line_position + line_count]
            line_position += line_count

            for line_index, line in enumerate(page_lines):
                if line_index:
                    output.append(0x8001)
                output.extend(
                    encoding.encode(
                        line,
                        EVENT_DIALECT,
                        packed=packed,
                        pack_codes=pack_codes,
                    )
                )

            last_subpage = subpage_index == subpage_count - 1
            last_group = group_index == len(pages) - 1
            if not last_subpage:
                separator = list(
                    interior[group_index]
                    if group_index < len(interior)
                    else final_break
                )
                if 0x8002 not in separator:
                    separator.append(0x8002)
                output.extend(separator)
            elif not last_group:
                output.extend(interior[group_index])

    output.extend(final_break)
    return with_terminator(output, terminator_suffix(original_words))


def encode_event_translation(
    original_words: tuple[int, ...],
    pages: list[str],
    encoding: LatinEncoding,
    *,
    raw_reader: bool,
    packed: bool,
    pack_codes=None,
) -> list[int]:
    if raw_reader:
        return layout_event_message(
            original_words,
            " ".join(pages),
            encoding,
            wrap=False,
            packed=False,
        )
    if len(pages) > 1:
        return layout_event_pages(
            original_words,
            pages,
            encoding,
            packed=packed,
            pack_codes=pack_codes,
        )

    return layout_event_message(
        original_words,
        pages[0],
        encoding,
        wrap=True,
        packed=packed,
        pack_codes=pack_codes,
    )
