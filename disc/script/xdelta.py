"""Create or verify the xdelta release patch for the built data track."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from disc.script.source import (
    SourceDiscContract,
    contract_sha256,
    load_source_contract,
    sha256,
    validate_source_disc,
)
from disc.script.util.cue import CueSheet
from project_paths import DISC_BUILD_ROOT

DEFAULT_DISC_ROOT = DISC_BUILD_ROOT
PATCH_FILENAME = "devil-summoner-rev-b-english.xdelta"
XDELTA_VERSION = "3.2.0"
APPLICATION_HEADER = "smtds-devil-summoner-rev-b-track1"
ENCODER_OPTIONS = (
    "-9",
    "-S",
    "none",
    "-D",
    "-a",
    f"-A={APPLICATION_HEADER}",
)
CommandRunner = Callable[[tuple[str, ...]], None]
XDELTA_VERSION_PATTERN = re.compile(
    r"^xdelta(?:3)?\s+version\s+([0-9]+\.[0-9]+\.[0-9]+)(?:,|\s|$)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class PatchPlan:
    contract: SourceDiscContract
    track_number: int
    track_mode: str
    source: Path
    target: Path
    target_relative: str
    patch: Path
    metadata: Path


def _validate_artifact_destination(path: Path) -> None:
    absolute = path.absolute()
    symlink = next(
        (
            candidate
            for candidate in (absolute, *absolute.parents)
            if candidate.is_symlink()
        ),
        None,
    )
    if symlink is not None:
        raise ValueError(
            f"xdelta artifact path cannot contain a symbolic link: {symlink}"
        )
    if absolute.exists() and not absolute.is_file():
        raise ValueError(
            "xdelta artifact destination must be a regular file if it exists: "
            f"{absolute}"
        )


def _validate_artifact_destinations(patch: Path, metadata: Path) -> None:
    _validate_artifact_destination(patch)
    _validate_artifact_destination(metadata)


def resolve_xdelta(executable: str) -> str:
    """Resolve and version-check xdelta3 without invoking a shell."""
    resolved = shutil.which(executable)
    if resolved is None:
        raise ValueError(
            f"xdelta3 executable not found: {executable!r}; install xdelta3 or "
            "pass its path with --xdelta"
        )
    result = subprocess.run(
        (resolved, "-V"),
        check=False,
        capture_output=True,
        text=True,
        env=xdelta_environment(),
    )
    version_output = (result.stdout or result.stderr).strip()
    match = XDELTA_VERSION_PATTERN.search(version_output)
    version = match.group(1) if match is not None else None
    if result.returncode or version != XDELTA_VERSION:
        detail = version_output or f"exit status {result.returncode}"
        raise ValueError(
            f"xdelta3 {XDELTA_VERSION} is required for reproducible patches; "
            f"found {detail}"
        )
    return resolved


def xdelta_environment() -> dict[str, str]:
    """Remove ambient command arguments accepted through XDELTA."""
    environment = os.environ.copy()
    environment.pop("XDELTA", None)
    return environment


def run_xdelta(command: tuple[str, ...]) -> None:
    """Run xdelta3 and turn its diagnostics into one actionable error."""
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=xdelta_environment(),
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"xdelta3 exited with status {result.returncode}{suffix}")


def _validate_companion_disc(sheet: CueSheet, disc_root: Path) -> None:
    built_cue = disc_root / sheet.path.name
    if not built_cue.is_file() or built_cue.read_bytes() != sheet.path.read_bytes():
        raise ValueError("built CUE is missing or differs from the verified source CUE")

    data_relative = sheet.mode1_track().file.relative_path
    for file in sheet.files:
        if file.relative_path == data_relative:
            continue
        source = sheet.source_path(file)
        built = disc_root / file.relative_path
        if not built.is_file() or not filecmp.cmp(source, built, shallow=False):
            raise ValueError(
                f"built companion track is missing or changed: {file.name}"
            )


def plan_patch(
    sheet: CueSheet,
    contract: SourceDiscContract,
    disc_root: Path,
    patch: Path | None = None,
) -> PatchPlan:
    """Resolve the verified source and built MODE1/2352 tracks."""
    validate_source_disc(sheet, contract)
    _validate_companion_disc(sheet, disc_root)
    data_track = sheet.mode1_track()
    source = sheet.source_path(data_track.file).resolve()
    target = (disc_root / data_track.file.relative_path).resolve()
    if not target.is_file():
        raise ValueError(f"built data track is missing: {target}")
    if target.stat().st_size != source.stat().st_size:
        raise ValueError(
            f"built data track is {target.stat().st_size:,} bytes, expected "
            f"{source.stat().st_size:,}"
        )
    if source.samefile(target):
        raise ValueError(
            "built data track resolves to the original source track; --disc must "
            "name a separate build directory"
        )

    patch_path = (patch or (disc_root / PATCH_FILENAME)).absolute()
    metadata_path = patch_path.with_suffix(f"{patch_path.suffix}.json")
    _validate_artifact_destinations(patch_path, metadata_path)
    resolved_patch = patch_path.resolve()
    resolved_metadata = metadata_path.resolve()
    source_root = sheet.path.parent.resolve()
    if resolved_patch.is_relative_to(source_root) or resolved_metadata.is_relative_to(
        source_root
    ):
        raise ValueError("xdelta artifacts cannot be written into the source-disc tree")

    protected_paths = {
        sheet.path.resolve(),
        (disc_root / sheet.path.name).resolve(),
        *(sheet.source_path(file).resolve() for file in sheet.files),
        *((disc_root / file.relative_path).resolve() for file in sheet.files),
    }
    if resolved_patch in protected_paths or resolved_metadata in protected_paths:
        raise ValueError("xdelta artifacts would overwrite a source or built disc file")
    if patch_path.suffix.lower() != ".xdelta":
        raise ValueError("xdelta output must use the .xdelta extension")
    return PatchPlan(
        contract=contract,
        track_number=data_track.number,
        track_mode=data_track.mode,
        source=source,
        target=target,
        target_relative=data_track.file.relative_path.as_posix(),
        patch=patch_path,
        metadata=metadata_path,
    )


def encode_command(plan: PatchPlan, executable: str, output: Path) -> tuple[str, ...]:
    return (
        executable,
        *ENCODER_OPTIONS,
        "-q",
        "-f",
        "-e",
        "-s",
        plan.source.as_posix(),
        plan.target.as_posix(),
        output.as_posix(),
    )


def decode_command(
    plan: PatchPlan,
    executable: str,
    patch: Path,
    output: Path,
) -> tuple[str, ...]:
    return (
        executable,
        "-q",
        "-f",
        "-d",
        "-s",
        plan.source.as_posix(),
        patch.as_posix(),
        output.as_posix(),
    )


def verify_decoding(
    plan: PatchPlan,
    executable: str,
    patch: Path,
    *,
    runner: CommandRunner = run_xdelta,
) -> None:
    """Decode a patch and compare the reconstructed track byte-for-byte."""
    if not patch.is_file():
        raise ValueError(f"xdelta patch is missing: {patch}")
    with tempfile.TemporaryDirectory(
        prefix="smtds-xdelta-check-", dir=patch.parent
    ) as directory:
        decoded = Path(directory) / "decoded-track.bin"
        runner(decode_command(plan, executable, patch, decoded))
        if not decoded.is_file():
            raise ValueError("xdelta3 did not create the decoded data track")
        if not filecmp.cmp(decoded, plan.target, shallow=False):
            raise ValueError("xdelta patch does not reconstruct the built data track")


def patch_document(
    plan: PatchPlan,
    *,
    patch_path: Path | None = None,
) -> dict[str, object]:
    """Describe the exact source, target, patch, and encoder contract."""
    artifact = patch_path or plan.patch
    return {
        "version": 1,
        "format": "VCDIFF/xdelta3",
        "encoder": {
            "program": "xdelta3",
            "version": XDELTA_VERSION,
            "options": list(ENCODER_OPTIONS),
        },
        "source": {
            "revision": plan.contract.name,
            "revision_sha256": contract_sha256(plan.contract),
            "track": plan.track_number,
            "mode": plan.track_mode,
            "size": plan.source.stat().st_size,
            "sha256": sha256(plan.source),
        },
        "target": {
            "file": plan.target_relative,
            "size": plan.target.stat().st_size,
            "sha256": sha256(plan.target),
        },
        "unchanged_tracks": [
            {
                "track": track.number,
                "mode": track.mode,
                "size": track.size,
                "sha256": track.sha256,
            }
            for track in plan.contract.tracks
            if track.number != plan.track_number
        ],
        "patch": {
            "file": plan.patch.name,
            "size": artifact.stat().st_size,
            "sha256": sha256(artifact),
        },
    }


def _write_document(path: Path, document: dict[str, object]) -> None:
    value = json.dumps(document, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as output:
        temporary = Path(output.name)
        output.write(value)
    try:
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _replace(source: Path, destination: Path) -> None:
    """Replace one same-volume path; isolated for failure-path tests."""
    source.replace(destination)


def _publish_pair(
    plan: PatchPlan,
    candidate_patch: Path,
    candidate_metadata: Path,
) -> None:
    """Publish a patch and sidecar together, restoring any prior pair on failure."""
    _validate_artifact_destinations(plan.patch, plan.metadata)
    backup_root = Path(
        tempfile.mkdtemp(prefix="smtds-xdelta-rollback-", dir=plan.patch.parent)
    )
    backup_patch = backup_root / "previous-patch"
    backup_metadata = backup_root / "previous-metadata"
    old_patch_moved = False
    old_metadata_moved = False
    new_patch_published = False
    new_metadata_published = False
    try:
        if plan.patch.exists():
            _replace(plan.patch, backup_patch)
            old_patch_moved = True
        if plan.metadata.exists():
            _replace(plan.metadata, backup_metadata)
            old_metadata_moved = True
        _replace(candidate_patch, plan.patch)
        new_patch_published = True
        _replace(candidate_metadata, plan.metadata)
        new_metadata_published = True
    except OSError as error:
        rollback_errors = []
        for published, path in (
            (new_metadata_published, plan.metadata),
            (new_patch_published, plan.patch),
        ):
            if published:
                try:
                    path.unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
        for moved, backup, destination in (
            (old_patch_moved, backup_patch, plan.patch),
            (old_metadata_moved, backup_metadata, plan.metadata),
        ):
            if moved:
                try:
                    _replace(backup, destination)
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
        if rollback_errors:
            preserved = [
                str(path) for path in (backup_patch, backup_metadata) if path.exists()
            ]
            detail = ", ".join(preserved) or str(backup_root)
            raise OSError(
                "xdelta artifact publication failed and the prior pair could not "
                f"be fully restored; inspect recovery state at {detail}"
            ) from error
        backup_root.rmdir()
        raise
    else:
        try:
            backup_patch.unlink(missing_ok=True)
            backup_metadata.unlink(missing_ok=True)
            backup_root.rmdir()
        except OSError as error:
            raise OSError(
                "xdelta artifacts were published, but prior-artifact backup cleanup "
                f"failed; inspect {backup_root}"
            ) from error


def create_patch(
    plan: PatchPlan,
    executable: str,
    *,
    runner: CommandRunner = run_xdelta,
) -> dict[str, object]:
    """Encode and decode-check a patch before replacing existing artifacts."""
    _validate_artifact_destinations(plan.patch, plan.metadata)
    plan.patch.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="smtds-xdelta-build-", dir=plan.patch.parent
    ) as directory:
        candidate = Path(directory) / plan.patch.name
        candidate_metadata = Path(directory) / plan.metadata.name
        runner(encode_command(plan, executable, candidate))
        if not candidate.is_file() or not candidate.stat().st_size:
            raise ValueError("xdelta3 did not create a non-empty patch")
        verify_decoding(plan, executable, candidate, runner=runner)
        document = patch_document(plan, patch_path=candidate)
        _write_document(candidate_metadata, document)
        _publish_pair(plan, candidate, candidate_metadata)
    return document


def check_patch(
    plan: PatchPlan,
    executable: str,
    *,
    runner: CommandRunner = run_xdelta,
) -> dict[str, object]:
    """Verify metadata and prove that the existing patch reconstructs Track 1."""
    if not plan.metadata.is_file():
        raise ValueError(f"xdelta metadata is missing: {plan.metadata}")
    document = json.loads(plan.metadata.read_text(encoding="utf-8"))
    expected = patch_document(plan)
    if document != expected:
        raise ValueError(f"xdelta metadata is stale: {plan.metadata}")
    verify_decoding(plan, executable, plan.patch, runner=runner)
    return expected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cue", type=Path, help="source CUE (default: disc/config.json)"
    )
    parser.add_argument(
        "--disc",
        type=Path,
        default=DEFAULT_DISC_ROOT,
        help="directory containing the built BIN/CUE disc",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=f"patch path (default: <disc>/{PATCH_FILENAME})",
    )
    parser.add_argument(
        "--xdelta",
        default="xdelta3",
        help="xdelta3 executable name or path",
    )
    parser.add_argument(
        "--list", action="store_true", help="show the patch plan without writing"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="decode and verify an existing patch without rewriting it",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list and args.check:
        raise SystemExit("--list and --check cannot be combined")
    try:
        contract = load_source_contract()
        cue = (args.cue or contract.cue).resolve()
        if not cue.is_file():
            raise ValueError(f"source CUE does not exist: {cue}")
        sheet = CueSheet.read(cue)
        disc_root = args.disc.resolve()
        output = args.output
        plan = plan_patch(sheet, contract, disc_root, output)
        print(f"source track {plan.track_number}: {plan.source}")
        print(f"built track: {plan.target}")
        print(f"xdelta patch: {plan.patch}")
        print(f"metadata: {plan.metadata}")
        if args.list:
            return

        executable = resolve_xdelta(args.xdelta)
        if args.check:
            document = check_patch(plan, executable)
            action = "verified"
        else:
            document = create_patch(plan, executable)
            action = "created and decode-verified"
        patch = document["patch"]
        assert isinstance(patch, dict)
        print(
            f"xdelta patch {action}: {patch['size']:,} bytes, SHA-256 {patch['sha256']}"
        )
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as error:
        raise SystemExit(error) from error


if __name__ == "__main__":
    main()
