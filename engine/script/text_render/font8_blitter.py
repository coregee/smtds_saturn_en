"""Assemble the shared FONT8-to-4bpp pixel blitter."""

from pathlib import Path

from tools.sh2asm import assemble

FONT8_BASE = 0x00219150
SOURCE_PATH = Path(__file__).with_name("asm") / "font8_pixel_blitter.s"
SURFACE_SOURCE_PATH = Path(__file__).with_name("asm") / "font8_surface_blitter.s"


def build_pixel_blitter(address: int) -> bytes:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    blob = assemble(source, address, symbols={"FONT8": FONT8_BASE})
    if blob.warnings:
        raise ValueError(
            f"FONT8 pixel-blitter assembly warnings at {address:#x}: {blob.warnings}"
        )
    return bytes(blob)


def build_surface_pixel_blitter(address: int) -> bytes:
    """Build the exact-X FONT8 surface renderer without a palette-1 shadow."""
    source = SURFACE_SOURCE_PATH.read_text(encoding="utf-8")
    blob = assemble(source, address, symbols={"FONT8": FONT8_BASE})
    if blob.warnings:
        raise ValueError(
            f"FONT8 surface-blitter assembly warnings at {address:#x}: {blob.warnings}"
        )
    return bytes(blob)
