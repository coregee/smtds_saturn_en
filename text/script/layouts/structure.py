from collections.abc import Callable


def is_glyph_payload(word: int) -> bool:
    return not word & 0x8000


def split_skeleton(
    words: tuple[int, ...],
    *,
    is_payload: Callable[[int], bool] | None = None,
) -> tuple[list[int], list[int]]:
    if is_payload is None:
        is_payload = is_glyph_payload
    first = None
    last = None
    for index, word in enumerate(words):
        if is_payload(word):
            if first is None:
                first = index
            last = index

    if first is None or last is None:
        return list(words), []
    return list(words[:first]), list(words[last + 1 :])


def page_structure(
    words: tuple[int, ...],
) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]:
    try:
        words = words[: words.index(0x8000) + 1]
    except ValueError:
        pass
    page_glyphs = [0]
    breaks = [[]]
    position = 0

    while position < len(words):
        word = words[position]
        if word & 0x8000:
            run = []
            while position < len(words) and words[position] & 0x8000:
                run.append(words[position])
                position += 1
            page_break = [control for control in run if control in (0x8002, 0x8003)]
            later_payload = any(not (later & 0x8000) for later in words[position:])
            if page_break and (0x8002 in run or not later_payload):
                breaks[-1] = page_break
                if 0x8002 in run and later_payload:
                    page_glyphs.append(0)
                    breaks.append([])
        else:
            page_glyphs[-1] += 1
            position += 1

    return tuple(page_glyphs), tuple(tuple(run) for run in breaks)


def terminator_suffix(words: tuple[int, ...]) -> tuple[int, ...]:
    try:
        return words[words.index(0x8000) :]
    except ValueError:
        return (0x8000,)


def with_terminator(
    words: list[int],
    suffix: tuple[int, ...] = (0x8000,),
) -> list[int]:
    output = [word for word in words if word != 0x8000]
    output.extend(suffix)
    return output
