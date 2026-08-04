"""EVENT and MSGR consumers of the generated FONT16 name rows."""

import struct
from dataclasses import dataclass
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.event.model import EVENT_TARGET
from engine.script.msgr.model import MSGR_TARGET
from engine.script.name.fields import FIELD_BY_KIND, NameField
from engine.script.patching import BytePatch, CodePatch, DigestPatch, PatchGroup
from engine.script.sh2 import assemble_checked


@dataclass(frozen=True)
class InsertSite:
    field: NameField
    pointer_address: int
    original_pointer: int
    terminator_stamp: int


@dataclass(frozen=True)
class RawMenuSpec:
    target_name: str
    renderer: int
    renderer_end: int
    renderer_sha256: str
    continue_address: int
    result_sites: tuple[int, ...]
    pointer_sites: tuple[tuple[NameField, int, int], ...]
    blitter_pointer: int
    original_blitter: int
    stock_advance: int


EVENT_SITES = (
    InsertSite(NameField.FIRST, 0x0602C554, 0x002029B8, 0x0602C51C),
    InsertSite(NameField.LAST, 0x0602C5C8, 0x002029B0, 0x0602C592),
    InsertSite(NameField.CITY, 0x0602C63C, 0x002029D0, 0x0602C606),
    InsertSite(NameField.WARD, 0x0602C6B0, 0x002029D8, 0x0602C67A),
)
MSGR_SITES = (
    InsertSite(NameField.FIRST, 0x0606F600, 0x002029B8, 0x0606F5C8),
    InsertSite(NameField.LAST, 0x0606F674, 0x002029B0, 0x0606F63E),
    InsertSite(NameField.CITY, 0x0606F6E8, 0x002029D0, 0x0606F6B2),
    InsertSite(NameField.WARD, 0x0606F75C, 0x002029D8, 0x0606F726),
)

EVENT_RAW_MENU = RawMenuSpec(
    target_name="EVENT",
    renderer=0x06030BB4,
    renderer_end=0x06030C14,
    renderer_sha256=(
        "12226d03c1e6596447e14e6a7042e4567d3b53665f450e90055a1f97696ded31"
    ),
    continue_address=0x06030CDA,
    result_sites=(0x06030C66, 0x06030C98),
    pointer_sites=(
        (NameField.FIRST, 0x06030D14, 0x002029B8),
        (NameField.LAST, 0x06030D1C, 0x002029B0),
    ),
    blitter_pointer=0x06030D20,
    original_blitter=0x0602BCC0,
    stock_advance=0x06076754,
)
MSGR_RAW_MENU = RawMenuSpec(
    target_name="MSGR",
    renderer=0x0606C63C,
    renderer_end=0x0606C69C,
    renderer_sha256=(
        "a9242a67ee55cc77008b1b501058e93f6d70bdb5add3a5fab3fc44e3d778d83f"
    ),
    continue_address=0x0606C762,
    result_sites=(0x0606C6EE, 0x0606C720),
    pointer_sites=(
        (NameField.FIRST, 0x0606C79C, 0x002029B8),
        (NameField.LAST, 0x0606C7A4, 0x002029B0),
    ),
    blitter_pointer=0x0606C7A8,
    original_blitter=0x0606ED6C,
    stock_advance=0x06079594,
)
RAW_MENU_SOURCE = Path(__file__).with_name("raw_menu_inserts.s")


def direct_insert_patches(sites: tuple[InsertSite, ...]) -> tuple[BytePatch, ...]:
    patches = []
    for site in sites:
        name = FIELD_BY_KIND[site.field].key
        patches.extend(
            (
                BytePatch(
                    name=f"{name}_insert_pointer",
                    address=site.pointer_address,
                    expected=struct.pack(">I", site.original_pointer),
                    replacement=struct.pack(
                        ">I",
                        FIELD_BY_KIND[site.field].runtime_address,
                    ),
                ),
                BytePatch(
                    name=f"{name}_terminator_stamp",
                    address=site.terminator_stamp,
                    expected=struct.pack(">H", 0x2121),
                    replacement=struct.pack(">H", 0x0009),
                ),
            )
        )
    return tuple(patches)


def codename_patches(
    branch_address: int,
    scratch_pointer: int,
    original_scratch: int,
) -> tuple[BytePatch, ...]:
    codename = FIELD_BY_KIND[NameField.CODENAME]
    return (
        BytePatch(
            name="codename_skip_copy",
            address=branch_address,
            expected=struct.pack(">2H", 0xE300, 0xE507),
            replacement=struct.pack(">2H", 0xA027, 0x0009),
        ),
        BytePatch(
            name="codename_insert_pointer",
            address=scratch_pointer,
            expected=struct.pack(">I", original_scratch),
            replacement=struct.pack(">I", codename.runtime_address),
        ),
    )


def build_raw_menu_renderer(spec: RawMenuSpec) -> bytes:
    """Draw one complete generated name row and return its final pixel X."""
    code = assemble_checked(
        RAW_MENU_SOURCE.read_text(encoding="utf-8"),
        spec.renderer,
        {
            "MENU_BLITTER_POINTER": spec.blitter_pointer,
            "ORIGINAL_BLITTER": spec.original_blitter,
            "STOCK_ADVANCE": spec.stock_advance,
            "TERMINATOR": 0x8000,
        },
        context=f"{spec.target_name} raw-menu name insert",
    )
    capacity = spec.renderer_end - spec.renderer
    if len(code) > capacity:
        raise ValueError(
            f"{spec.target_name} raw-menu name insert needs {len(code)} bytes; "
            f"capacity is {capacity} bytes"
        )
    return bytes(code).ljust(capacity, b"\0")


def raw_menu_patches(
    spec: RawMenuSpec,
) -> tuple[BytePatch | CodePatch | DigestPatch, ...]:
    pointer_patches = tuple(
        BytePatch(
            name=f"raw_menu_{FIELD_BY_KIND[field].key}_insert_pointer",
            address=address,
            expected=struct.pack(">I", original_pointer),
            replacement=struct.pack(">I", FIELD_BY_KIND[field].runtime_address),
        )
        for field, address, original_pointer in spec.pointer_sites
    )
    result_patches = tuple(
        CodePatch(
            name=f"raw_menu_name_result_{address:08x}",
            address=address,
            original_source="""
                mov     r8, r1
                add     #2, r1
                mov.w   @r1, r1
            """,
            replacement_source="""
                mov     r0, r9
                bra     EVENT_RAW_MENU_CONTINUE
                add     #2, r10
            """,
            symbols={"EVENT_RAW_MENU_CONTINUE": spec.continue_address},
        )
        for address in spec.result_sites
    )
    return (
        DigestPatch(
            name="raw_menu_name_renderer",
            address=spec.renderer,
            expected_sha256=spec.renderer_sha256,
            replacement=build_raw_menu_renderer(spec),
        ),
        *pointer_patches,
        *result_patches,
    )


def build_patch_groups(_context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    return (
        PatchGroup(
            capability="name_runtime",
            target=EVENT_TARGET,
            patches=(
                *direct_insert_patches(EVENT_SITES),
                *codename_patches(0x0602C44C, 0x0602C4D4, 0x06076A84),
                *raw_menu_patches(EVENT_RAW_MENU),
            ),
        ),
        PatchGroup(
            capability="name_runtime",
            target=MSGR_TARGET,
            patches=(
                *direct_insert_patches(MSGR_SITES),
                *codename_patches(0x0606F4F8, 0x0606F580, 0x0607984C),
                *raw_menu_patches(MSGR_RAW_MENU),
            ),
        ),
    )
