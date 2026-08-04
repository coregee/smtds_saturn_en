"""Declarative, lazy registry for engine patch capabilities."""

from dataclasses import dataclass
from importlib import import_module
from typing import Protocol

from engine.script.context import EngineBuildContext
from engine.script.patching import PatchGroup


class PatchFactory(Protocol):
    def __call__(
        self,
        context: EngineBuildContext,
    ) -> PatchGroup | tuple[PatchGroup, ...]: ...


@dataclass(frozen=True)
class PatchLoader:
    capability: str
    module: str
    factory: str = "build_patch_groups"

    def load(self, context: EngineBuildContext) -> tuple[PatchGroup, ...]:
        factory: PatchFactory = getattr(import_module(self.module), self.factory)
        value = factory(context)
        groups = (value,) if isinstance(value, PatchGroup) else tuple(value)
        if not all(isinstance(group, PatchGroup) for group in groups):
            raise TypeError(
                f"{self.module}.{self.factory} did not provide patch groups"
            )
        mismatched = {
            group.capability for group in groups if group.capability != self.capability
        }
        if mismatched:
            found = ", ".join(sorted(mismatched))
            raise ValueError(
                f"{self.module}.{self.factory} registered {found}; "
                f"expected {self.capability}"
            )
        return groups


# Loader order is patch order. Multiple entries may intentionally contribute
# target-specific groups to the same capability.
PATCH_LOADERS = (
    PatchLoader("config_ui", "engine.script.config_menu.patch"),
    PatchLoader(
        "combat_packed_fetch",
        "engine.script.combat.packed",
    ),
    PatchLoader(
        "combat_packed_fetch",
        "engine.script.combat.normcom_packed",
    ),
    PatchLoader("combat_vwf", "engine.script.combat.vwf"),
    PatchLoader(
        "dungeon_locations",
        "engine.script.dungeon_locations.patch",
    ),
    PatchLoader(
        "equipment_ui",
        "engine.script.equipment_ui.patch",
    ),
    PatchLoader("map_ui", "engine.script.map_ui.patch"),
    PatchLoader("event_vwf", "engine.script.event.vwf"),
    PatchLoader(
        "event_packed_fetch",
        "engine.script.event.packed",
    ),
    PatchLoader(
        "fixed_text_fields",
        "engine.script.fixed_text_fields.patch",
    ),
    PatchLoader("fusion_menu", "engine.script.fusion_menu.patch"),
    PatchLoader("hosi_messages", "engine.script.hosi_messages.patch"),
    PatchLoader("msgr_text", "engine.script.msgr.text"),
    PatchLoader("msgr_text", "engine.script.msgr.inserts"),
    PatchLoader(
        "itemname_runtime",
        "engine.script.itemname_runtime.patch",
    ),
    PatchLoader("name_runtime", "engine.script.name.entry"),
    PatchLoader("name_runtime", "engine.script.name.inserts"),
    PatchLoader(
        "normcom_help",
        "engine.script.normcom_help.patch",
    ),
    PatchLoader("name_runtime", "engine.script.saveload.load"),
    PatchLoader("name_runtime", "engine.script.saveload.names"),
    PatchLoader("saveload_ui", "engine.script.saveload.ui"),
    PatchLoader("saveload_ui", "engine.script.saveload.system"),
    PatchLoader(
        "smallfont_vwf",
        "engine.script.smallfont.patch",
    ),
    PatchLoader("status_ui", "engine.script.status_ui.patch"),
)


def capability_names() -> tuple[str, ...]:
    return tuple(dict.fromkeys(loader.capability for loader in PATCH_LOADERS))


def select_patch_groups(
    names: list[str],
    context: EngineBuildContext,
) -> tuple[PatchGroup, ...]:
    available = capability_names()
    if names:
        unknown = sorted(set(names) - set(available))
        if unknown:
            choices = ", ".join(available) if available else "none registered"
            raise ValueError(
                f"unknown engine capabilities: {', '.join(unknown)}; "
                f"available: {choices}"
            )
        selected = set(names)
    else:
        selected = set(available)

    return tuple(
        group
        for loader in PATCH_LOADERS
        if loader.capability in selected
        for group in loader.load(context)
    )
