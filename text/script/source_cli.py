"""Shared command-line support for registered text sources."""

import argparse

from text.script.sources import SOURCES


def add_source_arguments(
    parser: argparse.ArgumentParser,
    *,
    omitted_action: str,
    check_help: str,
) -> None:
    parser.add_argument(
        "sources",
        nargs="*",
        help=(
            "registered canonical source names (unique input filenames also "
            f"accepted); {omitted_action} when omitted"
        ),
    )
    parser.add_argument(
        "--list",
        dest="list_sources",
        action="store_true",
        help="list canonical source names, input paths, and corpus paths, then exit",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=check_help,
    )


def source_list_lines() -> tuple[str, ...]:
    return tuple(
        "\t".join(
            (
                source.name,
                source.path.as_posix(),
                source.corpus_path.as_posix(),
            )
        )
        for source in SOURCES
    )


def print_source_list() -> None:
    print("\n".join(source_list_lines()))
