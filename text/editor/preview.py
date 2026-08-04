"""Preview corpus text through the maintained pipeline layout contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from project_paths import FONT_GENERATED_ROOT
from text.script.dialects import TextDialect, get_dialect
from text.script.encoding.latin import (
    LatinEncoding,
    load_font12_encoding,
    load_latin_encoding,
)
from text.script.encoding.tokens import (
    INLINE_TOKEN_RE,
    normalize_english,
    parse_inline_tokens,
)
from text.script.formats.indexed_bytes.extract import load_atlases
from text.script.formats.indexed_bytes.repack import (
    encode_message as encode_indexed_bytes,
)
from text.script.formats.indexed_bytes.repack import (
    encoding_map,
)
from text.script.formats.indexed_words.repack import wrap_message as wrap_indexed
from text.script.formats.static_overlay.model import (
    AsciiString,
    FixedCells,
    FixedRows,
    SplitLines,
)
from text.script.formats.static_overlay.repack import wrap_message as wrap_static
from text.script.layouts import LayoutSpec, WidthUnit
from text.script.layouts.combat import (
    COMBAT_CHOICE_OPTION_LAYOUT,
    COMBAT_CHOICE_PROMPT_LAYOUT,
    normalize_combat_english,
    wrap_combat_lines,
)
from text.script.layouts.event import wrap_event_lines
from text.script.profiles import TextFont, TextReader, profile_for_reader
from text.script.source_models import (
    AsciiFieldsSource,
    DeduplicatedWordsSource,
    EveSource,
    FixedBytesSource,
    FixedHelpSource,
    FixedWordsSource,
    IndexedBytesSource,
    IndexedWordsSource,
    MirroredWordsSource,
    NameDescriptionSource,
    StaticOverlaySource,
)
from text.script.sources import SOURCES

SOURCE_BY_CORPUS = {source.corpus_path.as_posix(): source for source in SOURCES}
FONT8_METRICS_PATH = FONT_GENERATED_ROOT / "font8_metrics.json"

PreviewFont = TextFont | str


@dataclass(frozen=True)
class PreviewMode:
    source: Any
    profile_name: str
    font: PreviewFont
    dialect: TextDialect
    layout: LayoutSpec
    wrap_kind: str
    exact: bool = True
    consumer_note: str | None = None
    glyph_gap: int = 0


def _eve_preview_modes(
    source: EveSource, metadata: dict[str, Any]
) -> list[PreviewMode]:
    locations = metadata.get("locations")
    if not isinstance(locations, list) or not locations:
        locations = [{}]

    modes = []
    seen = set()
    for location in locations:
        if not isinstance(location, dict):
            continue
        reader = TextReader(location.get("reader", source.default_profile.reader.value))
        profile = profile_for_reader(source.default_profile.dialect, reader)
        font = TextFont(location.get("font", profile.font.value))
        key = (profile.name, font)
        if key in seen:
            continue
        seen.add(key)
        wrap_kind = (
            "event"
            if profile.dialect is TextDialect.EVENT
            and profile.reader is TextReader.TEXT_VM
            else "combat"
            if profile.dialect is TextDialect.COMBAT
            else "raw"
        )
        modes.append(
            PreviewMode(
                source=source,
                profile_name=profile.name,
                font=font,
                dialect=profile.dialect,
                layout=profile.layout,
                wrap_kind=wrap_kind,
                exact=wrap_kind != "raw",
            )
        )
    return modes


def _indexed_preview_mode(source: IndexedWordsSource) -> PreviewMode:
    width = source.layout_width_pixels
    lines = source.layout_lines or 1
    layout = LayoutSpec(
        name=f"{source.name}_indexed_words",
        width=width,
        width_unit=WidthUnit.PIXELS if width is not None else WidthUnit.NONE,
        lines_per_page=lines,
        surface_width=width,
    )
    return PreviewMode(
        source=source,
        profile_name=layout.name,
        font=TextFont.FONT16,
        dialect=source.dialect,
        layout=layout,
        wrap_kind="indexed" if width is not None else "raw",
        exact=width is not None,
    )


def _simple_preview_mode(
    source: Any,
    *,
    profile_name: str,
    font: PreviewFont,
    width: int | None = None,
    lines: int = 1,
    exact: bool = False,
    consumer_note: str | None = None,
    glyph_gap: int = 0,
) -> PreviewMode:
    return PreviewMode(
        source=source,
        profile_name=profile_name,
        font=font,
        dialect=getattr(source, "dialect", TextDialect.EVENT),
        layout=LayoutSpec(
            name=profile_name,
            width=width,
            width_unit=WidthUnit.PIXELS if width is not None else WidthUnit.NONE,
            lines_per_page=lines,
            surface_width=width,
        ),
        wrap_kind="raw",
        exact=exact,
        consumer_note=consumer_note,
        glyph_gap=glyph_gap,
    )


def _static_preview_mode(
    source: StaticOverlaySource,
    metadata: dict[str, Any],
) -> PreviewMode | None:
    kind = metadata.get("kind")
    record = next((row for row in source.records if row.kind == kind), None)
    if record is None:
        return None

    record_layout = record.layout
    if isinstance(record_layout, FixedRows):
        layout = LayoutSpec(
            name=f"{source.name}_{record.kind}",
            width=record_layout.pixel_limit,
            width_unit=WidthUnit.PIXELS,
            lines_per_page=record_layout.rows,
            surface_width=record_layout.pixel_limit,
        )
        wrap_kind = "static_rows"
    elif isinstance(record_layout, SplitLines):
        layout = LayoutSpec(
            name=f"{source.name}_{record.kind}",
            width=record_layout.pixel_limit,
            width_unit=WidthUnit.PIXELS,
            lines_per_page=record_layout.lines,
            surface_width=record_layout.pixel_limit,
        )
        wrap_kind = "static_split"
    elif isinstance(record_layout, FixedCells):
        width = record_layout.pixel_limit
        layout = LayoutSpec(
            name=f"{source.name}_{record.kind}",
            width=width,
            width_unit=WidthUnit.PIXELS if width is not None else WidthUnit.NONE,
            lines_per_page=1,
            surface_width=width,
        )
        wrap_kind = "static_cells"
    elif isinstance(record_layout, AsciiString):
        layout = LayoutSpec(
            name=f"{source.name}_{record.kind}",
            width=None,
            width_unit=WidthUnit.NONE,
            lines_per_page=1,
        )
        wrap_kind = "raw"
    else:
        return None

    return PreviewMode(
        source=source,
        profile_name=layout.name,
        font=TextFont.FONT16,
        dialect=TextDialect.EVENT,
        layout=layout,
        wrap_kind=wrap_kind,
        exact=layout.width is not None,
    )


def resolve_preview_modes(
    file: str,
    metadata: dict[str, Any],
) -> list[PreviewMode]:
    source = SOURCE_BY_CORPUS.get(file)
    if source is None and file in {
        "runtime_ui/healing_ui.json",
        "runtime_ui/shop_ui.json",
    }:
        width = 144 if file.endswith("healing_ui.json") else 64
        return [
            _simple_preview_mode(
                source,
                profile_name=(
                    "healing_runtime_font8"
                    if file.endswith("healing_ui.json")
                    else "shop_runtime_font8"
                ),
                font="font8",
                width=width,
                exact=True,
                consumer_note="verified generated FONT8 runtime field width",
                glyph_gap=1,
            )
        ]
    if isinstance(source, EveSource):
        return _eve_preview_modes(source, metadata)
    if isinstance(source, IndexedWordsSource):
        return [_indexed_preview_mode(source)]
    if isinstance(source, IndexedBytesSource):
        return [
            _simple_preview_mode(
                source,
                profile_name=f"{source.name}_fixed_console",
                font="console_mixed",
                consumer_note=(
                    "verified FNT8X12/FNT12X12 fixed-cell consumer; window width "
                    "is not mapped"
                ),
            )
        ]
    if isinstance(source, FixedBytesSource):
        return [
            _simple_preview_mode(
                source,
                profile_name=f"{source.name}_font8_field",
                font="font8",
                width=source.pixel_limit,
                exact=True,
                consumer_note="verified FONT8 field width",
            )
        ]
    if isinstance(source, NameDescriptionSource):
        if metadata.get("_field") == "name":
            return [
                _simple_preview_mode(
                    source,
                    profile_name=f"{source.name}_name",
                    font="font8",
                    width=source.max_full_name_pixels,
                    exact=True,
                    consumer_note="verified FONT8 full-name limit",
                )
            ]
        return [
            _simple_preview_mode(
                source,
                profile_name=f"{source.name}_description",
                font=TextFont.FONT16,
                consumer_note="verified FONT16 consumer; window width is not mapped",
            )
        ]
    if isinstance(source, FixedHelpSource):
        return [
            _simple_preview_mode(
                source,
                profile_name=f"{source.name}_help",
                font=TextFont.FONT16,
                lines=source.max_lines,
                consumer_note="verified FONT16 consumer; storage is checked separately",
            )
        ]
    if isinstance(
        source,
        (FixedWordsSource, MirroredWordsSource, DeduplicatedWordsSource),
    ):
        return [
            _simple_preview_mode(
                source,
                profile_name=f"{source.name}_fixed_words",
                font=TextFont.FONT16,
                consumer_note="verified FONT16 consumer; window geometry is not mapped",
            )
        ]
    if isinstance(source, AsciiFieldsSource):
        if source.name == "automap_marker_ui":
            return [
                _simple_preview_mode(
                    source,
                    profile_name="automap_marker_vwf",
                    font=TextFont.FONT16,
                    width=64,
                    exact=True,
                    consumer_note=(
                        "runtime-owned proportional FONT16 marker row; native "
                        "ASCII storage is checked separately"
                    ),
                )
            ]
        capacity = metadata.get("capacity_bytes")
        width = (
            (capacity - 1) * 8 if isinstance(capacity, int) and capacity > 0 else None
        )
        return [
            _simple_preview_mode(
                source,
                profile_name=f"{source.name}_console_field",
                font="console8",
                width=width,
                exact=width is not None,
                consumer_note=(
                    "verified fixed-width 8x12 console storage; the shown width is "
                    "field capacity, not a mapped window"
                ),
            )
        ]
    if isinstance(source, StaticOverlaySource):
        mode = _static_preview_mode(source, metadata)
        if mode is not None:
            return [mode]

    return [
        PreviewMode(
            source=source,
            profile_name="no_pixel_layout",
            font=TextFont.FONT16,
            dialect=getattr(source, "dialect", TextDialect.EVENT),
            layout=LayoutSpec(
                name="no_pixel_layout",
                width=None,
                width_unit=WidthUnit.NONE,
                lines_per_page=1,
            ),
            wrap_kind="raw",
            exact=False,
        )
    ]


def _encoding(font: PreviewFont) -> LatinEncoding:
    if font is TextFont.FONT12:
        return load_font12_encoding()
    if font == "font8":
        return load_latin_encoding(FONT8_METRICS_PATH)
    return load_latin_encoding()


def _wrapped_lines(
    mode: PreviewMode, english: str, encoding: LatinEncoding
) -> list[str]:
    if mode.wrap_kind == "event":
        return wrap_event_lines(english, encoding, mode.layout)
    if mode.wrap_kind == "combat":
        return wrap_combat_lines(english, encoding, mode.layout)
    if mode.wrap_kind == "indexed":
        return wrap_indexed(english, mode.source, encoding).split("\n")
    if mode.wrap_kind == "static_rows":
        return list(
            wrap_static(
                english,
                mode.layout.width,
                mode.layout.lines_per_page,
                encoding,
            )
        )
    if mode.wrap_kind == "static_split":
        return english.split("{n}")
    if mode.wrap_kind == "static_cells":
        return [english]
    return normalize_english(english).split("\n")


def _measure_line(
    line: str,
    mode: PreviewMode,
    encoding: LatinEncoding,
) -> int:
    if mode.font == "console8":
        try:
            return len(line.encode("ascii")) * 8
        except UnicodeEncodeError as error:
            raise ValueError("fixed 8x12 console text must be ASCII") from error
    if mode.font == "console_mixed":
        primary, secondary = load_atlases(mode.source)
        payload = encode_indexed_bytes(line, mode.source, primary, secondary)[:-1]
        return sum(
            8
            if value < mode.source.secondary_base
            else 12
            if value < mode.source.terminator
            else 0
            for value in payload
        )
    if mode.wrap_kind.startswith("static_"):
        width = encoding.measure_segment(line)
    else:
        width = encoding.measure(
            line,
            get_dialect(mode.dialect),
            mode.layout.insert_width,
        )
    if mode.glyph_gap:
        glyph_count = len(encoding.segment_glyphs(line))
        width += max(0, glyph_count - 1) * mode.glyph_gap
    return width


def _font_key(font: PreviewFont) -> str:
    return font.value if isinstance(font, TextFont) else font


def _mode_id(mode: PreviewMode) -> str:
    return f"{mode.profile_name}:{_font_key(mode.font)}"


def render_menu_slot_previews(
    file: str,
    metadata: dict[str, Any],
    english: str,
    *,
    role: str,
) -> list[dict[str, Any]]:
    """Measure COMBAT choice text against its exact runtime slot.

    Choice records are still encoded by the ordinary COMBAT pipeline, whose
    dialogue wrapper is 320 pixels by three rows.  Measuring the authored rows
    directly here prevents that wrapper from hiding the stricter one-row menu
    contract.
    """

    source = SOURCE_BY_CORPUS.get(file)
    if (
        not isinstance(source, EveSource)
        or source.default_profile.dialect is not TextDialect.COMBAT
    ):
        return []
    if role == "prompt":
        layout = COMBAT_CHOICE_PROMPT_LAYOUT
    elif role == "option":
        layout = COMBAT_CHOICE_OPTION_LAYOUT
    else:
        raise ValueError(f"unknown menu slot role: {role!r}")

    authored_lines = normalize_combat_english(english).split("\n")
    previews = []
    for mode in resolve_preview_modes(file, metadata):
        if mode.dialect is not TextDialect.COMBAT:
            continue
        slot_mode = replace(mode, layout=layout)
        encoding = _encoding(mode.font)
        error = None
        rendered_lines = []
        for line in authored_lines:
            try:
                width = _measure_line(line, slot_mode, encoding)
            except ValueError as caught:
                error = error or str(caught)
                width = None
            rendered_lines.append({"text": line, "width": width})

        over_width = sum(
            line["width"] is not None and line["width"] > layout.width
            for line in rendered_lines
        )
        previews.append(
            {
                "variant_id": _mode_id(mode),
                "role": role,
                "content_width": layout.width,
                "max_lines": layout.lines_per_page,
                "line_count": len(rendered_lines),
                "lines": rendered_lines,
                "token_widths": _token_widths(english, slot_mode),
                "over_width_lines": over_width,
                "overflow": (
                    error is not None
                    or len(rendered_lines) > layout.lines_per_page
                    or over_width > 0
                ),
                "exact": True,
                "error": error,
            }
        )
    return previews


def _token_widths(text: str, mode: PreviewMode) -> dict[str, int]:
    if isinstance(mode.font, str) and mode.font.startswith("console"):
        return {}
    dialect = get_dialect(mode.dialect)
    widths = {}
    for match in INLINE_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token in {"{n}", "{NL}"}:
            continue
        try:
            parts = parse_inline_tokens(token, dialect)
        except ValueError:
            continue
        if len(parts) == 1 and isinstance(parts[0], int):
            widths[token] = mode.layout.insert_width(parts[0])
    return widths


def page_line_counts(mode: PreviewMode, line_count: int) -> list[int]:
    """Match how the owning consumer distributes wrapped lines across pages."""

    if line_count <= 0:
        return [0]
    limit = mode.layout.lines_per_page
    if mode.wrap_kind == "event":
        page_count = max(1, -(-line_count // limit))
        counts = []
        consumed = 0
        for page_index in range(page_count):
            remaining = line_count - consumed
            pages_left = page_count - page_index
            count = -(-remaining // pages_left)
            counts.append(count)
            consumed += count
        return counts
    if mode.wrap_kind == "combat":
        return [min(limit, line_count - start) for start in range(0, line_count, limit)]
    return [line_count]


def _render_mode(mode: PreviewMode, english: str) -> dict[str, Any]:
    encoding = _encoding(mode.font)
    error = None
    try:
        lines = _wrapped_lines(mode, english, encoding)
    except ValueError as caught:
        error = str(caught)
        lines = normalize_english(english).split("\n")

    rendered_lines = []
    for line in lines:
        try:
            width = _measure_line(line, mode, encoding)
        except ValueError as caught:
            error = error or str(caught)
            width = None
        rendered_lines.append({"text": line, "width": width})

    layout = mode.layout
    surface_width = layout.surface_width
    if surface_width is None and layout.width_unit is WidthUnit.PIXELS:
        surface_width = layout.width
    font_key = _font_key(mode.font)
    font_labels = {
        "font12": "FONT12 / Ark 11px",
        "font16": "FONT16 / Ark 12px",
        "font8": "FONT8 / Ark 8px",
        "console8": "fixed 8x12 console",
        "console_mixed": "fixed FNT8X12 / FNT12X12 console",
    }
    font_names = {
        "font12": "FONT12.FON",
        "font16": "FONT16.FON",
        "font8": "FONT8.FON",
        "console8": "fixed 8x12",
        "console_mixed": "FNT8X12/FNT12X12",
    }
    font_name = font_names[font_key]
    glyph_widths = {}
    if font_key == "console_mixed":
        primary, secondary = load_atlases(mode.source)
        glyph_widths = {
            text: 8 if value < mode.source.secondary_base else 12
            for text, value in encoding_map(mode.source, primary, secondary).items()
        }
    constraints = []
    if layout.width is not None:
        constraints.append(f"{layout.width}px usable width")
    if layout.left_margin or layout.right_margin:
        constraints.append(
            f"{layout.left_margin}px left / {layout.right_margin}px right margin"
        )
    constraints.append(
        f"{layout.lines_per_page} "
        f"{'line' if layout.lines_per_page == 1 else 'lines'} per page"
    )
    if not mode.exact:
        constraints.append("no pipeline pixel-wrap rule")
    if mode.consumer_note:
        constraints.append(mode.consumer_note)

    return {
        "id": _mode_id(mode),
        "label": f"{mode.profile_name.replace('_', ' ')} · {font_name}",
        "profile": mode.profile_name,
        "font": font_key,
        "font_label": font_labels[font_key],
        "fixed_advance": 8 if font_key == "console8" else None,
        "glyph_gap": mode.glyph_gap,
        "glyph_widths": glyph_widths,
        "surface_width": surface_width,
        "content_width": (
            layout.width if layout.width_unit is WidthUnit.PIXELS else None
        ),
        "left_margin": layout.left_margin,
        "right_margin": layout.right_margin,
        "lines_per_page": layout.lines_per_page,
        "page_line_counts": page_line_counts(mode, len(rendered_lines)),
        "lines": rendered_lines,
        "token_widths": _token_widths(english, mode),
        "constraints": constraints,
        "exact": mode.exact,
        "error": error,
    }


def render_pipeline_preview(
    file: str,
    metadata: dict[str, Any],
    english: str,
) -> dict[str, Any]:
    modes = resolve_preview_modes(file, metadata)
    return {"variants": [_render_mode(mode, english) for mode in modes]}
