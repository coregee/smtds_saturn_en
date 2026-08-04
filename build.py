"""Build or verify the playable test disc or complete English release."""

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from disc.script.xdelta import PATCH_FILENAME
from project_paths import BUILD_ROOT, DISC_BUILD_ROOT, FONT_ROOT, PROJECT_ROOT, ROM_ROOT

FONT_CONFIG_ROOT = FONT_ROOT / "config"
REPLACEMENT_MANIFEST_PATH = ROM_ROOT / "release_manifest.json"


@dataclass(frozen=True)
class BuildStage:
    name: str
    module: str
    arguments: tuple[str, ...] = ()
    check_supported: bool = True
    expected_outputs: tuple[str, ...] = ()

    def command(self, check: bool) -> list[str]:
        command = ["-m", self.module, *self.arguments]
        if check and self.check_supported:
            command.append("--check")
        return command


def registered_fonts() -> tuple[str, ...]:
    fonts = []
    for path in sorted(FONT_CONFIG_ROOT.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("file")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{path}: file must be nonempty text")
        fonts.append(name)
    if len({name.casefold() for name in fonts}) != len(fonts):
        raise ValueError(f"{FONT_CONFIG_ROOT}: duplicate font targets")
    return tuple(fonts)


def build_stages(
    fonts: tuple[str, ...], *, release: bool = False
) -> tuple[BuildStage, ...]:
    audit_arguments = ("--check",) if release else ("--check", "--allow-empty")
    text_arguments = ("--fail-on-fallbacks",) if release else ()
    return (
        BuildStage(
            "Registered translation fields",
            "text.script.audit_translations",
            audit_arguments,
            check_supported=False,
        ),
        BuildStage(
            "Font",
            "font.script.repack",
            fonts,
            expected_outputs=("rom/build/*.FON", "font/generated/*.json"),
        ),
        BuildStage(
            "Text",
            "text.script.repack",
            text_arguments,
            expected_outputs=("rom/build text files", "text/generated contracts"),
        ),
        BuildStage("Visual catalog", "visual.script.validate", check_supported=False),
        BuildStage(
            "Visual images",
            "visual.script.repack",
            ("--if-extracted",),
            expected_outputs=("rom/build visual replacements",),
        ),
        BuildStage(
            "FMV movies",
            "fmv.script.repack",
            ("--if-extracted",),
            expected_outputs=("rom/build CPK replacements",),
        ),
        BuildStage(
            "Engine",
            "engine.script.build",
            expected_outputs=("rom/build patched binaries",),
        ),
    )


def disc_stage(*, release: bool = False) -> BuildStage:
    arguments = ("--manifest", str(REPLACEMENT_MANIFEST_PATH)) if release else ()
    return BuildStage(
        "Disc",
        "disc.script.build",
        arguments,
        expected_outputs=("rom/build/disc/*.cue", "rom/build/disc/*.bin"),
    )


def xdelta_stage(executable: str | None = None) -> BuildStage:
    arguments = ("--xdelta", executable) if executable is not None else ()
    return BuildStage(
        "Xdelta patch",
        "disc.script.xdelta",
        arguments,
        expected_outputs=(
            "rom/build/disc/*.xdelta",
            "rom/build/disc/*.xdelta.json",
        ),
    )


def artifact_stages(
    *, release: bool = False, xdelta_executable: str | None = None
) -> tuple[BuildStage, ...]:
    """Return final test-disc or release artifact stages."""
    stages: tuple[BuildStage, ...] = (disc_stage(release=release),)
    if release:
        stages += (xdelta_stage(xdelta_executable),)
    return stages


def run_stage(stage: BuildStage, check: bool) -> None:
    print(f"\n== {stage.name} ==", flush=True)
    result = subprocess.run(
        [sys.executable, "-B", *stage.command(check)],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)


def release_files() -> tuple[Path, ...]:
    if not BUILD_ROOT.is_dir():
        return ()
    disc_root = DISC_BUILD_ROOT.resolve()
    return tuple(
        sorted(
            (
                path
                for path in BUILD_ROOT.rglob("*")
                if path.is_file() and not path.resolve().is_relative_to(disc_root)
            ),
            key=lambda path: path.relative_to(BUILD_ROOT).as_posix().upper(),
        )
    )


def output_snapshot() -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(BUILD_ROOT).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in release_files()
    }


def refreshed_outputs(before: dict[str, tuple[int, int]]) -> tuple[Path, ...]:
    outputs = []
    for path in release_files():
        relative = path.relative_to(BUILD_ROOT).as_posix()
        state = (path.stat().st_size, path.stat().st_mtime_ns)
        if before.get(relative) != state:
            outputs.append(path)
    if not outputs:
        raise ValueError("release stages did not refresh any files under rom/build")
    return tuple(outputs)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_replacement_manifest(outputs: tuple[Path, ...]) -> None:
    rows = [
        {
            "path": path.relative_to(BUILD_ROOT).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in outputs
    ]
    document = {"version": 1, "files": rows}
    REPLACEMENT_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPLACEMENT_MANIFEST_PATH.write_text(
        json.dumps(document, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"\nReplacement manifest: {len(rows)} files -> {REPLACEMENT_MANIFEST_PATH}",
        flush=True,
    )


def remove_stale_release_artifacts() -> tuple[Path, ...]:
    """Remove release patches invalidated by a newly written test disc."""
    patch = DISC_BUILD_ROOT / PATCH_FILENAME
    removed = []
    for path in (patch, Path(f"{patch}.json")):
        if not path.exists():
            continue
        if not path.is_file():
            raise ValueError(f"release artifact path is not a file: {path}")
        path.unlink()
        removed.append(path)
        print(f"Removed stale release artifact: {path}", flush=True)
    return tuple(removed)


def print_plan(
    fonts: tuple[str, ...],
    check: bool,
    *,
    release: bool = False,
    xdelta_executable: str | None = None,
) -> None:
    mode = "verify" if check else "write"
    heading = "Complete release" if release else "Playable test disc"
    print(f"{heading} ({mode})")
    print(f"Fonts: {', '.join(fonts)}")
    if release:
        print(
            "Text selection: all; empty, structurally invalid, or "
            "Japanese-fallback translations fail"
        )
    else:
        print(
            "Text selection: all; blank fields and Japanese capacity fallbacks are "
            "permitted, while structural errors fail"
        )
    stages = (
        *build_stages(fonts, release=release),
        *artifact_stages(
            release=release,
            xdelta_executable=xdelta_executable,
        ),
    )
    for index, stage in enumerate(stages, 1):
        command = " ".join((sys.executable, "-B", *stage.command(check)))
        outputs = ", ".join(stage.expected_outputs) or "validation only"
        print(f"{index}. {stage.name}: {command}")
        print(f"   outputs: {outputs}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify existing outputs without writing"
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="show exact stages and expected outputs without writing",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="enforce completion gates and create the manifest-bound xdelta release",
    )
    parser.add_argument(
        "--xdelta",
        help="xdelta3 executable name or path (requires --release)",
    )
    arguments = parser.parse_args()

    if arguments.xdelta and not arguments.release:
        parser.error("--xdelta requires --release")

    try:
        fonts = registered_fonts()
        if arguments.plan:
            print_plan(
                fonts,
                arguments.check,
                release=arguments.release,
                xdelta_executable=arguments.xdelta,
            )
            return

        action = "Checking" if arguments.check else "Building"
        target = "complete release" if arguments.release else "playable test disc"
        print(f"{action} {target}")
        if arguments.check:
            for stage in build_stages(fonts, release=arguments.release):
                run_stage(stage, True)
        else:
            before = output_snapshot() if arguments.release else None
            for stage in build_stages(fonts, release=arguments.release):
                run_stage(stage, False)
            if before is not None:
                write_replacement_manifest(refreshed_outputs(before))
        for stage in artifact_stages(
            release=arguments.release,
            xdelta_executable=arguments.xdelta,
        ):
            run_stage(stage, arguments.check)
        if not arguments.check and not arguments.release:
            remove_stale_release_artifacts()
        result = "verified" if arguments.check else "built"
        print(f"\n{target.capitalize()} {result} successfully.")
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
