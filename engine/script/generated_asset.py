"""Validated loaders for text-owned generated runtime contracts."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from engine.script.context import EngineBuildContext

RUNTIME_UI_PATH = Path("runtime_ui/engine.json")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class RuntimeUiContract:
    path: Path
    sections: dict[str, object]

    def section(self, name: str) -> object:
        try:
            return self.sections[name]
        except KeyError as error:
            raise ValueError(
                f"{self.path}: missing runtime UI section {name!r}"
            ) from error


def load_runtime_ui(context: EngineBuildContext) -> RuntimeUiContract:
    path = context.text_generated_root / RUNTIME_UI_PATH
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1 or document.get("kind") != "engine_runtime_ui":
        raise ValueError(f"{path}: unsupported runtime UI contract")

    expected_digest = document.get("contract_sha256")
    unsigned = dict(document)
    unsigned.pop("contract_sha256", None)
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if expected_digest != sha256(canonical):
        raise ValueError(f"{path}: runtime UI contract digest mismatch")

    bindings = document.get("font_bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError(f"{path}: missing font bindings")
    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"{path}: invalid font binding {name!r}")
        relative = Path(binding.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"{path}: unsafe font binding path for {name!r}")
        font_path = context.font_generated_root / relative
        if sha256(font_path.read_bytes()) != binding.get("sha256"):
            raise ValueError(f"{path}: stale font binding {name!r}")

    sections = document.get("sections")
    section_bindings = document.get("section_bindings")
    requirements = document.get("required_capabilities")
    if (
        not isinstance(sections, dict)
        or not isinstance(section_bindings, dict)
        or not isinstance(requirements, list)
    ):
        raise ValueError(f"{path}: invalid runtime UI sections or requirements")
    for name, section in sections.items():
        binding = section_bindings.get(name)
        if not isinstance(binding, dict):
            raise ValueError(f"{path}: missing section binding {name!r}")
        relative = Path(binding.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"{path}: unsafe section binding path for {name!r}")
        section_path = context.text_generated_root / relative
        if sha256(section_path.read_bytes()) != binding.get("sha256"):
            raise ValueError(f"{path}: stale runtime UI section {name!r}")
    if not all(isinstance(name, str) and name for name in requirements):
        raise ValueError(f"{path}: invalid runtime UI capability requirement")
    return RuntimeUiContract(path, sections)
