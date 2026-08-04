# Ark Pixel Fonts

The English font and FMV pipelines use proportional Latin faces from Ark Pixel
Font:

- `ark-pixel-12px-proportional-latin.otf` supplies the English glyphs for both
  `FONT12.FON` and `FONT16.FON`. FONT12 requests an 11px raster from the
  scalable face; FONT16 retains the native 12px raster.
- `ark-pixel-16px-proportional-latin.otf` is reserved for deterministic libass
  rendering of the tracked `START2.ass` FMV subtitles.

FONT12 places the 11px raster at `offset_y = -1`. Capitals and ascenders then
occupy rows 2-9 of the 12-pixel cell, while lowercase descenders use rows
4-11. FreeType rounds the 11px lowercase body one row below the capitals and
ascenders, so FONT12 raises that rounded lowercase set by one pixel to preserve
a common baseline. FONT16 uses its independent native 12px placement.

Both files come from Ark Pixel Font version 2026.07.01:

- Upstream: https://github.com/TakWolf/ark-pixel-font
- 12px release asset:
  `ark-pixel-font-12px-proportional-otf-v2026.07.01.zip`
- 12px vendored OTF SHA-256:
  `ba0bbfc888f51ddde1b75944c26457bc26d666ab4fa1c73da726bbbec6497bf5`
- 16px release asset:
  `ark-pixel-font-16px-proportional-otf-v2026.07.01.zip`
- 16px vendored OTF SHA-256:
  `5ff8ed367e79aa2e1081a20c17f248a0c688baa566efbcda7ed00f62351f8491`
- License: SIL Open Font License 1.1
