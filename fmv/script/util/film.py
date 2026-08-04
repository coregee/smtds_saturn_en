"""Source-derived Sega FILM and Cinepak compatibility handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FILM_HEADER_SIZE = 64
SAMPLE_ENTRY_SIZE = 16
CINEPAK_FRAME_HEADER_SIZE = 12
CINEPAK_STRIP_HEADER_SIZE = 12
CINEPAK_CHUNK_HEADER_SIZE = 4
AUDIO_INFO = 0xFFFFFFFF
NON_KEYFRAME_FLAG = 1 << 31


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def _put_u32(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 4] = value.to_bytes(4, "big")


def _u24(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 3], "big")


def _put_u24(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 3] = value.to_bytes(3, "big")


@dataclass(frozen=True)
class FilmSample:
    payload: bytes
    info1: int
    info2: int

    @property
    def is_audio(self) -> bool:
        return self.info1 == AUDIO_INFO


@dataclass(frozen=True)
class FilmFile:
    header: bytes
    samples: tuple[FilmSample, ...]

    @property
    def version(self) -> bytes:
        return self.header[8:12]


@dataclass(frozen=True)
class CinepakContract:
    strip_count: int
    keyframe_interval: int


def read_film(path: Path) -> FilmFile:
    data = path.read_bytes()
    if len(data) < FILM_HEADER_SIZE or data[:4] != b"FILM":
        raise ValueError(f"{path}: not a Sega FILM file")
    if data[16:20] != b"FDSC" or data[48:52] != b"STAB":
        raise ValueError(f"{path}: malformed Sega FILM header")

    header_size = _u32(data, 4)
    sample_count = _u32(data, 60)
    expected_header_size = FILM_HEADER_SIZE + sample_count * SAMPLE_ENTRY_SIZE
    if header_size != expected_header_size or header_size > len(data):
        raise ValueError(
            f"{path}: malformed FILM sample table "
            f"(header {header_size}, expected {expected_header_size})"
        )
    if _u32(data, 52) != 16 + sample_count * SAMPLE_ENTRY_SIZE:
        raise ValueError(f"{path}: malformed FILM STAB size")

    samples: list[FilmSample] = []
    expected_offset = 0
    for index in range(sample_count):
        entry = FILM_HEADER_SIZE + index * SAMPLE_ENTRY_SIZE
        offset = _u32(data, entry)
        size = _u32(data, entry + 4)
        info1 = _u32(data, entry + 8)
        info2 = _u32(data, entry + 12)
        if offset != expected_offset or header_size + offset + size > len(data):
            raise ValueError(
                f"{path}: malformed FILM sample {index} "
                f"(offset {offset}, expected {expected_offset}, size {size})"
            )
        start = header_size + offset
        samples.append(FilmSample(data[start : start + size], info1, info2))
        expected_offset += size
    if header_size + expected_offset != len(data):
        raise ValueError(f"{path}: unreferenced bytes follow the FILM samples")
    return FilmFile(data[:FILM_HEADER_SIZE], tuple(samples))


def _cinepak_layout(payload: bytes, label: str) -> tuple[int, list[tuple[int, int]]]:
    if len(payload) < CINEPAK_FRAME_HEADER_SIZE:
        raise ValueError(f"{label}: truncated Cinepak frame")
    if _u24(payload, 1) != len(payload) - 8:
        raise ValueError(f"{label}: unexpected Sega Cinepak frame size")

    strip_count = int.from_bytes(payload[8:10], "big")
    strips: list[tuple[int, int]] = []
    position = CINEPAK_FRAME_HEADER_SIZE
    for strip_index in range(strip_count):
        if position + CINEPAK_STRIP_HEADER_SIZE > len(payload):
            raise ValueError(f"{label}: truncated Cinepak strip {strip_index}")
        strip_size = _u24(payload, position + 1)
        strip_end = position + strip_size
        if strip_size < CINEPAK_STRIP_HEADER_SIZE or strip_end > len(payload):
            raise ValueError(f"{label}: invalid Cinepak strip {strip_index} size")

        chunk_position = position + CINEPAK_STRIP_HEADER_SIZE
        while chunk_position < strip_end:
            if chunk_position + CINEPAK_CHUNK_HEADER_SIZE > strip_end:
                raise ValueError(
                    f"{label}: truncated Cinepak chunk in strip {strip_index}"
                )
            chunk_size = _u24(payload, chunk_position + 1)
            if (
                chunk_size < CINEPAK_CHUNK_HEADER_SIZE
                or chunk_position + chunk_size > strip_end
            ):
                raise ValueError(
                    f"{label}: invalid Cinepak chunk in strip {strip_index}"
                )
            chunk_position += chunk_size
        if chunk_position != strip_end:
            raise ValueError(f"{label}: invalid Cinepak strip boundary")
        strips.append((position, strip_end))
        position = strip_end
    if position != len(payload):
        raise ValueError(f"{label}: invalid Cinepak frame boundary")
    return strip_count, strips


def _cinepak_chunk_ids(payload: bytes, label: str) -> list[int]:
    _strip_count, strips = _cinepak_layout(payload, label)
    chunk_ids: list[int] = []
    for strip_start, strip_end in strips:
        chunk_position = strip_start + CINEPAK_STRIP_HEADER_SIZE
        while chunk_position < strip_end:
            chunk_ids.append(payload[chunk_position])
            chunk_position += _u24(payload, chunk_position + 1)
    return chunk_ids


def cinepak_contract(path: Path) -> CinepakContract:
    film = read_film(path)
    video = [sample for sample in film.samples if not sample.is_audio]
    if not video:
        raise ValueError(f"{path}: FILM file has no video samples")

    strip_counts = {
        _cinepak_layout(sample.payload, f"{path}: video sample {index}")[0]
        for index, sample in enumerate(video)
    }
    if len(strip_counts) != 1:
        raise ValueError(f"{path}: source changes Cinepak strip count between frames")
    strip_count = strip_counts.pop()
    if strip_count not in {1, 2, 3}:
        raise ValueError(
            f"{path}: unsupported source Cinepak strip count {strip_count}"
        )

    keyframes = [
        index
        for index, sample in enumerate(video)
        if not sample.info1 & NON_KEYFRAME_FLAG
    ]
    if not keyframes or keyframes[0] != 0:
        raise ValueError(f"{path}: source does not begin with a Cinepak keyframe")
    gaps = [
        current - prior
        for prior, current in zip(keyframes, keyframes[1:], strict=False)
    ]
    keyframe_interval = max(gaps, default=len(video))
    return CinepakContract(strip_count, keyframe_interval)


def _partial_codebook(chunk: bytes, label: str) -> bytearray:
    if chunk[0] not in {0x20, 0x22}:
        raise AssertionError(f"{label}: expected a full Cinepak codebook")
    entries = chunk[CINEPAK_CHUNK_HEADER_SIZE:]
    entry_size = 6
    if len(entries) % entry_size:
        raise ValueError(f"{label}: malformed full Cinepak codebook")

    partial = bytearray([chunk[0] + 1])
    partial.extend(b"\0\0\0")
    entry_count = len(entries) // entry_size
    for first in range(0, entry_count, 32):
        count = min(32, entry_count - first)
        flags = ((1 << count) - 1) << (32 - count)
        partial.extend(flags.to_bytes(4, "big"))
        start = first * entry_size
        partial.extend(entries[start : start + count * entry_size])
    _put_u24(partial, 1, len(partial))
    return partial


def _v1_vectors_as_stock_mode(
    chunk: bytes, *, is_keyframe: bool, label: str
) -> bytearray:
    if chunk[0] != 0x32:
        raise AssertionError(f"{label}: expected Cinepak V1-only vectors")
    vectors = chunk[CINEPAK_CHUNK_HEADER_SIZE:]
    converted = bytearray([0x30 if is_keyframe else 0x31])
    converted.extend(b"\0\0\0")
    group_size = 32 if is_keyframe else 16
    for first in range(0, len(vectors), group_size):
        group = vectors[first : first + group_size]
        if is_keyframe:
            flags = 0
        else:
            flags = sum(1 << (31 - 2 * index) for index in range(len(group)))
        converted.extend(flags.to_bytes(4, "big"))
        converted.extend(group)
    _put_u24(converted, 1, len(converted))
    return converted


def _align_cinepak(
    payload: bytes,
    label: str,
    allowed_chunk_ids: frozenset[int] | None = None,
) -> bytes:
    strip_count, strips = _cinepak_layout(payload, label)
    is_keyframe = payload[0] == 0
    aligned = bytearray(payload[:CINEPAK_FRAME_HEADER_SIZE])
    for strip_index, (strip_start, strip_end) in enumerate(strips):
        strip = bytearray(
            payload[strip_start : strip_start + CINEPAK_STRIP_HEADER_SIZE]
        )
        strip[0] = 0x10 if is_keyframe and strip_index == 0 else 0x11
        chunk_position = strip_start + CINEPAK_STRIP_HEADER_SIZE
        while chunk_position < strip_end:
            chunk_size = _u24(payload, chunk_position + 1)
            chunk = bytearray(payload[chunk_position : chunk_position + chunk_size])
            use_partial_codebooks = not (is_keyframe and strip_index == 0)
            if (
                use_partial_codebooks
                and chunk[0] in {0x20, 0x22}
                and allowed_chunk_ids is not None
                and chunk[0] + 1 in allowed_chunk_ids
            ):
                chunk = _partial_codebook(
                    chunk,
                    f"{label}: strip {strip_index} chunk {chunk[0]:#04x}",
                )
            if (
                chunk[0] == 0x32
                and allowed_chunk_ids is not None
                and 0x32 not in allowed_chunk_ids
            ):
                chunk = _v1_vectors_as_stock_mode(
                    chunk,
                    is_keyframe=is_keyframe,
                    label=f"{label}: strip {strip_index} vectors",
                )
            chunk.extend(b"\0" * (-len(chunk) % 4))
            _put_u24(chunk, 1, len(chunk))
            strip.extend(chunk)
            chunk_position += chunk_size
        strip.extend(b"\0" * (-len(strip) % 4))
        _put_u24(strip, 1, len(strip))
        if len(strip) % 4:
            raise AssertionError(f"{label}: failed to align strip {strip_index}")
        aligned.extend(strip)

    aligned[8:10] = strip_count.to_bytes(2, "big")
    _put_u24(aligned, 1, len(aligned) - 8)
    if len(aligned) % 4:
        raise AssertionError(f"{label}: failed to align Cinepak frame")
    return bytes(aligned)


def _write_film(header: bytes, samples: list[FilmSample]) -> bytes:
    output = bytearray(header)
    sample_table_size = 16 + len(samples) * SAMPLE_ENTRY_SIZE
    header_size = FILM_HEADER_SIZE + len(samples) * SAMPLE_ENTRY_SIZE
    _put_u32(output, 4, header_size)
    _put_u32(output, 52, sample_table_size)
    _put_u32(output, 60, len(samples))

    payload = bytearray()
    for sample in samples:
        if len(payload) % 4 or len(sample.payload) % 4:
            raise ValueError("Saturn FILM samples must be 4-byte aligned")
        output.extend(len(payload).to_bytes(4, "big"))
        output.extend(len(sample.payload).to_bytes(4, "big"))
        output.extend(sample.info1.to_bytes(4, "big"))
        output.extend(sample.info2.to_bytes(4, "big"))
        payload.extend(sample.payload)
    output.extend(payload)
    return bytes(output)


def normalize_for_saturn(source: Path, rebuilt: Path) -> None:
    """Restore the source FILM ABI around newly encoded video and audio."""

    original = read_film(source)
    encoded = read_film(rebuilt)
    source_video = [sample for sample in original.samples if not sample.is_audio]
    encoded_video = [sample for sample in encoded.samples if not sample.is_audio]
    if len(encoded_video) != len(source_video):
        raise ValueError(
            f"{rebuilt}: encoded video sample count {len(encoded_video)} "
            f"does not match source {len(source_video)}"
        )
    source_chunk_ids = frozenset(
        chunk_id
        for sample_index, sample in enumerate(source_video)
        for chunk_id in _cinepak_chunk_ids(
            sample.payload, f"{source}: source video sample {sample_index}"
        )
    )

    encoded_audio = [sample for sample in encoded.samples if sample.is_audio]
    source_audio_sizes = [
        len(sample.payload) for sample in original.samples if sample.is_audio
    ]
    encoded_audio_sizes = [len(sample.payload) for sample in encoded_audio]
    if sum(encoded_audio_sizes) != sum(source_audio_sizes):
        raise ValueError(
            f"{rebuilt}: encoded PCM byte count {sum(encoded_audio_sizes)} "
            f"does not match source {sum(source_audio_sizes)}"
        )
    if encoded_audio_sizes != source_audio_sizes:
        raise ValueError(
            f"{rebuilt}: encoded PCM packet boundaries {encoded_audio_sizes} "
            f"do not match source {source_audio_sizes}"
        )
    audio_samples = [
        FilmSample(sample.payload, AUDIO_INFO, 1) for sample in encoded_audio
    ]

    aligned_video = [
        FilmSample(
            _align_cinepak(
                encoded_sample.payload,
                f"{rebuilt}: encoded video sample {index}",
                source_chunk_ids,
            ),
            (source_sample.info1 & ~NON_KEYFRAME_FLAG)
            | (encoded_sample.info1 & NON_KEYFRAME_FLAG),
            source_sample.info2,
        )
        for index, (source_sample, encoded_sample) in enumerate(
            zip(source_video, encoded_video, strict=True)
        )
    ]

    ordered: list[FilmSample] = []
    video_index = 0
    audio_index = 0
    for source_sample in original.samples:
        if source_sample.is_audio:
            ordered.append(audio_samples[audio_index])
            audio_index += 1
        else:
            ordered.append(aligned_video[video_index])
            video_index += 1
    rebuilt.write_bytes(_write_film(original.header, ordered))


def validate_saturn_compatibility(source: Path, rebuilt: Path) -> None:
    original = read_film(source)
    encoded = read_film(rebuilt)
    if encoded.version != original.version:
        raise ValueError(
            f"{rebuilt}: changed FILM version "
            f"{original.version!r} -> {encoded.version!r}"
        )
    if encoded.header != original.header:
        raise ValueError(f"{rebuilt}: changed FILM base/FDSC/STAB header contract")

    source_kinds = [sample.is_audio for sample in original.samples]
    encoded_kinds = [sample.is_audio for sample in encoded.samples]
    if encoded_kinds != source_kinds:
        raise ValueError(f"{rebuilt}: changed FILM audio/video sample schedule")

    source_audio_sizes = [
        len(sample.payload) for sample in original.samples if sample.is_audio
    ]
    encoded_audio_sizes = [
        len(sample.payload) for sample in encoded.samples if sample.is_audio
    ]
    if encoded_audio_sizes != source_audio_sizes:
        raise ValueError(f"{rebuilt}: changed FILM PCM packet boundaries")

    contract = cinepak_contract(source)
    source_video = [sample for sample in original.samples if not sample.is_audio]
    source_chunk_ids = frozenset(
        chunk_id
        for sample_index, sample in enumerate(source_video)
        for chunk_id in _cinepak_chunk_ids(
            sample.payload, f"{source}: source video sample {sample_index}"
        )
    )
    keyframes: list[int] = []
    video_index = 0
    for sample_index, sample in enumerate(encoded.samples):
        if len(sample.payload) % 4:
            raise ValueError(f"{rebuilt}: sample {sample_index} is not 4-byte aligned")
        if sample.is_audio:
            continue
        strip_count, strips = _cinepak_layout(
            sample.payload, f"{rebuilt}: video sample {video_index}"
        )
        if strip_count != contract.strip_count:
            raise ValueError(
                f"{rebuilt}: video sample {video_index} uses {strip_count} strips; "
                f"source requires {contract.strip_count}"
            )
        payload_is_non_keyframe = sample.payload[0] != 0
        table_is_non_keyframe = bool(sample.info1 & NON_KEYFRAME_FLAG)
        if payload_is_non_keyframe != table_is_non_keyframe:
            raise ValueError(
                f"{rebuilt}: video sample {video_index} keyframe flag "
                "disagrees with its Cinepak header"
            )
        for strip_index, (strip_start, strip_end) in enumerate(strips):
            expected_strip_id = (
                0x10 if not payload_is_non_keyframe and strip_index == 0 else 0x11
            )
            if sample.payload[strip_start] != expected_strip_id:
                raise ValueError(
                    f"{rebuilt}: video sample {video_index} strip {strip_index} "
                    f"has type {sample.payload[strip_start]:#04x}; "
                    f"expected {expected_strip_id:#04x}"
                )
            if (strip_end - strip_start) % 4:
                raise ValueError(
                    f"{rebuilt}: video sample {video_index} strip "
                    f"{strip_index} is not 4-byte aligned"
                )
            chunk_position = strip_start + CINEPAK_STRIP_HEADER_SIZE
            while chunk_position < strip_end:
                chunk_size = _u24(sample.payload, chunk_position + 1)
                if chunk_size % 4:
                    raise ValueError(
                        f"{rebuilt}: video sample {video_index} contains "
                        "an unaligned Cinepak chunk"
                    )
                chunk_id = sample.payload[chunk_position]
                if chunk_id not in source_chunk_ids:
                    raise ValueError(
                        f"{rebuilt}: video sample {video_index} uses "
                        f"Cinepak chunk {chunk_id:#04x} absent from the source"
                    )
                chunk_position += chunk_size
        if not sample.info1 & NON_KEYFRAME_FLAG:
            keyframes.append(video_index)
        video_index += 1

    if not keyframes or keyframes[0] != 0:
        raise ValueError(f"{rebuilt}: does not begin with a Cinepak keyframe")
    gaps = [
        current - prior
        for prior, current in zip(keyframes, keyframes[1:], strict=False)
    ]
    if gaps and max(gaps) > contract.keyframe_interval:
        raise ValueError(
            f"{rebuilt}: keyframe interval {max(gaps)} exceeds "
            f"source limit {contract.keyframe_interval}"
        )
