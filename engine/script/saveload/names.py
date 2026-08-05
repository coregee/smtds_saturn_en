"""Render saved ASCII names into SAVE/LOAD's scratch strips."""

from dataclasses import dataclass
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.name.model import (
    byte_to_advance_table,
    byte_to_atlas_table,
    load_atlas_metrics,
    load_font8_codes,
)
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from engine.script.saveload.load import (
    CAVE_OFFSET as LOAD_REBUILD_OFFSET,
)
from engine.script.saveload.load import (
    LOAD_TARGET,
)
from engine.script.saveload.load import (
    build_cave as build_load_name_cave,
)
from tools.sh2asm import AsmBlob, assemble

FONT16_BASE = 0x0021A000
FREE_WINDOW_END = 0x6500
JOINED_SOURCE_PATH = Path(__file__).with_name("name_strip.s")
SAVE_NAME_CELLS = 8
SAVE_NAME_WIDTH = SAVE_NAME_CELLS * 16
SAVE_NAME_BYTES = 8 * 2 + 1
SAVE_NAME_BUFFER_BYTES = SAVE_NAME_BYTES + 1

SAVE_TARGET = BinaryTarget("SAVE.BIN", Path("SAVE.BIN"), 0x06020000)


@dataclass(frozen=True)
class NameStripSpec:
    target: BinaryTarget
    cave_offset: int
    source_path: Path
    copy_glyph: int
    read_sites: tuple[tuple[int, int], ...]
    draw_pool_offsets: tuple[int, ...]
    draw_counts: tuple[tuple[int, int], ...]
    template_cells: tuple[tuple[int, int], ...] = ()

    @property
    def cave_address(self) -> int:
        return self.target.load_address + self.cave_offset


SPECS = (
    NameStripSpec(
        target=SAVE_TARGET,
        cave_offset=0x40,
        source_path=JOINED_SOURCE_PATH,
        copy_glyph=0x0602AFDC,
        read_sites=(
            (0xB0EA, 0x6725),
            (0xB122, 0x6725),
            (0xB03C, 0x6725),
            (0xB074, 0x6725),
            (0xB1A4, 0x6D25),
            (0xB204, 0x6C25),
        ),
        draw_pool_offsets=(0xB0CC, 0xB168, 0xB304),
        draw_counts=((0xB1F0, 8), (0xB248, 0)),
        template_cells=((0x51B70, 0x075B), (0x51B78, 0x075F)),
    ),
    NameStripSpec(
        target=LOAD_TARGET,
        cave_offset=0x440,
        source_path=JOINED_SOURCE_PATH,
        copy_glyph=0x0602AA60,
        read_sites=(
            (0xAAC0, 0x6725),
            (0xAAF8, 0x6725),
            (0xAB6E, 0x6725),
            (0xABA6, 0x6725),
            (0xAC1E, 0x6D25),
            (0xAC7E, 0x6C25),
        ),
        draw_pool_offsets=(0xAB50, 0xABE8, 0xAD78),
        draw_counts=((0xAC6A, 8), (0xACC2, 0)),
    ),
)


def build_source(
    spec: NameStripSpec,
    atlas_metrics: tuple[dict[str, int], dict[str, int]] | None = None,
) -> str:
    source = spec.source_path.read_text(encoding="utf-8")
    if atlas_metrics is None:
        atlas_metrics = load_atlas_metrics()
    atlas_codes, advances = atlas_metrics
    codes = byte_to_atlas_table(atlas_codes)
    widths = byte_to_advance_table(advances)
    mutable = ""
    layout_note = ""
    if spec.source_path == JOINED_SOURCE_PATH:
        max_width = max(widths) * 16 + widths[ord(" ")]
        scale_map_bytes = max_width + 16
        if max_width > 0xFF or scale_map_bytes > 0xFF:
            raise ValueError("SAVE joined-name scale map exceeds byte indexing")
        mutable = (
            "\n.align 4\nname_buffer:\n"
            + f"    .byte {', '.join('0' for _ in range(SAVE_NAME_BUFFER_BYTES))}\n"
            + "name_scale_map:\n"
            + f"    .byte {', '.join('0' for _ in range(scale_map_bytes))}\n"
        )
        layout_note = f"\n; joined source width <= {max_width}px\n"
    return (
        source
        + mutable
        + layout_note
        + ("\n.align 4\nname_cursor:\n    .long 0\n" if not mutable else "")
        + ".align 2\nbyte_to_atlas:\n"
        + f"    .word {', '.join(str(code) for code in codes)}\n"
        + "byte_to_width:\n"
        + f"    .byte {', '.join(str(width) for width in widths)}\n"
    )


def build_cave(
    spec: NameStripSpec,
    atlas_metrics: tuple[dict[str, int], dict[str, int]] | None = None,
) -> AsmBlob:
    symbols = {"FONT16_BASE": FONT16_BASE}
    if spec.source_path == JOINED_SOURCE_PATH:
        symbols["NAME_WIDTH"] = SAVE_NAME_WIDTH
    cave = assemble(
        build_source(spec, atlas_metrics),
        spec.cave_address,
        symbols=symbols,
    )
    if cave.warnings:
        details = "\n  ".join(cave.warnings)
        raise ValueError(f"{spec.target.name} name-strip warnings:\n  {details}")
    if spec.cave_offset + len(cave) > FREE_WINDOW_END:
        raise ValueError(f"{spec.target.name} name-strip cave exceeds the zero window")
    return cave


def read_patch(target: BinaryTarget, offset: int, original: int) -> BytePatch:
    if original & 0xF00F != 0x6005:
        raise ValueError(f"{target.name} read at {offset:#x} is not mov.w @Rm+,Rn")
    source = target.path.name.lower().removesuffix(".bin")
    return BytePatch(
        name=f"{source}_name_byte_read_{offset:04x}",
        address=target.load_address + offset,
        expected=original.to_bytes(2, "big"),
        replacement=((original & 0xFFF0) | 0x0004).to_bytes(2, "big"),
    )


def build_patch_group(
    spec: NameStripSpec,
    atlas_metrics: tuple[dict[str, int], dict[str, int]] | None = None,
) -> PatchGroup:
    cave = build_cave(spec, atlas_metrics)
    source = spec.target.path.name.lower().removesuffix(".bin")
    patches = [
        BytePatch(
            name=f"{source}_name_strip_cave",
            address=spec.cave_address,
            expected=bytes(len(cave)),
            replacement=cave,
        )
    ]
    patches.extend(
        read_patch(spec.target, offset, original)
        for offset, original in spec.read_sites
    )
    patches.extend(
        BytePatch(
            name=f"{source}_name_draw_pool_{offset:04x}",
            address=spec.target.load_address + offset,
            expected=spec.copy_glyph.to_bytes(4, "big"),
            replacement=spec.cave_address.to_bytes(4, "big"),
        )
        for offset in spec.draw_pool_offsets
    )
    for offset, count in spec.draw_counts:
        if not 0 <= count <= 0x7F:
            raise ValueError(f"{spec.target.name} invalid name draw count {count}")
        patches.append(
            BytePatch(
                name=f"{source}_name_draw_count_{offset:04x}",
                address=spec.target.load_address + offset,
                expected=bytes.fromhex("e5 03"),
                replacement=bytes((0xE5, count)),
            )
        )
    patches.extend(
        BytePatch(
            name=f"{source}_name_template_cell_{offset:05x}",
            address=spec.target.load_address + offset,
            expected=bytes(2),
            replacement=code.to_bytes(2, "big"),
        )
        for offset, code in spec.template_cells
    )
    return PatchGroup(
        capability="name_runtime",
        target=spec.target,
        patches=tuple(patches),
    )


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    atlas_metrics = load_atlas_metrics(
        context.font_generated_root / "font16_metrics.json"
    )
    load_name_cave = build_load_name_cave(
        atlas_metrics,
        load_font8_codes(context.font_generated_root / "font8_metrics.json"),
    )
    if SPECS[1].cave_offset < LOAD_REBUILD_OFFSET + len(load_name_cave):
        raise ValueError("LOAD.BIN name-strip cave overlaps the name-row rebuild cave")
    return tuple(build_patch_group(spec, atlas_metrics) for spec in SPECS)
