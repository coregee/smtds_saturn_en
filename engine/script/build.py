import argparse
from collections import defaultdict

from engine.script.context import DEFAULT_CONTEXT, EngineBuildContext
from engine.script.patching import (
    BinaryTarget,
    PatchGroup,
    apply_patch_groups,
)
from engine.script.registry import capability_names, select_patch_groups


def group_by_target(
    groups: tuple[PatchGroup, ...],
) -> dict[BinaryTarget, tuple[PatchGroup, ...]]:
    grouped = defaultdict(list)
    targets_by_path = {}

    for group in groups:
        previous = targets_by_path.get(group.target.path)
        if previous is not None and previous != group.target:
            raise ValueError(
                f"conflicting definitions for binary target {group.target.path}"
            )
        targets_by_path[group.target.path] = group.target
        grouped[group.target].append(group)

    return {target: tuple(target_groups) for target, target_groups in grouped.items()}


def build_engine(
    groups: tuple[PatchGroup, ...],
    check: bool,
    context: EngineBuildContext = DEFAULT_CONTEXT,
) -> None:
    stale = []
    for target, target_groups in group_by_target(groups).items():
        source_path = context.extracted_root / target.path
        output_path = context.build_root / target.path
        patched = apply_patch_groups(source_path.read_bytes(), target_groups)

        if check:
            if not output_path.exists() or output_path.read_bytes() != patched:
                stale.append(output_path)
                action = "stale"
            else:
                action = "verified"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(patched)
            action = "wrote"

        capabilities = ", ".join(
            dict.fromkeys(group.capability for group in target_groups)
        )
        print(f"{target.path}: {action} {len(patched)} bytes ({capabilities})")

    if stale:
        paths = "\n  ".join(str(path) for path in stale)
        raise ValueError(f"stale engine build files:\n  {paths}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply registered runtime patches to extracted game binaries."
    )
    parser.add_argument(
        "capabilities",
        nargs="*",
        help="runtime capabilities; applies every registered capability when omitted",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list registered runtime capabilities and exit",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify existing build files without rewriting them",
    )
    arguments = parser.parse_args()

    try:
        if arguments.list:
            names = capability_names()
            if names:
                print("\n".join(names))
            else:
                print("No engine patches are registered yet.")
            return

        groups = select_patch_groups(arguments.capabilities, DEFAULT_CONTEXT)
        if not groups:
            print("No engine patches are registered yet; nothing to build.")
            return
        build_engine(groups, arguments.check, DEFAULT_CONTEXT)
    except (FileNotFoundError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
