"""Sentence-aware pixel wrapping for the one-off EVENT corpus migration."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass

Measure = Callable[[str], int]

_SENTENCE_END_RE = re.compile(r"(?:\.{2,}|[!?]+|\.)[\"')\]}]*$")
_CLAUSE_END_RE = re.compile(r"[,;][\"')\]}]*$")
_ABBREVIATIONS = frozenset(
    {
        "dr.",
        "jr.",
        "mr.",
        "mrs.",
        "ms.",
        "prof.",
        "sr.",
        "st.",
        "u.s.",
    }
)
_WEAK_BREAK_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "for",
        "from",
        "her",
        "his",
        "if",
        "in",
        "is",
        "its",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "then",
        "these",
        "this",
        "those",
        "to",
        "was",
        "were",
        "with",
        "your",
    }
)

# These weights were fitted against the layout-only edits in the first reviewed
# section of EVFILE_0.EVE. Punctuation dominates, but an extra line is not free:
# short neighboring sentences may still share a row when that is the cleaner
# use of the three-line surface.
_LINE_COST = 1800
_SENTENCE_BREAK_REWARD = 1200
_CLAUSE_BREAK_REWARD = 800
_WEAK_BREAK_COST = 2000
_ORDINARY_BREAK_COST = 800
_SOURCE_LINE_HINT_COST = 800
_SHORT_LINE_PIXELS = 90
_SHORT_NONSEMANTIC_BREAK_PIXELS = 150
_SHORT_NONSEMANTIC_BREAK_COST = 1600


@dataclass(frozen=True)
class _ParagraphCandidate:
    lines: tuple[str, ...]
    widths: tuple[int, ...]
    sentence_breaks: int
    clause_breaks: int
    weak_breaks: int
    ordinary_breaks: int
    short_nonsemantic_breaks: int


@dataclass(frozen=True)
class _Candidate:
    lines: tuple[str, ...]
    widths: tuple[int, ...]
    sentence_breaks: int
    clause_breaks: int
    weak_breaks: int
    ordinary_breaks: int
    short_nonsemantic_breaks: int

    def score(self, preferred_lines: int | None) -> int:
        line_count = len(self.lines)
        total_width = sum(self.widths)
        balance_numerator = sum(
            (line_count * width - total_width) ** 2 for width in self.widths
        )
        balance_cost = balance_numerator // (line_count * line_count * 1000)
        short_line_cost = (
            sum(max(0, _SHORT_LINE_PIXELS - width) ** 2 for width in self.widths) // 100
        )
        source_hint_cost = (
            0
            if preferred_lines is None
            else _SOURCE_LINE_HINT_COST * abs(line_count - preferred_lines)
        )
        return (
            _LINE_COST * line_count
            - _SENTENCE_BREAK_REWARD * self.sentence_breaks
            - _CLAUSE_BREAK_REWARD * self.clause_breaks
            + _WEAK_BREAK_COST * self.weak_breaks
            + _ORDINARY_BREAK_COST * self.ordinary_breaks
            + _SHORT_NONSEMANTIC_BREAK_COST * self.short_nonsemantic_breaks
            + source_hint_cost
            + balance_cost
            + short_line_cost
        )


def _break_kind(word: str) -> str:
    literal = re.sub(r"\{[^{}]+\}", "", word)
    normalized = literal.casefold().strip("\"'()[]{}<>")
    if normalized in _ABBREVIATIONS:
        return "ordinary"
    if _SENTENCE_END_RE.search(literal):
        return "sentence"
    if _CLAUSE_END_RE.search(literal):
        return "clause"
    if normalized.rstrip(".,;:!?") in _WEAK_BREAK_WORDS:
        return "weak"
    return "ordinary"


def _minimum_line_count(words: list[str], measure: Measure, width: int) -> int:
    lines = 0
    start = 0
    while start < len(words):
        end = start + 1
        while end < len(words):
            if measure(" ".join(words[start : end + 1])) > width:
                break
            end += 1
        lines += 1
        start = end
    return max(1, lines)


def _paragraph_candidates(
    paragraph: str,
    *,
    measure: Measure,
    width: int,
    max_lines: int,
) -> list[_ParagraphCandidate]:
    words = paragraph.split()
    if not words:
        return [
            _ParagraphCandidate(
                lines=("",),
                widths=(0,),
                sentence_breaks=0,
                clause_breaks=0,
                weak_breaks=0,
                ordinary_breaks=0,
                short_nonsemantic_breaks=0,
            )
        ]

    candidates = []

    def visit(
        start: int,
        lines: tuple[str, ...],
        widths: tuple[int, ...],
        break_kinds: tuple[str, ...],
    ) -> None:
        if start == len(words):
            candidates.append(
                _ParagraphCandidate(
                    lines=lines,
                    widths=widths,
                    sentence_breaks=break_kinds.count("sentence"),
                    clause_breaks=break_kinds.count("clause"),
                    weak_breaks=break_kinds.count("weak"),
                    ordinary_breaks=break_kinds.count("ordinary"),
                    short_nonsemantic_breaks=sum(
                        kind != "sentence"
                        and line_width < _SHORT_NONSEMANTIC_BREAK_PIXELS
                        for line_width, kind in zip(
                            widths,
                            break_kinds,
                            strict=False,
                        )
                    ),
                )
            )
            return
        if len(lines) >= max_lines:
            return

        for end in range(start + 1, len(words) + 1):
            line = " ".join(words[start:end])
            line_width = measure(line)
            if line_width > width and end > start + 1:
                break
            next_breaks = (
                break_kinds
                if end == len(words)
                else (*break_kinds, _break_kind(words[end - 1]))
            )
            visit(
                end,
                (*lines, line),
                (*widths, line_width),
                next_breaks,
            )
            if line_width > width:
                break

    visit(0, (), (), ())
    return candidates


def wrap_semantic_lines(
    text: str,
    *,
    measure: Measure,
    width: int,
    lines_per_page: int,
    preferred_lines: int | None = None,
) -> list[str]:
    """Wrap normalized text while preferring grammatical line boundaries.

    Existing newlines remain mandatory. When the text can fit on one display
    page, the scorer may use spare rows to avoid an awkward mid-sentence break.
    Text that inherently needs more than one page keeps its minimum line count
    so stylistic wrapping cannot create additional pages.
    """

    if width <= 0:
        raise ValueError("semantic wrap width must be positive")
    if lines_per_page <= 0:
        raise ValueError("semantic wrap line limit must be positive")

    paragraphs = text.split("\n")
    words_by_paragraph = [paragraph.split() for paragraph in paragraphs]
    minimum_lines = [
        _minimum_line_count(words, measure, width) if words else 1
        for words in words_by_paragraph
    ]
    minimum_total = sum(minimum_lines)
    maximum_total = (
        lines_per_page
        if len(paragraphs) == 1 and minimum_total <= lines_per_page
        else minimum_total
    )

    candidate_groups = [
        _paragraph_candidates(
            paragraph,
            measure=measure,
            width=width,
            max_lines=maximum_total - (minimum_total - paragraph_minimum),
        )
        for paragraph, paragraph_minimum in zip(
            paragraphs,
            minimum_lines,
            strict=True,
        )
    ]

    candidates = []
    for group in itertools.product(*candidate_groups):
        lines = tuple(line for paragraph in group for line in paragraph.lines)
        if len(lines) > maximum_total:
            continue
        widths = tuple(
            line_width for paragraph in group for line_width in paragraph.widths
        )
        candidates.append(
            _Candidate(
                lines=lines,
                widths=widths,
                sentence_breaks=sum(paragraph.sentence_breaks for paragraph in group),
                clause_breaks=sum(paragraph.clause_breaks for paragraph in group),
                weak_breaks=sum(paragraph.weak_breaks for paragraph in group),
                ordinary_breaks=sum(paragraph.ordinary_breaks for paragraph in group),
                short_nonsemantic_breaks=sum(
                    paragraph.short_nonsemantic_breaks for paragraph in group
                ),
            )
        )

    if not candidates:
        raise ValueError("semantic wrapper found no valid line arrangement")
    candidates_without_orphans = [
        candidate
        for candidate in candidates
        if all(width >= _SHORT_LINE_PIXELS for width in candidate.widths[:-1])
    ]
    if candidates_without_orphans:
        candidates = candidates_without_orphans
    selected = min(
        candidates,
        key=lambda candidate: (
            candidate.score(preferred_lines),
            len(candidate.lines),
            candidate.widths,
            candidate.lines,
        ),
    )
    return list(selected.lines)
