from text.script.formats.eve.model import EveMessage, EvePage

PAGE_CLEAR_OP = 0x8002
PAGE_EDGE_OPS = {0x8002, 0x8003}
PAYLOAD_OPS = {
    0x8006,
    0x8007,
    *range(0x8010, 0x8024),
}


def has_payload(words: tuple[int, ...]) -> bool:
    return any(not (word & 0x8000) or word in PAYLOAD_OPS for word in words)


def split_pages(message: EveMessage) -> tuple[EvePage, ...]:
    words = message.words
    try:
        text_end = words.index(0x8000)
    except ValueError:
        text_end = len(words)
    pages = []
    page_start = 0
    cursor = 0

    while cursor < text_end:
        if not (words[cursor] & 0x8000):
            cursor += 1
            continue

        run_start = cursor
        while cursor < text_end and words[cursor] & 0x8000:
            cursor += 1
        run = words[run_start:cursor]
        page_positions = [
            offset for offset, word in enumerate(run) if word in PAGE_EDGE_OPS
        ]
        if PAGE_CLEAR_OP not in run:
            continue

        first_page_op = run_start + page_positions[0]
        after_last_page_op = run_start + page_positions[-1] + 1
        later_payload = has_payload(words[after_last_page_op:text_end])

        if later_payload:
            if not has_payload(words[page_start:first_page_op]):
                continue
            pages.append(
                EvePage(
                    index=len(pages),
                    content_start_word=page_start,
                    content_end_word=first_page_op,
                    boundary_codes=words[first_page_op:after_last_page_op],
                    words=words[page_start:first_page_op],
                )
            )
            page_start = after_last_page_op
        else:
            pages.append(
                EvePage(
                    index=len(pages),
                    content_start_word=page_start,
                    content_end_word=first_page_op,
                    boundary_codes=words[first_page_op:],
                    words=words[page_start:first_page_op],
                )
            )
            page_start = len(words)
            break

    if page_start < len(words) or not pages:
        content_end = text_end
        while content_end > page_start and words[content_end - 1] == 0x8003:
            content_end -= 1
        pages.append(
            EvePage(
                index=len(pages),
                content_start_word=page_start,
                content_end_word=content_end,
                boundary_codes=words[content_end:],
                words=words[page_start:content_end],
            )
        )

    reconstructed = tuple(
        word
        for page in pages
        for segment in (page.words, page.boundary_codes)
        for word in segment
    )
    if reconstructed != words:
        raise ValueError(f"EVE message {message.index} page split is not lossless")
    return tuple(pages)
