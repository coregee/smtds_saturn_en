"""Neutral helpers for validating repository-relative paths."""

from pathlib import Path, PurePosixPath, PureWindowsPath


def safe_relative_path(
    value: object,
    context: str,
    *,
    allow_backslashes: bool = False,
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be non-empty text")
    if "\\" in value:
        if not allow_backslashes:
            raise ValueError(f"{context} must use forward slashes")
        value = value.replace("\\", "/")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or not posix.parts
    ):
        raise ValueError(f"{context} must be a safe relative path")
    return Path(*posix.parts)
