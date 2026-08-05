"""Register the dictionary-packed EVENT text-fetch patch."""

from engine.script.context import EngineBuildContext
from engine.script.event.model import EVENT_TARGET, PACKED_FETCH_ADDRESS
from engine.script.event.packed_layout import event_fetch_cave
from engine.script.event.packed_runtime import build_site_patch
from engine.script.patching import BytePatch, PatchGroup
from engine.script.text_render.packed_codec import bound_dictionary_table

FETCH_SITE_1 = 0x0602BB68
FETCH_SITE_2 = 0x0602BB80
FETCH_SITE_1_ORIGINAL = bytes.fromhex("61a26215292122288f0c2a12")
FETCH_SITE_2_ORIGINAL = bytes.fromhex("61a26215292122288df72a12")


def build_patch_groups(context: EngineBuildContext) -> PatchGroup:
    dictionary_table = bound_dictionary_table(
        context.text_generated_root / "event_codec.json",
        context.text_generated_root / "event_codec_binding.json",
        context.build_root,
    )
    fetch_cave = event_fetch_cave(dictionary_table)
    return PatchGroup(
        capability="event_packed_fetch",
        target=EVENT_TARGET,
        patches=(
            BytePatch(
                name="fetch_cave",
                address=PACKED_FETCH_ADDRESS,
                expected=bytes(len(fetch_cave)),
                replacement=fetch_cave,
            ),
            BytePatch(
                name="fetch_site_1",
                address=FETCH_SITE_1,
                expected=FETCH_SITE_1_ORIGINAL,
                replacement=build_site_patch(FETCH_SITE_1, PACKED_FETCH_ADDRESS),
            ),
            BytePatch(
                name="fetch_site_2",
                address=FETCH_SITE_2,
                expected=FETCH_SITE_2_ORIGINAL,
                replacement=build_site_patch(FETCH_SITE_2, PACKED_FETCH_ADDRESS),
            ),
        ),
    )
