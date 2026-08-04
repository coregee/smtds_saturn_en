"""Apply digest-bound fixed-field assets emitted by the text package."""

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from engine.script.patching import BinaryTarget, DigestPatch, PatchGroup

ASSETS = (
    Path("ascii_fields/AUTOMAPC.BIN.marker_ui.json"),
    Path("fixed_words/AUTOMAPC.BIN.system.json"),
    Path("fixed_words/COMBAT.BIN.system.json"),
    Path("fixed_words/COMBAT.BIN.condition_messages.json"),
    Path("fixed_words/LEVEL_UP.BIN.json"),
    Path("fixed_words/LOAD.BIN.capacity.json"),
    Path("fixed_words/MAZE.BIN.messages.json"),
    Path("deduplicated_words/COMBAT.BIN.debug_text.json"),
    Path("mirrored_words/normcom_tables/NORMCOM.BIN.json"),
    Path("mirrored_words/normcom_tables/EVENT.BIN.json"),
    Path("mirrored_words/normcom_tables/COMBAT.BIN.json"),
    Path("mirrored_words/normcom_tables/MSGR.COF.json"),
)


@dataclass(frozen=True)
class RuntimeWordField:
    name: str
    file_offset: int
    words: tuple[int, ...]


@dataclass(frozen=True)
class RuntimeByteField:
    name: str
    file_offset: int
    data: bytes


def load_runtime_byte_fields(
    relative: Path,
    generated_root: Path,
    extracted_root: Path,
    *,
    expected_source: Path,
    max_bytes: int,
) -> tuple[int, tuple[RuntimeByteField, ...]]:
    """Load complete ASCII fields that an engine-owned runtime relocates."""
    path = generated_root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1 or document.get("source") != str(
        expected_source.as_posix()
    ):
        raise ValueError(f"{path}: invalid runtime-field asset")

    original = (extracted_root / expected_source).read_bytes()
    if hashlib.sha256(original).hexdigest() != document.get("source_sha256"):
        raise ValueError(f"{path}: extracted {expected_source} hash changed")
    try:
        load_address = int(document["load_address"], 16)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path}: invalid load address") from error

    rows = document.get("runtime_fields")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: missing runtime fields")
    fields = []
    names = set()
    offsets = set()
    for index, row in enumerate(rows):
        context = f"{path}: runtime field {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        name = row.get("name")
        try:
            file_offset = int(row["file_offset"], 16)
            byte_count = row["byte_count"]
            data = bytes.fromhex(row["bytes_hex"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{context}: invalid encoded bytes") from error
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or file_offset in offsets
            or file_offset < 0
            or file_offset >= len(original)
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or not 1 <= byte_count <= max_bytes
            or len(data) != byte_count
            or not data.endswith(b"\x00")
            or b"\x00" in data[:-1]
        ):
            raise ValueError(f"{context}: invalid runtime span")
        try:
            data[:-1].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError(f"{context}: runtime field is not ASCII") from error
        fields.append(
            RuntimeByteField(
                name=name,
                file_offset=file_offset,
                data=data,
            )
        )
        names.add(name)
        offsets.add(file_offset)
    return load_address, tuple(fields)


def load_runtime_fields(
    relative: Path,
    generated_root: Path,
    extracted_root: Path,
    *,
    expected_source: Path,
    max_words: int,
) -> tuple[int, tuple[RuntimeWordField, ...]]:
    """Load full encoded fields that an engine-owned runtime relocates."""
    path = generated_root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1 or document.get("source") != str(
        expected_source.as_posix()
    ):
        raise ValueError(f"{path}: invalid runtime-field asset")

    original = (extracted_root / expected_source).read_bytes()
    if hashlib.sha256(original).hexdigest() != document.get("source_sha256"):
        raise ValueError(f"{path}: extracted {expected_source} hash changed")
    try:
        load_address = int(document["load_address"], 16)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path}: invalid load address") from error

    rows = document.get("runtime_fields")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: missing runtime fields")
    fields = []
    names = set()
    offsets = set()
    for index, row in enumerate(rows):
        context = f"{path}: runtime field {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        name = row.get("name")
        try:
            file_offset = int(row["file_offset"], 16)
            word_count = row["word_count"]
            data = bytes.fromhex(row["words_hex"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{context}: invalid encoded words") from error
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or file_offset in offsets
            or file_offset < 0
            or file_offset >= len(original)
            or file_offset & 1
            or not isinstance(word_count, int)
            or isinstance(word_count, bool)
            or not 1 <= word_count <= max_words
            or len(data) != word_count * 2
        ):
            raise ValueError(f"{context}: invalid runtime span")
        fields.append(
            RuntimeWordField(
                name=name,
                file_offset=file_offset,
                words=struct.unpack(f">{word_count}H", data),
            )
        )
        names.add(name)
        offsets.add(file_offset)
    return load_address, tuple(fields)


def load_group(
    relative: Path,
    generated_root: Path,
    extracted_root: Path,
) -> PatchGroup | None:
    path = generated_root / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError(f"{path}: unsupported fixed-text asset version")
    source = data.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError(f"{path}: source must be nonempty text")
    source_path = Path(source)
    if source_path.is_absolute() or ".." in source_path.parts:
        raise ValueError(f"{path}: source path must be relative")
    original = (extracted_root / source_path).read_bytes()
    if hashlib.sha256(original).hexdigest() != data.get("source_sha256"):
        raise ValueError(f"{path}: extracted source hash changed")
    try:
        load_address = int(data["load_address"], 16)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path}: invalid load address") from error

    raw_patches = data.get("patches")
    if not isinstance(raw_patches, list):
        raise ValueError(f"{path}: patches must be an array")
    patches = []
    names = set()
    for index, row in enumerate(raw_patches):
        context = f"{path}: patch {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        name = row.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"{context}: invalid or duplicate name")
        names.add(name)
        try:
            offset = int(row["file_offset"], 16)
            replacement = bytes.fromhex(row["replacement_hex"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{context}: invalid offset or replacement") from error
        if offset < 0 or offset + len(replacement) > len(original):
            raise ValueError(f"{context}: replacement exceeds the source")
        patches.append(
            DigestPatch(
                name=name,
                address=load_address + offset,
                expected_sha256=row.get("expected_sha256", ""),
                replacement=replacement,
            )
        )

    if not patches:
        return None
    return PatchGroup(
        "fixed_text_fields",
        BinaryTarget(source_path.name, source_path, load_address),
        tuple(patches),
    )
