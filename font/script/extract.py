import argparse

from font.script.util.font_codec import (
    ATLAS_PATH,
    DEFAULT_RENDER_OPTIONS,
    EXTRACTED_PATH,
    IMAGE_PATH,
    RENDER_OPTIONS,
    FontSpec,
    RenderOptions,
    decode_glyph,
    glyph_count,
    render_sheet,
    select_fonts,
)


def extract_font(
    spec: FontSpec,
    options: RenderOptions,
    overwrite: bool,
) -> None:
    """Extract native glyphs and create a scaled reference sheet."""
    font_data = (EXTRACTED_PATH / spec.path).read_bytes()
    count = glyph_count(font_data, spec)
    glyph_directory = IMAGE_PATH / spec.name
    existing_glyph = next(glyph_directory.glob("glyph_*.png"), None)
    if existing_glyph is not None and not overwrite:
        raise FileExistsError(
            f"{glyph_directory} already contains glyphs; use --overwrite to replace them"
        )

    if overwrite:
        for glyph_file in glyph_directory.glob("glyph_*.png"):
            glyph_file.unlink()

    glyph_directory.mkdir(parents=True, exist_ok=True)
    ATLAS_PATH.mkdir(parents=True, exist_ok=True)

    for glyph_index in range(count):
        glyph = decode_glyph(font_data, spec, glyph_index)
        glyph.save(glyph_directory / f"glyph_{glyph_index:04d}.png")

    atlas_file = ATLAS_PATH / f"{spec.name}_original.png"
    render_sheet(font_data, spec, options).save(atlas_file)
    print(f"{spec.path}: extracted {count} glyphs")
    print(f"  glyphs:   {glyph_directory}")
    print(f"  atlas:    {atlas_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract editable glyph PNGs and original font atlases."
    )
    parser.add_argument(
        "fonts",
        nargs="*",
        help="font filenames or stems; extracts every known font when omitted",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing editable glyph PNGs",
    )
    arguments = parser.parse_args()

    try:
        specs = select_fonts(arguments.fonts)
        for spec in specs:
            options = RENDER_OPTIONS.get(spec.path, DEFAULT_RENDER_OPTIONS)
            extract_font(spec, options, arguments.overwrite)
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
