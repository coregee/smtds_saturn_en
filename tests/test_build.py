import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from disc.script.manifest import manifest_files
from project_paths import PROJECT_ROOT as REPO_ROOT

SPEC = importlib.util.spec_from_file_location("parent_build", REPO_ROOT / "build.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load the parent build module")
parent_build = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parent_build
SPEC.loader.exec_module(parent_build)


class ParentBuildTests(unittest.TestCase):
    def test_build_modes_preserve_dependency_order(self) -> None:
        fonts = parent_build.registered_fonts()
        test_stages = parent_build.build_stages(fonts)
        release_stages = parent_build.build_stages(fonts, release=True)

        self.assertEqual(
            [stage.name for stage in test_stages],
            [
                "Registered translation fields",
                "Font",
                "Text",
                "Visual catalog",
                "Visual images",
                "FMV movies",
                "Engine",
            ],
        )
        self.assertEqual(test_stages[0].arguments, ("--check", "--allow-empty"))
        self.assertEqual(test_stages[1].arguments, fonts)
        self.assertEqual(test_stages[2].arguments, ())
        self.assertEqual(release_stages[0].arguments, ("--check",))
        self.assertEqual(release_stages[2].arguments, ("--fail-on-fallbacks",))
        self.assertNotIn("Binary catalogue", [stage.name for stage in release_stages])

        disc = parent_build.disc_stage()
        self.assertEqual(disc.name, "Disc")
        self.assertEqual(disc.arguments, ())
        self.assertEqual(
            parent_build.disc_stage(release=True).arguments[0], "--manifest"
        )
        self.assertEqual(
            [stage.name for stage in parent_build.artifact_stages()],
            ["Disc"],
        )
        self.assertEqual(
            [stage.name for stage in parent_build.artifact_stages(release=True)],
            ["Disc", "Xdelta patch"],
        )
        self.assertEqual(
            parent_build.xdelta_stage(r"C:\tools\xdelta3.exe").arguments,
            ("--xdelta", r"C:\tools\xdelta3.exe"),
        )

    def test_check_commands_are_supported_by_every_writing_stage(self) -> None:
        stages = (
            *parent_build.build_stages(parent_build.registered_fonts()),
            *parent_build.artifact_stages(),
            *parent_build.build_stages(parent_build.registered_fonts(), release=True),
            *parent_build.artifact_stages(release=True),
        )
        for stage in stages:
            command = stage.command(True)
            self.assertEqual(command[0], "-m")
            if stage.name != "Visual catalog":
                self.assertIn("--check", command)

    def test_plan_reports_direct_playable_test_disc(self) -> None:
        fonts = parent_build.registered_fonts()
        output = io.StringIO()
        with redirect_stdout(output):
            parent_build.print_plan(fonts, check=True)
        plan = output.getvalue()
        self.assertIn("Playable test disc (verify)", plan)
        self.assertIn("Text selection: all", plan)
        self.assertIn("-m text.script.audit_translations --check --allow-empty", plan)
        self.assertIn("-m text.script.repack --check", plan)
        self.assertIn("-m engine.script.build --check", plan)
        self.assertIn("-m disc.script.build --check", plan)
        self.assertNotIn("--manifest", plan)
        self.assertNotIn("disc.script.xdelta", plan)

    def test_release_plan_is_strict_and_manifest_backed(self) -> None:
        fonts = parent_build.registered_fonts()
        output = io.StringIO()
        with redirect_stdout(output):
            parent_build.print_plan(fonts, check=True, release=True)
        plan = output.getvalue()
        self.assertIn("Complete release (verify)", plan)
        self.assertIn("-m text.script.audit_translations --check", plan)
        self.assertNotIn("audit_translations --check --allow-empty", plan)
        self.assertIn("-m text.script.repack --fail-on-fallbacks --check", plan)
        self.assertIn("-m disc.script.build --manifest", plan)
        self.assertIn("-m disc.script.xdelta --check", plan)

        selected = io.StringIO()
        with redirect_stdout(selected):
            parent_build.print_plan(
                fonts,
                True,
                release=True,
                xdelta_executable=r"C:\tools\xdelta3.exe",
            )
        self.assertIn(
            r"-m disc.script.xdelta --xdelta C:\tools\xdelta3.exe --check",
            selected.getvalue(),
        )

    def test_extensionless_launcher_runs_default_plan(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "build"), "--plan"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Playable test disc (write)", result.stdout)
        self.assertNotIn("disc.script.xdelta", result.stdout)

    def test_xdelta_override_requires_release_mode(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(REPO_ROOT / "build"),
                "--plan",
                "--xdelta",
                "xdelta3",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--xdelta requires --release", result.stderr)

    def test_test_build_removes_only_stale_release_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = root / parent_build.PATCH_FILENAME
            sidecar = Path(f"{patch}.json")
            cue = root / "game.cue"
            patch.write_bytes(b"patch")
            sidecar.write_text("{}", encoding="utf-8")
            cue.write_text("cue", encoding="utf-8")
            original = parent_build.DISC_BUILD_ROOT
            try:
                parent_build.DISC_BUILD_ROOT = root
                removed = parent_build.remove_stale_release_artifacts()
            finally:
                parent_build.DISC_BUILD_ROOT = original

            self.assertEqual(removed, (patch, sidecar))
            self.assertFalse(patch.exists())
            self.assertFalse(sidecar.exists())
            self.assertTrue(cue.exists())

    def test_refreshed_outputs_exclude_unchanged_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unchanged = root / "LOCAL.BIN"
            changed = root / "EVENT.BIN"
            artifact = root / "disc" / "release.xdelta"
            unchanged.write_bytes(b"local")
            changed.write_bytes(b"old")
            artifact.parent.mkdir()
            artifact.write_bytes(b"artifact")
            original = parent_build.BUILD_ROOT
            original_disc = parent_build.DISC_BUILD_ROOT
            try:
                parent_build.BUILD_ROOT = root
                parent_build.DISC_BUILD_ROOT = root / "disc"
                before = parent_build.output_snapshot()
                changed.write_bytes(b"new output")
                self.assertEqual(parent_build.refreshed_outputs(before), (changed,))
            finally:
                parent_build.BUILD_ROOT = original
                parent_build.DISC_BUILD_ROOT = original_disc

    def test_release_manifest_round_trips_and_rejects_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "EVENT.BIN"
            manifest = root / "release.json"
            output.write_bytes(b"built")
            document = {
                "version": 1,
                "files": [
                    {
                        "path": "EVENT.BIN",
                        "size": 5,
                        "sha256": parent_build.sha256(output),
                    }
                ],
            }
            manifest.write_text(json.dumps(document), encoding="utf-8")

            self.assertTrue(manifest_files(root, manifest)[0].samefile(output))
            output.write_bytes(b"stale")
            with self.assertRaisesRegex(ValueError, "digest changed"):
                manifest_files(root, manifest)


if __name__ == "__main__":
    unittest.main()
