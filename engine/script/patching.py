import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from engine.script.sh2 import disassemble
from tools.sh2asm import assemble


class PatchError(ValueError):
    """Raised when a binary cannot be patched safely."""


@dataclass(frozen=True)
class BinaryTarget:
    name: str
    path: Path
    load_address: int

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not self.name:
            raise ValueError("binary target name cannot be empty")
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"binary target path must be relative: {path}")
        if self.load_address < 0:
            raise ValueError("binary target load address cannot be negative")
        object.__setattr__(self, "path", path)

    def file_offset(self, address: int) -> int:
        return address - self.load_address


@dataclass(frozen=True)
class BytePatch:
    name: str
    address: int
    expected: bytes
    replacement: bytes

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("byte patch name cannot be empty")
        if self.address < 0:
            raise ValueError("byte patch address cannot be negative")
        if not self.expected:
            raise ValueError(f"{self.name}: expected bytes cannot be empty")
        if len(self.expected) != len(self.replacement):
            raise ValueError(
                f"{self.name}: expected and replacement lengths differ "
                f"({len(self.expected)} != {len(self.replacement)})"
            )


@dataclass(frozen=True)
class CodePatch:
    """Same-size SH-2 replacement retaining both sides as assembly source."""

    name: str
    address: int
    original_source: str
    replacement_source: str
    symbols: Mapping[str, int] = field(default_factory=dict, repr=False, compare=False)
    allow_trailing_delay_slot: bool = False
    expected: bytes = field(init=False, repr=False)
    replacement: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("code patch name cannot be empty")
        if self.address < 0:
            raise ValueError("code patch address cannot be negative")
        original = assemble(self.original_source, self.address, symbols=self.symbols)
        replacement = assemble(
            self.replacement_source, self.address, symbols=self.symbols
        )
        warnings = tuple(
            warning
            for warning in (*original.warnings, *replacement.warnings)
            if not (
                self.allow_trailing_delay_slot
                and "delay slot runs off the end" in warning
            )
        )
        if warnings:
            raise ValueError(f"{self.name}: assembler warnings: {warnings}")
        expected = bytes(original)
        encoded_replacement = bytes(replacement)
        if not expected:
            raise ValueError(f"{self.name}: original assembly cannot be empty")
        if len(expected) != len(encoded_replacement):
            raise ValueError(
                f"{self.name}: original and replacement assembly lengths differ "
                f"({len(expected)} != {len(encoded_replacement)})"
            )
        object.__setattr__(self, "symbols", dict(self.symbols))
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "replacement", encoded_replacement)


@dataclass(frozen=True)
class DigestPatch:
    """Same-size replacement asserted by the SHA-256 of its source region."""

    name: str
    address: int
    expected_sha256: str
    replacement: bytes

    def __post_init__(self) -> None:
        digest = self.expected_sha256.lower()
        if not self.name:
            raise ValueError("digest patch name cannot be empty")
        if self.address < 0:
            raise ValueError("digest patch address cannot be negative")
        if not self.replacement:
            raise ValueError(f"{self.name}: replacement bytes cannot be empty")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError(f"{self.name}: invalid SHA-256 digest")
        object.__setattr__(self, "expected_sha256", digest)


@dataclass(frozen=True)
class PatchGroup:
    capability: str
    target: BinaryTarget
    patches: tuple[BytePatch | CodePatch | DigestPatch, ...]

    def __post_init__(self) -> None:
        if not self.capability:
            raise ValueError("patch capability cannot be empty")
        if not self.patches:
            raise ValueError(f"{self.capability}: patch group cannot be empty")


def apply_patch_groups(
    original: bytes,
    groups: Iterable[PatchGroup],
) -> bytes:
    groups = tuple(groups)
    if not groups:
        return original

    target = groups[0].target
    for group in groups[1:]:
        if group.target != target:
            raise PatchError(
                f"cannot apply {group.target.name} patches to {target.name}"
            )

    sites = []
    names = set()
    for group in groups:
        for patch in group.patches:
            qualified_name = f"{group.capability}/{patch.name}"
            if qualified_name in names:
                raise PatchError(f"duplicate patch name: {qualified_name}")
            names.add(qualified_name)

            start = target.file_offset(patch.address)
            size = (
                len(patch.expected)
                if isinstance(patch, (BytePatch, CodePatch))
                else len(patch.replacement)
            )
            end = start + size
            if start < 0 or end > len(original):
                raise PatchError(
                    f"{target.name}: {qualified_name} at {patch.address:#010x} "
                    f"maps outside the file (offset {start:#x})"
                )
            sites.append((start, end, qualified_name, patch))

    sites.sort(key=lambda site: (site[0], site[1]))
    for previous, current in zip(sites, sites[1:]):
        if current[0] < previous[1]:
            raise PatchError(
                f"{target.name}: patches {previous[2]} and {current[2]} overlap"
            )

    for start, end, qualified_name, patch in sites:
        actual = original[start:end]
        if isinstance(patch, (BytePatch, CodePatch)):
            if actual != patch.expected:
                detail = ""
                if isinstance(patch, CodePatch):
                    decoded = "\n    ".join(disassemble(actual, patch.address))
                    detail = (
                        f"\n  original source: {patch.original_source.strip()}"
                        f"\n  decoded actual:\n    {decoded}"
                    )
                raise PatchError(
                    f"{target.name}: {qualified_name} did not match at "
                    f"{patch.address:#010x} (file offset {start:#x}); "
                    f"expected {patch.expected.hex(' ')}, found {actual.hex(' ')}"
                    f"{detail}"
                )
        else:
            actual_sha256 = hashlib.sha256(actual).hexdigest()
            if actual_sha256 != patch.expected_sha256:
                raise PatchError(
                    f"{target.name}: {qualified_name} did not match at "
                    f"{patch.address:#010x} (file offset {start:#x}); "
                    f"expected SHA-256 {patch.expected_sha256}, "
                    f"found {actual_sha256}"
                )

    patched = bytearray(original)
    for start, end, _qualified_name, patch in sites:
        patched[start:end] = patch.replacement
    return bytes(patched)
