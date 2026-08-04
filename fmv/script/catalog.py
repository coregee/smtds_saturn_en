"""Probe and hash the root and BGDATA Sega FILM/Cinepak inventory."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from fmv.script.util.media import (
    CATALOG_PATH,
    CATALOG_VERSION,
    cpk_files,
    executable,
    probe,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all", action="store_true", help="include COMBDATA animations"
    )
    parser.add_argument("--output", type=Path, default=CATALOG_PATH)
    parser.add_argument("--ffprobe")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        ffprobe = executable("ffprobe", args.ffprobe)
        paths = cpk_files(args.all)
        rows = []
        for index, path in enumerate(paths, 1):
            print(f"[{index}/{len(paths)}] {path.name}", file=sys.stderr)
            rows.append(probe(path, ffprobe))
        document = {
            "version": CATALOG_VERSION,
            "selection": "all CPK files" if args.all else "root and BGDATA CPK files",
            "fmv_rule": (
                "the editable FMV working set includes every root and BGDATA "
                "Cinepak; likely_fmv marks audio-bearing clips plus TAITLFIX.CPK"
            ),
            "files": rows,
        }
        text = json.dumps(document, indent=2) + "\n"
        if args.check:
            if (
                not args.output.exists()
                or args.output.read_text(encoding="utf-8") != text
            ):
                raise ValueError(f"stale FMV catalog: {args.output}")
            action = "verified"
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8", newline="\n")
            action = "wrote"
        likely = sum(row["likely_fmv"] for row in rows)
        print(
            f"{action} {len(rows)} CPK entries ({likely} likely FMVs) -> {args.output}"
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
