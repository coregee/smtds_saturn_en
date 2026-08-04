import unittest
from pathlib import Path

from engine.script.context import DEFAULT_CONTEXT
from engine.script.fixed_text_fields.generated import ASSETS
from engine.script.fixed_text_fields.patch import build_patch_groups
from engine.script.patching import apply_patch_groups

CONDITION_ASSET = Path("fixed_words/COMBAT.BIN.condition_messages.json")


class CombatConditionAssetTests(unittest.TestCase):
    def test_all_combat_fixed_assets_load_and_apply_without_overlap(self) -> None:
        self.assertIn(CONDITION_ASSET, ASSETS)
        groups = tuple(
            group
            for group in build_patch_groups(DEFAULT_CONTEXT)
            if group.target.name == "COMBAT.BIN"
        )
        self.assertEqual(len(groups), 4)
        self.assertEqual(sum(len(group.patches) for group in groups), 134)

        original = (DEFAULT_CONTEXT.extracted_root / "COMBAT.BIN").read_bytes()
        patched = apply_patch_groups(original, groups)
        self.assertNotEqual(patched, original)


if __name__ == "__main__":
    unittest.main()
