"""Run the compact validation suite for a clean repository checkout."""

import importlib.util
import shutil
import subprocess
import sys

from project_paths import PROJECT_ROOT

RUFF_VERSION = "0.15.22"
MYPY_VERSION = "1.17.1"


def ruff_command(*arguments: str) -> tuple[str, ...]:
    if importlib.util.find_spec("ruff") is not None:
        return (sys.executable, "-m", "ruff", *arguments)
    executable = shutil.which("ruff")
    if executable:
        return (executable, *arguments)
    uvx = shutil.which("uvx")
    if uvx:
        return (uvx, f"ruff@{RUFF_VERSION}", *arguments)
    raise RuntimeError("Ruff is unavailable; install requirements.txt or install uv")


def mypy_command() -> tuple[str, ...]:
    if importlib.util.find_spec("mypy") is not None:
        return (sys.executable, "-m", "mypy")
    executable = shutil.which("mypy")
    if executable:
        return (executable,)
    uvx = shutil.which("uvx")
    if uvx:
        return (uvx, f"mypy@{MYPY_VERSION}")
    raise RuntimeError("mypy is unavailable; install requirements.txt or install uv")


def checks() -> tuple[tuple[str, tuple[str, ...]], ...]:
    python = sys.executable
    return (
        ("Python formatting", ruff_command("format", "--check", ".")),
        ("Python correctness lint", ruff_command("check", ".")),
        ("Focused type checking", mypy_command()),
        (
            "Compact regression suite",
            (
                python,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                ".",
                "-p",
                "test_*.py",
                "-v",
            ),
        ),
        (
            "Translation corpus audit",
            (
                python,
                "-B",
                "-m",
                "text.script.audit_translations",
                "--check",
                "--allow-empty",
            ),
        ),
        ("SH-2 assembler self-test", (python, "-B", "-m", "tools.sh2asm")),
        (
            "Engine capability discovery",
            (python, "-B", "-m", "engine.script.build", "--list"),
        ),
        ("Build plan", (python, "-B", "build", "--plan")),
    )


def main() -> None:
    try:
        source_checks = checks()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    for name, command in source_checks:
        print(f"\n== {name} ==", flush=True)
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=False,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
    print("\nRepository validation passed.")


if __name__ == "__main__":
    main()
