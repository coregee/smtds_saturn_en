import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from project_paths import FONT_ROOT as FONT_PATH
from project_paths import PROJECT_ROOT as SATURN_ROOT

EXTRACTED_PATH = SATURN_ROOT / "rom" / "extracted"
BUILD_PATH = SATURN_ROOT / "rom" / "build"
GENERATED_PATH = FONT_PATH / "generated"
ATLAS_PATH = FONT_PATH / "atlas"
IMAGE_PATH = FONT_PATH / "image"
CONFIG_PATH = FONT_PATH / "config"


@dataclass(frozen=True)
class FontSpec:
    path: str
    width: int
    height: int
    bpp: int
    row_stride: int
    glyph_stride: int

    @property
    def name(self) -> str:
        return Path(self.path).stem.lower()


@dataclass(frozen=True)
class RenderOptions:
    columns: int = 16
    scale: int = 4


DEFAULT_RENDER_OPTIONS = RenderOptions()


@dataclass(frozen=True)
class GlyphRange:
    start: int
    characters: tuple[str, ...]


@dataclass(frozen=True)
class TypefaceOptions:
    size: int
    face_index: int = 0
    placement: str = "center"
    anchor: str = "mm"
    offset_x: int = 0
    offset_y: int = 0
    stroke_width: int = 0
    antialias: bool = True
    compose_from_glyphs: bool = False
    glyph_offsets: tuple["GlyphOffset", ...] = ()


@dataclass(frozen=True)
class GlyphOffset:
    characters: tuple[str, ...]
    offset_x: int = 0
    offset_y: int = 0


@dataclass(frozen=True)
class AdvanceTableOptions:
    storage_glyph: int
    code_limit: int


@dataclass(frozen=True)
class MetricsOptions:
    code_limit: int
    measurement: str = "source"
    space_advance: int | None = None


@dataclass(frozen=True)
class FontFileOptions:
    use_font_file: bool
    source: Path | None
    typeface: TypefaceOptions | None
    preserve_unreplaced: bool = False
    blank_glyphs: tuple[int, ...] = ()
    advance_table: AdvanceTableOptions | None = None
    metrics: MetricsOptions | None = None


@dataclass(frozen=True)
class FontDefinition:
    spec: FontSpec
    render: RenderOptions
    original_glyphs: Mapping[int, str]
    replacement_ranges: Mapping[str, tuple[GlyphRange, ...]]
    font_file: FontFileOptions


DEFINITION_FILES = (
    "font6.json",
    "fnt8x12.json",
    "fnt12x12.json",
    "font8.json",
    "font12.json",
    "font16.json",
    "icon.json",
    "kanji.json",
)


def parse_decimal_index(value: int | str, context: str) -> int:
    """Parse a non-negative decimal glyph index."""
    if isinstance(value, bool):
        raise ValueError(f"{context}: glyph index must be decimal")
    try:
        index = int(value, 10) if isinstance(value, str) else value
    except ValueError as error:
        raise ValueError(f"{context}: glyph index must be decimal") from error
    if not isinstance(index, int) or index < 0:
        raise ValueError(f"{context}: glyph index must be a non-negative integer")
    return index


def parse_group_entries(
    groups: Mapping[str, object],
    context: str,
) -> tuple[dict[int, str], dict[str, tuple[GlyphRange, ...]]]:
    """Expand named atlas groups and their inline replacement entries."""
    glyphs = {}
    parsed_groups = {}

    for group, entries in groups.items():
        if not isinstance(group, str) or not group:
            raise ValueError(f"{context}: atlas group names must be non-empty strings")
        if not isinstance(entries, list):
            raise ValueError(f"{context}.{group}: expected an array of mapping objects")

        ranges = []
        replacement_ranges = []
        for entry_number, entry in enumerate(entries):
            entry_context = f"{context}.{group}[{entry_number}]"
            if not isinstance(entry, dict) or not entry:
                raise ValueError(f"{entry_context}: expected a non-empty object")

            replace = entry.get("replace", False)
            if not isinstance(replace, bool):
                raise ValueError(f"{entry_context}: replace must be true or false")

            if "start" in entry:
                fields = set(entry)
                value_fields = fields & {"characters", "glyphs"}
                allowed_fields = {
                    "start",
                    "characters",
                    "glyphs",
                    "replace",
                }
                if len(value_fields) != 1 or fields - allowed_fields:
                    raise ValueError(
                        f"{entry_context}: range needs start and exactly one of "
                        "characters or glyphs"
                    )
                start = parse_decimal_index(entry["start"], entry_context)
                raw_values = entry[value_fields.pop()]
                if isinstance(raw_values, str):
                    values = tuple(raw_values)
                elif isinstance(raw_values, list) and all(
                    isinstance(value, str) and value for value in raw_values
                ):
                    values = tuple(raw_values)
                else:
                    raise ValueError(
                        f"{entry_context}: glyph values must be a string or string array"
                    )
                if not values:
                    raise ValueError(f"{entry_context}: mapping range is empty")
                ranges.append(GlyphRange(start=start, characters=values))
                if replace:
                    replacement_ranges.append(
                        GlyphRange(start=start, characters=values)
                    )
            else:
                mappings = {
                    index: value for index, value in entry.items() if index != "replace"
                }
                if not mappings:
                    raise ValueError(f"{entry_context}: mapping object is empty")
                for raw_index, value in mappings.items():
                    index_context = f"{entry_context}.{raw_index}"
                    index = parse_decimal_index(raw_index, index_context)
                    if isinstance(value, str) and value:
                        original = value
                        replacement = value
                    elif isinstance(value, dict) and len(value) == 1:
                        original, replacement = next(iter(value.items()))
                        if not isinstance(original, str) or not (
                            isinstance(replacement, str) or replacement is None
                        ):
                            raise ValueError(
                                f"{index_context}: alias must map to a string or null"
                            )
                        if not original:
                            raise ValueError(
                                f"{index_context}: original glyph must be non-empty"
                            )
                    else:
                        raise ValueError(
                            f"{index_context}: glyph must be a string or one-pair alias"
                        )
                    ranges.append(GlyphRange(start=index, characters=(original,)))
                    if replace and replacement:
                        replacement_ranges.append(
                            GlyphRange(start=index, characters=(replacement,))
                        )

        for glyph_range in ranges:
            for offset, character in enumerate(glyph_range.characters):
                index = glyph_range.start + offset
                if index in glyphs:
                    raise ValueError(f"{context}: duplicate glyph index {index}")
                glyphs[index] = character
        parsed_groups[group] = tuple(replacement_ranges)

    return glyphs, parsed_groups


def load_config(path: Path) -> FontDefinition:
    """Load one game-font definition and repack configuration."""
    data = json.loads(path.read_text(encoding="utf-8"))
    format_data = data["format"]
    atlas_config = data["atlas"]
    repack_data = data["repack"]
    atlas_path = (path.parent / atlas_config["file"]).resolve()
    atlas_data = json.loads(atlas_path.read_text(encoding="utf-8"))
    if atlas_data["file"].casefold() != data["file"].casefold():
        raise ValueError(
            f"{path.name} targets {data['file']}, but {atlas_path.name} "
            f"describes {atlas_data['file']}"
        )

    original_glyphs, replacement_ranges = parse_group_entries(
        atlas_data["atlas"],
        f"{atlas_path.name}.atlas",
    )

    source = None
    typeface = None
    blank_glyphs = ()
    advance_table = None
    metrics = None
    if repack_data["use_font_file"]:
        source = Path(repack_data["source"]).expanduser()
        if not source.is_absolute():
            source = (path.parent / source).resolve()

        typeface_data = repack_data["render"]
        glyph_offsets = []
        adjusted_characters = set()
        for adjustment_number, adjustment in enumerate(
            typeface_data.get("glyph_offsets", ())
        ):
            adjustment_context = (
                f"{path.name}.repack.render.glyph_offsets[{adjustment_number}]"
            )
            if not isinstance(adjustment, dict):
                raise ValueError(f"{adjustment_context}: expected an object")
            characters = adjustment.get("characters")
            if not isinstance(characters, str) or not characters:
                raise ValueError(
                    f"{adjustment_context}: characters must be a non-empty string"
                )
            duplicates = adjusted_characters & set(characters)
            if duplicates:
                raise ValueError(
                    f"{adjustment_context}: duplicate adjusted characters "
                    f"{''.join(sorted(duplicates))!r}"
                )
            adjusted_characters.update(characters)
            glyph_offsets.append(
                GlyphOffset(
                    characters=tuple(characters),
                    offset_x=adjustment.get("offset_x", 0),
                    offset_y=adjustment.get("offset_y", 0),
                )
            )
        typeface = TypefaceOptions(
            size=typeface_data["size"],
            face_index=typeface_data.get("face_index", 0),
            placement=typeface_data.get("placement", "center"),
            anchor=typeface_data.get("anchor", "mm"),
            offset_x=typeface_data.get("offset_x", 0),
            offset_y=typeface_data.get("offset_y", 0),
            stroke_width=typeface_data.get("stroke_width", 0),
            antialias=typeface_data.get("antialias", True),
            compose_from_glyphs=typeface_data.get("compose_from_glyphs", False),
            glyph_offsets=tuple(glyph_offsets),
        )
        blank_glyphs = tuple(repack_data.get("blank_glyphs", ()))
        advance_table_data = repack_data.get("advance_table")
        if advance_table_data:
            advance_table = AdvanceTableOptions(
                storage_glyph=advance_table_data["storage_glyph"],
                code_limit=advance_table_data["code_limit"],
            )
        metrics_data = repack_data.get("metrics")
        if metrics_data:
            measurement = metrics_data.get("measurement", "source")
            if measurement not in {"source", "ink"}:
                raise ValueError(
                    f"{path.name}: metrics measurement must be source or ink"
                )
            space_advance = metrics_data.get("space_advance")
            if space_advance is not None and (
                not isinstance(space_advance, int)
                or not 1 <= space_advance <= format_data["width"]
            ):
                raise ValueError(
                    f"{path.name}: metrics space advance must fit the glyph"
                )
            metrics = MetricsOptions(
                code_limit=metrics_data["code_limit"],
                measurement=measurement,
                space_advance=space_advance,
            )
        elif advance_table is not None:
            metrics = MetricsOptions(code_limit=advance_table.code_limit)

    return FontDefinition(
        spec=FontSpec(
            path=data["file"],
            width=format_data["width"],
            height=format_data["height"],
            bpp=format_data["bpp"],
            row_stride=format_data["row_stride"],
            glyph_stride=format_data["glyph_stride"],
        ),
        render=RenderOptions(
            columns=atlas_config["columns"],
            scale=atlas_config["scale"],
        ),
        original_glyphs=original_glyphs,
        replacement_ranges=replacement_ranges,
        font_file=FontFileOptions(
            use_font_file=repack_data["use_font_file"],
            source=source,
            typeface=typeface,
            preserve_unreplaced=repack_data.get("preserve_unreplaced", False),
            blank_glyphs=blank_glyphs,
            advance_table=advance_table,
            metrics=metrics,
        ),
    )


DEFINITIONS = tuple(
    load_config(CONFIG_PATH / filename) for filename in DEFINITION_FILES
)
FONTS = tuple(definition.spec for definition in DEFINITIONS)
RENDER_OPTIONS = {definition.spec.path: definition.render for definition in DEFINITIONS}


def get_definition(name: str) -> FontDefinition:
    """Find a font definition by filename or stem."""
    key = name.casefold()
    for definition in DEFINITIONS:
        spec = definition.spec
        if key in (spec.path.casefold(), spec.name.casefold()):
            return definition

    choices = ", ".join(spec.path for spec in FONTS)
    raise ValueError(f"unknown font {name!r}; choose from: {choices}")


def select_definitions(names: Sequence[str]) -> tuple[FontDefinition, ...]:
    """Select definitions by font filename or stem."""
    if not names:
        return DEFINITIONS
    return tuple(get_definition(name) for name in names)


def select_fonts(names: Sequence[str]) -> tuple[FontSpec, ...]:
    """Select fonts by filename or stem, case-insensitively."""
    if not names:
        return FONTS

    lookup: dict[str, FontSpec] = {}
    for spec in FONTS:
        lookup[spec.path.casefold()] = spec
        lookup[Path(spec.path).stem.casefold()] = spec

    selected = []
    for name in names:
        key = name.casefold()
        if key not in lookup:
            choices = ", ".join(spec.path for spec in FONTS)
            raise ValueError(f"unknown font {name!r}; choose from: {choices}")
        selected.append(lookup[key])

    return tuple(selected)


def glyph_count(font_data: bytes | bytearray, spec: FontSpec) -> int:
    """Return the number of complete glyph records in a font."""
    remainder = len(font_data) % spec.glyph_stride
    if remainder:
        raise ValueError(
            f"{spec.path} has {remainder} bytes after its last complete glyph"
        )
    return len(font_data) // spec.glyph_stride


def pixel_position(x: int, bpp: int) -> tuple[int, int, int]:
    """Return byte index, right shift, and value mask for an MSB-first pixel."""
    if bpp not in (1, 2, 4):
        raise ValueError(f"unsupported bpp: {bpp}")

    pixels_per_byte = 8 // bpp
    byte_index = x // pixels_per_byte
    pixel_index = x % pixels_per_byte
    shift = (pixels_per_byte - 1 - pixel_index) * bpp
    mask = (1 << bpp) - 1
    return byte_index, shift, mask


def get_pixel(row: bytes | bytearray, x: int, bpp: int) -> int:
    """Read one packed pixel from a byte row."""
    byte_index, shift, mask = pixel_position(x, bpp)
    return (row[byte_index] >> shift) & mask


def set_pixel(row: bytearray, x: int, bpp: int, value: int) -> None:
    """Replace one packed pixel without changing adjacent bits."""
    byte_index, shift, mask = pixel_position(x, bpp)
    shifted_mask = mask << shift
    cleared_byte = row[byte_index] & (0xFF ^ shifted_mask)
    row[byte_index] = cleared_byte | ((value & mask) << shift)


def pixel_to_brightness(value: int, bpp: int) -> int:
    """Map a packed pixel value onto Pillow's 0-255 grayscale range."""
    maximum = (1 << bpp) - 1
    return value * 255 // maximum


def brightness_to_pixel(brightness: int, bpp: int) -> int:
    """Quantize grayscale brightness to the nearest packed pixel value."""
    maximum = (1 << bpp) - 1
    return (brightness * maximum + 127) // 255


def decode_glyph(
    font_data: bytes | bytearray,
    spec: FontSpec,
    glyph_index: int,
) -> Image.Image:
    """Decode one glyph at its native resolution."""
    glyph = Image.new("L", (spec.width, spec.height))
    pixels = glyph.load()
    glyph_offset = glyph_index * spec.glyph_stride

    for y in range(spec.height):
        row_offset = glyph_offset + y * spec.row_stride
        row = font_data[row_offset : row_offset + spec.row_stride]

        for x in range(spec.width):
            value = get_pixel(row, x, spec.bpp)
            pixels[x, y] = pixel_to_brightness(value, spec.bpp)

    return glyph


def render_sheet(
    font_data: bytes | bytearray,
    spec: FontSpec,
    options: RenderOptions,
) -> Image.Image:
    """Render every glyph into a scaled reference sheet."""
    count = glyph_count(font_data, spec)
    rows = (count + options.columns - 1) // options.columns
    sheet = Image.new(
        "L",
        (options.columns * spec.width, rows * spec.height),
    )

    for glyph_index in range(count):
        glyph = decode_glyph(font_data, spec, glyph_index)
        sheet_x = (glyph_index % options.columns) * spec.width
        sheet_y = (glyph_index // options.columns) * spec.height
        sheet.paste(glyph, (sheet_x, sheet_y))

    if options.scale != 1:
        sheet = sheet.resize(
            (sheet.width * options.scale, sheet.height * options.scale),
            Image.Resampling.NEAREST,
        )

    index_font = ImageFont.load_default()
    measurement = ImageDraw.Draw(Image.new("L", (1, 1)))
    column_labels = [str(column) for column in range(options.columns)]
    row_labels = [str(row * options.columns) for row in range(rows)]
    labels = column_labels + row_labels
    bounds = {
        label: measurement.textbbox((0, 0), label, font=index_font) for label in labels
    }
    label_height = max(bottom - top for left, top, right, bottom in bounds.values())
    row_label_width = max(bounds[label][2] - bounds[label][0] for label in row_labels)
    left_margin = row_label_width + 8
    top_margin = label_height + 8
    indexed_sheet = Image.new(
        "L",
        (left_margin + sheet.width, top_margin + sheet.height),
    )
    indexed_sheet.paste(sheet, (left_margin, top_margin))

    draw = ImageDraw.Draw(indexed_sheet)
    cell_width = spec.width * options.scale
    cell_height = spec.height * options.scale

    for column, label in enumerate(column_labels):
        left, top, right, bottom = bounds[label]
        width = right - left
        height = bottom - top
        center_x = left_margin + column * cell_width + cell_width / 2
        center_y = top_margin / 2
        draw.text(
            (center_x - width / 2 - left, center_y - height / 2 - top),
            label,
            font=index_font,
            fill=255,
        )

    for row, label in enumerate(row_labels):
        left, top, right, bottom = bounds[label]
        width = right - left
        height = bottom - top
        center_y = top_margin + row * cell_height + cell_height / 2
        draw.text(
            (left_margin - width - 4 - left, center_y - height / 2 - top),
            label,
            font=index_font,
            fill=255,
        )

    draw.line((left_margin - 2, 0, left_margin - 2, indexed_sheet.height), fill=64)
    draw.line((0, top_margin - 2, indexed_sheet.width, top_margin - 2), fill=64)
    return indexed_sheet


def encode_glyph(
    font_data: bytearray,
    spec: FontSpec,
    glyph_index: int,
    glyph: Image.Image,
) -> None:
    """Quantize and encode one glyph over an existing font record."""
    if glyph.size != (spec.width, spec.height):
        raise ValueError(
            f"glyph {glyph_index} for {spec.path} is {glyph.width}x{glyph.height}; "
            f"expected {spec.width}x{spec.height}"
        )

    grayscale = glyph.convert("L")
    pixels = grayscale.load()
    glyph_offset = glyph_index * spec.glyph_stride

    for y in range(spec.height):
        row_offset = glyph_offset + y * spec.row_stride
        row = bytearray(font_data[row_offset : row_offset + spec.row_stride])

        for x in range(spec.width):
            value = brightness_to_pixel(pixels[x, y], spec.bpp)
            set_pixel(row, x, spec.bpp, value)

        font_data[row_offset : row_offset + spec.row_stride] = row
