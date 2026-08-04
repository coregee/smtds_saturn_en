"""Corpus-trained dictionary tokens for packed EVENT dialogue."""

from collections import Counter
from dataclasses import dataclass

PACKED_TOKEN_BASE = 8
PACKED_TOKEN_LIMIT = 120
DICTIONARY_TOKEN_START = 63
DICTIONARY_TOKENS = PACKED_TOKEN_LIMIT - DICTIONARY_TOKEN_START
MAX_EXPANSION = 7
SPACE_CODE = 267

BASE_CODES = (SPACE_CODE, *range(1, DICTIONARY_TOKEN_START))
CODE_TO_BASE_TOKEN = {code: token for token, code in enumerate(BASE_CODES)}


def replace_pair(
    tokens: list[int],
    pair: tuple[int, int],
    replacement: int,
) -> list[int]:
    output = []
    position = 0
    while position < len(tokens):
        if (
            position + 1 < len(tokens)
            and (tokens[position], tokens[position + 1]) == pair
        ):
            output.append(replacement)
            position += 2
        else:
            output.append(tokens[position])
            position += 1
    return output


@dataclass(frozen=True)
class EventDictionary:
    """Sequential byte-pair merges over the stock packed Latin alphabet."""

    merges: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if len(self.merges) > DICTIONARY_TOKENS:
            raise ValueError("EVENT dictionary has too many merges")
        expansions = [tuple((token,)) for token in range(DICTIONARY_TOKEN_START)]
        for index, pair in enumerate(self.merges):
            token = DICTIONARY_TOKEN_START + index
            if any(not 0 <= value < token for value in pair):
                raise ValueError(
                    f"EVENT dictionary token {token} has a forward reference"
                )
            expansion = expansions[pair[0]] + expansions[pair[1]]
            if len(expansion) > MAX_EXPANSION:
                raise ValueError(
                    f"EVENT dictionary token {token} expands to {len(expansion)} glyphs"
                )
            expansions.append(expansion)

    @property
    def expansions(self) -> tuple[tuple[int, ...], ...]:
        expansions = [tuple((token,)) for token in range(DICTIONARY_TOKEN_START)]
        for left, right in self.merges:
            expansions.append(expansions[left] + expansions[right])
        return tuple(expansions[DICTIONARY_TOKEN_START:])

    def encode_tokens(self, tokens: list[int]) -> list[int]:
        output = list(tokens)
        for index, pair in enumerate(self.merges):
            output = replace_pair(
                output,
                pair,
                DICTIONARY_TOKEN_START + index,
            )
        return output

    def encode_codes(self, codes: list[int]) -> list[int]:
        """Pack base glyphs two per word and retain other glyph/control words."""
        output = []
        direct = []

        def flush() -> None:
            tokens = self.encode_tokens(direct)
            for position in range(0, len(tokens), 2):
                first = tokens[position] + PACKED_TOKEN_BASE
                second = (
                    tokens[position + 1] + PACKED_TOKEN_BASE
                    if position + 1 < len(tokens)
                    else 0
                )
                output.append(first << 8 | second)
            direct.clear()

        for code in codes:
            token = CODE_TO_BASE_TOKEN.get(code)
            if token is None:
                flush()
                output.append(code)
            else:
                direct.append(token)
        flush()
        return output

    def decode_words(self, words: list[int] | tuple[int, ...]) -> list[int]:
        """Reference decoder used by build validation and unit tests."""
        expansions = self.expansions
        output = []
        for word in words:
            first = word >> 8
            token = first - PACKED_TOKEN_BASE
            if not 0 <= token < PACKED_TOKEN_LIMIT:
                output.append(word)
                continue
            packed = [token]
            second = word & 0xFF
            if second:
                token = second - PACKED_TOKEN_BASE
                if not 0 <= token < PACKED_TOKEN_LIMIT:
                    raise ValueError(f"invalid packed EVENT token byte {second:#x}")
                packed.append(token)
            for token in packed:
                base_tokens = (
                    expansions[token - DICTIONARY_TOKEN_START]
                    if token >= DICTIONARY_TOKEN_START
                    else (token,)
                )
                output.extend(BASE_CODES[value] for value in base_tokens)
        return output

    def manifest(self) -> dict:
        return {
            "version": 1,
            "token_base": PACKED_TOKEN_BASE,
            "token_limit": PACKED_TOKEN_LIMIT,
            "dictionary_token_start": DICTIONARY_TOKEN_START,
            "max_expansion": MAX_EXPANSION,
            "base_codes": list(BASE_CODES),
            "merges": [list(pair) for pair in self.merges],
            "expansions": [list(expansion) for expansion in self.expansions],
        }


def train_event_dictionary(sequences: list[list[int]]) -> EventDictionary:
    """Choose deterministic, bounded byte-pair merges for base-token runs."""
    working = [list(sequence) for sequence in sequences if sequence]
    expansions = [tuple((token,)) for token in range(DICTIONARY_TOKEN_START)]
    merges = []

    for token in range(DICTIONARY_TOKEN_START, PACKED_TOKEN_LIMIT):
        counts = Counter(
            pair for sequence in working for pair in zip(sequence, sequence[1:])
        )
        candidates = [
            (count, pair)
            for pair, count in counts.items()
            if count >= 2
            and len(expansions[pair[0]]) + len(expansions[pair[1]]) <= MAX_EXPANSION
        ]
        if not candidates:
            break
        _count, pair = min(candidates, key=lambda item: (-item[0], item[1]))
        merges.append(pair)
        expansions.append(expansions[pair[0]] + expansions[pair[1]])
        working = [replace_pair(sequence, pair, token) for sequence in working]

    return EventDictionary(tuple(merges))


def base_token_runs(words: list[int] | tuple[int, ...]) -> list[list[int]]:
    """Return compressible runs from an unpacked EVENT word stream."""
    runs = []
    current = []
    for word in words:
        token = CODE_TO_BASE_TOKEN.get(word)
        if token is None:
            if current:
                runs.append(current)
                current = []
        else:
            current.append(token)
    if current:
        runs.append(current)
    return runs


def dictionary_from_manifest(document: dict) -> EventDictionary:
    if document.get("version") != 1:
        raise ValueError("unsupported EVENT dictionary manifest")
    expected = {
        "token_base": PACKED_TOKEN_BASE,
        "token_limit": PACKED_TOKEN_LIMIT,
        "dictionary_token_start": DICTIONARY_TOKEN_START,
        "max_expansion": MAX_EXPANSION,
        "base_codes": list(BASE_CODES),
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise ValueError(f"EVENT dictionary manifest has invalid {key}")
    try:
        merges = tuple(tuple(pair) for pair in document["merges"])
    except (KeyError, TypeError) as error:
        raise ValueError("EVENT dictionary manifest has invalid merges") from error
    dictionary = EventDictionary(merges)
    if document.get("expansions") != [list(row) for row in dictionary.expansions]:
        raise ValueError("EVENT dictionary manifest expansions do not match its merges")
    return dictionary
