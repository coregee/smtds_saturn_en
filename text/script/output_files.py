"""Shared check-or-write handling for generated text artifacts."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OutputFiles:
    check: bool
    stale: list[Path] = field(default_factory=list)

    def bytes(self, path: Path, data: bytes) -> Path:
        if self.check:
            if not path.exists() or path.read_bytes() != data:
                self.stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path

    def text(self, path: Path, text: str) -> Path:
        if self.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                self.stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def require_current(self, description: str) -> None:
        if self.stale:
            paths = "\n  ".join(str(path) for path in self.stale)
            raise ValueError(f"{description}:\n  {paths}")
