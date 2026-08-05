"""FFmpeg discovery, probing, and path handling for Saturn Cinepak files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from project_paths import EXTRACTED_ROOT, FMV_ROOT

CATALOG_PATH = FMV_ROOT / "catalog.json"
DECODED_ROOT = FMV_ROOT / "decoded"
GENERATED_ROOT = FMV_ROOT / "generated"
SUBTITLE_ROOT = FMV_ROOT / "subtitles"
EDIT_MANIFEST_PATH = GENERATED_ROOT / "movies.json"
REPACK_MANIFEST_PATH = GENERATED_ROOT / "repacked.json"
CATALOG_VERSION = 3
EDIT_MANIFEST_VERSION = 1
REPACK_MANIFEST_VERSION = 2


def executable(name: str, override: str | None) -> str:
    value = override or shutil.which(name)
    if not value and os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        candidate = (
            Path(os.environ["LOCALAPPDATA"])
            / "Microsoft"
            / "WinGet"
            / "Links"
            / f"{name}.exe"
        )
        if candidate.is_file():
            value = str(candidate)
    if not value:
        raise ValueError(f"{name} was not found; install FFmpeg or pass --{name}")
    return value


def run(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command))
    subprocess.run(command, check=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path, ffprobe: str) -> dict:
    command = [
        ffprobe,
        "-v",
        "error",
        "-count_packets",
        "-show_entries",
        "format=duration,size,format_name:"
        "stream=index,codec_name,codec_type,width,height,r_frame_rate,"
        "avg_frame_rate,time_base,sample_rate,channels,nb_read_packets",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((row for row in streams if row.get("codec_type") == "video"), None)
    audio = next((row for row in streams if row.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError(f"{path}: no video stream")
    try:
        relative = path.resolve().relative_to(EXTRACTED_ROOT.resolve()).as_posix()
    except ValueError:
        relative = str(path.resolve())
    frame_count = int(video.get("nb_read_packets") or 0)
    frame_rate = Fraction(video.get("r_frame_rate") or "0/1")
    duration = float(data.get("format", {}).get("duration", 0.0))
    if frame_count and frame_rate > 0:
        # FFprobe reports the FILM header's raw 1/600 value as seconds for some
        # Saturn CPKs. Packet count / frame rate reflects their real playback.
        duration = round(float(frame_count / frame_rate), 6)
    is_title_animation = relative.casefold() == "taitlfix.cpk"
    return {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": file_sha256(path),
        "duration": duration,
        "frame_count": frame_count,
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": video.get("r_frame_rate"),
        "time_base": video.get("time_base"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "sample_rate": int(audio["sample_rate"])
        if audio and audio.get("sample_rate")
        else None,
        "channels": audio.get("channels") if audio else None,
        "likely_fmv": bool(audio) or is_title_animation,
    }


def cpk_files(include_combat: bool) -> list[Path]:
    paths = list(EXTRACTED_ROOT.glob("*.CPK"))
    paths += list((EXTRACTED_ROOT / "BGDATA").glob("*.CPK"))
    if include_combat:
        paths += list((EXTRACTED_ROOT / "COMBDATA").glob("*.CPK"))
    return sorted(paths, key=lambda path: path.relative_to(EXTRACTED_ROOT).as_posix())


def source_path(value: str) -> tuple[Path, Path]:
    relative = safe_relative_path(value, ".cpk")
    source = EXTRACTED_ROOT / relative
    if not source.is_file():
        raise ValueError(f"source CPK does not exist: {source}")
    return relative, source


def safe_relative_path(value: str, suffix: str | None = None) -> Path:
    relative = Path(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or (suffix is not None and relative.suffix.casefold() != suffix.casefold())
    ):
        expected = f" {suffix}" if suffix else ""
        raise ValueError(f"unsafe or invalid disc-relative{expected} path: {value!r}")
    return relative


def editable_path(relative: Path, root: Path = DECODED_ROOT) -> Path:
    return (root / relative).with_suffix(".mkv")


def subtitle_path(relative: Path, root: Path = SUBTITLE_ROOT) -> Path | None:
    candidates = [
        candidate
        for suffix in (".ass", ".srt")
        if (candidate := (root / relative).with_suffix(suffix)).is_file()
    ]
    if len(candidates) > 1:
        raise ValueError(
            f"{relative.as_posix()}: multiple subtitle scripts are present: "
            + ", ".join(str(path) for path in candidates)
        )
    return candidates[0].resolve() if candidates else None


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != CATALOG_VERSION:
        raise ValueError(f"{path}: unsupported FMV catalog")
    files = document.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"{path}: malformed FMV catalog")
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            raise ValueError(f"{path}: FMV catalog row must be an object")
        required = {
            "path",
            "size",
            "sha256",
            "duration",
            "frame_count",
            "width",
            "height",
            "frame_rate",
            "time_base",
            "video_codec",
            "audio_codec",
            "sample_rate",
            "channels",
            "likely_fmv",
        }
        if set(row) != required:
            raise ValueError(f"{path}: malformed FMV catalog row")
        relative = safe_relative_path(str(row["path"]), ".cpk").as_posix()
        key = relative.casefold()
        if key in seen:
            raise ValueError(f"{path}: duplicate FMV catalog path {relative}")
        seen.add(key)
    return document


def catalog_rows(
    document: dict[str, object], names: tuple[str, ...] = ()
) -> list[dict[str, object]]:
    rows = document["files"]
    if not isinstance(rows, list):
        raise ValueError("malformed FMV catalog")
    if not names:
        return list(rows)
    wanted = {safe_relative_path(name, ".cpk").as_posix().casefold() for name in names}
    selected = [
        row
        for row in rows
        if isinstance(row, dict) and str(row["path"]).casefold() in wanted
    ]
    found = {str(row["path"]).casefold() for row in selected}
    missing = sorted(wanted - found)
    if missing:
        raise ValueError(f"CPK paths are absent from the FMV catalog: {missing}")
    return selected


def source_matches_catalog(row: dict[str, object]) -> tuple[Path, Path]:
    relative, source = source_path(str(row["path"]))
    if source.stat().st_size != row["size"] or file_sha256(source) != row["sha256"]:
        raise ValueError(
            f"{relative.as_posix()}: extracted source changed since catalog"
        )
    return relative, source


def manifest_text(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2) + "\n"


def load_edit_manifest(path: Path = EDIT_MANIFEST_PATH) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or set(document) != {"version", "format", "catalog_sha256", "movies"}
        or document.get("version") != EDIT_MANIFEST_VERSION
        or document.get("format") != "ffv1_pcm_mkv"
        or not isinstance(document.get("catalog_sha256"), str)
        or len(document["catalog_sha256"]) != 64
        or not isinstance(document.get("movies"), list)
    ):
        raise ValueError(f"{path}: unsupported FMV edit manifest")
    seen: set[str] = set()
    for row in document["movies"]:
        if not isinstance(row, dict) or set(row) != {
            "source",
            "source_size",
            "source_sha256",
            "editable",
            "editable_size",
            "editable_sha256",
        }:
            raise ValueError(f"{path}: malformed FMV edit manifest row")
        source = safe_relative_path(str(row["source"]), ".cpk").as_posix()
        editable = safe_relative_path(str(row["editable"]), ".mkv").as_posix()
        if (
            Path(source).with_suffix(".mkv").as_posix().casefold()
            != editable.casefold()
        ):
            raise ValueError(f"{path}: editable path does not mirror {source}")
        key = source.casefold()
        if key in seen:
            raise ValueError(f"{path}: duplicate FMV edit source {source}")
        seen.add(key)
    return document


def load_repack_manifest(path: Path = REPACK_MANIFEST_PATH) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    version = document.get("version") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) != {"version", "movies"}
        or version not in {1, REPACK_MANIFEST_VERSION}
        or not isinstance(document.get("movies"), list)
    ):
        raise ValueError(f"{path}: unsupported FMV repack manifest")
    legacy_keys = {
        "source",
        "editable_sha256",
        "transform_sha256",
        "output_size",
        "output_sha256",
    }
    current_keys = legacy_keys | {
        "source_sha256",
        "font_set_sha256",
        "recipe_sha256",
        "input_sha256",
    }
    expected_rows = (legacy_keys,) if version == 1 else (legacy_keys, current_keys)
    seen: set[str] = set()
    for row in document["movies"]:
        if not isinstance(row, dict) or set(row) not in expected_rows:
            raise ValueError(f"{path}: malformed FMV repack manifest row")
        source = safe_relative_path(str(row["source"]), ".cpk").as_posix()
        key = source.casefold()
        if key in seen:
            raise ValueError(f"{path}: duplicate FMV repack source {source}")
        seen.add(key)
    return document


def edit_manifest_row(
    source: Path, source_file: Path, editable: Path, decoded_root: Path = DECODED_ROOT
) -> dict[str, object]:
    return {
        "source": source.as_posix(),
        "source_size": source_file.stat().st_size,
        "source_sha256": file_sha256(source_file),
        "editable": editable.relative_to(decoded_root).as_posix(),
        "editable_size": editable.stat().st_size,
        "editable_sha256": file_sha256(editable),
    }


def subtitle_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    for old, new in (
        ("\\", "\\\\"),
        (":", "\\:"),
        ("'", "\\'"),
        (",", "\\,"),
        ("[", "\\["),
        ("]", "\\]"),
        (";", "\\;"),
    ):
        value = value.replace(old, new)
    return value
