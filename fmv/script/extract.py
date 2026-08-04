"""Decode every catalogued FMV into a hash-bound lossless editing set."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from fmv.script.util.media import (
    CATALOG_PATH,
    DECODED_ROOT,
    EDIT_MANIFEST_PATH,
    EDIT_MANIFEST_VERSION,
    GENERATED_ROOT,
    catalog_rows,
    edit_manifest_row,
    editable_path,
    executable,
    file_sha256,
    load_catalog,
    load_edit_manifest,
    manifest_text,
    run,
    source_matches_catalog,
)


def decode_command(ffmpeg: str, source: Path, output: Path) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-v",
        "warning",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-c:v",
        "ffv1",
        "-level",
        "3",
        "-g",
        "1",
        "-slicecrc",
        "1",
        "-map",
        "0:a:0?",
        "-c:a",
        "pcm_s16be",
        str(output),
    ]


def previous_rows(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    document = load_edit_manifest(path)
    return {
        str(row["source"]).casefold(): row
        for row in document["movies"]
        if isinstance(row, dict)
    }


def write_edit_manifest(
    path: Path,
    catalog: Path,
    rows: dict[str, dict[str, object]],
) -> None:
    document = {
        "version": EDIT_MANIFEST_VERSION,
        "format": "ffv1_pcm_mkv",
        "catalog_sha256": file_sha256(catalog),
        "movies": sorted(rows.values(), key=lambda row: str(row["source"]).casefold()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        manifest_text(document),
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="disc-relative CPK paths")
    parser.add_argument("--manifest", type=Path, default=CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=DECODED_ROOT)
    parser.add_argument("--edit-manifest", type=Path, default=EDIT_MANIFEST_PATH)
    parser.add_argument(
        "--lossless",
        action="store_true",
        help="accepted for compatibility; editable extraction is always lossless",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace editable files and reset their baseline hashes",
    )
    parser.add_argument(
        "--adopt-existing",
        action="store_true",
        help="trust unregistered editable files as clean baseline extractions",
    )
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--ffmpeg")
    args = parser.parse_args()
    try:
        catalog = load_catalog(args.manifest)
        rows = catalog_rows(catalog, tuple(args.paths))
        if not rows:
            raise ValueError("no CPK files selected")
        old_rows = previous_rows(args.edit_manifest)
        new_rows = dict(old_rows)
        ffmpeg = executable("ffmpeg", args.ffmpeg) if not args.check else ""
        created = 0
        preserved = 0
        changed = 0
        for index, row in enumerate(rows, 1):
            relative, source = source_matches_catalog(row)
            output = editable_path(relative, args.output)
            key = relative.as_posix().casefold()
            old = old_rows.get(key)
            print(f"[{index}/{len(rows)}] {relative.as_posix()}")
            if output.is_file() and old is not None and not args.overwrite:
                if (
                    old["source_size"] != row["size"]
                    or old["source_sha256"] != row["sha256"]
                ):
                    raise ValueError(
                        f"{relative.as_posix()}: source catalog and edit manifest differ"
                    )
                preserved += 1
                if file_sha256(output) != old["editable_sha256"]:
                    changed += 1
                continue
            if args.check:
                if not output.is_file() or old is None:
                    raise ValueError(
                        f"{relative.as_posix()}: lossless editable or baseline hash is missing"
                    )
                continue
            if output.is_file() and old is None and not args.overwrite:
                if args.adopt_existing:
                    new_rows[key] = edit_manifest_row(
                        relative, source, output, args.output
                    )
                    write_edit_manifest(args.edit_manifest, args.manifest, new_rows)
                    preserved += 1
                    continue
                raise ValueError(
                    f"{output}: exists without a baseline hash; pass --overwrite "
                    "to decode it again or --adopt-existing after verifying it"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            staged = output.with_name(f".{output.stem}.tmp{output.suffix}")
            try:
                run(decode_command(ffmpeg, source, staged))
                staged.replace(output)
            finally:
                staged.unlink(missing_ok=True)
            new_rows[key] = edit_manifest_row(relative, source, output, args.output)
            write_edit_manifest(args.edit_manifest, args.manifest, new_rows)
            created += 1

        if args.check:
            if not args.edit_manifest.is_file():
                raise ValueError(f"FMV edit manifest is missing: {args.edit_manifest}")
            current = load_edit_manifest(args.edit_manifest)
            if current["catalog_sha256"] != file_sha256(args.manifest):
                raise ValueError(
                    f"{args.edit_manifest}: source catalog fingerprint is stale"
                )
            selected = {str(row["path"]).casefold() for row in rows}
            manifest_sources = {
                str(row["source"]).casefold()
                for row in current["movies"]
                if isinstance(row, dict)
            }
            missing = sorted(selected - manifest_sources)
            if missing:
                raise ValueError(f"FMV edit manifest is missing sources: {missing}")
            print(
                f"FMV edit set: verified {len(rows)} files; "
                f"{changed} differ from baseline"
            )
            return
        GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
        write_edit_manifest(args.edit_manifest, args.manifest, new_rows)
        print(
            f"FMV edit set: {created} extracted / {preserved} preserved / "
            f"{changed} modified"
        )
        print(f"editable movies: {args.output}")
        print(f"hash manifest:   {args.edit_manifest}")
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
