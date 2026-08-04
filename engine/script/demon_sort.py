"""Shared English collation for runtime demon-name lists."""

from collections.abc import Iterable, Mapping, Sequence

IGNORED_CHARACTERS = frozenset(" -'")
RANK_SENTINEL = 0xFF


def english_name_key(name: str) -> str:
    """Return the case-insensitive dictionary key used by both game lists."""
    key: list[str] = []
    for character in name:
        if character in IGNORED_CHARACTERS:
            continue
        if not character.isascii() or not character.isalnum():
            raise ValueError(
                f"unsupported demon-name sort character {character!r} in {name!r}"
            )
        key.append(character.lower())
    if not key:
        raise ValueError(f"demon-name sort key is empty for {name!r}")
    return "".join(key)


def dense_rank_table(
    names: Sequence[str],
    *,
    count: int,
    append_sentinel: bool = True,
) -> bytes:
    """Encode dense English ranks for the first ``count`` demon IDs."""
    if not 0 < count <= len(names):
        raise ValueError(f"demon-name rank count {count} is outside {len(names)} names")
    keys = tuple(english_name_key(name) for name in names[:count])
    ordered_keys = sorted(set(keys))
    maximum_rank = RANK_SENTINEL - int(append_sentinel)
    if len(ordered_keys) - 1 > maximum_rank:
        raise ValueError(
            f"demon-name ranks need {len(ordered_keys)} values; "
            f"maximum is {maximum_rank + 1}"
        )
    rank_by_key = {key: rank for rank, key in enumerate(ordered_keys)}
    result = bytearray(rank_by_key[key] for key in keys)
    if append_sentinel:
        result.append(RANK_SENTINEL)
    return bytes(result)


def encode_sorted_pool(
    names: Sequence[str],
    codes: Mapping[str, int],
) -> tuple[bytes, bytes]:
    """Encode names by English order while retaining ID-indexed u16 offsets.

    The runtime can compare the resulting offsets as complete name ranks. Exact
    duplicate display names share storage; runtime sorters use demon ID as a
    deterministic secondary key when those offsets are equal.
    """
    names_by_key: dict[str, set[str]] = {}
    for name in names:
        names_by_key.setdefault(english_name_key(name), set()).add(name)
    collisions = {
        key: values for key, values in names_by_key.items() if len(values) > 1
    }
    if collisions:
        details = ", ".join(
            f"{key!r}: {sorted(values)!r}" for key, values in sorted(collisions.items())
        )
        raise ValueError(
            "distinct demon names have the same English sort key: " + details
        )

    offset_by_name: dict[str, int] = {}
    pool = bytearray()
    for key in sorted(names_by_key):
        name = next(iter(names_by_key[key]))
        offset_by_name[name] = len(pool)
        try:
            pool.extend(codes[character] for character in name)
        except KeyError as error:
            raise ValueError(
                f"unsupported FONT12 character {error.args[0]!r} in {name!r}"
            ) from error
        pool.append(0xFF)

    if len(pool) > 0xFFFF:
        raise ValueError("sorted demon-name pool exceeds 16-bit offsets")
    offsets = bytearray()
    for name in names:
        offsets.extend(offset_by_name[name].to_bytes(2, "big"))
    return bytes(offsets), bytes(pool)


def sorted_indices(names: Iterable[str]) -> tuple[int, ...]:
    """Return deterministic record order for diagnostics and tests."""
    materialized = tuple(names)
    return tuple(
        sorted(
            range(len(materialized)),
            key=lambda index: (english_name_key(materialized[index]), index),
        )
    )
