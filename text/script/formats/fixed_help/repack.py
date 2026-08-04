import json
import struct
from pathlib import Path

from text.script.dialects import get_dialect
from text.script.encoding.latin import load_latin_encoding
from text.script.encoding.tokens import normalize_english
from text.script.formats.fixed_help.extract import TERMINATOR, extract_corpus
from text.script.formats.fixed_help.model import FixedHelpResult
from text.script.source_models import FixedHelpSource

NEWLINE = 0x8001


def indentation(words: tuple[int, ...]) -> tuple[int, int]:
    end = words.index(TERMINATOR)
    content = words[:end]
    leading = 0
    while leading < len(content) and content[leading] == 0:
        leading += 1

    post_newline = 0
    if NEWLINE in content:
        position = content.index(NEWLINE) + 1
        while (
            position + post_newline < len(content)
            and content[position + post_newline] == 0
        ):
            post_newline += 1
    return leading, post_newline


def encode_record(
    text: str,
    source: FixedHelpSource,
    leading: int,
    post_newline: int,
) -> tuple[int, ...]:
    lines = tuple(normalize_english(text).split("\n"))
    if not 1 <= len(lines) <= source.max_lines or any(not line for line in lines):
        raise ValueError(
            f"{source.path}: help text needs one or two nonempty lines: {text!r}"
        )

    encoding = load_latin_encoding()
    dialect = get_dialect(source.dialect)
    words = [0] * leading
    for line_index, line in enumerate(lines):
        if line_index:
            words.append(NEWLINE)
            words.extend([0] * post_newline)
        words.extend(encoding.encode(line, dialect, packed=source.packed))
    words.append(TERMINATOR)
    return tuple(words)


def repack_help(source: FixedHelpSource, corpus_root: Path) -> FixedHelpResult:
    corpus_path = corpus_root / source.corpus_path
    corpus_rows = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus_rows != extract_corpus(source, corpus_root):
        raise ValueError(
            f"{corpus_path}: stale or malformed corpus; regenerate with extract.py"
        )

    original = source.input_path.read_bytes()
    output = bytearray(len(original))
    longest = 0
    translated = 0
    for record, row in enumerate(corpus_rows):
        offset = record * source.record_words * 2
        words = struct.unpack_from(f">{source.record_words}H", original, offset)
        leading, post_newline = indentation(words)
        translation = row["tr"].strip()
        if not translation:
            raise ValueError(f"{corpus_path}: record at {offset:#x} is untranslated")
        encoded = encode_record(translation, source, leading, post_newline)
        if len(encoded) > source.record_words:
            raise ValueError(
                f"{source.path}: record at {offset:#x} uses "
                f"{len(encoded)}/{source.record_words} words: {translation!r}"
            )
        struct.pack_into(f">{len(encoded)}H", output, offset, *encoded)
        longest = max(longest, len(encoded))
        translated += 1

    return FixedHelpResult(
        data=bytes(output),
        records=source.record_count,
        translated_records=translated,
        longest_words=longest,
        capacity_words=source.record_words,
    )
