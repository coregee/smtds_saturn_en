"""Follow ITEMNAME full-name pointers in pause and equipment list consumers."""

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from engine.script.context import EngineBuildContext
from engine.script.equipment_ui.model import EquipmentUI, load_config
from engine.script.generated_asset import load_runtime_ui
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from engine.script.text_render.font8_blitter import build_pixel_blitter
from engine.script.text_render.font8_metrics import font8_metrics, load_metrics
from tools.sh2asm import assemble

BASE = 0x06020000
ASM_ROOT = Path(__file__).with_name("asm")
ITEM_BASE = 0x00228C00
ITEM_FIRST_NAME = ITEM_BASE + 4
ITEM_END = 0x0022F7A0
BUY_CAVE = 0x06020900
BUY_CAVE_LIMIT = 0x06021000
BUY_HOOK = 0x06033C9C
BUY_HOOK_ORIGINAL = bytes.fromhex("2f862f962fa62fb62fc62fd6")
SHOP_RAW_GLYPH = 0x0602D734
SHOP_STOCK_GLYPH = 0x0602D868
SHOP_INVENTORY_LABEL_POINTER_SITES = (
    0x0603407C,
    0x06034168,
    0x06034264,
)
SHOP_CHARACTER_NAME_POINTER_SITES = (
    0x06034650,
    0x060347EC,
    0x060355E8,
    0x06035840,
)
SHOP_CHARACTER_NAME_WIDTH = 72
SHOP_CHARACTER_NAME_SOURCE_PTR = 0x0606254C
# Runtime signatures for the five fixed non-player CHARNAME records.  Record
# zero is the mutable player codename and must never be replaced.
SHOP_FIXED_CHARACTER_RECORDS = (
    bytes.fromhex("9f77ae9f7793a600"),
    bytes.fromhex("7cac78ed00000000"),
    bytes.fromhex("4e54cd6a4e694100"),
    bytes.fromhex("4e54cd6ad3694100"),
    bytes.fromhex("4e54cd6a49de6941"),
)


@dataclass(frozen=True)
class EquipmentSpec:
    target: BinaryTarget
    cave_offset: int
    pointer_sites: tuple[int, ...]
    stock_drawer: int
    glyph_drawer: int


SPECS = (
    EquipmentSpec(
        BinaryTarget("EVENT.BIN", Path("EVENT.BIN"), BASE),
        0x0400,
        (0x060596EC, 0x0605A6A8, 0x0605A914),
        0x060584E4,
        0x0605839C,
    ),
    EquipmentSpec(
        BinaryTarget("NORMCOM.BIN", Path("NORMCOM.BIN"), BASE),
        0x1000,
        (0x0603AE00, 0x0603BD90, 0x0603BFFC),
        0x06039C0C,
        0x06039AC4,
    ),
)


def build_equipment_drawer(
    address: int,
    spec: EquipmentSpec,
    ui: EquipmentUI,
    font8_data: tuple[bytes, dict[str, int]] | None = None,
) -> bytes:
    widths, _ = font8_data or font8_metrics()

    def adjustment(register: str, value: int, context: str) -> str:
        if not -128 <= value <= 127:
            raise ValueError(f"{context}: {value} is outside an SH-2 signed byte")
        return f"        add     #{value}, {register}" if value else ""

    offset_x = adjustment("r10", ui.item_names.x, "item_names.offset_x")
    offset_y = adjustment("r11", ui.item_names.y, "item_names.offset_y")
    template = (ASM_ROOT / "equipment_drawer.s").read_text(encoding="utf-8")
    source = template % {
        "offset_x": offset_x,
        "offset_y": offset_y,
    }
    blob = assemble(
        source,
        address,
        symbols={
            "ITEM_FIRST": ITEM_FIRST_NAME,
            "ITEM_END": ITEM_END,
            "ITEM_BASE": ITEM_BASE,
            "GLYPH": spec.glyph_drawer,
            "STOCK": spec.stock_drawer,
        },
    )
    if blob.warnings:
        raise ValueError(
            f"{spec.target.name}: ITEMNAME assembly warnings: {blob.warnings}"
        )
    return bytes(blob) + widths


def build_buy_sell_drawer(
    address: int,
    pixel_blitter: int,
    font8_data: tuple[bytes, dict[str, int]] | None = None,
) -> bytes:
    widths, _ = font8_data or font8_metrics()
    source = (ASM_ROOT / "buy_sell_drawer.s").read_text(encoding="utf-8")
    blob = assemble(
        source,
        address,
        symbols={
            "ITEM_BASE": ITEM_BASE,
            "FRAMEBUFFER_PTR": 0x06066354,
            "PIXEL": pixel_blitter,
        },
    )
    if blob.warnings:
        raise ValueError(f"EVENT.BIN: BUY/SELL assembly warnings: {blob.warnings}")
    return bytes(blob) + widths


def build_shop_panel_glyph(
    address: int,
    font8_data: tuple[bytes, dict[str, int]] | None = None,
) -> bytes:
    widths, codes = font8_data or font8_metrics()
    source = (ASM_ROOT / "shop_panel_glyph.s").read_text(encoding="utf-8")
    label = "Inv."
    width = sum(widths[codes[character]] for character in label)
    if width > 16:
        raise ValueError(f"EVENT.BIN: shop label {label!r} exceeds 16px: {width}px")
    blob = assemble(
        source,
        address,
        symbols={
            "INVENTORY_TILE_0_SIGNED": 0xD3 - 0x100,
            "INVENTORY_TILE_1_SIGNED": 0xD4 - 0x100,
            "I_CODE": codes["I"],
            "I_ADVANCE": widths[codes["I"]],
            "N_CODE": codes["n"],
            "N_ADVANCE": widths[codes["n"]],
            "V_CODE_SIGNED": codes["v"] - 0x100,
            "V_ADVANCE": widths[codes["v"]],
            "PERIOD_CODE_SIGNED": codes["."] - 0x100,
            "RAW_GLYPH": SHOP_RAW_GLYPH,
        },
    )
    if blob.warnings:
        raise ValueError(f"EVENT.BIN: shop panel assembly warnings: {blob.warnings}")
    return bytes(blob)


def build_shop_character_name_glyph(
    address: int,
    pixel_blitter: int,
    widths_address: int,
    character_data: tuple[bytes, bytes],
) -> bytes:
    """Resolve fixed shop rows to full names and retain live-name VWF."""
    matches, name_pool = character_data
    if not matches or len(matches) % 10:
        raise ValueError("EVENT.BIN: invalid shop character-name match table")
    if not name_pool:
        raise ValueError("EVENT.BIN: empty shop character-name pool")
    source = (ASM_ROOT / "shop_character_name_glyph.s").read_text(encoding="utf-8")
    symbols = {
        "WIDTHS": widths_address,
        "PIXEL": pixel_blitter,
        "RAW_GLYPH": SHOP_RAW_GLYPH,
        "PARTY_SOURCE_PTR": SHOP_CHARACTER_NAME_SOURCE_PTR,
        "STATE": address,
        "LAST_FIXED": address + 4,
        "SUPPRESS": address + 8,
        "MATCHES": address,
        "MATCH_COUNT": len(matches) // 10,
        "NAME_POOL": address,
    }
    probe = assemble(source, address, symbols=symbols)
    if probe.warnings:
        raise ValueError(
            f"EVENT.BIN: shop character-name assembly warnings: {probe.warnings}"
        )
    state_address = (address + len(probe) + 3) & ~3
    symbols["STATE"] = state_address
    symbols["LAST_FIXED"] = state_address + 4
    symbols["SUPPRESS"] = state_address + 8
    symbols["MATCHES"] = state_address + 12
    symbols["NAME_POOL"] = symbols["MATCHES"] + len(matches)
    blob = assemble(source, address, symbols=symbols)
    if blob.warnings:
        raise ValueError(
            f"EVENT.BIN: shop character-name assembly warnings: {blob.warnings}"
        )
    payload = bytearray(blob)
    payload.extend(bytes(state_address - address - len(payload)))
    payload.extend(struct.pack(">III", 8, 0xFFFFFFFF, 0))
    payload.extend(matches)
    payload.extend(name_pool)
    return bytes(payload)


def build_shop_character_name_data(
    rows: Sequence[object],
    font8_data: tuple[bytes, dict[str, int]] | None = None,
) -> tuple[bytes, bytes]:
    """Bind fixed source CHARNAME signatures to generated full English names."""
    widths, codes = font8_data or font8_metrics()
    if len(rows) != 6:
        raise ValueError("EVENT.BIN: shop character names need six generated rows")

    pool = bytearray()
    offsets: dict[int, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("record") != index:
            raise ValueError(f"EVENT.BIN: invalid shop character-name row {index}")
        name = row.get("tr")
        if not isinstance(name, str) or not name:
            raise ValueError(f"EVENT.BIN: untranslated shop character-name row {index}")
        if index == 0:
            continue
        try:
            encoded = bytes(codes[character] for character in name)
        except KeyError as error:
            raise ValueError(
                f"EVENT.BIN: shop character name {name!r} uses unsupported "
                f"FONT8 character {error.args[0]!r}"
            ) from error
        pixel_width = sum(widths[code] for code in encoded)
        if pixel_width > SHOP_CHARACTER_NAME_WIDTH:
            raise ValueError(
                f"EVENT.BIN: shop character name exceeds "
                f"{SHOP_CHARACTER_NAME_WIDTH}px ({pixel_width}px): {name!r}"
            )
        offsets[index] = len(pool)
        pool.append(pixel_width)
        pool.extend(encoded)
        pool.append(0)

    matches = bytearray()
    for index, record in enumerate(SHOP_FIXED_CHARACTER_RECORDS, start=1):
        if len(record) != 8:
            raise ValueError(
                f"EVENT.BIN: shop character signature {index} is not eight bytes"
            )
        matches.extend(record)
        matches.extend(struct.pack(">H", offsets[index]))
    return bytes(matches), bytes(pool)


def build_trampoline(address: int, target: int) -> bytes:
    source = (ASM_ROOT / "trampoline.s").read_text(encoding="utf-8")
    blob = assemble(
        source,
        address,
        symbols={"TARGET": target},
    )
    if blob.warnings:
        raise ValueError(f"trampoline assembly warnings: {blob.warnings}")
    return bytes(blob)


def build_group(
    spec: EquipmentSpec,
    ui: EquipmentUI | None = None,
    font8_data: tuple[bytes, dict[str, int]] | None = None,
    character_data: tuple[bytes, bytes] | None = None,
) -> PatchGroup:
    ui = ui or load_config()
    address = BASE + spec.cave_offset
    drawer = build_equipment_drawer(address, spec, ui, font8_data)
    patches = [BytePatch("equipment_name_cave", address, bytes(len(drawer)), drawer)]
    for site in spec.pointer_sites:
        patches.append(
            BytePatch(
                f"equipment_name_pointer_{site:08x}",
                site,
                struct.pack(">I", spec.stock_drawer),
                struct.pack(">I", address),
            )
        )
    if spec.target.name == "EVENT.BIN":
        if character_data is None:
            raise ValueError("EVENT.BIN: missing generated shop character-name data")
        pixel = build_pixel_blitter(BUY_CAVE)
        drawer_offset = (len(pixel) + 3) & ~3
        drawer_address = BUY_CAVE + drawer_offset
        buy_payload = bytearray(pixel)
        buy_payload.extend(bytes(drawer_offset - len(buy_payload)))
        buy_drawer = build_buy_sell_drawer(drawer_address, BUY_CAVE, font8_data)
        widths_address = drawer_address + len(buy_drawer) - 256
        buy_payload.extend(buy_drawer)
        while (BUY_CAVE + len(buy_payload)) & 3:
            buy_payload.append(0)
        shop_panel_glyph_address = BUY_CAVE + len(buy_payload)
        buy_payload.extend(build_shop_panel_glyph(shop_panel_glyph_address, font8_data))
        while (BUY_CAVE + len(buy_payload)) & 3:
            buy_payload.append(0)
        shop_character_name_address = BUY_CAVE + len(buy_payload)
        buy_payload.extend(
            build_shop_character_name_glyph(
                shop_character_name_address,
                BUY_CAVE,
                widths_address,
                character_data,
            )
        )
        if BUY_CAVE + len(buy_payload) > BUY_CAVE_LIMIT:
            raise ValueError("EVENT.BIN: BUY/SELL cave exceeds event VWF cave")
        patches.append(
            BytePatch(
                "buy_sell_name_cave",
                BUY_CAVE,
                bytes(len(buy_payload)),
                bytes(buy_payload),
            )
        )
        trampoline = build_trampoline(BUY_HOOK, drawer_address)
        if len(trampoline) != len(BUY_HOOK_ORIGINAL):
            raise ValueError("BUY/SELL trampoline does not fill the original prologue")
        patches.append(
            BytePatch(
                "buy_sell_name_hook",
                BUY_HOOK,
                BUY_HOOK_ORIGINAL,
                trampoline,
            )
        )
        for site in SHOP_INVENTORY_LABEL_POINTER_SITES:
            patches.append(
                BytePatch(
                    f"shop_inventory_label_pointer_{site:08x}",
                    site,
                    struct.pack(">I", SHOP_RAW_GLYPH),
                    struct.pack(">I", shop_panel_glyph_address),
                )
            )
        for site in SHOP_CHARACTER_NAME_POINTER_SITES:
            patches.append(
                BytePatch(
                    f"shop_character_name_glyph_pointer_{site:08x}",
                    site,
                    struct.pack(">I", SHOP_STOCK_GLYPH),
                    struct.pack(">I", shop_character_name_address),
                )
            )
    return PatchGroup("itemname_runtime", spec.target, tuple(patches))


def build_patch_groups(context: EngineBuildContext) -> tuple[PatchGroup, ...]:
    contract = load_runtime_ui(context)
    ui = load_config(
        text_path=(
            context.text_generated_root / "runtime_ui/sections/equipment_ui.json"
        )
    )
    # Validate the context-bound font contract before composing target groups.
    font8_data = load_metrics(context.font_generated_root / "font8_metrics.json")
    character_rows = contract.section("character_names")
    if not isinstance(character_rows, list):
        raise ValueError(f"{contract.path}: invalid character_names section")
    character_data = build_shop_character_name_data(character_rows, font8_data)
    return tuple(build_group(spec, ui, font8_data, character_data) for spec in SPECS)
