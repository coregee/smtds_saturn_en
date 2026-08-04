import struct
import unittest

from engine.script.context import DEFAULT_CONTEXT
from engine.script.demon_sort import (
    dense_rank_table,
    english_name_key,
    sorted_indices,
)
from engine.script.fusion_menu.data import (
    encode_demon_sort_pool,
    load_codes,
    load_names,
)
from engine.script.fusion_menu.patch import (
    NAME_SORT_POINTER_SITE,
    NAME_SORT_REGION,
    NAME_SORT_REGION_SIZE,
)
from engine.script.fusion_menu.patch import (
    build_patch as build_fusion_patch,
)
from engine.script.generated_asset import load_runtime_ui
from engine.script.patching import apply_patch_groups
from engine.script.status_ui.model import (
    DA3D_NAME_SORT_COMPARE_SITE,
    DA3D_NAME_SORT_COUNT,
    DA3D_NAME_SORT_RANK_TABLE,
)
from engine.script.status_ui.patch import build_da3d_patch

ANALYSE_STOCK_COMPARE = bytes.fromhex(
    "013de808611d71ff0187326cd034011a301c1f016023013dd431611d71ff0187e7006923011a341c"
)
ANALYSE_ENGLISH_COMPARE = bytes.fromhex(
    "6433014d611d71ff6013d736037c633c6263326c69236023014d611d71ff6013017c611ca00d0009"
)


class EnglishDemonSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        contract = load_runtime_ui(DEFAULT_CONTEXT)
        rows = contract.section("demon_names")
        if not isinstance(rows, list):
            raise TypeError("runtime demon_names section must be a list")
        cls.names = load_names(rows, "demon sort test")
        cls.codes = load_codes(
            DEFAULT_CONTEXT.font_generated_root / "font12_metrics.json"
        )

    def test_dictionary_key_ignores_case_and_name_separators(self) -> None:
        self.assertEqual(english_name_key("Jack-o'-Lantern"), "jackolantern")
        self.assertLess(english_name_key("Chimera"), english_name_key("Chi You"))
        self.assertLess(english_name_key("Dakini"), english_name_key("Da Peng"))
        self.assertLess(english_name_key("Nekomata"), english_name_key("Neko Shogun"))
        with self.assertRaisesRegex(ValueError, "unsupported demon-name sort"):
            english_name_key("Snowman ☃")

    def test_fusion_offsets_are_complete_all_demon_ranks(self) -> None:
        self.assertEqual(len(self.names), 319)
        offsets, pool = encode_demon_sort_pool(self.names, self.codes)
        decoded_offsets = struct.unpack(f">{len(self.names)}H", offsets)
        self.assertEqual(len(set(decoded_offsets)), 290)
        self.assertEqual(
            tuple(sorted(range(len(self.names)), key=decoded_offsets.__getitem__)),
            sorted_indices(self.names),
        )
        for index, name in enumerate(self.names):
            encoded = bytes(self.codes[character] for character in name) + b"\xff"
            start = decoded_offsets[index]
            self.assertEqual(pool[start : start + len(encoded)], encoded)

        duplicate_groups: dict[int, list[int]] = {}
        for demon_id, offset in enumerate(decoded_offsets, start=1):
            duplicate_groups.setdefault(offset, []).append(demon_id)
        self.assertTrue(
            any(len(demon_ids) > 1 for demon_ids in duplicate_groups.values())
        )
        roster = list(range(len(self.names), 0, -1))
        roster.sort(key=lambda demon_id: (decoded_offsets[demon_id - 1], demon_id))
        self.assertEqual(
            tuple(demon_id - 1 for demon_id in roster),
            sorted_indices(self.names),
        )

    def test_analyse_ranks_cover_only_the_stock_255_id_domain(self) -> None:
        ranks = dense_rank_table(self.names, count=DA3D_NAME_SORT_COUNT)
        self.assertEqual(len(ranks), 256)
        self.assertEqual(ranks[-1], 0xFF)
        self.assertEqual(set(ranks[:-1]), set(range(255)))
        ordered = tuple(sorted(range(255), key=ranks.__getitem__))
        self.assertEqual(ordered, sorted_indices(self.names[:255]))
        self.assertEqual(self.names[254], "Slime")
        self.assertEqual(self.names[255], "Shei")
        self.assertEqual(
            dense_rank_table(("A", "A", "B"), count=3, append_sentinel=False),
            b"\x00\x00\x01",
        )

    def test_fusion_patch_replaces_only_the_verified_sort_window_and_hook(self) -> None:
        group = build_fusion_patch()
        patches = {patch.name: patch for patch in group.patches}
        runtime = patches["fusion_english_name_sort"]
        hook = patches["fusion_name_sort_pointer"]
        self.assertEqual(runtime.address, NAME_SORT_REGION)
        self.assertEqual(len(runtime.replacement), NAME_SORT_REGION_SIZE)
        self.assertEqual(hook.address, NAME_SORT_POINTER_SITE)
        self.assertEqual(hook.replacement, struct.pack(">I", NAME_SORT_REGION))

        original = (DEFAULT_CONTEXT.extracted_root / "EVENT.BIN").read_bytes()
        patched = apply_patch_groups(original, (group,))
        offset = NAME_SORT_REGION - group.target.load_address
        self.assertEqual(
            patched[offset : offset + NAME_SORT_REGION_SIZE], runtime.replacement
        )

    def test_analyse_patch_uses_shared_ranks_and_preserves_stock_sort_shell(
        self,
    ) -> None:
        group = build_da3d_patch()
        patches = {patch.name: patch for patch in group.patches}
        compare = patches["demon_analyzer_english_name_compare"]
        ranks = patches["demon_analyzer_english_name_ranks"]
        self.assertEqual(compare.address, DA3D_NAME_SORT_COMPARE_SITE)
        self.assertEqual(compare.expected, ANALYSE_STOCK_COMPARE)
        self.assertEqual(compare.replacement, ANALYSE_ENGLISH_COMPARE)
        self.assertEqual(len(compare.replacement), 40)
        self.assertEqual(ranks.address, DA3D_NAME_SORT_RANK_TABLE)
        self.assertEqual(
            ranks.replacement,
            dense_rank_table(self.names, count=DA3D_NAME_SORT_COUNT),
        )

        original = (DEFAULT_CONTEXT.extracted_root / "DA_3D.BIN").read_bytes()
        apply_patch_groups(original, (group,))


if __name__ == "__main__":
    unittest.main()
