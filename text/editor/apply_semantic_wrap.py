"""Apply sentence-aware EVENT line breaks to the corpus exactly once."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from project_paths import TEXT_CORPUS_ROOT
from text.editor.preview import SOURCE_BY_CORPUS, PreviewMode, resolve_preview_modes
from text.editor.server import JsonSpanParser, discover_translation_entries
from text.script.dialects import EVENT_DIALECT, TextDialect
from text.script.encoding.latin import LatinEncoding, load_latin_encoding
from text.script.layouts.semantic import wrap_semantic_lines
from text.script.profiles import TextFont
from text.script.source_models import EveSource

AUTHORED_LINE_MARKERS = ("\n", "{n}", "{NL}", "{OP:8001}")


@dataclass(frozen=True)
class MigrationPlan:
    updated_text: str
    changed: int
    unchanged: int
    skipped_authored: int
    skipped_profile: int


def _eligible_mode(file: str, metadata: dict) -> PreviewMode | None:
    modes = resolve_preview_modes(file, metadata)
    if len(modes) != 1:
        return None
    mode = modes[0]
    if (
        mode.wrap_kind != "event"
        or mode.font is not TextFont.FONT16
        or mode.dialect is not TextDialect.EVENT
        or mode.layout.width is None
    ):
        return None
    return mode


def semantic_event_lines(
    translation: str,
    japanese: str,
    mode: PreviewMode,
    encoding: LatinEncoding,
) -> list[str]:
    """Choose migration-only breaks without normalizing corpus punctuation."""

    if any(marker in translation for marker in AUTHORED_LINE_MARKERS):
        raise ValueError("semantic migration cannot replace authored line breaks")

    # Eligible corpus entries already use canonical single spacing. Keeping the
    # original punctuation adjacency matters: "...The" is a continuation, not
    # a standalone ellipsis sentence for migration purposes.
    source_line = " ".join(translation.split())
    if source_line != translation:
        raise ValueError("semantic migration requires canonical corpus spacing")

    @cache
    def measure(value: str) -> int:
        return encoding.measure(
            value,
            EVENT_DIALECT,
            mode.layout.insert_width,
        )

    return wrap_semantic_lines(
        source_line,
        measure=measure,
        width=mode.layout.width,
        lines_per_page=mode.layout.lines_per_page,
        preferred_lines=min(
            japanese.count("{n}") + japanese.count("\n") + 1,
            mode.layout.lines_per_page,
        ),
    )


def plan_migration(
    source_text: str,
    *,
    file: str,
    encoding: LatinEncoding,
) -> MigrationPlan:
    parser = JsonSpanParser(source_text)
    document = parser.parse()
    replacements: list[tuple[int, int, str]] = []
    changed = 0
    unchanged = 0
    skipped_authored = 0
    skipped_profile = 0

    for entry in discover_translation_entries(document, file=file):
        mode = _eligible_mode(file, entry["metadata"])
        if mode is None:
            skipped_profile += 1
            continue

        translation = entry["tr"]
        if any(marker in translation for marker in AUTHORED_LINE_MARKERS):
            skipped_authored += 1
            continue

        updated_translation = "\n".join(
            semantic_event_lines(
                translation,
                entry["jp"],
                mode,
                encoding,
            )
        )
        if updated_translation == translation:
            unchanged += 1
            continue
        if updated_translation.replace("\n", " ") != translation:
            raise ValueError(
                f"{file} {entry['pointer']}: migration changed more than whitespace"
            )

        span_path = (*entry["pointer"], "tr")
        try:
            start, end = parser.string_spans[span_path]
        except KeyError as error:
            raise ValueError(
                f"{file} {entry['pointer']}: missing translation span"
            ) from error
        replacements.append(
            (start, end, json.dumps(updated_translation, ensure_ascii=False))
        )
        if entry["reviewed"]:
            reviewed_path = (*entry["pointer"], "reviewed")
            try:
                reviewed_start, reviewed_end = parser.scalar_spans[reviewed_path]
            except KeyError as error:
                raise ValueError(
                    f"{file} {entry['pointer']}: missing reviewed span"
                ) from error
            replacements.append((reviewed_start, reviewed_end, "false"))
        changed += 1

    updated_text = source_text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated_text = f"{updated_text[:start]}{replacement}{updated_text[end:]}"
    json.loads(updated_text)
    return MigrationPlan(
        updated_text=updated_text,
        changed=changed,
        unchanged=unchanged,
        skipped_authored=skipped_authored,
        skipped_profile=skipped_profile,
    )


def _write_atomic(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _default_paths() -> tuple[Path, ...]:
    relative_paths = sorted(
        Path(relative)
        for relative, source in SOURCE_BY_CORPUS.items()
        if isinstance(source, EveSource)
        and source.default_profile.dialect is TextDialect.EVENT
    )
    return tuple(TEXT_CORPUS_ROOT / relative for relative in relative_paths)


def _selected_paths(arguments: Sequence[str]) -> tuple[Path, ...]:
    if not arguments:
        return _default_paths()

    selected = []
    corpus_root = TEXT_CORPUS_ROOT.resolve()
    for raw in arguments:
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        if path.is_dir():
            candidates = sorted(path.rglob("*.json"))
        else:
            candidates = [path]
        for candidate in candidates:
            candidate.resolve().relative_to(corpus_root)
            selected.append(candidate)
    return tuple(dict.fromkeys(selected))


def run(paths: Sequence[Path], *, check: bool) -> int:
    encoding = load_latin_encoding()
    total_changed = 0
    for path in paths:
        relative = path.resolve().relative_to(TEXT_CORPUS_ROOT.resolve()).as_posix()
        source_text = path.read_text(encoding="utf-8")
        plan = plan_migration(source_text, file=relative, encoding=encoding)
        total_changed += plan.changed
        action = "would add" if check else "added"
        print(
            f"{relative}: {action} {plan.changed} wraps; "
            f"{plan.skipped_authored} authored, {plan.unchanged} unchanged, "
            f"{plan.skipped_profile} other-profile"
        )
        if plan.changed and not check:
            _write_atomic(path, plan.updated_text)

    print(f"semantic EVENT migration: {total_changed} corpus fields")
    return 1 if check and total_changed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write sentence-aware newlines once to unformatted FONT16 EVENT dialogue."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="corpus JSON files or directories; defaults to EVENT EVE sources",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report fields that would change without writing them",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    raise SystemExit(run(_selected_paths(arguments.paths), check=arguments.check))


if __name__ == "__main__":
    main()
