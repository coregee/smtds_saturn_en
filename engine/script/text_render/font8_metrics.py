"""Load the generated FONT8 width table and character mapping."""

import json
from functools import cache
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT

FONT_GENERATED_ROOT = DEFAULT_CONTEXT.font_generated_root

METRICS_PATH = FONT_GENERATED_ROOT / "font8_metrics.json"


def load_metrics(
    path: Path = METRICS_PATH,
) -> tuple[bytes, dict[str, int]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 2 or not document.get("complete"):
        raise ValueError(f"{path}: incomplete FONT8 metrics")
    table = document.get("width_table", {})
    if table.get("code_limit") != 256 or table.get("measurement") != "ink":
        raise ValueError(f"{path}: expected a 256-entry ink-width table")

    widths = bytearray(256)
    codes = {}
    for row in document.get("glyphs", ()):
        code = row.get("code")
        advance = row.get("advance")
        if not isinstance(code, int) or not 0 <= code < 256:
            raise ValueError(f"{path}: invalid glyph code")
        if not isinstance(advance, int) or not 1 <= advance <= 8:
            raise ValueError(f"{path}: invalid FONT8 advance")
        widths[code] = advance
        for text in (row.get("text"), *row.get("aliases", ())):
            if isinstance(text, str) and len(text) == 1:
                codes.setdefault(text, code)
    return bytes(widths), codes


@cache
def font8_metrics(
    path: Path = METRICS_PATH,
) -> tuple[bytes, dict[str, int]]:
    """Load and cache FONT8 metrics from an explicit generated path."""
    return load_metrics(path)
