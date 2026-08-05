"""Relocate generated SAVE/LOAD static text and patch its consumers."""

from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.patching import BytePatch, PatchGroup
from engine.script.saveload.load import LOAD_TARGET
from engine.script.saveload.names import SAVE_TARGET
from engine.script.saveload.ui import UI_SPECS, build_ui_cave, save_text_asset
from engine.script.static_text import StaticTextAsset, load_static_asset
from tools.sh2asm import assemble

FREE_WINDOW_END = 0x6500
SMALL_ROWS = 3
WARNING_FIRST_ROWS = 4
WARNING_SECOND_ROWS = 6


def align_up(value: int, alignment: int = 4) -> int:
    return (value + alignment - 1) & -alignment


def instruction_patch(
    target,
    name: str,
    offset: int,
    expected: int,
    source: str,
) -> BytePatch:
    replacement = assemble(source, target.load_address + offset)
    if len(replacement) != 2 or replacement.warnings:
        raise ValueError(f"{target.name} {name} is not one safe instruction")
    return BytePatch(
        name=name,
        address=target.load_address + offset,
        expected=expected.to_bytes(2, "big"),
        replacement=replacement,
    )


def data_start(
    target,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> int:
    ui_spec = next(spec for spec in UI_SPECS if spec.target == target)
    return align_up(ui_spec.cave_offset + len(build_ui_cave(ui_spec, context)))


def require_blocks(asset: StaticTextAsset, expected: set[str], source: str) -> None:
    if not expected <= set(asset.blocks):
        names = ", ".join(sorted(expected))
        raise ValueError(f"{source} static text is missing required blocks: {names}")


def fixed_row_cells(word_count: int, rows: int, name: str) -> int:
    cells, remainder = divmod(word_count, rows)
    if remainder or not 1 <= cells <= 0x7F:
        raise ValueError(f"{name} is not a valid {rows}-row static-text block")
    return cells


def relocate_blocks(
    asset: StaticTextAsset,
    names: tuple[str, ...],
) -> tuple[bytes, dict[str, int]]:
    data = bytearray()
    offsets = {}
    for name in names:
        data.extend(bytes((-len(data)) % 4))
        offsets[name] = len(data)
        block = asset.blocks[name]
        data.extend(asset.data[block.offset : block.offset + block.size])
    return bytes(data), offsets


def build_save_patch(
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> PatchGroup:
    asset = save_text_asset(context)
    system_blocks = (
        "save_write_failure",
        "save_capacity_error_0",
        "save_capacity_error_1",
        "save_capacity_failure",
    )
    require_blocks(asset, set(system_blocks), "SAVE.BIN")
    failure_block = asset.blocks["save_write_failure"]
    capacity_0 = asset.blocks["save_capacity_error_0"]
    capacity_1 = asset.blocks["save_capacity_error_1"]
    capacity_failure = asset.blocks["save_capacity_failure"]
    failure_cells = fixed_row_cells(
        failure_block.word_count,
        SMALL_ROWS,
        "SAVE.BIN save_write_failure",
    )
    capacity_failure_cells = fixed_row_cells(
        capacity_failure.word_count,
        SMALL_ROWS,
        "SAVE.BIN save_capacity_failure",
    )
    for name, block in (
        ("save_capacity_error_0", capacity_0),
        ("save_capacity_error_1", capacity_1),
    ):
        if not 1 <= block.word_count <= 0x7F:
            raise ValueError(f"SAVE.BIN {name} has an invalid cell count")

    system_data, block_offsets = relocate_blocks(asset, system_blocks)
    offset = data_start(SAVE_TARGET, context)
    address = SAVE_TARGET.load_address + offset
    if offset + len(system_data) > FREE_WINDOW_END:
        raise ValueError("SAVE.BIN static-text data exceeds the zero window")
    patches = [
        BytePatch(
            name="save_system_data",
            address=address,
            expected=bytes(len(system_data)),
            replacement=system_data,
        ),
        BytePatch(
            name="save_failure_pointer",
            address=SAVE_TARGET.load_address + 0x87D8,
            expected=(0x06070658).to_bytes(4, "big"),
            replacement=(address + block_offsets["save_write_failure"]).to_bytes(
                4, "big"
            ),
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_failure_stride",
            0x8708,
            0xE116,
            f"mov #{failure_cells * 2},r1",
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_failure_count",
            0x8722,
            0xE50B,
            f"mov #{failure_cells},r5",
        ),
        BytePatch(
            name="save_capacity_line_0_pointer_a",
            address=SAVE_TARGET.load_address + 0x8DE4,
            expected=(0x0607076A).to_bytes(4, "big"),
            replacement=(address + block_offsets["save_capacity_error_0"]).to_bytes(
                4, "big"
            ),
        ),
        BytePatch(
            name="save_capacity_line_1_pointer_a",
            address=SAVE_TARGET.load_address + 0x8DE8,
            expected=(0x06070788).to_bytes(4, "big"),
            replacement=(address + block_offsets["save_capacity_error_1"]).to_bytes(
                4, "big"
            ),
        ),
        BytePatch(
            name="save_capacity_line_0_pointer_b",
            address=SAVE_TARGET.load_address + 0x8ED4,
            expected=(0x0607076A).to_bytes(4, "big"),
            replacement=(address + block_offsets["save_capacity_error_0"]).to_bytes(
                4, "big"
            ),
        ),
        BytePatch(
            name="save_capacity_line_1_pointer_b",
            address=SAVE_TARGET.load_address + 0x8ED8,
            expected=(0x06070788).to_bytes(4, "big"),
            replacement=(address + block_offsets["save_capacity_error_1"]).to_bytes(
                4, "big"
            ),
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_capacity_line_0_count_a",
            0x8D7C,
            0xE50F,
            f"mov #{capacity_0.word_count},r5",
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_capacity_line_1_count_a",
            0x8D8E,
            0xE511,
            f"mov #{capacity_1.word_count},r5",
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_capacity_line_0_count_b",
            0x8E6A,
            0xE50F,
            f"mov #{capacity_0.word_count},r5",
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_capacity_line_1_count_b",
            0x8E7C,
            0xE511,
            f"mov #{capacity_1.word_count},r5",
        ),
        BytePatch(
            name="save_capacity_failure_pointer",
            address=SAVE_TARGET.load_address + 0x9C10,
            expected=(0x060708DC).to_bytes(4, "big"),
            replacement=(address + block_offsets["save_capacity_failure"]).to_bytes(
                4, "big"
            ),
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_capacity_failure_stride",
            0x9B38,
            0xE116,
            f"mov #{capacity_failure_cells * 2},r1",
        ),
        instruction_patch(
            SAVE_TARGET,
            "save_capacity_failure_count",
            0x9B52,
            0xE50B,
            f"mov #{capacity_failure_cells},r5",
        ),
    ]
    return PatchGroup("saveload_ui", SAVE_TARGET, tuple(patches))


def build_load_patch(
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> PatchGroup:
    asset = load_static_asset(
        Path("static") / "LOAD.BIN.static.json",
        LOAD_TARGET.path,
        context.text_generated_root,
        context.extracted_root,
    )
    expected_blocks = {
        "start_without_save_warning",
        "insufficient_free_space_instructions",
        "save_capacity_error_0",
        "save_capacity_error_1",
        "load_failure",
    }
    require_blocks(asset, expected_blocks, "LOAD.BIN")
    start_warning = asset.blocks["start_without_save_warning"]
    space_warning = asset.blocks["insufficient_free_space_instructions"]
    capacity_0 = asset.blocks["save_capacity_error_0"]
    capacity_1 = asset.blocks["save_capacity_error_1"]
    failure = asset.blocks["load_failure"]

    warning_cells = fixed_row_cells(
        start_warning.word_count,
        WARNING_FIRST_ROWS,
        "LOAD.BIN start_without_save_warning",
    )
    if (
        fixed_row_cells(
            space_warning.word_count,
            WARNING_SECOND_ROWS,
            "LOAD.BIN insufficient_free_space_instructions",
        )
        != warning_cells
    ):
        raise ValueError("LOAD.BIN warning records have different row widths")
    if space_warning.offset != start_warning.offset + start_warning.size:
        raise ValueError("LOAD.BIN warning records must be contiguous")
    failure_cells = fixed_row_cells(
        failure.word_count,
        SMALL_ROWS,
        "LOAD.BIN load_failure",
    )
    for name, block in (
        ("save_capacity_error_0", capacity_0),
        ("save_capacity_error_1", capacity_1),
    ):
        if not 1 <= block.word_count <= 0x7F:
            raise ValueError(f"LOAD.BIN {name} has an invalid cell count")

    offset = data_start(LOAD_TARGET, context)
    address = LOAD_TARGET.load_address + offset
    if offset + len(asset.data) > FREE_WINDOW_END:
        raise ValueError("LOAD.BIN static-text data exceeds the zero window")

    patches = [
        BytePatch(
            name="load_system_data",
            address=address,
            expected=bytes(len(asset.data)),
            replacement=asset.data,
        ),
        BytePatch(
            name="load_warning_pointer",
            address=LOAD_TARGET.load_address + 0x80E4,
            expected=(0x0602B01E).to_bytes(4, "big"),
            replacement=(address + start_warning.offset).to_bytes(4, "big"),
        ),
        instruction_patch(
            LOAD_TARGET,
            "load_capacity_overlay_count",
            0x7FBA,
            0xE503,
            "mov #0,r5",
        ),
        BytePatch(
            name="load_capacity_line_0_pointer",
            address=LOAD_TARGET.load_address + 0x8660,
            expected=(0x0602B1BE).to_bytes(4, "big"),
            replacement=(address + capacity_0.offset).to_bytes(4, "big"),
        ),
        BytePatch(
            name="load_capacity_line_1_pointer",
            address=LOAD_TARGET.load_address + 0x8664,
            expected=(0x0602B1DC).to_bytes(4, "big"),
            replacement=(address + capacity_1.offset).to_bytes(4, "big"),
        ),
        instruction_patch(
            LOAD_TARGET,
            "load_capacity_line_0_count",
            0x85F4,
            0xE50F,
            f"mov #{capacity_0.word_count},r5",
        ),
        instruction_patch(
            LOAD_TARGET,
            "load_capacity_line_1_count",
            0x8606,
            0xE511,
            f"mov #{capacity_1.word_count},r5",
        ),
        BytePatch(
            name="load_failure_pointer",
            address=LOAD_TARGET.load_address + 0x8798,
            expected=(0x0602B1FE).to_bytes(4, "big"),
            replacement=(address + failure.offset).to_bytes(4, "big"),
        ),
        instruction_patch(
            LOAD_TARGET,
            "load_failure_stride",
            0x8690,
            0xE116,
            f"mov #{failure_cells * 2},r1",
        ),
        instruction_patch(
            LOAD_TARGET,
            "load_failure_count",
            0x86AA,
            0xE50B,
            f"mov #{failure_cells},r5",
        ),
    ]
    for offset_ in (0x7F3C, 0x7F74, 0x7FC4):
        patches.append(
            instruction_patch(
                LOAD_TARGET,
                f"load_warning_stride_{offset_:04x}",
                offset_,
                0xE128,
                f"mov #{warning_cells * 2},r1",
            )
        )
    for offset_ in (0x7F4C, 0x7F84, 0x7FD4):
        patches.append(
            instruction_patch(
                LOAD_TARGET,
                f"load_warning_count_{offset_:04x}",
                offset_,
                0xE514,
                f"mov #{warning_cells},r5",
            )
        )
    return PatchGroup("saveload_ui", LOAD_TARGET, tuple(patches))


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    return build_save_patch(context), build_load_patch(context)
