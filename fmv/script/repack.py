"""Materialize changed FMVs and reuse validated cached replacements."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fmv.script.util.film import (
    CinepakContract,
    cinepak_contract,
    normalize_for_saturn,
    validate_saturn_compatibility,
)
from fmv.script.util.media import (
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
from project_paths import BUILD_ROOT, FONT_ROOT

SUBTITLE_FONT_ROOT = FONT_ROOT / "source" / "ark-pixel-font"
SUBTITLE_FONT_PATH = SUBTITLE_FONT_ROOT / "ark-pixel-16px-proportional-latin.otf"
# Bump whenever fixed encoder or Saturn-normalization behavior changes output bytes.
REPACK_RECIPE_VERSION = 1
REPACK_STATE_FIELDS = (
    "source_sha256",
    "editable_sha256",
    "transform_sha256",
    "font_set_sha256",
    "recipe_sha256",
    "input_sha256",
)


@dataclass(frozen=True)
class RepackPlan:
    relative: Path
    source: Path
    editable: Path
    subtitles: Path | None
    output: Path
    max_bytes: int
    input_state: dict[str, object]
    cached: bool


def document_sha256(document: object) -> str:
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def qscale_candidates(qscale: int, auto_fit: bool) -> tuple[int, ...]:
    values = [qscale]
    if auto_fit:
        values += [value for value in (8, 10, 12, 16, 20, 24, 28, 31) if value > qscale]
    return tuple(values)


def subtitle_font_set_sha256(subtitles: Path | None) -> str | None:
    if subtitles is None:
        return None
    if not SUBTITLE_FONT_PATH.is_file():
        raise ValueError(f"subtitle font is missing: {SUBTITLE_FONT_PATH}")
    fonts = sorted(
        (
            path
            for path in SUBTITLE_FONT_ROOT.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".otf", ".ttf", ".ttc"}
        ),
        key=lambda path: path.relative_to(SUBTITLE_FONT_ROOT).as_posix().casefold(),
    )
    if not fonts:
        raise ValueError(f"subtitle font directory is empty: {SUBTITLE_FONT_ROOT}")
    return document_sha256(
        [
            {
                "path": path.relative_to(SUBTITLE_FONT_ROOT).as_posix(),
                "sha256": file_sha256(path),
            }
            for path in fonts
        ]
    )


def repack_input_state(
    *,
    relative: Path,
    source: Path,
    source_sha256: str,
    editable: Path,
    editable_sha256: str,
    subtitles: Path | None,
    max_bytes: int,
    qscale: int,
    auto_fit: bool,
    codebook_iterations: int,
) -> dict[str, object]:
    if max_bytes <= 0 or max_bytes > source.stat().st_size:
        raise ValueError("max bytes must be positive and no larger than the source CPK")
    transform_sha256 = file_sha256(subtitles) if subtitles is not None else None
    font_set_sha256 = subtitle_font_set_sha256(subtitles)
    recipe_sha256 = document_sha256(
        {
            "version": REPACK_RECIPE_VERSION,
            "qscales": qscale_candidates(qscale, auto_fit),
            "codebook_iterations": codebook_iterations,
            "max_bytes": max_bytes,
            "video_codec": "cinepak",
            "pixel_format": "rgb24",
            "audio_codec": "pcm_s16be_planar",
            "container": "film_cpk",
            "saturn_normalization": True,
        }
    )
    inputs = {
        "source": relative.as_posix(),
        "source_size": source.stat().st_size,
        "source_sha256": source_sha256,
        "editable_size": editable.stat().st_size,
        "editable_sha256": editable_sha256,
        "transform_kind": subtitles.suffix.casefold()
        if subtitles is not None
        else None,
        "transform_sha256": transform_sha256,
        "font_set_sha256": font_set_sha256,
        "recipe_sha256": recipe_sha256,
    }
    return {
        "source_sha256": source_sha256,
        "editable_sha256": editable_sha256,
        "transform_sha256": transform_sha256,
        "font_set_sha256": font_set_sha256,
        "recipe_sha256": recipe_sha256,
        "input_sha256": document_sha256(inputs),
    }


def cache_matches(
    record: dict[str, object] | None,
    state: dict[str, object],
    output: Path,
) -> bool:
    if record is None or not output.is_file():
        return False
    if any(record.get(field) != state[field] for field in REPACK_STATE_FIELDS):
        return False
    return record.get("output_size") == output.stat().st_size and record.get(
        "output_sha256"
    ) == file_sha256(output)


def repack_record(
    relative: Path,
    state: dict[str, object],
    output: Path,
) -> dict[str, object]:
    return {
        "source": relative.as_posix(),
        **state,
        "output_size": output.stat().st_size,
        "output_sha256": file_sha256(output),
    }


def write_repack_manifest(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(manifest_text(document))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    input_state: dict[str, object],
    subtitles: Path | None = None,
) -> dict[str, object]:
    original = probe(source, ffprobe)
    edited = probe(input_path, ffprobe)
    contract = cinepak_contract(source)
    validate_editable(original, edited, relative)
    if max_bytes <= 0 or max_bytes > source.stat().st_size:
        raise ValueError("max bytes must be positive and no larger than the source CPK")
    qscales = qscale_candidates(qscale, auto_fit)

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
    return repack_record(relative, input_state, output)


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

        active: list[RepackPlan] = []
        for key in sorted(wanted):
            row = rows[key]
            relative, source = source_path(str(row["source"]))
            source_digest = file_sha256(source)
            if (
                source.stat().st_size != row["source_size"]
                or source_digest != row["source_sha256"]
            ):
                raise ValueError(
                    f"{relative.as_posix()}: extracted source changed since extraction"
                )
            editable = editable_path(relative, args.decoded)
            if not editable.is_file():
                raise ValueError(f"editable FMV is missing: {editable}")
            digest = file_sha256(editable)
            subtitles = subtitle_override or subtitle_path(relative)
            is_active = digest != row["editable_sha256"] or subtitles is not None
            if not is_active:
                print(f"{'unchanged':9} {relative.as_posix()}")
                continue
            output = (args.output or BUILD_ROOT / relative).resolve()
            max_bytes = (
                source.stat().st_size if args.max_bytes is None else args.max_bytes
            )
            input_state = repack_input_state(
                relative=relative,
                source=source,
                source_sha256=source_digest,
                editable=editable,
                editable_sha256=digest,
                subtitles=subtitles,
                max_bytes=max_bytes,
                qscale=args.qscale,
                auto_fit=not args.no_auto_fit,
                codebook_iterations=args.codebook_iterations,
            )
            cached = cache_matches(prior_rows.get(key), input_state, output)
            print(f"{('cached' if cached else 'changed'):9} {relative.as_posix()}")
            active.append(
                RepackPlan(
                    relative=relative,
                    source=source,
                    editable=editable,
                    subtitles=subtitles,
                    output=output,
                    max_bytes=max_bytes,
                    input_state=input_state,
                    cached=cached,
                )
            )

        cached_count = sum(plan.cached for plan in active)
        print(
            f"FMV edit set: {len(active)}/{len(wanted)} active; "
            f"{cached_count} cached, {len(active) - cached_count} need repack"
        )
        if args.list:
            return

        if args.check:
            changed_keys = {plan.relative.as_posix().casefold() for plan in active}
            for plan in active:
                if not plan.cached:
                    raise ValueError(
                        f"{plan.output}: FMV replacement or repack state is stale"
                    )
                validate_saturn_compatibility(plan.source, plan.output)
            for key in wanted - changed_keys:
                relative = Path(str(rows[key]["source"]))
                output = (BUILD_ROOT / relative).resolve()
                if output.is_file():
                    raise ValueError(
                        f"{output}: stale FMV replacement has no changed editable"
                    )
            print("FMV replacements: verified successfully")
            return

        changed_keys = {plan.relative.as_posix().casefold() for plan in active}
        for key in wanted - changed_keys:
            relative = Path(str(rows[key]["source"]))
            output = (BUILD_ROOT / relative).resolve()
            if output.is_file():
                output.unlink()
                print(f"removed unchanged FMV output: {output}")
            prior_rows.pop(key, None)
        pending = []
        for plan in active:
            if plan.output == plan.source.resolve():
                raise ValueError("output would overwrite the extracted source")
            key = plan.relative.as_posix().casefold()
            if not plan.cached:
                pending.append(plan)
                continue
            prior_rows[key] = repack_record(
                plan.relative, plan.input_state, plan.output
            )
            # Release manifests discover owned outputs by refreshed mtime.
            plan.output.touch()
            print(f"reused cached FMV replacement: {plan.output}")
        if pending:
            ffmpeg = executable("ffmpeg", args.ffmpeg)
            ffprobe = executable("ffprobe", args.ffprobe)
            for plan in pending:
                record = repack_movie(
                    relative=plan.relative,
                    source=plan.source,
                    input_path=plan.editable,
                    output=plan.output,
                    ffmpeg=ffmpeg,
                    ffprobe=ffprobe,
                    max_bytes=plan.max_bytes,
                    qscale=args.qscale,
                    auto_fit=not args.no_auto_fit,
                    codebook_iterations=args.codebook_iterations,
                    input_state=plan.input_state,
                    subtitles=plan.subtitles,
                )
                prior_rows[plan.relative.as_posix().casefold()] = record
                print(f"disc-ready replacement: {plan.output}")

        repack_document = {
            "version": REPACK_MANIFEST_VERSION,
            "movies": sorted(
                prior_rows.values(), key=lambda row: str(row["source"]).casefold()
            ),
        }
        write_repack_manifest(args.repack_manifest, repack_document)
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
