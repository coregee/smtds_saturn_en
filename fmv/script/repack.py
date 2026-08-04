"""Repack only hash-catalogued FMVs whose lossless editable files changed."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from fmv.script.util.film import (
    CinepakContract,
    cinepak_contract,
    normalize_for_saturn,
    validate_saturn_compatibility,
)
from fmv.script.util.media import (
    BUILD_ROOT,
    DECODED_ROOT,
    EDIT_MANIFEST_PATH,
    REPACK_MANIFEST_PATH,
    REPACK_MANIFEST_VERSION,
    editable_path,
    executable,
    file_sha256,
    load_edit_manifest,
    load_repack_manifest,
    manifest_text,
    probe,
    run,
    safe_relative_path,
    source_path,
    subtitle_filter_path,
    subtitle_path,
)
from project_paths import FONT_ROOT

SUBTITLE_FONT_ROOT = FONT_ROOT / "source" / "ark-pixel-font"
SUBTITLE_FONT_PATH = SUBTITLE_FONT_ROOT / "ark-pixel-16px-proportional-latin.otf"


def validate_editable(original: dict, edited: dict, relative: Path) -> None:
    for field in ("width", "height", "frame_rate", "frame_count"):
        if edited[field] != original[field]:
            raise ValueError(
                f"{relative.as_posix()}: editable changed {field}: "
                f"{original[field]!r} -> {edited[field]!r}"
            )
    original_has_audio = original["audio_codec"] is not None
    edited_has_audio = edited["audio_codec"] is not None
    if original_has_audio != edited_has_audio:
        raise ValueError(
            f"{relative.as_posix()}: editable must preserve the original audio presence"
        )
    for field in ("sample_rate", "channels"):
        if edited[field] != original[field]:
            raise ValueError(
                f"{relative.as_posix()}: editable changed {field}: "
                f"{original[field]!r} -> {edited[field]!r}"
            )


def encode_command(
    ffmpeg: str,
    input_path: Path,
    output: Path,
    original: dict,
    qscale: int,
    codebook_iterations: int,
    subtitles: Path | None,
    contract: CinepakContract,
) -> list[str]:
    command = [
        ffmpeg,
        "-y",
        "-v",
        "warning",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
    ]
    if subtitles is not None:
        if not SUBTITLE_FONT_PATH.is_file():
            raise ValueError(f"subtitle font is missing: {SUBTITLE_FONT_PATH}")
        command += [
            "-vf",
            f"subtitles=filename='{subtitle_filter_path(subtitles)}':"
            f"fontsdir='{subtitle_filter_path(SUBTITLE_FONT_ROOT)}'",
        ]
    command += [
        "-c:v",
        "cinepak",
        "-pix_fmt",
        "rgb24",
        "-q:v",
        str(qscale),
        "-enc_time_base",
        str(original["time_base"]).replace("/", ":"),
        "-fps_mode",
        "passthrough",
        "-max_extra_cb_iterations",
        str(codebook_iterations),
        "-min_strips",
        str(contract.strip_count),
        "-max_strips",
        str(contract.strip_count),
        "-g",
        str(contract.keyframe_interval),
    ]
    if original["audio_codec"]:
        command += [
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s16be_planar",
            "-ar",
            str(original["sample_rate"]),
            "-ac",
            str(original["channels"]),
        ]
    command += ["-f", "film_cpk", str(output)]
    return command


def validate_rebuilt(original: dict, rebuilt: dict, relative: Path) -> None:
    for field in (
        "width",
        "height",
        "frame_rate",
        "frame_count",
        "time_base",
        "sample_rate",
        "channels",
    ):
        if rebuilt[field] != original[field]:
            raise ValueError(
                f"repacked {relative.as_posix()} changed {field}: "
                f"{original[field]!r} -> {rebuilt[field]!r}"
            )
    if rebuilt["video_codec"] != "cinepak":
        raise ValueError(f"repacked video codec is {rebuilt['video_codec']!r}")
    if bool(rebuilt["audio_codec"]) != bool(original["audio_codec"]):
        raise ValueError(f"repacked {relative.as_posix()} changed audio presence")


def repack_movie(
    *,
    relative: Path,
    source: Path,
    input_path: Path,
    output: Path,
    ffmpeg: str,
    ffprobe: str,
    max_bytes: int,
    qscale: int,
    auto_fit: bool,
    codebook_iterations: int,
    subtitles: Path | None = None,
) -> dict[str, object]:
    original = probe(source, ffprobe)
    edited = probe(input_path, ffprobe)
    contract = cinepak_contract(source)
    validate_editable(original, edited, relative)
    if max_bytes <= 0 or max_bytes > source.stat().st_size:
        raise ValueError("max bytes must be positive and no larger than the source CPK")
    qscales = [qscale]
    if auto_fit:
        qscales += [
            value for value in (8, 10, 12, 16, 20, 24, 28, 31) if value > qscale
        ]

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(f".{output.stem}.tmp{output.suffix}")
    size = 0
    try:
        for candidate in qscales:
            run(
                encode_command(
                    ffmpeg,
                    input_path,
                    staged,
                    original,
                    candidate,
                    codebook_iterations,
                    subtitles,
                    contract,
                )
            )
            normalize_for_saturn(source, staged)
            size = staged.stat().st_size
            print(f"qscale {candidate}: {size:,}/{max_bytes:,} bytes")
            if size <= max_bytes:
                break
        else:
            raise ValueError(
                f"repacked CPK is still {size:,} bytes at qscale {qscales[-1]}"
            )

        rebuilt = probe(staged, ffprobe)
        validate_rebuilt(original, rebuilt, relative)
        validate_saturn_compatibility(source, staged)
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    print(
        f"validated {relative.as_posix()}; "
        f"{max_bytes - size:,} bytes remain in its disc allocation"
    )
    return {
        "source": relative.as_posix(),
        "editable_sha256": file_sha256(input_path),
        "transform_sha256": (file_sha256(subtitles) if subtitles is not None else None),
        "output_size": size,
        "output_sha256": file_sha256(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="optional disc-relative CPK paths")
    parser.add_argument("--manifest", type=Path, default=EDIT_MANIFEST_PATH)
    parser.add_argument("--repack-manifest", type=Path, default=REPACK_MANIFEST_PATH)
    parser.add_argument("--decoded", type=Path, default=DECODED_ROOT)
    parser.add_argument("--output", type=Path, help="single-file output override")
    parser.add_argument(
        "--subtitles",
        type=Path,
        help="burn ASS/SRT subtitles into one selected movie",
    )
    parser.add_argument("--max-bytes", type=int, help="single-file size override")
    parser.add_argument("--qscale", type=int, default=6, choices=range(1, 32))
    parser.add_argument("--no-auto-fit", action="store_true")
    parser.add_argument("--codebook-iterations", type=int, default=2)
    parser.add_argument(
        "--list", action="store_true", help="list edits without writing"
    )
    parser.add_argument("--check", action="store_true", help="verify current outputs")
    parser.add_argument(
        "--if-extracted",
        action="store_true",
        help="do nothing when the local FMV edit manifest has not been generated",
    )
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    args = parser.parse_args()
    if args.list and args.check:
        parser.error("--list and --check cannot be combined")
    if args.output is not None and len(args.paths) != 1:
        parser.error("--output requires exactly one selected CPK")
    if args.max_bytes is not None and len(args.paths) != 1:
        parser.error("--max-bytes requires exactly one selected CPK")
    if args.subtitles is not None and len(args.paths) != 1:
        parser.error("--subtitles requires exactly one selected CPK")
    if not args.manifest.is_file() and args.if_extracted:
        print("FMV edit set: inactive (run fmv/script/extract.py to enable)")
        return
    try:
        document = load_edit_manifest(args.manifest)
        rows = {
            str(row["source"]).casefold(): row
            for row in document["movies"]
            if isinstance(row, dict)
        }
        if args.paths:
            wanted = {
                safe_relative_path(value, ".cpk").as_posix().casefold()
                for value in args.paths
            }
            missing = sorted(wanted - set(rows))
            if missing:
                raise ValueError(f"CPK paths are absent from edit manifest: {missing}")
        else:
            wanted = set(rows)

        prior_rows: dict[str, dict[str, object]] = {}
        if args.repack_manifest.is_file():
            prior = load_repack_manifest(args.repack_manifest)
            prior_rows = {
                str(row["source"]).casefold(): row
                for row in prior["movies"]
                if isinstance(row, dict)
            }

        subtitle_override = args.subtitles
        if subtitle_override is not None:
            subtitle_override = subtitle_override.resolve()
            if (
                not subtitle_override.is_file()
                or subtitle_override.suffix.casefold() not in {".ass", ".srt"}
            ):
                raise ValueError("subtitles must be an existing ASS or SRT file")

        changed: list[tuple[Path, Path, Path, Path | None, dict[str, object]]] = []
        for key in sorted(wanted):
            row = rows[key]
            relative, source = source_path(str(row["source"]))
            if (
                source.stat().st_size != row["source_size"]
                or file_sha256(source) != row["source_sha256"]
            ):
                raise ValueError(
                    f"{relative.as_posix()}: extracted source changed since extraction"
                )
            editable = editable_path(relative, args.decoded)
            if not editable.is_file():
                raise ValueError(f"editable FMV is missing: {editable}")
            digest = file_sha256(editable)
            subtitles = subtitle_override or subtitle_path(relative)
            is_changed = digest != row["editable_sha256"] or subtitles is not None
            state = "changed" if is_changed else "unchanged"
            print(f"{state:9} {relative.as_posix()}")
            if is_changed:
                changed.append((relative, source, editable, subtitles, row))

        print(f"FMV edit set: {len(changed)}/{len(wanted)} selected movies changed")
        if args.list:
            return

        if args.check:
            changed_keys = {
                relative.as_posix().casefold()
                for relative, _source, _editable, _subtitles, _row in changed
            }
            for relative, source, editable, subtitles, _row in changed:
                key = relative.as_posix().casefold()
                output = (args.output or BUILD_ROOT / relative).resolve()
                record = prior_rows.get(key)
                if record is None or not output.is_file():
                    raise ValueError(
                        f"{output}: FMV replacement or repack hash is missing"
                    )
                if (
                    record["editable_sha256"] != file_sha256(editable)
                    or record["transform_sha256"]
                    != (file_sha256(subtitles) if subtitles is not None else None)
                    or record["output_size"] != output.stat().st_size
                    or record["output_sha256"] != file_sha256(output)
                ):
                    raise ValueError(f"{output}: FMV replacement is stale")
                validate_saturn_compatibility(source, output)
            for key in wanted - changed_keys:
                relative = Path(str(rows[key]["source"]))
                output = (BUILD_ROOT / relative).resolve()
                if output.is_file():
                    raise ValueError(
                        f"{output}: stale FMV replacement has no changed editable"
                    )
            print("FMV replacements: verified successfully")
            return

        changed_keys = {
            relative.as_posix().casefold()
            for relative, _source, _editable, _subtitles, _row in changed
        }
        for key in wanted - changed_keys:
            relative = Path(str(rows[key]["source"]))
            output = (BUILD_ROOT / relative).resolve()
            if output.is_file():
                output.unlink()
                print(f"removed unchanged FMV output: {output}")
            prior_rows.pop(key, None)
        if changed:
            ffmpeg = executable("ffmpeg", args.ffmpeg)
            ffprobe = executable("ffprobe", args.ffprobe)
            for relative, source, editable, subtitles, _row in changed:
                output = (args.output or BUILD_ROOT / relative).resolve()
                if output == source.resolve():
                    raise ValueError("output would overwrite the extracted source")
                record = repack_movie(
                    relative=relative,
                    source=source,
                    input_path=editable,
                    output=output,
                    ffmpeg=ffmpeg,
                    ffprobe=ffprobe,
                    max_bytes=args.max_bytes or source.stat().st_size,
                    qscale=args.qscale,
                    auto_fit=not args.no_auto_fit,
                    codebook_iterations=args.codebook_iterations,
                    subtitles=subtitles,
                )
                prior_rows[relative.as_posix().casefold()] = record
                print(f"disc-ready replacement: {output}")

        repack_document = {
            "version": REPACK_MANIFEST_VERSION,
            "movies": sorted(
                prior_rows.values(), key=lambda row: str(row["source"]).casefold()
            ),
        }
        args.repack_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.repack_manifest.write_text(
            manifest_text(repack_document), encoding="utf-8", newline="\n"
        )
        print("FMV replacements: repacked successfully")
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
