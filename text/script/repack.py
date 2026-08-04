"""CLI and compatibility facade for the staged text repacker."""

import argparse

from text.script.repack_codec import (
    build_event_dictionary as _build_event_dictionary,
)
from text.script.repack_codec import (
    codec_output_paths,
    event_codec_binding_json,
    event_codec_json,
)
from text.script.repack_pipeline import CORPUS_ROOT, run_repack
from text.script.repack_selection import (
    parse_selection,
    resolve_selection,
    selected_message_indices,
)
from text.script.source_cli import add_source_arguments, print_source_list

__all__ = (
    "argument_parser",
    "build_event_dictionary",
    "codec_output_paths",
    "event_codec_binding_json",
    "event_codec_json",
    "main",
    "parse_selection",
    "resolve_selection",
    "selected_message_indices",
)


def build_event_dictionary(sources, selection, message_indices):
    """Compatibility wrapper using the repository corpus root."""
    return _build_event_dictionary(
        sources,
        CORPUS_ROOT,
        selection,
        message_indices,
    )


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repack registered text corpora into game files."
    )
    add_source_arguments(
        parser,
        omitted_action="repacks every source",
        check_help="verify existing build files without rewriting them",
    )
    parser.add_argument(
        "--message",
        dest="messages",
        action="append",
        type=int,
        help="repack only this message index; may be repeated for one source",
    )
    parser.add_argument(
        "--select",
        dest="selections",
        action="append",
        metavar="SOURCE:INDEX[,INDEX...]",
        help=(
            "deterministic batch selection; listed messages translate, all other "
            "EVE messages remain Japanese, and static sources are rebuilt"
        ),
    )
    parser.add_argument(
        "--fail-on-fallbacks",
        action="store_true",
        help=(
            "fail if any requested translation would leave Japanese source bytes in use"
        ),
    )
    return parser


def main() -> None:
    parser = argument_parser()
    arguments = parser.parse_args()
    if arguments.list_sources:
        print_source_list()
        return
    try:
        selection = resolve_selection(
            arguments.sources,
            arguments.messages,
            arguments.selections,
        )
        run_repack(
            selection,
            arguments.check,
            fail_on_fallbacks=arguments.fail_on_fallbacks,
        )
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
