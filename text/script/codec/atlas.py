import json
from dataclasses import dataclass
from pathlib import Path

from project_paths import FONT_ROOT

FONT_ATLAS_PATH = FONT_ROOT / "atlas"


@dataclass(frozen=True)
class FontAtlas:
    by_index: dict[int, str]
    by_text: dict[str, int]
    ambiguous_text: frozenset[str]

    def index_for(self, text: str) -> int:
        """Resolve an original or replacement glyph value to its cell."""
        if text in self.ambiguous_text:
            raise ValueError(f"ambiguous atlas glyph {text!r}")
        try:
            return self.by_text[text]
        except KeyError as error:
            raise ValueError(f"unknown atlas glyph {text!r}") from error


def parse_decimal_index(value: int | str, context: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{context}: glyph index must be decimal")
    try:
        index = int(value, 10) if isinstance(value, str) else value
    except ValueError as error:
        raise ValueError(f"{context}: glyph index must be decimal") from error
    if not isinstance(index, int) or index < 0:
        raise ValueError(f"{context}: glyph index must be a non-negative integer")
    return index


def load_atlas(path: Path) -> FontAtlas:
    """Load stock decoding and original/replacement encoding aliases."""
    groups = json.loads(path.read_text(encoding="utf-8"))["atlas"]
    by_index = {}
    indices_by_text = {}
    preferred_aliases = {}

    def add(index: int, original: str, aliases: tuple[str, ...], context: str) -> None:
        if index in by_index:
            raise ValueError(f"{path.name}.atlas: duplicate glyph index {index}")
        by_index[index] = original
        for alias in aliases:
            indices_by_text.setdefault(alias, set()).add(index)

    for group, entries in groups.items():
        if not isinstance(entries, list):
            raise ValueError(f"{path.name}.atlas.{group}: expected an array")
        for entry_number, entry in enumerate(entries):
            context = f"{path.name}.atlas.{group}[{entry_number}]"
            if not isinstance(entry, dict) or not entry:
                raise ValueError(f"{context}: expected a non-empty object")
            replace = entry.get("replace", False)
            if not isinstance(replace, bool):
                raise ValueError(f"{context}: replace must be true or false")

            if "start" in entry:
                fields = set(entry)
                value_fields = fields & {"characters", "glyphs"}
                invalid_fields = fields - {
                    "start",
                    "characters",
                    "glyphs",
                    "replace",
                }
                if len(value_fields) != 1 or invalid_fields:
                    raise ValueError(
                        f"{context}: range needs start and exactly one value field"
                    )
                start = parse_decimal_index(entry["start"], context)
                raw_values = entry[value_fields.pop()]
                if isinstance(raw_values, str):
                    values = tuple(raw_values)
                elif isinstance(raw_values, list) and all(
                    isinstance(value, str) and value for value in raw_values
                ):
                    values = tuple(raw_values)
                else:
                    raise ValueError(f"{context}: invalid glyph values")
                if not values:
                    raise ValueError(f"{context}: mapping range is empty")
                for offset, value in enumerate(values):
                    add(start + offset, value, (value,), context)
                continue

            mappings = {
                index: value for index, value in entry.items() if index != "replace"
            }
            if not mappings:
                raise ValueError(f"{context}: mapping object is empty")
            for raw_index, value in mappings.items():
                index = parse_decimal_index(raw_index, context)
                if isinstance(value, str) and value:
                    original = value
                    aliases = (value,)
                elif isinstance(value, dict) and len(value) == 1:
                    original, replacement = next(iter(value.items()))
                    if not isinstance(original, str) or not (
                        isinstance(replacement, str) or replacement is None
                    ):
                        raise ValueError(
                            f"{context}.{raw_index}: alias must map to a string or null"
                        )
                    if not original:
                        raise ValueError(
                            f"{context}.{raw_index}: original glyph cannot be empty"
                        )
                    if replacement:
                        aliases = (original, replacement)
                        preferred_aliases.setdefault(replacement, index)
                    else:
                        aliases = (original,)
                else:
                    raise ValueError(
                        f"{context}.{raw_index}: glyph must be a string or one-pair alias"
                    )
                add(index, original, aliases, context)

    ambiguous = frozenset(
        text
        for text, indices in indices_by_text.items()
        if len(indices) > 1 and text not in preferred_aliases
    )
    by_text = {
        text: next(iter(indices))
        for text, indices in indices_by_text.items()
        if len(indices) == 1
    }
    by_text.update(preferred_aliases)
    return FontAtlas(by_index, by_text, ambiguous)


FONT8_ATLAS = load_atlas(FONT_ATLAS_PATH / "font8.json")
FONT12_ATLAS = load_atlas(FONT_ATLAS_PATH / "font12.json")
FONT16_ATLAS = load_atlas(FONT_ATLAS_PATH / "font16.json")
FONT8_GLYPHS = FONT8_ATLAS.by_index
FONT12_GLYPHS = FONT12_ATLAS.by_index
FONT16_GLYPHS = FONT16_ATLAS.by_index
