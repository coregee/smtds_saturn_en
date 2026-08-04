"""Readable SH-2 source helpers used by runtime patches and references."""

import re
from collections.abc import Mapping
from pathlib import Path

from tools.sh2asm import AsmBlob, assemble

TOKEN = re.compile(r"@([A-Z][A-Z0-9_]*)@")


def render_template(path: Path, values: Mapping[str, object]) -> str:
    """Render a deliberately small, auditable assembly-template language."""
    source = path.read_text(encoding="utf-8")
    required = set(TOKEN.findall(source))
    supplied = set(values)
    missing = required - supplied
    unused = supplied - required
    if missing:
        raise ValueError(
            f"{path.name}: missing template values: {', '.join(sorted(missing))}"
        )
    if unused:
        raise ValueError(
            f"{path.name}: unused template values: {', '.join(sorted(unused))}"
        )
    return TOKEN.sub(lambda match: str(values[match.group(1)]), source)


def assemble_checked(
    source: str,
    address: int,
    symbols: Mapping[str, int],
    *,
    context: str,
) -> AsmBlob:
    """Assemble SH-2 source and reject warnings with consistent context."""
    blob = assemble(source, address, symbols=symbols)
    if blob.warnings:
        raise ValueError(
            f"{context} assembly warnings at {address:#x}: {blob.warnings}"
        )
    return blob


def disassemble(
    data: bytes,
    address: int,
    *,
    require_capstone: bool = False,
) -> tuple[str, ...]:
    """Return Capstone SH-2 instructions, or a hex fallback if unavailable."""
    try:
        from capstone import CS_ARCH_SH, CS_MODE_BIG_ENDIAN, CS_MODE_SH2, Cs
    except ImportError as error:
        if require_capstone:
            raise RuntimeError(
                "Capstone is required to generate SH-2 references"
            ) from error
        return (f"{address:08x}  {data.hex(' ')}",)

    decoder = Cs(CS_ARCH_SH, CS_MODE_SH2 | CS_MODE_BIG_ENDIAN)
    lines = []
    consumed = 0
    for instruction in decoder.disasm(data, address):
        raw = instruction.bytes.hex(" ")
        operation = " ".join(
            part for part in (instruction.mnemonic, instruction.op_str) if part
        )
        lines.append(f"{instruction.address:08x}  {raw:<11}  {operation}")
        consumed += instruction.size
    if consumed != len(data):
        remainder = data[consumed:]
        lines.append(f"{address + consumed:08x}  {remainder.hex(' '):<11}  .byte")
    return tuple(lines)
