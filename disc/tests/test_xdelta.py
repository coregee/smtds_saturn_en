import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from disc.script import xdelta
from disc.script.source import load_source_contract
from disc.script.util.cue import CueSheet
from disc.script.xdelta import (
    ENCODER_OPTIONS,
    PATCH_FILENAME,
    check_patch,
    create_patch,
    plan_patch,
    resolve_xdelta,
)


class FakeXdelta:
    def __init__(self, target: bytes):
        self.target = target
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> None:
        self.commands.append(command)
        output = Path(command[-1])
        if "-e" in command:
            output.write_bytes(b"synthetic-vcdiff")
        elif "-d" in command:
            output.write_bytes(self.target)
        else:
            raise AssertionError(command)


class XdeltaTests(unittest.TestCase):
    def fixture(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        original = root / "original"
        built = root / "disc"
        original.mkdir()
        built.mkdir()
        source_data = b"source-data"
        target_data = b"target-data"
        audio = b"audio"
        cue_text = (
            'FILE "Track 1.bin" BINARY\n'
            "  TRACK 01 MODE1/2352\n"
            "    INDEX 01 00:00:00\n"
            'FILE "Track 2.bin" BINARY\n'
            "  TRACK 02 AUDIO\n"
            "    INDEX 00 00:00:00\n"
            "    INDEX 01 00:02:00\n"
        )
        cue = original / "game.cue"
        cue.write_text(cue_text, encoding="utf-8")
        (original / "Track 1.bin").write_bytes(source_data)
        (original / "Track 2.bin").write_bytes(audio)
        (built / "game.cue").write_text(cue_text, encoding="utf-8")
        (built / "Track 1.bin").write_bytes(target_data)
        (built / "Track 2.bin").write_bytes(audio)
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "source_cue": "game.cue",
                    "source_revision": {
                        "name": "Synthetic revision",
                        "tracks": [
                            {
                                "number": 1,
                                "mode": "MODE1/2352",
                                "file_type": "BINARY",
                                "indexes": {"1": 0},
                                "size": len(source_data),
                                "sha256": hashlib.sha256(source_data).hexdigest(),
                            },
                            {
                                "number": 2,
                                "mode": "AUDIO",
                                "file_type": "BINARY",
                                "indexes": {"0": 0, "1": 150},
                                "size": len(audio),
                                "sha256": hashlib.sha256(audio).hexdigest(),
                            },
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        contract = load_source_contract(config)
        return CueSheet.read(cue), contract, built, target_data

    def test_patch_round_trip_writes_verified_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, target = self.fixture(
                Path(directory) / "workspace with spaces"
            )
            plan = plan_patch(sheet, contract, built)
            fake = FakeXdelta(target)

            document = create_patch(plan, "xdelta3", runner=fake)
            patch_state = plan.patch.stat().st_mtime_ns
            metadata_state = plan.metadata.stat().st_mtime_ns
            checked = check_patch(plan, "xdelta3", runner=fake)

            self.assertEqual(document, checked)
            self.assertEqual(plan.patch.name, PATCH_FILENAME)
            self.assertEqual(plan.patch.read_bytes(), b"synthetic-vcdiff")
            self.assertEqual(document["source"]["track"], 1)
            self.assertEqual(document["source"]["mode"], "MODE1/2352")
            self.assertEqual(document["target"]["file"], "Track 1.bin")
            self.assertEqual(
                document["unchanged_tracks"],
                [
                    {
                        "track": 2,
                        "mode": "AUDIO",
                        "size": 5,
                        "sha256": hashlib.sha256(b"audio").hexdigest(),
                    }
                ],
            )
            self.assertEqual(
                document["patch"]["sha256"],
                hashlib.sha256(b"synthetic-vcdiff").hexdigest(),
            )
            self.assertEqual(len(fake.commands), 3)
            self.assertEqual(
                fake.commands[0][1 : 1 + len(ENCODER_OPTIONS)], ENCODER_OPTIONS
            )
            self.assertIn("-e", fake.commands[0])
            self.assertTrue(all("-d" in command for command in fake.commands[1:]))
            self.assertTrue(
                any("workspace with spaces" in value for value in fake.commands[0])
            )
            self.assertTrue(
                all(
                    "Track 2.bin" not in value
                    for command in fake.commands
                    for value in command
                )
            )
            self.assertEqual(plan.patch.stat().st_mtime_ns, patch_state)
            self.assertEqual(plan.metadata.stat().st_mtime_ns, metadata_state)

    def test_check_rejects_stale_patch_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, target = self.fixture(Path(directory))
            plan = plan_patch(sheet, contract, built)
            fake = FakeXdelta(target)
            create_patch(plan, "xdelta3", runner=fake)
            plan.patch.write_bytes(b"changed")

            with self.assertRaisesRegex(ValueError, "metadata is stale"):
                check_patch(plan, "xdelta3", runner=fake)

    def test_plan_rejects_a_changed_audio_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, _ = self.fixture(Path(directory))
            (built / "Track 2.bin").write_bytes(b"wrong")

            with self.assertRaisesRegex(ValueError, "companion track"):
                plan_patch(sheet, contract, built)

    def test_plan_protects_every_source_and_built_disc_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, _ = self.fixture(Path(directory))
            original = sheet.path.parent
            protected = (
                sheet.path,
                original / "Track 1.bin",
                original / "Track 2.bin",
                built / sheet.path.name,
                built / "Track 1.bin",
                built / "Track 2.bin",
            )

            for output in protected:
                with self.subTest(output=output):
                    with self.assertRaisesRegex(ValueError, "overwrite|source-disc"):
                        plan_patch(sheet, contract, built, output)

            with self.assertRaisesRegex(ValueError, "source-disc tree"):
                plan_patch(sheet, contract, built, original / "release.xdelta")
            with self.assertRaisesRegex(ValueError, r"\.xdelta extension"):
                plan_patch(sheet, contract, built, built / "release.vcdiff")

    def test_plan_rejects_the_original_disc_as_the_build_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, _, _ = self.fixture(Path(directory))

            with self.assertRaisesRegex(ValueError, "separate build directory"):
                plan_patch(sheet, contract, sheet.path.parent)

    def test_decode_must_reconstruct_the_exact_built_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, _ = self.fixture(Path(directory))
            plan = plan_patch(sheet, contract, built)
            plan.patch.write_bytes(b"previous-patch")
            plan.metadata.write_text("previous metadata", encoding="utf-8")
            wrong = FakeXdelta(b"wrong-track")

            with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                create_patch(plan, "xdelta3", runner=wrong)
            self.assertEqual(plan.patch.read_bytes(), b"previous-patch")
            self.assertEqual(
                plan.metadata.read_text(encoding="utf-8"), "previous metadata"
            )

    def test_publication_failure_restores_the_prior_patch_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, target = self.fixture(Path(directory))
            plan = plan_patch(sheet, contract, built)
            plan.patch.write_bytes(b"previous-patch")
            plan.metadata.write_text("previous metadata", encoding="utf-8")
            real_replace = xdelta._replace

            def fail_candidate_metadata(source: Path, destination: Path) -> None:
                if destination == plan.metadata and source.name == plan.metadata.name:
                    raise OSError("synthetic metadata publication failure")
                real_replace(source, destination)

            with (
                mock.patch(
                    "disc.script.xdelta._replace",
                    side_effect=fail_candidate_metadata,
                ),
                self.assertRaisesRegex(OSError, "metadata publication failure"),
            ):
                create_patch(plan, "xdelta3", runner=FakeXdelta(target))

            self.assertEqual(plan.patch.read_bytes(), b"previous-patch")
            self.assertEqual(
                plan.metadata.read_text(encoding="utf-8"), "previous metadata"
            )

    def test_existing_artifact_directories_are_never_consumed(self) -> None:
        for artifact in ("patch", "metadata"):
            with (
                self.subTest(artifact=artifact),
                tempfile.TemporaryDirectory() as directory,
            ):
                sheet, contract, built, target = self.fixture(Path(directory))
                plan = plan_patch(sheet, contract, built)
                path = plan.patch if artifact == "patch" else plan.metadata
                path.mkdir()
                sentinel = path / "sentinel.txt"
                sentinel.write_text("keep", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "regular file"):
                    create_patch(plan, "xdelta3", runner=FakeXdelta(target))
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_existing_patch_symlink_is_rejected_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, _ = self.fixture(Path(directory))
            sensitive = built.parent / "sensitive.xdelta"
            sensitive.write_bytes(b"keep-sensitive")
            output = built / "release.xdelta"
            try:
                output.symlink_to(sensitive)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                plan_patch(sheet, contract, built, output)
            self.assertEqual(sensitive.read_bytes(), b"keep-sensitive")

    def test_failed_rollback_preserves_a_stable_recovery_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, target = self.fixture(Path(directory))
            plan = plan_patch(sheet, contract, built)
            plan.patch.write_bytes(b"previous-patch")
            plan.metadata.write_text("previous metadata", encoding="utf-8")
            real_replace = xdelta._replace

            def fail_publication_and_patch_restore(
                source: Path,
                destination: Path,
            ) -> None:
                if destination == plan.metadata and source.name == plan.metadata.name:
                    raise OSError("synthetic metadata publication failure")
                if destination == plan.patch and source.name == "previous-patch":
                    raise OSError("synthetic patch restoration failure")
                real_replace(source, destination)

            with (
                mock.patch(
                    "disc.script.xdelta._replace",
                    side_effect=fail_publication_and_patch_restore,
                ),
                self.assertRaisesRegex(OSError, "recovery state"),
            ):
                create_patch(plan, "xdelta3", runner=FakeXdelta(target))

            recovery_roots = tuple(plan.patch.parent.glob("smtds-xdelta-rollback-*"))
            self.assertEqual(len(recovery_roots), 1)
            self.assertEqual(
                (recovery_roots[0] / "previous-patch").read_bytes(),
                b"previous-patch",
            )
            self.assertEqual(
                plan.metadata.read_text(encoding="utf-8"), "previous metadata"
            )

    def test_missing_executable_has_an_actionable_error(self) -> None:
        impossible = "definitely-not-an-installed-xdelta3"
        self.assertIsNone(shutil.which(impossible))
        with self.assertRaisesRegex(ValueError, "--xdelta"):
            resolve_xdelta(impossible)

    def test_executable_version_is_exact_and_ambient_arguments_are_removed(
        self,
    ) -> None:
        for reported in (
            "Xdelta version 3.1.0, Copyright",
            "Xdelta version 13.2.0, Copyright",
            "Xdelta version 3.2.0-dev, Copyright",
        ):
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": reported, "stderr": ""},
            )()
            with (
                self.subTest(reported=reported),
                mock.patch("disc.script.xdelta.shutil.which", return_value="xdelta3"),
                mock.patch(
                    "disc.script.xdelta.subprocess.run", return_value=completed
                ) as run,
                mock.patch.dict(os.environ, {"XDELTA": "-n"}),
                self.assertRaisesRegex(ValueError, "3.2.0 is required"),
            ):
                resolve_xdelta("xdelta3")
            self.assertNotIn("XDELTA", run.call_args.kwargs["env"])

    def test_exact_pinned_version_is_accepted(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": "Xdelta version 3.2.0, Copyright",
                "stderr": "",
            },
        )()
        with (
            mock.patch(
                "disc.script.xdelta.shutil.which", return_value="resolved-xdelta3"
            ),
            mock.patch(
                "disc.script.xdelta.subprocess.run", return_value=completed
            ) as run,
        ):
            self.assertEqual(resolve_xdelta("xdelta3"), "resolved-xdelta3")
        self.assertEqual(run.call_args.args[0], ("resolved-xdelta3", "-V"))

    @unittest.skipUnless(shutil.which("xdelta3"), "xdelta3 is not installed")
    def test_real_xdelta_round_trip_when_tool_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sheet, contract, built, _ = self.fixture(Path(directory))
            plan = plan_patch(sheet, contract, built)
            executable = resolve_xdelta("xdelta3")

            create_patch(plan, executable)
            check_patch(plan, executable)


if __name__ == "__main__":
    unittest.main()
