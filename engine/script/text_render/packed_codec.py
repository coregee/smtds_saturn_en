"""Shared dictionary-packed text format and generated-table ownership."""

import hashlib
import json
from pathlib import Path

from project_paths import BUILD_ROOT, TEXT_GENERATED_ROOT

PACKED_TOKEN_BASE = 8
PACKED_TOKEN_RANGE = 120
PACKED_SPACE_CODE = 267
DICTIONARY_TOKEN_START = 63
DICTIONARY_TOKENS = PACKED_TOKEN_RANGE - DICTIONARY_TOKEN_START
DICTIONARY_RECORD_SIZE = 8
MAX_EXPANSION = DICTIONARY_RECORD_SIZE - 1

DICTIONARY_PATH = TEXT_GENERATED_ROOT / "event_codec.json"
DICTIONARY_BINDING_PATH = TEXT_GENERATED_ROOT / "event_codec_binding.json"


if not 0 < PACKED_TOKEN_BASE <= 0x7F:
    raise ValueError("packed token base must fit a positive byte")
if not 0 < PACKED_TOKEN_RANGE <= 0x7F:
    raise ValueError("packed token range must fit a signed SH-2 immediate")
if PACKED_TOKEN_BASE + PACKED_TOKEN_RANGE > 0x80:
    raise ValueError("packed token bytes would overlap EVENT control words")


def validate_dictionary_binding(
    dictionary_path: Path = DICTIONARY_PATH,
    binding_path: Path = DICTIONARY_BINDING_PATH,
    build_root: Path = BUILD_ROOT,
) -> None:
    """Reject text outputs encoded with a different generated dictionary."""
    try:
        dictionary_data = dictionary_path.read_bytes()
    except FileNotFoundError as error:
        raise ValueError(
            f"missing generated EVENT dictionary {dictionary_path}; repack text first"
        ) from error
    try:
        document = json.loads(binding_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(
            f"missing EVENT dictionary binding {binding_path}; repack text first"
        ) from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{binding_path}: invalid JSON") from error

    if not isinstance(document, dict) or set(document) != {
        "version",
        "codec_sha256",
        "registered_outputs",
        "outputs",
    }:
        raise ValueError(f"{binding_path}: invalid EVENT dictionary binding")
    if document["version"] != 1:
        raise ValueError(f"{binding_path}: unsupported binding version")
    registered = document["registered_outputs"]
    outputs = document["outputs"]
    if (
        not isinstance(registered, list)
        or any(not isinstance(path, str) or not path for path in registered)
        or len(set(registered)) != len(registered)
    ):
        raise ValueError(f"{binding_path}: invalid registered text outputs")
    if (
        not isinstance(outputs, dict)
        or any(
            not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or len(digest) != 64
            for path, digest in outputs.items()
        )
        or not set(outputs) <= set(registered)
    ):
        raise ValueError(f"{binding_path}: invalid bound text outputs")

    dictionary_digest = hashlib.sha256(dictionary_data).hexdigest()
    if document["codec_sha256"] != dictionary_digest:
        raise ValueError(
            "EVENT dictionary and binding do not match; repack text before "
            "building the engine"
        )

    for relative_path in registered:
        output_path = build_root / relative_path
        expected_digest = outputs.get(relative_path)
        if expected_digest is None:
            if output_path.exists():
                raise ValueError(
                    f"{output_path}: stale text output is not bound to the "
                    "current EVENT dictionary; repack text"
                )
            continue
        try:
            output_data = output_path.read_bytes()
        except FileNotFoundError as error:
            raise ValueError(
                f"missing bound text output {output_path}; repack text"
            ) from error
        if hashlib.sha256(output_data).hexdigest() != expected_digest:
            raise ValueError(
                f"{output_path}: text output does not match the current EVENT "
                "dictionary binding; repack text"
            )


def load_dictionary_table(path: Path = DICTIONARY_PATH) -> bytes:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(
            f"missing generated EVENT dictionary {path}; repack text first"
        ) from error
    expected = {
        "version": 1,
        "token_base": PACKED_TOKEN_BASE,
        "token_limit": PACKED_TOKEN_RANGE,
        "dictionary_token_start": DICTIONARY_TOKEN_START,
        "max_expansion": MAX_EXPANSION,
        "base_codes": [PACKED_SPACE_CODE, *range(1, DICTIONARY_TOKEN_START)],
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise ValueError(f"{path}: invalid EVENT dictionary {key}")
    expansions = document.get("expansions")
    if not isinstance(expansions, list) or len(expansions) > DICTIONARY_TOKENS:
        raise ValueError(f"{path}: invalid EVENT dictionary expansions")

    table = bytearray(DICTIONARY_TOKENS * DICTIONARY_RECORD_SIZE)
    for index, expansion in enumerate(expansions):
        if (
            not isinstance(expansion, list)
            or not 2 <= len(expansion) <= MAX_EXPANSION
            or any(
                not isinstance(token, int) or not 0 <= token < DICTIONARY_TOKEN_START
                for token in expansion
            )
        ):
            raise ValueError(
                f"{path}: invalid expansion for token {index + DICTIONARY_TOKEN_START}"
            )
        offset = index * DICTIONARY_RECORD_SIZE
        table[offset] = len(expansion)
        table[offset + 1 : offset + 1 + len(expansion)] = bytes(expansion)
    return bytes(table)


def bound_dictionary_table(
    dictionary_path: Path = DICTIONARY_PATH,
    binding_path: Path = DICTIONARY_BINDING_PATH,
    build_root: Path = BUILD_ROOT,
) -> bytes:
    """Load the generated dictionary after validating all bound text outputs."""
    validate_dictionary_binding(dictionary_path, binding_path, build_root)
    return load_dictionary_table(dictionary_path)
