"""Replace equipment action and comparison labels with proportional FONT8."""

import struct
from dataclasses import dataclass
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.equipment_ui.model import EquipmentUI, load_config
from engine.script.generated_asset import load_runtime_ui
from engine.script.patching import BinaryTarget, BytePatch, CodePatch, PatchGroup
from engine.script.sh2 import render_template
from engine.script.text_render.font8_metrics import load_metrics
from tools.sh2asm import assemble

BASE = 0x06020000
BASE_LABEL_ORIGINAL_X = -48
DERIVED_LABEL_ORIGINAL_X = 0
ROW_HEIGHT = 14
DRAWER_SOURCE = Path(__file__).with_name("asm") / "label_drawer.s"


@dataclass(frozen=True)
class SelectionSites:
    recommend_start: int
    unequip_start: int
    recommend_span: int
    unequip_span: int
    top: int
    bottom: tuple[int, int]


@dataclass(frozen=True)
class EquipmentSpec:
    target: BinaryTarget
    cave_file: int
    label_pointer: int
    bitmap_calls: tuple[int, int]
    base_value_x_site: int
    stock_drawer: int
    glyph_drawer: int
    selection_sites: SelectionSites


SPECS = (
    EquipmentSpec(
        BinaryTarget("EVENT.BIN", Path("EVENT.BIN"), BASE),
        0x05A0,
        0x060598A8,
        (0x06058A92, 0x06058B4A),
        0x060593E0,
        0x060584E4,
        0x0605839C,
        SelectionSites(
            0x06059768,
            0x06059770,
            0x06059778,
            0x06059780,
            0x0605980A,
            (0x0605980C, 0x0605983C),
        ),
    ),
    EquipmentSpec(
        BinaryTarget("NORMCOM.BIN", Path("NORMCOM.BIN"), BASE),
        0x11A0,
        0x0603AFBC,
        (0x0603A1BA, 0x0603A272),
        0x0603AAF4,
        0x06039C0C,
        0x06039AC4,
        SelectionSites(
            0x0603AE7C,
            0x0603AE84,
            0x0603AE8C,
            0x0603AE94,
            0x0603AF1E,
            (0x0603AF20, 0x0603AF50),
        ),
    ),
)


def signed_byte(value: int, context: str) -> int:
    if not -128 <= value <= 127:
        raise ValueError(f"{context}: {value} is outside an SH-2 signed byte")
    return value


def adjustment(register: str, value: int, context: str) -> str:
    value = signed_byte(value, context)
    return f"add #{value}, {register}" if value else ""


def label_position(label, original_x: int, row: int, context: str) -> tuple[int, int]:
    return (
        signed_byte(original_x + label.offset.x, f"{context}.offset_x"),
        signed_byte(row * ROW_HEIGHT + label.offset.y, f"{context}.offset_y"),
    )


def encoded(text: str, widths: bytes, codes: dict[str, int]) -> str:
    output = []
    for character in text:
        try:
            code = codes[character]
        except KeyError as error:
            raise ValueError(
                f"unsupported equipment-label character {character!r}"
            ) from error
        if code == 0xFF or not widths[code]:
            raise ValueError(f"invalid equipment-label glyph {code}")
        output.append(code)
    if len(output) > 16:
        raise ValueError(f"equipment label exceeds 16 glyphs: {text!r}")
    return ", ".join(str(code) for code in (*output, 0xFF))


def drawer_values(
    ui: EquipmentUI,
    widths: bytes,
    codes: dict[str, int],
) -> dict[str, object]:
    labels = ui.labels
    base_positions = tuple(
        label_position(label, BASE_LABEL_ORIGINAL_X, row, f"base_stats[{row}]")
        for row, label in enumerate(ui.base)
    )
    derived_positions = tuple(
        label_position(label, DERIVED_LABEL_ORIGINAL_X, row, f"derived_stats[{row}]")
        for row, label in enumerate(ui.derived)
    )
    values: dict[str, object] = {
        "RECOMMEND_X_ADJUST": adjustment(
            "r10", ui.recommend.offset.x, "actions.recommend.offset_x"
        ),
        "RECOMMEND_Y_ADJUST": adjustment(
            "r11", ui.recommend.offset.y, "actions.recommend.offset_y"
        ),
        "UNEQUIP_X_ADJUST": adjustment(
            "r10", ui.unequip.offset.x, "actions.unequip.offset_x"
        ),
        "UNEQUIP_Y_ADJUST": adjustment(
            "r11", ui.unequip.offset.y, "actions.unequip.offset_y"
        ),
        "S_RECOMMEND": encoded(labels.recommend, widths, codes),
        "S_UNEQUIP": encoded(labels.unequip, widths, codes),
        "S_ST": encoded(labels.base[0], widths, codes),
        "S_IN": encoded(labels.base[1], widths, codes),
        "S_MA": encoded(labels.base[2], widths, codes),
        "S_VI": encoded(labels.base[3], widths, codes),
        "S_AG": encoded(labels.base[4], widths, codes),
        "S_LU": encoded(labels.base[5], widths, codes),
        "S_SWORD_ATTACK": encoded(labels.derived[0], widths, codes),
        "S_SWORD_ACCURACY": encoded(labels.derived[1], widths, codes),
        "S_GUN_ATTACK": encoded(labels.derived[2], widths, codes),
        "S_GUN_ACCURACY": encoded(labels.derived[3], widths, codes),
        "S_DEFENSE": encoded(labels.derived[4], widths, codes),
        "S_EVASION": encoded(labels.derived[5], widths, codes),
        "S_MAGIC_POWER": encoded(labels.derived[6], widths, codes),
        "S_MAGIC_EFFECT": encoded(labels.derived[7], widths, codes),
        "WIDTHS": ", ".join(str(width) for width in widths),
    }
    for index, (x, y) in enumerate(base_positions):
        values[f"BASE_{index}_X"] = x
        values[f"BASE_{index}_Y"] = y
    for index, (x, y) in enumerate(derived_positions):
        values[f"DERIVED_{index}_X"] = x
        values[f"DERIVED_{index}_Y"] = y
    return values


def build_drawer(
    address: int,
    spec: EquipmentSpec,
    ui: EquipmentUI,
    widths: bytes,
    codes: dict[str, int],
) -> bytes:
    source = render_template(DRAWER_SOURCE, drawer_values(ui, widths, codes))
    blob = assemble(
        source,
        address,
        symbols={
            "STOCK_DRAW": spec.stock_drawer,
            "GLYPH": spec.glyph_drawer,
        },
    )
    if blob.warnings:
        raise ValueError(
            f"{spec.target.name}: equipment-label warnings: {blob.warnings}"
        )
    return bytes(blob)


def instruction_patch(
    name: str,
    site: int,
    original: str,
    replacement: str,
) -> CodePatch | None:
    patch = CodePatch(name, site, original, replacement)
    if len(patch.expected) != 2:
        raise ValueError(f"{name}: geometry patch must use one instruction")
    return None if patch.expected == patch.replacement else patch


def selection_patches(
    spec: EquipmentSpec,
    ui: EquipmentUI,
) -> tuple[CodePatch, ...]:
    recommend = ui.recommend.selection_box
    unequip = ui.unequip.selection_box
    top = signed_byte(-6 + recommend.offset.y, "selection_box.offset_y")
    bottom = signed_byte(top + recommend.height - 1, "selection_box.height")
    values = (
        (
            "recommend_selection_x",
            spec.selection_sites.recommend_start,
            "mov #8,r12",
            f"mov #{signed_byte(8 + recommend.offset.x, 'recommend selection x')},r12",
        ),
        (
            "unequip_selection_x",
            spec.selection_sites.unequip_start,
            "mov #60,r12",
            f"mov #{signed_byte(60 + unequip.offset.x, 'unequip selection x')},r12",
        ),
        (
            "recommend_selection_width",
            spec.selection_sites.recommend_span,
            "mov #32,r12",
            f"mov #{recommend.width - 8},r12",
        ),
        (
            "unequip_selection_width",
            spec.selection_sites.unequip_span,
            "mov #24,r12",
            f"mov #{unequip.width - 8},r12",
        ),
        (
            "selection_top",
            spec.selection_sites.top,
            "mov #-6,r8",
            f"mov #{top},r8",
        ),
    )
    patches = [
        patch
        for name, site, original, replacement in values
        if (patch := instruction_patch(name, site, original, replacement))
    ]
    for index, site in enumerate(spec.selection_sites.bottom):
        register = "r4" if index == 0 else "r12"
        patch = instruction_patch(
            f"selection_bottom_{index}",
            site,
            f"mov #9,{register}",
            f"mov #{bottom},{register}",
        )
        if patch:
            patches.append(patch)
    return tuple(patches)


def build_group(
    spec: EquipmentSpec,
    ui: EquipmentUI | None = None,
    widths: bytes | None = None,
    codes: dict[str, int] | None = None,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> PatchGroup:
    ui = ui or load_config(load_runtime_ui(context))
    if widths is None or codes is None:
        widths, codes = load_metrics(context.font_generated_root / "font8_metrics.json")
    address = BASE + spec.cave_file
    drawer = build_drawer(address, spec, ui, widths, codes)
    if spec.target.name == "EVENT.BIN" and spec.cave_file + len(drawer) > 0x0900:
        raise ValueError("EVENT.BIN equipment labels overlap the BUY/SELL cave")
    if spec.target.name == "NORMCOM.BIN" and spec.cave_file + len(drawer) > 0x1800:
        raise ValueError("NORMCOM.BIN equipment labels overlap the status atlas")

    patches = [
        BytePatch("label_drawer", address, bytes(len(drawer)), drawer),
        BytePatch(
            "label_drawer_pointer",
            spec.label_pointer,
            struct.pack(">I", spec.stock_drawer),
            struct.pack(">I", address),
        ),
        CodePatch(
            "base_value_alignment",
            spec.base_value_x_site,
            "mov #-32,r6",
            "mov #-31,r6",
        ),
    ]
    patches.extend(selection_patches(spec, ui))
    original_calls = ("jsr @r10", "jsr @r0")
    for index, (site, original) in enumerate(zip(spec.bitmap_calls, original_calls)):
        patches.append(
            CodePatch(
                f"suppress_stock_heading_{index}",
                site,
                original,
                "nop",
                allow_trailing_delay_slot=True,
            )
        )
    return PatchGroup("equipment_ui", spec.target, tuple(patches))


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    ui = load_config(load_runtime_ui(context))
    widths, codes = load_metrics(context.font_generated_root / "font8_metrics.json")
    return tuple(build_group(spec, ui, widths, codes, context) for spec in SPECS)
