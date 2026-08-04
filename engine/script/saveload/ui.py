"""Render generated SAVE/LOAD UI text proportionally."""

import struct
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.dungeon_text import (
    PADDING_CODE,
    SAVELOAD_DUNGEON_CELLS,
    build_saveload_dungeon_records,
    validate_dungeon_prefix_mirror,
)
from engine.script.name.model import load_atlas_metrics
from engine.script.patching import (
    BinaryTarget,
    BytePatch,
    CodePatch,
    DigestPatch,
    PatchGroup,
)
from engine.script.saveload.load import LOAD_TARGET
from engine.script.saveload.names import (
    SAVE_TARGET,
)
from engine.script.saveload.names import (
    SPECS as NAME_STRIP_SPECS,
)
from engine.script.saveload.names import (
    build_cave as build_name_cave,
)
from engine.script.static_text import EXTRACTED_ROOT, StaticTextAsset, load_static_asset
from text.script.dungeon_locations import ASSET_PATH as DUNGEON_ASSET_PATH
from text.script.dungeon_locations import SOURCE_PATH as DUNGEON_SOURCE_PATH
from tools.sh2asm import AsmBlob, assemble
from visual.script.saveload import build_replacement as build_saveload_image
from visual.script.util.images import (
    saveload_image_records,
    validate_saveload_image_records,
)

SOURCE_PATH = Path(__file__).with_name("text_vwf.s")
FREE_WINDOW_END = 0x6500
LOCATION_CELLS = 16
LOCATION_BLOCKS = (
    "location_home",
    "location_office",
    "location_asahi",
    "location_rinkai_park",
    "location_mount_kasagi",
    "location_yarai",
    "location_chuo",
    "location_hibarigaoka",
)
PROMPT_BLOCKS = ("prompt_overwrite", "prompt_quit_game")


@dataclass(frozen=True)
class UISpec:
    target: BinaryTarget
    cave_offset: int
    original_blitter: int
    blitter_pool_offset: int
    advance_offset: int
    old_location_address: int
    location_pool_offsets: tuple[int, int, int]
    location_instruction_offsets: tuple[int, int, int, int]
    empty_offset: int
    dungeon_index_address: int
    dungeon_table_offset: int
    dungeon_hook_offset: int
    dungeon_draw_text: int
    dungeon_draw_context: int
    prompt_sites: tuple[tuple[int, bytes], ...] = ()

    @property
    def cave_address(self) -> int:
        return self.target.load_address + self.cave_offset


UI_SPECS = (
    UISpec(
        target=SAVE_TARGET,
        cave_offset=0x800,
        original_blitter=0x06028128,
        blitter_pool_offset=0x8248,
        advance_offset=0x8224,
        old_location_address=0x06071B2C,
        location_pool_offsets=(0xAC70, 0xAC7C, 0xAD24),
        location_instruction_offsets=(0xAC42, 0xAC56, 0xACD8, 0xACE2),
        empty_offset=0x50760,
        prompt_sites=(
            (
                0x508A4,
                bytes.fromhex(
                    "04 1c 04 1d 00 57 01 b5 01 b1 00 6b 00 4a 00 5d 00 4b 00 44 00 b4"
                ),
            ),
            (
                0x508C6,
                bytes.fromhex(
                    "00 ea 00 ad 00 96 00 6b 03 6c 01 77 00 4a 00 5d 00 4b 00 44 00 b4"
                ),
            ),
        ),
        dungeon_index_address=0x06073BC9,
        dungeon_table_offset=0x50928,
        dungeon_hook_offset=0xAD28,
        dungeon_draw_text=0x060281E8,
        dungeon_draw_context=0x06070560,
    ),
    UISpec(
        target=LOAD_TARGET,
        cave_offset=0xC00,
        original_blitter=0x06029460,
        blitter_pool_offset=0x9580,
        advance_offset=0x955C,
        old_location_address=0x06072A14,
        location_pool_offsets=(0xA814, 0xA820, 0xA8C4),
        location_instruction_offsets=(0xA7E4, 0xA7F8, 0xA87A, 0xA882),
        empty_offset=0x0B1B4,
        dungeon_index_address=0x06074AA9,
        dungeon_table_offset=0x51810,
        dungeon_hook_offset=0xA8C8,
        dungeon_draw_text=0x06029520,
        dungeon_draw_context=0x06071654,
    ),
)


@cache
def save_text_asset() -> StaticTextAsset:
    return load_static_asset(
        Path("static") / "SAVE.BIN.static.json",
        SAVE_TARGET.path,
    )


@cache
def dungeon_source() -> bytes:
    return (EXTRACTED_ROOT / DUNGEON_SOURCE_PATH).read_bytes()


@cache
def dungeon_records():
    codes, advances = load_atlas_metrics()
    return build_saveload_dungeon_records(
        load_static_asset(
            DUNGEON_ASSET_PATH,
            DUNGEON_SOURCE_PATH,
        ),
        dungeon_source(),
        codes,
        advances,
    )


def block_data(asset: StaticTextAsset, name: str) -> bytes:
    try:
        block = asset.blocks[name]
    except KeyError as error:
        raise ValueError(f"SAVE.BIN static text is missing block {name!r}") from error
    return asset.data[block.offset : block.offset + block.size]


def block_words(asset: StaticTextAsset, name: str) -> tuple[int, ...]:
    data = block_data(asset, name)
    return struct.unpack(f">{len(data) // 2}H", data)


def atlas_width_table() -> bytes:
    codes, advances = load_atlas_metrics()
    limit = max(codes.values()) + 1
    table = bytearray(limit)
    for character, code in codes.items():
        width = advances[character]
        previous = table[code]
        if previous not in (0, width):
            raise ValueError(f"FONT16 atlas code {code} has conflicting advances")
        table[code] = width
    return bytes(table)


def location_records() -> tuple[tuple[int, ...], ...]:
    records = []
    for name in LOCATION_BLOCKS:
        words = block_words(save_text_asset(), name)
        if len(words) != LOCATION_CELLS:
            raise ValueError(f"SAVE.BIN {name} must contain {LOCATION_CELLS} cells")
        records.append(words)
    return tuple(records)


def used_location_cells(record: tuple[int, ...], name: str) -> int:
    try:
        count = record.index(PADDING_CODE)
    except ValueError:
        return len(record)
    if any(word != PADDING_CODE for word in record[count:]):
        raise ValueError(f"SAVE.BIN {name} has non-trailing padding")
    return count


def build_source() -> str:
    widths = atlas_width_table()
    locations = tuple(code for record in location_records() for code in record)
    dungeon_rows = "".join(
        f"    .word {', '.join(str(code) for code in record)}\n"
        for record in dungeon_records()
    )
    return (
        SOURCE_PATH.read_text(encoding="utf-8")
        + "\n.align 4\ntext_scratch:\n"
        + "    .long 0, 0\n"
        + "width_table:\n"
        + f"    .byte {', '.join(str(width) for width in widths)}\n"
        + ".align 2\nlocation_table:\n"
        + f"    .word {', '.join(str(code) for code in locations)}\n"
        + ".align 2\ndungeon_table:\n"
        + dungeon_rows
    )


def build_ui_cave(spec: UISpec) -> AsmBlob:
    widths = atlas_width_table()
    cave = assemble(
        build_source(),
        spec.cave_address,
        symbols={
            "ORIGINAL_BLITTER": spec.original_blitter,
            "PADDING_CODE": PADDING_CODE,
            "WIDTH_LIMIT": len(widths),
            "DUNGEON_INDEX": spec.dungeon_index_address,
            "DUNGEON_RECORD_BYTES": SAVELOAD_DUNGEON_CELLS * 2,
            "DUNGEON_RECORD_CELLS": SAVELOAD_DUNGEON_CELLS,
            "DRAW_TEXT": spec.dungeon_draw_text,
            "DRAW_CONTEXT": spec.dungeon_draw_context,
        },
    )
    if cave.warnings:
        details = "\n  ".join(cave.warnings)
        raise ValueError(f"{spec.target.name} UI cave warnings:\n  {details}")
    if spec.cave_offset + len(cave) > FREE_WINDOW_END:
        raise ValueError(f"{spec.target.name} UI cave exceeds the zero window")
    return cave


def instruction_patch(
    spec: UISpec,
    name: str,
    offset: int,
    expected: int,
    source: str,
) -> BytePatch:
    replacement = assemble(source, spec.target.load_address + offset)
    if len(replacement) != 2 or replacement.warnings:
        raise ValueError(f"{spec.target.name} {name} is not one safe instruction")
    return BytePatch(
        name=name,
        address=spec.target.load_address + offset,
        expected=expected.to_bytes(2, "big"),
        replacement=replacement,
    )


def storage_selector_patches(
    spec: UISpec, target_source: bytes
) -> tuple[DigestPatch, ...]:
    source = spec.target.path.as_posix()
    validate_saveload_image_records(target_source, source)
    return tuple(
        DigestPatch(
            name=f"{source.lower().removesuffix('.bin')}_storage_{record.key}",
            address=spec.target.load_address + record.asset.offset,
            expected_sha256=record.expected_sha256,
            replacement=build_saveload_image(target_source, record),
        )
        for record in saveload_image_records(source)
    )


def build_ui_patch(spec: UISpec) -> PatchGroup:
    cave = build_ui_cave(spec)
    source = spec.target.path.name.lower().removesuffix(".bin")
    target_source = (EXTRACTED_ROOT / spec.target.path).read_bytes()
    validate_dungeon_prefix_mirror(
        dungeon_source(),
        target_source,
        spec.dungeon_table_offset,
        spec.target.name,
    )
    locations = location_records()
    location_address = cave.labels["location_table"]
    home_pool, office_pool, array_pool = spec.location_pool_offsets
    home_count, office_count, stride, array_count = spec.location_instruction_offsets
    patches = [
        BytePatch(
            name=f"{source}_ui_cave",
            address=spec.cave_address,
            expected=bytes(len(cave)),
            replacement=cave,
        ),
        BytePatch(
            name=f"{source}_text_blitter",
            address=spec.target.load_address + spec.blitter_pool_offset,
            expected=spec.original_blitter.to_bytes(4, "big"),
            replacement=spec.cave_address.to_bytes(4, "big"),
        ),
        instruction_patch(
            spec, f"{source}_text_advance", spec.advance_offset, 0x7110, "add r0,r1"
        ),
        BytePatch(
            name=f"{source}_home_location_pointer",
            address=spec.target.load_address + home_pool,
            expected=spec.old_location_address.to_bytes(4, "big"),
            replacement=location_address.to_bytes(4, "big"),
        ),
        BytePatch(
            name=f"{source}_office_location_pointer",
            address=spec.target.load_address + office_pool,
            expected=(spec.old_location_address + 4).to_bytes(4, "big"),
            replacement=(location_address + LOCATION_CELLS * 2).to_bytes(4, "big"),
        ),
        BytePatch(
            name=f"{source}_location_array_pointer",
            address=spec.target.load_address + array_pool,
            expected=(spec.old_location_address + 14).to_bytes(4, "big"),
            replacement=(location_address + LOCATION_CELLS * 4).to_bytes(4, "big"),
        ),
        instruction_patch(
            spec,
            f"{source}_home_location_count",
            home_count,
            0xE502,
            f"mov #{used_location_cells(locations[0], LOCATION_BLOCKS[0])},r5",
        ),
        instruction_patch(
            spec,
            f"{source}_office_location_count",
            office_count,
            0xE505,
            f"mov #{used_location_cells(locations[1], LOCATION_BLOCKS[1])},r5",
        ),
        instruction_patch(
            spec,
            f"{source}_location_stride",
            stride,
            0xE108,
            f"mov #{LOCATION_CELLS * 2},r1",
        ),
        instruction_patch(
            spec,
            f"{source}_location_array_count",
            array_count,
            0xE504,
            f"mov #{LOCATION_CELLS},r5",
        ),
        BytePatch(
            name=f"{source}_empty_label",
            address=spec.target.load_address + spec.empty_offset,
            expected=bytes.fromhex("01 cd 00 00 01 27 00 00 01 db"),
            replacement=block_data(save_text_asset(), "empty"),
        ),
        CodePatch(
            name=f"{source}_dungeon_location_hook",
            address=spec.target.load_address + spec.dungeon_hook_offset,
            original_source=(
                "mov.l r8,@-r15\n"
                "mov.l r9,@-r15\n"
                "mov.l r10,@-r15\n"
                "mov.l r11,@-r15\n"
                "mov.l r12,@-r15\n"
                "mov.l r13,@-r15\n"
            ),
            replacement_source=("mov.l =DUNGEON_DRAW_ENTRY,r0\njmp @r0\nnop\n.pool\n"),
            symbols={"DUNGEON_DRAW_ENTRY": cave.labels["dungeon_draw_entry"]},
        ),
    ]
    if spec.prompt_sites and len(spec.prompt_sites) != len(PROMPT_BLOCKS):
        raise ValueError(f"{spec.target.name} prompt-site count does not match text")
    patches.extend(
        BytePatch(
            name=f"{source}_prompt_{index}",
            address=spec.target.load_address + offset,
            expected=expected,
            replacement=block_data(save_text_asset(), PROMPT_BLOCKS[index]),
        )
        for index, (offset, expected) in enumerate(spec.prompt_sites)
    )
    patches.extend(storage_selector_patches(spec, target_source))
    return PatchGroup(
        capability="saveload_ui",
        target=spec.target,
        patches=tuple(patches),
    )


def build_patch_groups(_context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    for name_spec, ui_spec in zip(NAME_STRIP_SPECS, UI_SPECS):
        name_end = name_spec.cave_offset + len(build_name_cave(name_spec))
        if name_spec.target != ui_spec.target or ui_spec.cave_offset < name_end:
            raise ValueError(
                f"{ui_spec.target.name} UI cave overlaps its name-strip cave"
            )
    return tuple(map(build_ui_patch, UI_SPECS))
