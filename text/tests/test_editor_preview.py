import unittest

from text.editor.preview import (
    FONT8_METRICS_PATH,
    render_pipeline_preview,
    resolve_preview_modes,
)
from text.editor.server import CorpusIndex
from text.script.encoding.latin import load_latin_encoding


class EditorConsumerPreviewTests(unittest.TestCase):
    def test_fixed_byte_fields_use_font8_and_the_registered_pixel_limit(self) -> None:
        mode = resolve_preview_modes(
            "fixed_bytes/CHARNAME.DAT.json",
            {"record": 0},
        )[0]

        self.assertEqual(mode.font, "font8")
        self.assertEqual(mode.layout.width, 64)
        self.assertTrue(mode.exact)

    def test_name_and_description_fields_have_different_consumers(self) -> None:
        name = resolve_preview_modes(
            "name_description/ITEMNAME.DAT.json",
            {"_field": "name"},
        )[0]
        description = resolve_preview_modes(
            "name_description/ITEMNAME.DAT.json",
            {"_field": "description"},
        )[0]

        self.assertEqual(name.font, "font8")
        self.assertEqual(name.layout.width, 80)
        self.assertEqual(description.font.value, "font16")
        self.assertIsNone(description.layout.width)

    def test_indexed_byte_messages_use_the_mixed_fixed_console(self) -> None:
        preview = render_pipeline_preview(
            "indexed_bytes/BTL_MES.MD8.json",
            {"index": 0},
            "ABC",
        )["variants"][0]

        self.assertEqual(preview["font"], "console_mixed")
        self.assertEqual(preview["lines"][0]["width"], 24)
        self.assertFalse(preview["exact"])

    def test_ascii_fields_render_as_fixed_8x12_storage(self) -> None:
        preview = render_pipeline_preview(
            "ascii_fields/SNDTEST.BIN.json",
            {"kind": "request_number", "capacity_bytes": 8},
            "ABC",
        )["variants"][0]

        self.assertEqual(preview["font"], "console8")
        self.assertEqual(preview["content_width"], 56)
        self.assertEqual(preview["lines"][0]["width"], 24)

    def test_runtime_shop_and_healing_fields_use_their_font8_widths(self) -> None:
        shop = resolve_preview_modes("runtime_ui/shop_ui.json", {})[0]
        healing = resolve_preview_modes("runtime_ui/healing_ui.json", {})[0]

        self.assertEqual(shop.font, "font8")
        self.assertEqual(shop.layout.width, 64)
        self.assertEqual(healing.font, "font8")
        self.assertEqual(healing.layout.width, 144)
        self.assertEqual(shop.glyph_gap, 1)

        text = "All Members"
        preview = render_pipeline_preview("runtime_ui/healing_ui.json", {}, text)[
            "variants"
        ][0]
        encoding = load_latin_encoding(FONT8_METRICS_PATH)
        glyphs = encoding.segment_glyphs(text)
        expected_width = sum(glyph.advance for glyph in glyphs) + len(glyphs) - 1
        self.assertEqual(preview["glyph_gap"], 1)
        self.assertEqual(preview["lines"][0]["width"], expected_width)

    def test_eve_menu_context_uses_verified_groups_and_the_live_draft(self) -> None:
        index = CorpusIndex()
        index.refresh()
        menu_group = next(
            group
            for groups in index.menu_groups_by_entry.values()
            for group in groups
            if group["prompt_entries"] or group["option_entries"]
        )
        selected_entry = (
            menu_group["prompt_entries"][0]
            if menu_group["prompt_entries"]
            else menu_group["option_entries"][0][0]
        )

        contexts = index.menu_contexts(
            file=selected_entry["file"],
            pointer=selected_entry["pointer"],
            proposed_tr="PROPOSED MENU TEXT",
        )

        self.assertTrue(contexts)
        self.assertTrue(all(context["grouping_exact"] for context in contexts))
        self.assertTrue(
            all(type(context["geometry_exact"]) is bool for context in contexts)
        )
        self.assertTrue(all(context["option_slots"] in (2, 4) for context in contexts))
        shown_text = [
            value
            for context in contexts
            for value in (
                *((context["prompt"]["tr"],) if context["prompt"] is not None else ()),
                *(option["tr"] for option in context["options"]),
            )
        ]
        self.assertIn("PROPOSED MENU TEXT", shown_text)

    def test_cld_f_combat_prompt_shows_its_two_ordered_options(self) -> None:
        index = CorpusIndex()
        index.refresh()
        file = "eve/CLD_F.EVE.json"
        entries_by_message = {
            message: next(
                entry
                for entry in index.entries_by_file[file]
                if any(
                    location.get("message") == message
                    for location in entry["metadata"].get("locations", ())
                )
            )
            for message in (6, 7, 8, 9)
        }

        def context_for(message: int, proposed_tr: str) -> dict:
            entry = entries_by_message[message]
            return next(
                context
                for context in index.menu_contexts(
                    file=file,
                    pointer=entry["pointer"],
                    proposed_tr=proposed_tr,
                )
                if context["script_index"] == 26
            )

        lead_context = context_for(6, "LEAD DRAFT")
        prompt_context = context_for(7, "PROMPT DRAFT")
        option_context = context_for(8, "OPTION DRAFT")

        self.assertEqual(lead_context["prompt"]["tr"], entries_by_message[7]["tr"])
        self.assertNotEqual(lead_context["prompt"]["tr"], entries_by_message[6]["tr"])
        self.assertEqual(prompt_context["prompt"]["tr"], "PROMPT DRAFT")
        self.assertEqual(option_context["prompt"]["tr"], entries_by_message[7]["tr"])
        self.assertTrue(lead_context["geometry_exact"])
        self.assertEqual(
            [option["tr"] for option in lead_context["options"]],
            [entries_by_message[8]["tr"], entries_by_message[9]["tr"]],
        )
        self.assertEqual(option_context["options"][0]["tr"], "OPTION DRAFT")

        prompt_slot = lead_context["prompt"]["slot_previews"][0]
        option_slot = lead_context["options"][0]["slot_previews"][0]
        self.assertEqual(prompt_slot["content_width"], 320)
        self.assertEqual(option_slot["content_width"], 160)
        self.assertEqual(prompt_slot["max_lines"], 1)
        self.assertEqual(option_slot["max_lines"], 1)
        self.assertFalse(prompt_slot["overflow"])
        self.assertFalse(option_slot["overflow"])

        two_line_prompt = context_for(7, "First row\nSecond row")["prompt"]
        two_line_slot = two_line_prompt["slot_previews"][0]
        self.assertEqual(two_line_slot["line_count"], 2)
        self.assertTrue(two_line_slot["overflow"])

        prompt_fit = context_for(7, "W" * 32)["prompt"]["slot_previews"][0]
        prompt_over = context_for(7, "W" * 33)["prompt"]["slot_previews"][0]
        option_fit = context_for(8, "W" * 16)["options"][0]["slot_previews"][0]
        option_over = context_for(8, "W" * 17)["options"][0]["slot_previews"][0]
        self.assertEqual(prompt_fit["lines"][0]["width"], 320)
        self.assertFalse(prompt_fit["overflow"])
        self.assertEqual(prompt_over["lines"][0]["width"], 330)
        self.assertTrue(prompt_over["overflow"])
        self.assertEqual(option_fit["lines"][0]["width"], 160)
        self.assertFalse(option_fit["overflow"])
        self.assertEqual(option_over["lines"][0]["width"], 170)
        self.assertTrue(option_over["overflow"])

        prompt_pages = sorted(
            (
                entry
                for entry in index.entries_by_file[file]
                if any(
                    location.get("message") == 147
                    for location in entry["metadata"].get("locations", ())
                )
            ),
            key=lambda entry: min(
                location["page"]
                for location in entry["metadata"]["locations"]
                if location.get("message") == 147
            ),
        )
        self.assertEqual(len(prompt_pages), 2)

        def page_context(entry: dict, proposed_tr: str) -> dict:
            return next(
                context
                for context in index.menu_contexts(
                    file=file,
                    pointer=entry["pointer"],
                    proposed_tr=proposed_tr,
                )
                if context["script_index"] == 162
            )

        first_page_context = page_context(prompt_pages[0], "EARLIER PAGE DRAFT")
        final_page_context = page_context(prompt_pages[1], "FINAL PAGE DRAFT")
        self.assertEqual(
            first_page_context["prompt"]["tr"], "Really...{WAIT} Please..."
        )
        self.assertEqual(final_page_context["prompt"]["tr"], "FINAL PAGE DRAFT")
        self.assertFalse(first_page_context["prompt"]["slot_previews"][0]["overflow"])

    def test_menu_slots_keep_their_own_insert_widths(self) -> None:
        index = CorpusIndex()
        index.refresh()
        file = "eve/KEMO.EVE.json"
        selected = next(
            entry for entry in index.entries_by_file[file] if entry["pointer"] == [474]
        )
        context = next(
            context
            for context in index.menu_contexts(
                file=file,
                pointer=selected["pointer"],
                proposed_tr=selected["tr"],
            )
            if context["script_index"] == 409
        )
        demon_option = next(
            option for option in context["options"] if option["tr"] == "{demon_name}"
        )
        slot = demon_option["slot_previews"][0]

        self.assertEqual(slot["token_widths"], {"{demon_name}": 128})
        self.assertEqual(slot["lines"], [{"text": "{demon_name}", "width": 128}])
        self.assertFalse(slot["overflow"])


if __name__ == "__main__":
    unittest.main()
