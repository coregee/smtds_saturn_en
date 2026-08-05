import io
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from engine.script import build as engine_build
from engine.script.context import EngineBuildContext
from engine.script.patching import BinaryTarget, BytePatch, PatchGroup
from tools.sh2asm import AsmBlob


def make_context(root: Path) -> EngineBuildContext:
    context = EngineBuildContext(
        extracted_root=root / "extracted",
        font_generated_root=root / "font-generated",
        text_generated_root=root / "text-generated",
        build_root=root / "build",
    )
    for path in (
        context.extracted_root,
        context.font_generated_root,
        context.text_generated_root,
        context.build_root,
    ):
        path.mkdir()
    return context


class RuntimeBuildContextTests(unittest.TestCase):
    def test_engine_io_uses_context_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = make_context(Path(temporary))
            target = BinaryTarget("TEST.BIN", Path("nested/TEST.BIN"), 0x1000)
            source = context.extracted_root / target.path
            source.parent.mkdir()
            source.write_bytes(b"\x00")
            group = PatchGroup(
                "test",
                target,
                (BytePatch("byte", 0x1000, b"\x00", b"\x01"),),
            )

            with redirect_stdout(io.StringIO()):
                engine_build.build_engine((group,), False, context)
                engine_build.build_engine((group,), True, context)

            self.assertEqual((context.build_root / target.path).read_bytes(), b"\x01")

    def test_config_factory_uses_context_assets(self) -> None:
        from engine.script.config_menu import patch as config_patch

        with tempfile.TemporaryDirectory() as temporary:
            context = make_context(Path(temporary))
            source = context.extracted_root / config_patch.TARGET.path
            source.write_bytes(b"config source")
            static_asset = object()

            with (
                patch.object(
                    config_patch, "static_asset", return_value=static_asset
                ) as load_asset,
                patch.object(
                    config_patch, "build_config", return_value=b"config replacement"
                ) as build_config,
            ):
                group = config_patch.build_patch_groups(context)

            load_asset.assert_called_once_with(context)
            build_config.assert_called_once_with(
                b"config source",
                context.build_root / "FONT16.FON",
                context.font_generated_root / "font16_metrics.json",
                static_asset,
            )
            self.assertEqual(group.patches[0].replacement, b"config replacement")

    def test_map_factory_uses_context_assets(self) -> None:
        from engine.script.map_ui import patch as map_patch

        with tempfile.TemporaryDirectory() as temporary:
            context = make_context(Path(temporary))
            source = context.extracted_root / map_patch.TARGET.path
            source.write_bytes(b"map source")
            static_asset = object()

            with (
                patch.object(
                    map_patch, "static_asset", return_value=static_asset
                ) as load_asset,
                patch.object(
                    map_patch, "build_map", return_value=b"map replacement"
                ) as build_map,
            ):
                group = map_patch.build_patch_groups(context)

            load_asset.assert_called_once_with(context)
            build_map.assert_called_once_with(
                b"map source",
                context.build_root / "FONT16.FON",
                context.font_generated_root / "font16_metrics.json",
                static_asset,
            )
            self.assertEqual(group.patches[0].replacement, b"map replacement")

    def test_status_factory_shares_context_contract(self) -> None:
        from engine.script.status_ui import patch as status_patch

        with tempfile.TemporaryDirectory() as temporary:
            context = make_context(Path(temporary))
            contract = object()
            builders = (
                "build_normcom_patch",
                "build_event_patch",
                "build_da3d_patch",
                "build_level_up_patch",
            )
            with ExitStack() as stack:
                load_contract = stack.enter_context(
                    patch.object(status_patch, "load_runtime_ui", return_value=contract)
                )
                builder_mocks = {
                    name: stack.enter_context(
                        patch.object(status_patch, name, return_value=name)
                    )
                    for name in builders
                }
                groups = status_patch.build_patch_groups(context)

            load_contract.assert_called_once_with(context)
            self.assertEqual(groups, builders)
            for name in builders:
                builder_mocks[name].assert_called_once_with(context, contract)

    def test_saveload_ui_reads_context_extracted_root(self) -> None:
        from engine.script.saveload import ui as saveload_ui

        with tempfile.TemporaryDirectory() as temporary:
            context = make_context(Path(temporary))
            dungeon = context.extracted_root / saveload_ui.DUNGEON_SOURCE_PATH
            dungeon.parent.mkdir(parents=True, exist_ok=True)
            dungeon.write_bytes(b"dungeon source")
            spec = saveload_ui.UI_SPECS[1]
            target = context.extracted_root / spec.target.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"load source")
            static_asset = saveload_ui.save_text_asset()
            cave = AsmBlob(
                b"\x00\x00",
                spec.cave_address,
                [],
                {
                    "location_table": spec.cave_address + 0x100,
                    "dungeon_draw_entry": spec.cave_address + 0x200,
                },
                [],
            )
            locations = tuple(
                (saveload_ui.PADDING_CODE,) * saveload_ui.LOCATION_CELLS
                for _name in saveload_ui.LOCATION_BLOCKS
            )
            saveload_ui.dungeon_source.cache_clear()
            try:
                with (
                    patch.object(saveload_ui, "build_ui_cave", return_value=cave),
                    patch.object(
                        saveload_ui,
                        "save_text_asset",
                        return_value=static_asset,
                    ) as load_asset,
                    patch.object(
                        saveload_ui, "location_records", return_value=locations
                    ),
                    patch.object(saveload_ui, "block_data", return_value=bytes(10)),
                    patch.object(
                        saveload_ui, "validate_dungeon_prefix_mirror"
                    ) as validate,
                    patch.object(
                        saveload_ui, "storage_selector_patches", return_value=()
                    ) as storage_patches,
                ):
                    saveload_ui.build_ui_patch(spec, context)
            finally:
                saveload_ui.dungeon_source.cache_clear()

            validate.assert_called_once_with(
                b"dungeon source",
                b"load source",
                spec.dungeon_table_offset,
                spec.target.name,
            )
            storage_patches.assert_called_once_with(spec, b"load source")
            load_asset.assert_called_once_with(context)

    def test_saveload_ui_reads_context_font_metrics(self) -> None:
        from engine.script.saveload import ui as saveload_ui

        with tempfile.TemporaryDirectory() as temporary:
            context = make_context(Path(temporary))
            with patch.object(
                saveload_ui,
                "load_atlas_metrics",
                return_value=({"A": 0}, {"A": 4}),
            ) as load_metrics:
                widths = saveload_ui.atlas_width_table(context)

            load_metrics.assert_called_once_with(
                context.font_generated_root / "font16_metrics.json"
            )
            self.assertEqual(widths, b"\x04")

    def test_saveload_system_passes_context_to_ui_layout(self) -> None:
        from engine.script.saveload import system as saveload_system
        from engine.script.saveload import ui as saveload_ui

        with tempfile.TemporaryDirectory() as temporary:
            context = make_context(Path(temporary))
            spec = next(
                candidate
                for candidate in saveload_ui.UI_SPECS
                if candidate.target == saveload_system.SAVE_TARGET
            )
            with patch.object(
                saveload_system, "build_ui_cave", return_value=b"\x00\x00"
            ) as build_ui_cave:
                start = saveload_system.data_start(spec.target, context)

            build_ui_cave.assert_called_once_with(spec, context)
            self.assertEqual(start, spec.cave_offset + 4)


if __name__ == "__main__":
    unittest.main()
