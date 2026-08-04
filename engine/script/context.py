"""Paths and invocation-scoped inputs for one engine build."""

from dataclasses import dataclass
from pathlib import Path

from project_paths import (
    BUILD_ROOT,
    EXTRACTED_ROOT,
    FONT_GENERATED_ROOT,
    TEXT_GENERATED_ROOT,
)


@dataclass(frozen=True)
class EngineBuildContext:
    """Filesystem roots available to engine patch factories."""

    extracted_root: Path
    font_generated_root: Path
    text_generated_root: Path
    build_root: Path


DEFAULT_CONTEXT = EngineBuildContext(
    extracted_root=EXTRACTED_ROOT,
    font_generated_root=FONT_GENERATED_ROOT,
    text_generated_root=TEXT_GENERATED_ROOT,
    build_root=BUILD_ROOT,
)
