import tempfile
import unittest
from pathlib import Path

from fmv.script.util import film


def cinepak_frame(*, strips: int, aligned: bool) -> bytes:
    frame = bytearray(12)
    frame[8:10] = strips.to_bytes(2, "big")
    for strip_index in range(strips):
        chunks = bytearray()
        for full_id in (0x20, 0x22):
            chunk_id = full_id + 1 if aligned and strip_index > 0 else full_id
            data = b"\x00" * (8 if aligned else 6)
            chunks.extend(bytes([chunk_id]) + (4 + len(data)).to_bytes(3, "big") + data)
        vector_id = 0x30 if aligned else 0x32
        vector_data = b"\x00" * (8 if aligned else 4)
        chunks.extend(
            bytes([vector_id]) + (4 + len(vector_data)).to_bytes(3, "big") + vector_data
        )
        strip = bytearray(12)
        strip[0] = 0x10 if not aligned or strip_index == 0 else 0x11
        strip[4:6] = (strip_index * 4).to_bytes(2, "big")
        strip[8:10] = ((strip_index + 1) * 4).to_bytes(2, "big")
        strip.extend(chunks)
        strip[1:4] = len(strip).to_bytes(3, "big")
        frame.extend(strip)
    frame[1:4] = (len(frame) - 8).to_bytes(3, "big")
    return bytes(frame)


def film_file(version: bytes, samples: list[tuple[bytes, int, int]]) -> bytes:
    header = bytearray(64)
    header[:4] = b"FILM"
    header[8:12] = version
    header[16:20] = b"FDSC"
    header[20:24] = (32).to_bytes(4, "big")
    header[24:28] = b"cvid"
    header[48:52] = b"STAB"
    header[56:60] = (600).to_bytes(4, "big")
    output = bytearray(header)
    header_size = 64 + 16 * len(samples)
    output[4:8] = header_size.to_bytes(4, "big")
    output[52:56] = (16 + 16 * len(samples)).to_bytes(4, "big")
    output[60:64] = len(samples).to_bytes(4, "big")
    offset = 0
    payloads = bytearray()
    for payload, info1, info2 in samples:
        output.extend(offset.to_bytes(4, "big"))
        output.extend(len(payload).to_bytes(4, "big"))
        output.extend(info1.to_bytes(4, "big"))
        output.extend(info2.to_bytes(4, "big"))
        payloads.extend(payload)
        offset += len(payload)
    output.extend(payloads)
    return bytes(output)


class FilmCompatibilityTests(unittest.TestCase):
    def test_normalize_restores_source_container_and_alignment(self) -> None:
        source_video = cinepak_frame(strips=2, aligned=True)
        encoded_video = cinepak_frame(strips=2, aligned=False)
        source_bytes = film_file(
            b"1.07",
            [
                (b"abcdefgh", film.AUDIO_INFO, 1),
                (source_video, 0, 50),
            ],
        )
        encoded_bytes = film_file(
            b"1.09",
            [
                (encoded_video, 0, 50),
                (b"abcdefgh", film.AUDIO_INFO, 1),
            ],
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.cpk"
            rebuilt = root / "rebuilt.cpk"
            source.write_bytes(source_bytes)
            rebuilt.write_bytes(encoded_bytes)

            film.normalize_for_saturn(source, rebuilt)
            film.validate_saturn_compatibility(source, rebuilt)
            result = film.read_film(rebuilt)

        self.assertEqual(result.version, b"1.07")
        self.assertTrue(result.samples[0].is_audio)
        self.assertEqual(result.samples[0].payload, b"abcdefgh")
        self.assertFalse(result.samples[1].is_audio)
        self.assertEqual(len(result.samples[1].payload) % 4, 0)
        strip_count, strips = film._cinepak_layout(
            result.samples[1].payload, "test frame"
        )
        self.assertEqual(strip_count, 2)
        self.assertTrue(all((end - start) % 4 == 0 for start, end in strips))
        self.assertEqual(
            film._cinepak_chunk_ids(result.samples[1].payload, "test frame"),
            [0x20, 0x22, 0x30, 0x21, 0x23, 0x30],
        )
        self.assertEqual(
            [result.samples[1].payload[start] for start, _end in strips],
            [0x10, 0x11],
        )

    def test_v1_only_delta_vectors_convert_to_stock_motion_mode(self) -> None:
        vectors = bytes(range(17))
        chunk = b"\x32" + (4 + len(vectors)).to_bytes(3, "big") + vectors
        converted = film._v1_vectors_as_stock_mode(
            chunk, is_keyframe=False, label="test"
        )
        self.assertEqual(converted[0], 0x31)
        self.assertEqual(int.from_bytes(converted[4:8], "big"), 0xAAAAAAAA)
        self.assertEqual(converted[8:24], vectors[:16])
        self.assertEqual(int.from_bytes(converted[24:28], "big"), 0x80000000)
        self.assertEqual(converted[28], vectors[16])

    def test_normalize_rejects_changed_pcm_byte_count(self) -> None:
        video = cinepak_frame(strips=1, aligned=True)
        source_bytes = film_file(
            b"1.06",
            [(b"abcdefgh", film.AUDIO_INFO, 1), (video, 0, 50)],
        )
        encoded_bytes = film_file(
            b"1.09",
            [(video, 0, 50), (b"abcd", film.AUDIO_INFO, 1)],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.cpk"
            rebuilt = root / "rebuilt.cpk"
            source.write_bytes(source_bytes)
            rebuilt.write_bytes(encoded_bytes)
            with self.assertRaisesRegex(ValueError, "PCM byte count"):
                film.normalize_for_saturn(source, rebuilt)


if __name__ == "__main__":
    unittest.main()
