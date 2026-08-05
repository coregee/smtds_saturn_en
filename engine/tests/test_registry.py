import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engine.script import registry
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup

EXPECTED_CAPABILITIES = (
    "config_ui",
    "combat_packed_fetch",
    "combat_vwf",
    "dungeon_locations",
    "equipment_ui",
    "map_ui",
    "event_vwf",
    "event_packed_fetch",
    "fixed_text_fields",
    "fusion_menu",
    "hosi_messages",
    "msgr_text",
    "itemname_runtime",
    "name_runtime",
    "normcom_help",
    "saveload_ui",
    "smallfont_vwf",
    "status_ui",
)


def group(capability: str, name: str) -> PatchGroup:
    return PatchGroup(
        capability,
        BinaryTarget(f"{name}.BIN", Path(f"{name}.BIN"), 0),
        (BytePatch(name, 0, b"\x00", b"\x01"),),
    )


class RegistryTests(unittest.TestCase):
    def test_feature_modules_import_without_build_side_effects(self) -> None:
        modules = tuple(
            dict.fromkeys(loader.module for loader in registry.PATCH_LOADERS)
        )
        script = f"""
import importlib
from pathlib import Path
from engine.script import patching
from engine.script import sh2
from tools import sh2asm

def blocked(*_args, **_kwargs):
    raise AssertionError("feature import performed build work")

Path.read_bytes = blocked
Path.read_text = blocked
sh2.assemble_checked = blocked
sh2asm.assemble = blocked
for cls in (patching.BytePatch, patching.CodePatch,
            patching.DigestPatch, patching.PatchGroup):
    cls.__init__ = blocked
for name in {modules!r}:
    importlib.import_module(name)
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_capability_listing_imports_no_feature_patches(self) -> None:
        script = f"""
import sys
from engine.script import registry

assert registry.capability_names() == {EXPECTED_CAPABILITIES!r}
for name in (
    "engine.script.config_menu.patch",
    "engine.script.event.vwf",
    "engine.script.status_ui.patch",
):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_feature_packages_are_lazy(self) -> None:
        packages = (
            "combat",
            "config_menu",
            "dungeon_locations",
            "equipment_ui",
            "event",
            "fixed_text_fields",
            "fusion_menu",
            "hosi_messages",
            "itemname_runtime",
            "map_ui",
            "msgr",
            "name",
            "normcom_help",
            "saveload",
            "smallfont",
            "status_ui",
        )
        patch_modules = (
            "engine.script.config_menu.patch",
            "engine.script.dungeon_locations.patch",
            "engine.script.equipment_ui.patch",
            "engine.script.event.packed",
            "engine.script.event.vwf",
            "engine.script.fixed_text_fields.patch",
            "engine.script.fusion_menu.patch",
            "engine.script.hosi_messages.patch",
            "engine.script.itemname_runtime.patch",
            "engine.script.map_ui.patch",
            "engine.script.msgr.inserts",
            "engine.script.msgr.text",
            "engine.script.combat.packed",
            "engine.script.combat.normcom_packed",
            "engine.script.combat.vwf",
            "engine.script.normcom_help.patch",
            "engine.script.saveload.load",
            "engine.script.saveload.names",
            "engine.script.saveload.system",
            "engine.script.saveload.ui",
            "engine.script.name.entry",
            "engine.script.name.inserts",
            "engine.script.name.model",
            "engine.script.smallfont.patch",
            "engine.script.status_ui.patch",
        )
        preloaded = {
            module: sys.modules.pop(module)
            for module in patch_modules
            if module in sys.modules
        }
        try:
            for package in packages:
                importlib.import_module(f"engine.script.{package}")
            for module in patch_modules:
                self.assertNotIn(module, sys.modules)
        finally:
            sys.modules.update(preloaded)

    def test_selection_loads_only_requested_capabilities_in_order(self) -> None:
        from engine.script.context import DEFAULT_CONTEXT

        alpha_1 = group("alpha", "alpha_1")
        alpha_2 = group("alpha", "alpha_2")
        beta = group("beta", "beta")
        loaders = (
            registry.PatchLoader("alpha", "fake.alpha", "FIRST"),
            registry.PatchLoader("beta", "fake.beta", "GROUP"),
            registry.PatchLoader("alpha", "fake.alpha", "SECOND"),
        )
        modules = {
            "fake.alpha": SimpleNamespace(
                FIRST=lambda _context: alpha_1,
                SECOND=lambda _context: (alpha_2,),
            ),
            "fake.beta": SimpleNamespace(GROUP=lambda _context: beta),
        }
        imported = []

        def load_module(name: str) -> SimpleNamespace:
            imported.append(name)
            return modules[name]

        with (
            patch.object(registry, "PATCH_LOADERS", loaders),
            patch.object(registry, "import_module", side_effect=load_module),
        ):
            selected = registry.select_patch_groups(["alpha"], DEFAULT_CONTEXT)

        self.assertEqual(selected, (alpha_1, alpha_2))
        self.assertEqual(imported, ["fake.alpha", "fake.alpha"])

    def test_unknown_capability_fails_before_loading_modules(self) -> None:
        from engine.script.context import DEFAULT_CONTEXT

        with patch.object(registry, "import_module") as load_module:
            with self.assertRaisesRegex(ValueError, "unknown engine capabilities"):
                registry.select_patch_groups(["not_registered"], DEFAULT_CONTEXT)
        load_module.assert_not_called()


if __name__ == "__main__":
    unittest.main()
