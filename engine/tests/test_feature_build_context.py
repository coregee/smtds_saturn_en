import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from engine.script.context import DEFAULT_CONTEXT
from engine.script.generated_asset import load_runtime_ui
from engine.script.name.model import load_atlas_metrics, load_font8_codes
from engine.script.text_render.font8_metrics import load_metrics
from engine.script.text_render.font_metrics import (
    load_font12_metrics,
    load_font16_metrics,
)


class FeatureBuildContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from engine.script.fusion_menu.data import load_codes

        cls.contract = load_runtime_ui(DEFAULT_CONTEXT)
        cls.font8_data = load_metrics(
            DEFAULT_CONTEXT.font_generated_root / "font8_metrics.json"
        )
        cls.font12_document = load_font12_metrics(
            DEFAULT_CONTEXT.font_generated_root / "font12_metrics.json"
        )
        cls.font12_codes = load_codes(
            DEFAULT_CONTEXT.font_generated_root / "font12_metrics.json"
        )
        cls.font16_document = load_font16_metrics(
            DEFAULT_CONTEXT.font_generated_root / "font16_metrics.json"
        )
        cls.atlas_metrics = load_atlas_metrics(
            DEFAULT_CONTEXT.font_generated_root / "font16_metrics.json"
        )
        cls.font8_codes = load_font8_codes(
            DEFAULT_CONTEXT.font_generated_root / "font8_metrics.json"
        )

    def custom_context(self):
        return replace(
            DEFAULT_CONTEXT,
            font_generated_root=Path("custom-font-generated"),
            text_generated_root=Path("custom-text-generated"),
        )

    def test_name_factory_passes_context_generated_inputs(self) -> None:
        from engine.script.name import entry

        context = self.custom_context()
        text_asset = entry.name_text_asset()
        with (
            patch.object(
                entry, "load_runtime_ui", return_value=self.contract
            ) as runtime_ui,
            patch.object(
                entry, "load_atlas_metrics", return_value=self.atlas_metrics
            ) as atlas_metrics,
            patch.object(
                entry, "load_font8_codes", return_value=self.font8_codes
            ) as font8_codes,
            patch.object(
                entry, "name_text_asset", return_value=text_asset
            ) as name_text_asset,
        ):
            entry.build_patch_groups(context)

        runtime_ui.assert_called_once_with(context)
        atlas_metrics.assert_called_once_with(
            context.font_generated_root / "font16_metrics.json"
        )
        font8_codes.assert_called_once_with(
            context.font_generated_root / "font8_metrics.json"
        )
        name_text_asset.assert_called_once_with(context)

    def test_equipment_factory_passes_context_generated_inputs(self) -> None:
        from engine.script.equipment_ui import patch as equipment

        context = self.custom_context()
        with (
            patch.object(
                equipment, "load_runtime_ui", return_value=self.contract
            ) as runtime_ui,
            patch.object(
                equipment, "load_metrics", return_value=self.font8_data
            ) as font8_metrics,
        ):
            equipment.build_patch_groups(context)

        runtime_ui.assert_called_once_with(context)
        font8_metrics.assert_called_once_with(
            context.font_generated_root / "font8_metrics.json"
        )

    def test_fusion_factory_passes_context_generated_inputs(self) -> None:
        from engine.script.fusion_menu import patch as fusion

        context = self.custom_context()
        font12_path = context.font_generated_root / "font12_metrics.json"
        with (
            patch.object(
                fusion, "load_runtime_ui", return_value=self.contract
            ) as runtime_ui,
            patch.object(
                fusion, "load_font12_metrics", return_value=self.font12_document
            ) as font12_metrics,
            patch.object(
                fusion, "load_codes", return_value=self.font12_codes
            ) as font12_codes,
            patch.object(
                fusion, "load_metrics", return_value=self.font8_data
            ) as font8_metrics,
        ):
            fusion.build_patch_groups(context)

        runtime_ui.assert_called_once_with(context)
        font12_metrics.assert_called_once_with(font12_path)
        font12_codes.assert_called_once_with(font12_path)
        font8_metrics.assert_called_once_with(
            context.font_generated_root / "font8_metrics.json"
        )

    def test_smallfont_factory_passes_context_generated_inputs(self) -> None:
        from engine.script.smallfont import patch as smallfont

        context = self.custom_context()
        with (
            patch.object(
                smallfont, "load_runtime_ui", return_value=self.contract
            ) as runtime_ui,
            patch.object(
                smallfont, "load_metrics", return_value=self.font8_data
            ) as font8_metrics,
            patch.object(
                smallfont,
                "load_font16_metrics",
                return_value=self.font16_document,
            ) as font16_metrics,
        ):
            smallfont.build_patch_groups(context)

        runtime_ui.assert_called_once_with(context)
        self.assertEqual(font8_metrics.call_count, 3)
        font8_metrics.assert_called_with(
            context.font_generated_root / "font8_metrics.json"
        )
        font16_metrics.assert_called_once_with(
            context.font_generated_root / "font16_metrics.json"
        )


if __name__ == "__main__":
    unittest.main()
