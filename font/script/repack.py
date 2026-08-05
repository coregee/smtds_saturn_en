import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont

from font.script.util.font_codec import (
    ATLAS_PATH,
    BUILD_PATH,
    EXTRACTED_PATH,
    GENERATED_PATH,
    IMAGE_PATH,
    FontDefinition,
    TypefaceOptions,
    decode_glyph,
    encode_glyph,
    glyph_count,
    render_sheet,
    select_definitions,
)


@dataclass(frozen=True)
class Replacement:
    glyph_index: int
    character: str


@dataclass
class SourceCounts:
    font_file: int = 0
    extracted_image: int = 0
    original_file: int = 0
    font_file_failures: int = 0
    extracted_image_failures: int = 0


def collect_replacements(
    definition: FontDefinition,
) -> tuple[Replacement, ...]:
    """Expand atlas entries marked for source-font replacement."""
    replacements = []
    used_indices = set()

    for category, ranges in definition.replacement_ranges.items():
        for glyph_range in ranges:
            for offset, character in enumerate(glyph_range.characters):
                glyph_index = glyph_range.start + offset
                if glyph_index in used_indices:
                    raise ValueError(
                        f"glyph {glyph_index} is mapped by more than one category"
                    )
                used_indices.add(glyph_index)
                replacements.append(Replacement(glyph_index, character))

    if not replacements:
        raise ValueError("no replacement categories are enabled")

    return tuple(replacements)


def render_character(
    character: str,
    definition: FontDefinition,
    font: ImageFont.FreeTypeFont,
    options: TypefaceOptions,
) -> Image.Image:
    """Rasterize one source character into the target glyph cell."""
    spec = definition.spec
    glyph = Image.new("L", (spec.width, spec.height), 0)
    draw = ImageDraw.Draw(glyph)
    draw.fontmode = "L" if options.antialias else "1"
    if options.placement == "center":
        position = (
            spec.width / 2 + options.offset_x,
            spec.height / 2 + options.offset_y,
        )
    elif options.placement == "origin":
        position = (options.offset_x, options.offset_y)
    else:
        raise ValueError(f"unknown typeface placement: {options.placement}")

    for adjustment in options.glyph_offsets:
        if character in adjustment.characters:
            position = (
                position[0] + adjustment.offset_x,
                position[1] + adjustment.offset_y,
            )
            break

    characters = character if options.compose_from_glyphs else (character,)
    x, y = position
    for source_glyph in characters:
        draw.text(
            (x, y),
            source_glyph,
            font=font,
            fill=255,
            anchor=options.anchor,
            stroke_width=options.stroke_width,
            stroke_fill=255,
        )
        if options.compose_from_glyphs:
            x += round(font.getlength(source_glyph))
    return glyph


def source_advance(character: str, font: ImageFont.FreeTypeFont) -> int:
    """Return the sum of native per-glyph advances used by the compositor."""
    return sum(round(font.getlength(source_glyph)) for source_glyph in character)


def ink_advance(
    font_data: bytes | bytearray,
    definition: FontDefinition,
    glyph_index: int,
) -> int:
    """Measure the encoded cell, including one blank column after its ink."""
    glyph = decode_glyph(font_data, definition.spec, glyph_index)
    pixels = glyph.load()
    occupied = [
        x
        for y in range(definition.spec.height)
        for x in range(definition.spec.width)
        if pixels[x, y]
    ]
    if not occupied:
        return max(1, definition.spec.width // 2)
    return min(definition.spec.width, max(occupied) + 2)


def build_metrics_manifest(
    definition: FontDefinition,
    replacements: Mapping[int, Replacement],
    advances: Mapping[int, int],
) -> tuple[Path, str] | None:
    """Publish the glyph codes and advances consumed by text layout."""
    metrics = definition.font_file.metrics
    if metrics is None:
        return None

    glyphs = []
    missing = []
    for glyph_index, replacement in sorted(replacements.items()):
        if glyph_index >= metrics.code_limit:
            continue
        advance = advances.get(glyph_index)
        if advance is None:
            missing.append(glyph_index)
            continue

        row = {
            "text": replacement.character,
            "code": glyph_index,
            "advance": advance,
        }
        original = definition.original_glyphs.get(glyph_index)
        if original is not None and original != replacement.character:
            row["aliases"] = [original]
        glyphs.append(row)

    width_table = {"code_limit": metrics.code_limit}
    advance_table = definition.font_file.advance_table
    if advance_table is not None:
        width_table = {
            "storage_glyph": advance_table.storage_glyph,
            "code_limit": metrics.code_limit,
        }
    if metrics.measurement != "source":
        width_table["measurement"] = metrics.measurement

    manifest = {
        "version": 2,
        "font": definition.spec.path,
        "complete": not missing,
        "width_table": width_table,
        "glyphs": glyphs,
        "missing_codes": missing,
    }
    output_path = GENERATED_PATH / f"{definition.spec.name}_metrics.json"
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    return output_path, text


def try_encode(
    font_data: bytearray,
    definition: FontDefinition,
    glyph_index: int,
    glyph: Image.Image,
) -> bool:
    """Encode a candidate without retaining partial changes on failure."""
    spec = definition.spec
    record_start = glyph_index * spec.glyph_stride
    record_end = record_start + spec.glyph_stride
    previous_record = bytes(font_data[record_start:record_end])

    try:
        encode_glyph(font_data, spec, glyph_index, glyph)
    except (OSError, TypeError, ValueError):
        font_data[record_start:record_end] = previous_record
        return False

    return True


def prepare_font_file(
    definition: FontDefinition,
) -> tuple[
    dict[int, Replacement],
    ImageFont.FreeTypeFont | None,
    str | None,
    str | None,
]:
    """Prepare configured typeface replacements without aborting fallback."""
    options = definition.font_file
    if not options.use_font_file:
        return {}, None, None, None

    if options.source is None or options.typeface is None:
        return (
            {},
            None,
            None,
            f"{definition.spec.name} enables use_font_file without source settings",
        )

    try:
        replacements = collect_replacements(definition)
        font = ImageFont.truetype(
            str(options.source),
            options.typeface.size,
            index=options.typeface.face_index,
        )
    except (OSError, TypeError, ValueError) as error:
        return {}, None, None, str(error)

    replacement_by_index = {
        replacement.glyph_index: replacement for replacement in replacements
    }
    face = f"{font.getname()[0]} (index {options.typeface.face_index})"
    return replacement_by_index, font, face, None


def load_extracted_image(path: Path) -> Image.Image:
    """Load an editable glyph independently of its source file handle."""
    with Image.open(path) as glyph:
        glyph.load()
        return glyph.convert("L")


def repack_font(
    definition: FontDefinition,
    preview_only: bool,
    check: bool = False,
) -> None:
    """Resolve and repack each glyph in configured priority order."""
    spec = definition.spec
    source_file = EXTRACTED_PATH / spec.path
    original_data = source_file.read_bytes()
    font_data = bytearray(original_data)
    count = glyph_count(font_data, spec)
    glyph_directory = IMAGE_PATH / spec.name

    replacements, font, face, font_setup_error = prepare_font_file(definition)
    typeface = definition.font_file.typeface
    blank_glyphs = set(definition.font_file.blank_glyphs)
    counts = SourceCounts()
    rendered_glyphs = {}
    advances = {}
    advance_table_error = None

    with TemporaryDirectory(prefix=f"{spec.name}_glyphs_") as temp_name:
        temp_directory = Path(temp_name)

        for glyph_index in range(count):
            replacement = replacements.get(glyph_index)

            if glyph_index in blank_glyphs:
                glyph = Image.new("L", (spec.width, spec.height), 0)
                if not try_encode(font_data, definition, glyph_index, glyph):
                    raise ValueError(f"could not blank {spec.path} glyph {glyph_index}")
                counts.font_file += 1
                rendered_glyphs[glyph_index] = glyph
                continue

            if replacement is not None and font is not None and typeface is not None:
                try:
                    glyph = render_character(
                        replacement.character,
                        definition,
                        font,
                        typeface,
                    )
                    if try_encode(font_data, definition, glyph_index, glyph):
                        counts.font_file += 1
                        rendered_glyphs[glyph_index] = glyph
                        metrics = definition.font_file.metrics
                        if metrics is not None and metrics.measurement == "ink":
                            advances[glyph_index] = ink_advance(
                                font_data,
                                definition,
                                glyph_index,
                            )
                        else:
                            advances[glyph_index] = source_advance(
                                replacement.character,
                                font,
                            )
                        continue
                except (OSError, TypeError, ValueError):
                    pass
                counts.font_file_failures += 1

            if replacement is None and definition.font_file.preserve_unreplaced:
                counts.original_file += 1
                continue

            glyph_file = glyph_directory / f"glyph_{glyph_index:04d}.png"
            try:
                glyph = load_extracted_image(glyph_file)
                if try_encode(font_data, definition, glyph_index, glyph):
                    counts.extracted_image += 1
                    continue
            except (OSError, TypeError, ValueError):
                pass
            counts.extracted_image_failures += 1

            try:
                glyph = decode_glyph(original_data, spec, glyph_index)
                glyph.save(temp_directory / f"glyph_{glyph_index:04d}.png")
                if not try_encode(font_data, definition, glyph_index, glyph):
                    raise ValueError("decoded glyph could not be re-encoded")
            except (OSError, TypeError, ValueError) as error:
                raise ValueError(
                    f"all sources failed for {spec.path} glyph {glyph_index}: {error}"
                ) from error

            counts.original_file += 1

    metrics_replacements = replacements
    metrics_options = definition.font_file.metrics
    if metrics_options is not None and metrics_options.measurement == "ink":
        metrics_replacements = {
            replacement.glyph_index: replacement
            for replacement in collect_replacements(definition)
        }
        for glyph_index in metrics_replacements:
            if glyph_index < metrics_options.code_limit:
                advances[glyph_index] = ink_advance(
                    font_data,
                    definition,
                    glyph_index,
                )
    if metrics_options is not None and metrics_options.space_advance is not None:
        for glyph_index, replacement in metrics_replacements.items():
            if replacement.character == " ":
                advances[glyph_index] = metrics_options.space_advance

    advance_table = definition.font_file.advance_table
    if advance_table is not None:
        table = bytearray(advance_table.code_limit)
        missing_advances = []
        for glyph_index in replacements:
            if glyph_index >= advance_table.code_limit:
                continue
            if glyph_index not in advances:
                missing_advances.append(glyph_index)
                continue
            advance = advances[glyph_index]
            if not 0 <= advance <= 0xFF:
                raise ValueError(
                    f"advance {advance} for {spec.path} glyph {glyph_index} "
                    "does not fit in one byte"
                )
            table[glyph_index] = advance

        if missing_advances:
            advance_table_error = (
                f"not written; {len(missing_advances)} replacement glyphs "
                "fell back without source-font advances"
            )
        else:
            table_offset = advance_table.storage_glyph * spec.glyph_stride
            table_end = table_offset + len(table)
            if table_end > len(font_data):
                raise ValueError(f"advance table exceeds {spec.path}")
            font_data[table_offset:table_end] = table

    metrics = build_metrics_manifest(
        definition,
        metrics_replacements,
        advances,
    )
    output_file = BUILD_PATH / spec.path
    if check:
        stale = []
        if not output_file.exists() or output_file.read_bytes() != bytes(font_data):
            stale.append(output_file)
        if metrics is not None:
            metrics_file, metrics_text = metrics
            if (
                not metrics_file.exists()
                or metrics_file.read_text(encoding="utf-8") != metrics_text
            ):
                stale.append(metrics_file)
        if stale:
            paths = "\n  ".join(str(path) for path in stale)
            raise ValueError(f"stale font build files:\n  {paths}")
        print(f"{spec.path}: verified {count} glyphs -> {output_file}")
        if metrics is not None:
            print(f"  metrics:   {metrics[0]}")
        return

    ATLAS_PATH.mkdir(parents=True, exist_ok=True)
    atlas_file = ATLAS_PATH / f"{spec.name}_replaced.png"
    render_sheet(font_data, spec, definition.render).save(atlas_file)

    if not preview_only:
        for glyph_index, glyph in rendered_glyphs.items():
            glyph.save(glyph_directory / f"glyph_{glyph_index:04d}.png")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(font_data)
        print(f"  output:    {output_file}")
        if metrics is not None:
            metrics_file, metrics_text = metrics
            metrics_file.parent.mkdir(parents=True, exist_ok=True)
            metrics_file.write_text(
                metrics_text,
                encoding="utf-8",
                newline="\n",
            )
            print(f"  metrics:   {metrics_file}")

    print(f"{spec.path}: repacked {count} glyphs")
    print("  sources:")
    print(f"    font file:       {counts.font_file}")
    print(f"    extracted image: {counts.extracted_image}")
    print(f"    original file:   {counts.original_file}")
    if face is not None:
        print(f"  typeface:  {face}")
    if font_setup_error is not None:
        print(f"  font file fallback: {font_setup_error}")
    if advance_table_error is not None:
        print(f"  advance table: {advance_table_error}")
    if counts.font_file_failures or counts.extracted_image_failures:
        print("  failed attempts:")
        print(f"    font file:       {counts.font_file_failures}")
        print(f"    extracted image: {counts.extracted_image_failures}")
    print(f"  atlas:     {atlas_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repack editable glyphs with inline source-font replacements."
    )
    parser.add_argument(
        "fonts",
        nargs="*",
        help="font filenames or stems; repacks every configured font when omitted",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="write replaced atlas sheets without changing glyph PNGs or build fonts",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify build fonts and generated metrics without rewriting files",
    )
    arguments = parser.parse_args()

    try:
        if arguments.preview_only and arguments.check:
            raise ValueError("--preview-only and --check cannot be combined")
        for definition in select_definitions(arguments.fonts):
            repack_font(definition, arguments.preview_only, arguments.check)
    except (FileNotFoundError, KeyError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
