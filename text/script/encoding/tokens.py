import re

from text.script.dialects import DialectSpec

NORMALIZE_CHARACTERS = {
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "—": "-",
    "–": "-",
    "…": "...",
    "é": "e",
    "　": " ",
    " ": " ",
}

NAMED_GLYPH_CODES = {
    "yen_symbol": 0x00C0,
    "mag_symbol": 0x00C1,
    "white_square": 0x00C0,
    "maru_symbol": 0x0106,
}

LITERAL_GLYPH_CODES = {
    # The source table decodes FONT16's stock outline-heart cell as U+300E.
    "\u300e": 0x0105,
    "♂": 0x00B8,
    "←": 0x00BF,
}

INLINE_TOKEN_RE = re.compile(
    r"\{(?:(INS|OP|GLYPH):([0-9a-fA-F]{4})|"
    r"([A-Za-z_][A-Za-z0-9_]*))\}"
)


def normalize_english(text: str) -> str:
    for source, replacement in NORMALIZE_CHARACTERS.items():
        text = text.replace(source, replacement)
    text = text.replace("{n}", "\n")
    text = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    return re.sub(r"([.!?])([A-Za-z{])", r"\1 \2", text)


def parse_inline_tokens(
    text: str,
    dialect: DialectSpec,
) -> tuple[str | int, ...]:
    token_codes = {
        token.removeprefix("{").removesuffix("}"): code
        for code, token in dialect.inline_pause_tokens.items()
    }
    token_codes.update(NAMED_GLYPH_CODES)
    token_codes.update(dialect.named_insert_codes)
    parts = []
    position = 0

    def append_literal(literal: str) -> None:
        literal_start = 0
        for literal_position, character in enumerate(literal):
            code = LITERAL_GLYPH_CODES.get(character)
            if code is None:
                continue
            if literal_position > literal_start:
                parts.append(literal[literal_start:literal_position])
            parts.append(code)
            literal_start = literal_position + 1
        if literal_start < len(literal):
            parts.append(literal[literal_start:])

    for match in INLINE_TOKEN_RE.finditer(text):
        if match.start() > position:
            literal = text[position : match.start()]
            if "{" in literal or "}" in literal:
                raise ValueError(f"unknown text token in {literal!r}")
            append_literal(literal)

        if match.group(3) is not None:
            token_name = match.group(3)
            try:
                code = token_codes[token_name]
            except KeyError as error:
                raise ValueError(
                    f"{{{token_name}}} is not valid in {dialect.kind.value} text"
                ) from error
        else:
            token_kind = match.group(1)
            code = int(match.group(2), 16)
            if token_kind == "INS" and code not in dialect.insert_ops:
                raise ValueError(
                    f"{code:#06x} is not a {dialect.kind.value} insert operation"
                )
            if token_kind == "OP" and (
                not code & 0x8000 or code in {0x8000, 0x8001, 0x8002, 0x8003}
            ):
                raise ValueError(f"{code:#06x} is not an inline control operation")
            if token_kind == "GLYPH" and code & 0x8000:
                raise ValueError(f"{code:#06x} is not a glyph code")

        parts.append(code)
        position = match.end()

    if position < len(text):
        literal = text[position:]
        if "{" in literal or "}" in literal:
            raise ValueError(f"unknown text token in {literal!r}")
        append_literal(literal)
    return tuple(parts)
