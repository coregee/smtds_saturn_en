"""Report translation coverage and verify preserved inline opcodes."""

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from project_paths import TEXT_ROOT
from text.script.corpus_io import load_translation_state
from text.script.dialects import NAMED_INSERT_TOKENS
from text.script.encoding.tokens import NAMED_GLYPH_CODES
from text.script.source_models import FixedWordsSource
from text.script.sources import SOURCES

CORPUS_ROOT = TEXT_ROOT / "corpus"
BRACE_TOKEN = re.compile(r"\{[^{}]+\}")
WORD_OPCODE = re.compile(
    r"\{(?:(INS|OP|GLYPH):([0-9a-fA-F]{4})|"
    r"(BEAT|WAIT|" + "|".join(sorted(NAMED_INSERT_TOKENS)) + r"))\}"
)
BYTE_OPCODE = re.compile(r"\{(?:(OP|GLYPH):([0-9a-fA-F]{2})|(NUM))\}")
FLEXIBLE_NAME_TOKENS = frozenset({"first_name", "last_name"})
DIALECT_FIXED_WORD_PATHS = frozenset(
    (CORPUS_ROOT / source.corpus_path).resolve()
    for source in SOURCES
    if isinstance(source, FixedWordsSource) and source.dialect is not None
)


@dataclass(frozen=True)
class TranslationField:
    path: Path
    pointer: tuple[str | int, ...]
    japanese: str
    translation: str
    reviewed: bool
    excluded: bool

    @property
    def label(self) -> str:
        suffix = "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in self.pointer
        )
        return f"{self.path.as_posix()}{suffix}"


@dataclass(frozen=True)
class FileStatus:
    path: Path
    fields: int
    status_fields: int
    translated: int
    empty: int
    status_excluded: int
    status_reviewed: int
    status_translated: int
    status_untranslated: int
    opcode_mismatches: int
    invalid_tokens: int


def iter_translation_fields(
    value: object,
    path: Path,
    pointer: tuple[str | int, ...] = (),
):
    if isinstance(value, dict):
        japanese = value.get("jp")
        has_target_state = any(key in value for key in ("tr", "reviewed", "excluded"))
        if isinstance(japanese, str) or has_target_state:
            suffix = "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}" for part in pointer
            )
            context = f"{path.as_posix()}{suffix}"
            if not isinstance(japanese, str):
                raise ValueError(f"{context}.jp must be text")
            state = load_translation_state(value, context)
            yield TranslationField(
                path,
                pointer,
                japanese,
                state.translation,
                state.reviewed,
                state.excluded,
            )
        for key, child in value.items():
            yield from iter_translation_fields(child, path, (*pointer, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_translation_fields(child, path, (*pointer, index))


def opcode_pattern(path: Path) -> re.Pattern | None:
    parts = {part.casefold() for part in path.parts}
    if "indexed_bytes" in parts:
        return BYTE_OPCODE
    if parts & {"eve", "indexed_words", "name_description"} or (
        path.resolve() in DIALECT_FIXED_WORD_PATHS
    ):
        return WORD_OPCODE
    return None


def opcode_counter(path: Path, text: str) -> Counter:
    pattern = opcode_pattern(path)
    if pattern is None:
        return Counter()
    output = Counter()
    for match in pattern.finditer(text):
        if match.group(1) == "GLYPH":
            continue
        named_token = match.group(3)
        if named_token in FLEXIBLE_NAME_TOKENS:
            continue
        if named_token is not None:
            output[(named_token, None)] += 1
        else:
            output[(match.group(1), int(match.group(2), 16))] += 1
    return output


def allowed_translation_tokens(path: Path) -> set[str]:
    parts = {part.casefold() for part in path.parts}
    if "indexed_bytes" in parts:
        return {"{NUM}"}
    allowed = {"{n}"}
    if "fixed_words" in parts:
        allowed.add("{insert}")
    if parts & {"eve", "fixed_help", "indexed_words", "name_description"} or (
        path.resolve() in DIALECT_FIXED_WORD_PATHS
    ):
        allowed.update({"{NL}", "{BEAT}", "{WAIT}"})
        allowed.update(f"{{{name}}}" for name in NAMED_GLYPH_CODES)
        allowed.update(f"{{{name}}}" for name in NAMED_INSERT_TOKENS)
    return allowed


def invalid_translation_tokens(path: Path, text: str) -> tuple[str, ...]:
    pattern = opcode_pattern(path)
    invalid = []
    for token in BRACE_TOKEN.findall(text):
        if token in allowed_translation_tokens(path):
            continue
        if pattern is not None and pattern.fullmatch(token):
            continue
        invalid.append(token)
    return tuple(invalid)


def has_translatable_source(text: str) -> bool:
    """Ignore padding-only records whose source contains only line markers."""
    return bool(text.replace("{n}", "").strip())


def scan_file(path: Path) -> tuple[FileStatus, list[str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    all_fields = list(iter_translation_fields(document, path))
    fields = [field for field in all_fields if has_translatable_source(field.japanese)]
    translatable = {field.pointer for field in fields}
    issues = []
    translated = 0
    empty = 0
    status_excluded = 0
    status_reviewed = 0
    status_translated = 0
    status_untranslated = 0
    mismatches = 0
    invalid_count = 0

    for field in all_fields:
        if field.excluded:
            status_excluded += 1
        elif field.reviewed:
            status_reviewed += 1
        elif field.translation.strip():
            status_translated += 1
        else:
            status_untranslated += 1

        if not field.translation.strip():
            if field.pointer in translatable:
                empty += 1
            continue
        if field.pointer in translatable:
            translated += 1
        japanese_opcodes = opcode_counter(path, field.japanese)
        translation_opcodes = opcode_counter(path, field.translation)
        if japanese_opcodes != translation_opcodes:
            mismatches += 1
            missing = japanese_opcodes - translation_opcodes
            extra = translation_opcodes - japanese_opcodes
            issues.append(
                f"{field.label}: opcode mismatch; "
                f"missing={dict(missing)}, extra={dict(extra)}"
            )
        invalid = invalid_translation_tokens(path, field.translation)
        if invalid:
            invalid_count += 1
            issues.append(f"{field.label}: invalid translation tokens {invalid}")

    return (
        FileStatus(
            path=path,
            fields=len(fields),
            status_fields=len(all_fields),
            translated=translated,
            empty=empty,
            status_excluded=status_excluded,
            status_reviewed=status_reviewed,
            status_translated=status_translated,
            status_untranslated=status_untranslated,
            opcode_mismatches=mismatches,
            invalid_tokens=invalid_count,
        ),
        issues,
    )


def select_paths(arguments: tuple[str, ...]) -> tuple[Path, ...]:
    if not arguments:
        return tuple(sorted(CORPUS_ROOT.rglob("*.json")))
    paths = []
    for raw in arguments:
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.json")))
        elif path.suffix.casefold() == ".json":
            paths.append(path)
        else:
            raise ValueError(f"{path}: expected a JSON file or directory")
    return tuple(dict.fromkeys(path.resolve() for path in paths))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="corpus JSON files or directories; defaults to the complete corpus",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when any translation is empty or structurally invalid",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="with --check, allow blank translations but reject structural errors",
    )
    arguments = parser.parse_args()

    try:
        statuses = []
        issues = []
        for path in select_paths(tuple(arguments.paths)):
            status, file_issues = scan_file(path)
            statuses.append(status)
            issues.extend(file_issues)
            if status.status_fields:
                print(
                    f"{path.relative_to(Path.cwd())}: "
                    f"{status.translated}/{status.fields} translated; "
                    f"{status.empty} empty, "
                    "review status "
                    f"{status.status_excluded} excluded / "
                    f"{status.status_reviewed} reviewed / "
                    f"{status.status_translated} translated / "
                    f"{status.status_untranslated} untranslated "
                    f"({status.status_fields} total fields); "
                    f"{status.opcode_mismatches} opcode mismatches, "
                    f"{status.invalid_tokens} invalid-token fields"
                )

        totals = FileStatus(
            path=CORPUS_ROOT,
            fields=sum(status.fields for status in statuses),
            status_fields=sum(status.status_fields for status in statuses),
            translated=sum(status.translated for status in statuses),
            empty=sum(status.empty for status in statuses),
            status_excluded=sum(status.status_excluded for status in statuses),
            status_reviewed=sum(status.status_reviewed for status in statuses),
            status_translated=sum(status.status_translated for status in statuses),
            status_untranslated=sum(status.status_untranslated for status in statuses),
            opcode_mismatches=sum(status.opcode_mismatches for status in statuses),
            invalid_tokens=sum(status.invalid_tokens for status in statuses),
        )
        print(
            f"TOTAL: {totals.translated}/{totals.fields} translated; "
            f"{totals.empty} empty, "
            "review status "
            f"{totals.status_excluded} excluded / "
            f"{totals.status_reviewed} reviewed / "
            f"{totals.status_translated} translated / "
            f"{totals.status_untranslated} untranslated "
            f"({totals.status_fields} total fields); "
            f"{totals.opcode_mismatches} opcode mismatches, "
            f"{totals.invalid_tokens} invalid-token fields"
        )
        for issue in issues:
            print(f"  {issue}")
        if arguments.check and (
            (totals.empty and not arguments.allow_empty)
            or totals.opcode_mismatches
            or totals.invalid_tokens
        ):
            raise ValueError("translation coverage check failed")
    except (json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
