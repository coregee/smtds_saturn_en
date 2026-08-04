"""Minimal CUE sheet parser for locating disc track files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from safe_paths import safe_relative_path

FILE_PATTERN = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+(\S+)\s*$', re.IGNORECASE)
TRACK_PATTERN = re.compile(r"^\s*TRACK\s+(\d+)\s+(\S+)\s*$", re.IGNORECASE)
INDEX_PATTERN = re.compile(
    r"^\s*INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)\s*$",
    re.IGNORECASE,
)


def cue_path(value: str) -> Path:
    """Convert a CUE path to a safe path relative to the sheet."""
    try:
        return safe_relative_path(
            value,
            "CUE file path",
            allow_backslashes=True,
        )
    except ValueError as error:
        raise ValueError(f"CUE contains an unsafe file path: {value!r}") from error


@dataclass(frozen=True)
class CueFile:
    name: str
    kind: str

    @property
    def relative_path(self) -> Path:
        return cue_path(self.name)


@dataclass(frozen=True)
class CueTrack:
    number: int
    mode: str
    file: CueFile
    indexes: dict[int, int]

    @property
    def index_one(self) -> int:
        try:
            return self.indexes[1]
        except KeyError as error:
            raise ValueError(f"CUE track {self.number:02d} has no INDEX 01") from error


@dataclass(frozen=True)
class CueSheet:
    path: Path
    files: tuple[CueFile, ...]
    tracks: tuple[CueTrack, ...]

    @classmethod
    def read(cls, path: Path) -> "CueSheet":
        current_file: CueFile | None = None
        track_rows: list[tuple[int, str, CueFile, dict[int, int]]] = []
        files: list[CueFile] = []

        for line_number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(), 1
        ):
            if match := FILE_PATTERN.match(line):
                current_file = CueFile(
                    match.group(1) or match.group(2), match.group(3).upper()
                )
                files.append(current_file)
            elif match := TRACK_PATTERN.match(line):
                if current_file is None:
                    raise ValueError(
                        f"{path.name}:{line_number}: TRACK appears before FILE"
                    )
                track_rows.append(
                    (int(match.group(1)), match.group(2).upper(), current_file, {})
                )
            elif match := INDEX_PATTERN.match(line):
                if not track_rows:
                    raise ValueError(
                        f"{path.name}:{line_number}: INDEX appears before TRACK"
                    )
                index = int(match.group(1))
                minutes, seconds, frames = map(int, match.groups()[1:])
                if seconds >= 60 or frames >= 75:
                    raise ValueError(
                        f"{path.name}:{line_number}: invalid INDEX timestamp"
                    )
                track_rows[-1][3][index] = (minutes * 60 + seconds) * 75 + frames

        if not files or not track_rows:
            raise ValueError(f"{path.name}: no FILE/TRACK records found")
        tracks = tuple(
            CueTrack(number, mode, file, indexes)
            for number, mode, file, indexes in track_rows
        )
        return cls(path.resolve(), tuple(files), tracks)

    def mode1_track(self) -> CueTrack:
        matches = [track for track in self.tracks if track.mode == "MODE1/2352"]
        if len(matches) != 1:
            raise ValueError(
                f"{self.path.name}: expected one MODE1/2352 track, found {len(matches)}"
            )
        return matches[0]

    def source_path(self, file: CueFile) -> Path:
        return self.path.parent / file.relative_path
