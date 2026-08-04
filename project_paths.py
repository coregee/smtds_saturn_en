"""Canonical repository paths shared by build packages and tests."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DISC_ROOT = PROJECT_ROOT / "disc"
ENGINE_ROOT = PROJECT_ROOT / "engine"
FMV_ROOT = PROJECT_ROOT / "fmv"
FONT_ROOT = PROJECT_ROOT / "font"
TEXT_ROOT = PROJECT_ROOT / "text"
VISUAL_ROOT = PROJECT_ROOT / "visual"

ROM_ROOT = PROJECT_ROOT / "rom"
ORIGINAL_ROOT = ROM_ROOT / "original"
EXTRACTED_ROOT = ROM_ROOT / "extracted"
BUILD_ROOT = ROM_ROOT / "build"
DISC_BUILD_ROOT = BUILD_ROOT / "disc"

FONT_GENERATED_ROOT = FONT_ROOT / "generated"
TEXT_CORPUS_ROOT = TEXT_ROOT / "corpus"
TEXT_GENERATED_ROOT = TEXT_ROOT / "generated"
TEXT_LAYOUT_ROOT = TEXT_ROOT / "layout"
