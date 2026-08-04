"""Shared JSON loading primitives for translator-facing corpus formats."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranslationState:
    """Editable target state retained when a corpus source identity survives."""

    translation: str
    reviewed: bool
    excluded: bool
    english_reference: str | None = None


def is_placeholder_source(japanese: str) -> bool:
    """Return whether a source has no reviewable content beyond line markers."""

    return not japanese.replace("{n}", "").strip()


def load_json_array(path: Path) -> list:
    """Load an optional corpus array while leaving row validation to its format."""
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a JSON array")
    return rows


def load_translation_state(value: object, context: str) -> TranslationState:
    """Validate the strict target schema without treating ``en`` as a fallback."""

    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    translation = value.get("tr")
    if not isinstance(translation, str):
        raise ValueError(f"{context}.tr must be text")
    reviewed = value.get("reviewed")
    if not isinstance(reviewed, bool):
        raise ValueError(f"{context}.reviewed must be boolean")
    excluded = value.get("excluded")
    if not isinstance(excluded, bool):
        raise ValueError(f"{context}.excluded must be boolean")
    if "en" in value and not isinstance(value["en"], str):
        raise ValueError(f"{context}.en must be text when present")
    english_reference = value.get("en")
    return TranslationState(translation, reviewed, excluded, english_reference)


def translation_pair(
    japanese: str,
    state: TranslationState | None = None,
) -> dict[str, object]:
    """Create one canonical ``jp``/``tr`` pair, retaining optional English source."""

    if state is None:
        state = TranslationState("", False, is_placeholder_source(japanese))
    pair: dict[str, object] = {"jp": japanese}
    if state.english_reference is not None:
        pair["en"] = state.english_reference
    pair["tr"] = state.translation
    pair["reviewed"] = state.reviewed
    pair["excluded"] = state.excluded
    return pair
