"""Validated labels and relative layout for the equipment interface."""

import json
from dataclasses import dataclass
from pathlib import Path

from engine.script.generated_asset import RuntimeUiContract
from project_paths import ENGINE_ROOT

CONFIG_PATH = ENGINE_ROOT / "config" / "equipment_ui.json"
BASE_KEYS = ("strength", "intelligence", "magic", "vitality", "agility", "luck")
DERIVED_KEYS = (
    "sword_attack",
    "sword_accuracy",
    "gun_attack",
    "gun_accuracy",
    "defense",
    "evasion",
    "magic_power",
    "magic_effect",
)


@dataclass(frozen=True)
class Offset:
    x: int
    y: int


@dataclass(frozen=True)
class SelectionBox:
    offset: Offset
    width: int
    height: int


@dataclass(frozen=True)
class PlacedLabel:
    text: str
    offset: Offset


@dataclass(frozen=True)
class ActionLabel:
    text: str
    offset: Offset
    selection_box: SelectionBox


@dataclass(frozen=True)
class EquipmentLabels:
    recommend: str
    unequip: str
    base: tuple[str, ...]
    derived: tuple[str, ...]


@dataclass(frozen=True)
class EquipmentUI:
    recommend: ActionLabel
    unequip: ActionLabel
    item_names: Offset
    base: tuple[PlacedLabel, ...]
    derived: tuple[PlacedLabel, ...]

    @property
    def labels(self) -> EquipmentLabels:
        return EquipmentLabels(
            self.recommend.text,
            self.unequip.text,
            tuple(label.text for label in self.base),
            tuple(label.text for label in self.derived),
        )


def integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context}: expected an integer")
    return value


def offset(document: dict, context: str) -> Offset:
    return Offset(
        integer(document["offset_x"], f"{context}.offset_x"),
        integer(document["offset_y"], f"{context}.offset_y"),
    )


def placed_label(document: object, context: str) -> PlacedLabel:
    if not isinstance(document, dict) or set(document) != {
        "text",
        "offset_x",
        "offset_y",
    }:
        raise ValueError(f"{context}: expected text, offset_x, and offset_y")
    text = document["text"]
    if not isinstance(text, str) or not text:
        raise ValueError(f"{context}.text: expected nonempty text")
    return PlacedLabel(text, offset(document, context))


def action_label(document: object, context: str) -> ActionLabel:
    if not isinstance(document, dict) or set(document) != {
        "text",
        "offset_x",
        "offset_y",
        "selection_box",
    }:
        raise ValueError(f"{context}: expected text, offsets, and selection_box")
    label = placed_label(
        {key: document[key] for key in ("text", "offset_x", "offset_y")},
        context,
    )
    box = document["selection_box"]
    if not isinstance(box, dict) or set(box) != {
        "offset_x",
        "offset_y",
        "width",
        "height",
    }:
        raise ValueError(f"{context}.selection_box: invalid fields")
    width = integer(box["width"], f"{context}.selection_box.width")
    height = integer(box["height"], f"{context}.selection_box.height")
    if not 8 <= width <= 135:
        raise ValueError(f"{context}.selection_box.width: expected 8..135")
    if not 1 <= height <= 128:
        raise ValueError(f"{context}.selection_box.height: expected 1..128")
    return ActionLabel(
        label.text,
        label.offset,
        SelectionBox(offset(box, f"{context}.selection_box"), width, height),
    )


def keyed_labels(document: object, keys: tuple[str, ...], context: str):
    if not isinstance(document, dict) or set(document) != set(keys):
        raise ValueError(f"{context}: invalid label fields")
    return tuple(placed_label(document[key], f"{context}.{key}") for key in keys)


def load_config(
    contract: RuntimeUiContract,
    path: Path = CONFIG_PATH,
) -> EquipmentUI:
    document = json.loads(path.read_text(encoding="utf-8"))
    text_document = contract.section("equipment_ui")
    if not isinstance(text_document, dict):
        raise ValueError(f"{contract.path}: invalid equipment_ui section")
    if not isinstance(document, dict) or set(document) != {
        "actions",
        "item_names",
        "base_stats",
        "derived_stats",
    }:
        raise ValueError(f"{path}: invalid top-level fields")
    actions = document["actions"]
    if not isinstance(actions, dict) or set(actions) != {"recommend", "unequip"}:
        raise ValueError(f"{path}: invalid action fields")
    item_names = document["item_names"]
    if not isinstance(item_names, dict) or set(item_names) != {
        "offset_x",
        "offset_y",
    }:
        raise ValueError(f"{path}: invalid item_names fields")

    def with_text(layout: dict, source: dict) -> dict:
        return {**layout, "text": source["text"]}

    recommend = action_label(
        with_text(actions["recommend"], text_document["actions"]["recommend"]),
        "actions.recommend",
    )
    unequip = action_label(
        with_text(actions["unequip"], text_document["actions"]["unequip"]),
        "actions.unequip",
    )
    if (
        recommend.selection_box.offset.y != unequip.selection_box.offset.y
        or recommend.selection_box.height != unequip.selection_box.height
    ):
        raise ValueError(
            f"{CONFIG_PATH}: action selection boxes share offset_y and height"
        )
    return EquipmentUI(
        recommend,
        unequip,
        offset(item_names, "item_names"),
        keyed_labels(
            {
                key: with_text(
                    document["base_stats"][key],
                    text_document["base_stats"][key],
                )
                for key in BASE_KEYS
            },
            BASE_KEYS,
            "base_stats",
        ),
        keyed_labels(
            {
                key: with_text(
                    document["derived_stats"][key],
                    text_document["derived_stats"][key],
                )
                for key in DERIVED_KEYS
            },
            DERIVED_KEYS,
            "derived_stats",
        ),
    )
