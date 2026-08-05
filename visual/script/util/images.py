"""Discover and encode Devil Summoner's proven Saturn image families."""

from __future__ import annotations

import hashlib
import json
import struct
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from project_paths import EXTRACTED_ROOT, VISUAL_ROOT

IMAGE_ROOT = VISUAL_ROOT / "image"
GENERATED_ROOT = VISUAL_ROOT / "generated"
MANIFEST_PATH = GENERATED_ROOT / "images.json"

RGB555_ENCODING = "saturn_rgb555_be"
RGB888_ENCODING = "saturn_rgb888_be"
INDEXED8_RGB555_ENCODING = "saturn_indexed8_rgb555_be"
MANIFEST_ENCODING = "saturn_images"
LEGACY_MANIFEST_VERSION = 3
MANIFEST_VERSION = 4
TEXTURE_LOAD_BASE = 0x00250000
TITLE_LOAD_BASE = 0x06020000
TITLE_DESCRIPTOR_SCAN_START = 0x16000
TITLE_DESCRIPTOR_SCAN_END = 0x16644


@dataclass(frozen=True)
class ImageAsset:
    source: str
    image: str
    offset: int
    width: int
    height: int
    layout: str = "linear"
    encoding: str = RGB555_ENCODING
    palette_offset: int | None = None
    palette_entries: int | None = None

    @property
    def byte_length(self) -> int:
        bytes_per_pixel = {
            RGB555_ENCODING: 2,
            RGB888_ENCODING: 4,
            INDEXED8_RGB555_ENCODING: 1,
        }.get(self.encoding)
        if bytes_per_pixel is None:
            raise ValueError(f"{self.image}: unsupported encoding {self.encoding!r}")
        return self.width * self.height * bytes_per_pixel

    def manifest_row(self, source_data: bytes) -> dict[str, object]:
        image = decode_image(source_data, self)
        return {
            "source": self.source,
            "image": self.image,
            "encoding": self.encoding,
            "layout": self.layout,
            "offset": self.offset,
            "palette_offset": self.palette_offset,
            "palette_entries": self.palette_entries,
            "length": self.byte_length,
            "width": self.width,
            "height": self.height,
            "pixel_sha256": pixel_sha256(image),
        }


@dataclass(frozen=True)
class SaveLoadImageRecord:
    """One game-owned SAVE/LOAD storage-selector raster and its descriptor."""

    key: str
    asset: ImageAsset
    descriptor_offset: int
    expected_sha256: str

    @property
    def translation_file(self) -> str:
        return f"saveload_{self.key}.png"


SAVELOAD_OVERLAY_BASE = 0x06020000
SAVELOAD_IMAGE_RECORDS = (
    SaveLoadImageRecord(
        "internal_selected",
        ImageAsset("SAVE.BIN", "SAVE/storage/internal_selected.png", 0x383F0, 104, 24),
        0x50590,
        "1bf1e8a4cf7f80bc387683a61c7b6221aad15b4ed1129bcd442c009d4ec0026b",
    ),
    SaveLoadImageRecord(
        "internal_idle",
        ImageAsset("SAVE.BIN", "SAVE/storage/internal_idle.png", 0x37070, 104, 24),
        0x505A0,
        "c39e2b11812aa43df80234a57af570599bc60b2876896c8673a41e0fc730055b",
    ),
    SaveLoadImageRecord(
        "cartridge_selected",
        ImageAsset("SAVE.BIN", "SAVE/storage/cartridge_selected.png", 0x3FD30, 104, 24),
        0x505B0,
        "2c5e4a80888281edece1373622617da24eea827ad18ff7bab5c798b348014d53",
    ),
    SaveLoadImageRecord(
        "cartridge_idle",
        ImageAsset("SAVE.BIN", "SAVE/storage/cartridge_idle.png", 0x34970, 104, 24),
        0x505C0,
        "8cc48856551be38b15a98e6b3d7a93a63a450afb8a59a543931406d8518d2254",
    ),
    SaveLoadImageRecord(
        "internal_selected",
        ImageAsset("LOAD.BIN", "LOAD/storage/internal_selected.png", 0x380EC, 104, 24),
        0x51684,
        "1bf1e8a4cf7f80bc387683a61c7b6221aad15b4ed1129bcd442c009d4ec0026b",
    ),
    SaveLoadImageRecord(
        "internal_idle",
        ImageAsset("LOAD.BIN", "LOAD/storage/internal_idle.png", 0x36D6C, 104, 24),
        0x51694,
        "c39e2b11812aa43df80234a57af570599bc60b2876896c8673a41e0fc730055b",
    ),
    SaveLoadImageRecord(
        "cartridge_selected",
        ImageAsset("LOAD.BIN", "LOAD/storage/cartridge_selected.png", 0x3FA2C, 104, 24),
        0x516A4,
        "2c5e4a80888281edece1373622617da24eea827ad18ff7bab5c798b348014d53",
    ),
    SaveLoadImageRecord(
        "cartridge_idle",
        ImageAsset("LOAD.BIN", "LOAD/storage/cartridge_idle.png", 0x3466C, 104, 24),
        0x516B4,
        "8cc48856551be38b15a98e6b3d7a93a63a450afb8a59a543931406d8518d2254",
    ),
)


def saveload_image_records(source: str) -> tuple[SaveLoadImageRecord, ...]:
    records = tuple(
        record for record in SAVELOAD_IMAGE_RECORDS if record.asset.source == source
    )
    if len(records) != 4:
        raise ValueError(f"{source}: no complete SAVE/LOAD image record set")
    return records


def validate_saveload_image_records(source_data: bytes, source: str) -> None:
    """Assert the Rev B image payloads and game-side upload descriptors."""

    for record in saveload_image_records(source):
        asset = record.asset
        end = asset.offset + asset.byte_length
        if end > len(source_data):
            raise ValueError(f"{source}: too small for {asset.image}")
        actual_sha256 = hashlib.sha256(source_data[asset.offset : end]).hexdigest()
        if actual_sha256 != record.expected_sha256:
            raise ValueError(
                f"{source}: source pixels changed for {asset.image}; "
                f"expected SHA-256 {record.expected_sha256}, found {actual_sha256}"
            )
        expected_descriptor = struct.pack(
            ">HHHHII",
            asset.width,
            asset.height,
            1,
            0,
            SAVELOAD_OVERLAY_BASE + asset.offset,
            0,
        )
        actual_descriptor = source_data[
            record.descriptor_offset : record.descriptor_offset + 16
        ]
        if actual_descriptor != expected_descriptor:
            raise ValueError(
                f"{source}: image descriptor changed for {asset.image} at "
                f"0x{record.descriptor_offset:X}"
            )


ROOT_RASTERS = {
    "BAD_P1.CHR": (0, 64, 64, "tiled8"),
    "BAD_P2.CHR": (0, 64, 64, "tiled8"),
    "GOMI.CHR": (0, 96, 56, "tiled8"),
    "P_PANEL.CHR": (0, 144, 112, "linear"),
    "TUKI.CHR": (0, 184, 128, "tiled8"),
    "HP_M.CHR": (0, 24, 3, "linear"),
    "EACHR.COF": (0, 320, 96, "tiled8"),
    "COMBDATA/TESTBG.BIN": (0, 320, 224, "linear"),
    "MMP/MMBG00.COF": (0x84, 352, 224, "tiled8"),
    "MMP/NAMEBG.COF": (0x84, 352, 224, "tiled8"),
}

TEX3D_MODELS = {
    "ARCA_CHR": "ARCADE",
    "ASU_CHR": "ASU",
    "CHI_CHR": "CHI",
    "CYU_CHR": "CYU",
    "DOUT_CHR": "DOUT00",
    "EX_CHR": "EX",
    "GIRL_CHR": "GIRL00",
    "HAKU_CHR": "HAKU",
    "HBIN_CHR": "HBIN00",
    "HDAI_CHR": "HDAI00",
    "HDEN_CHR": "HDEN00",
    "HGIN_CHR": "HGIN00",
    "HHAK_CHR": "HHAK00",
    "HMAN_CHR": "HMAN00",
    "HOUT_CHR": "HOUT00",
    "HST_CHR": "HST00",
    "HTOS_CHR": "HTOS00",
    "HYA_CHR": "HYA00",
    "ICYU_CHR": "ICYU",
    "IDAI_CHR": "IDAI00",
    "IDEN_CHR": "IDEN00",
    "IGIN_CHR": "IGIN00",
    "IMAN_CHR": "IMAN00",
    "IST_CHR": "IST00",
    "ITOS_CHR": "ITOS00",
    "ITV_CHR": "ITV00",
    "IYA_CHR": "IYA00",
    "IYOZ_CHR": "IYOZ00",
    "KO_CHR": "KO",
    "KOUJ_CHR": "KOUJI00",
    "KUMI_CHR": "KUMI",
    "KYOZ_CHR": "KYOZ00",
    "MU_CHR": "MU",
    "SHI_CHR": "SHI00",
    "ZATU_CHR": "ZATU00",
    "ZATUFCHR": "ZATU_F",
}

TITLE_INDEXED_IMAGES = (
    ImageAsset(
        "TITLE.BIN",
        "TITLE/devil_summoner.png",
        0x16644,
        288,
        53,
        encoding=INDEXED8_RGB555_ENCODING,
        palette_offset=0x1A1E4,
        # Startup copies 200 words, but fade paths update only indices 0..197.
        palette_entries=198,
    ),
    ImageAsset(
        "TITLE.BIN",
        "TITLE/shin_megami_tensei.png",
        0x1A3E4,
        288,
        36,
        encoding=INDEXED8_RGB555_ENCODING,
        palette_offset=0x1CC64,
        palette_entries=64,
    ),
    ImageAsset(
        "TITLE.BIN",
        "TITLE/emblems.png",
        0x1CE64,
        120,
        28,
        encoding=INDEXED8_RGB555_ENCODING,
        palette_offset=0x1DB84,
        palette_entries=64,
    ),
)

TITLE_PRESS_START_GLYPHS = tuple(
    ImageAsset(
        "TITLE.BIN",
        f"TITLE/press_start_button/{index:02d}_{character.casefold()}.png",
        offset,
        16,
        12,
    )
    for index, (character, offset) in enumerate(
        zip(
            "PRESSSTARTBUTTON",
            (
                0x1DD84,
                0x1DF04,
                0x1E084,
                0x1E204,
                0x1E384,
                0x1E504,
                0x1E684,
                0x1E804,
                0x1E984,
                0x1EB04,
                0x1EC84,
                0x1EE04,
                0x1F104,
                0x1EF84,
                0x1F284,
                0x1F404,
            ),
            strict=True,
        )
    )
)

TITLE_START_BUTTON_GLYPHS = tuple(
    ImageAsset(
        "TITLE.BIN",
        f"TITLE/start_button/{index:02d}_{character.casefold()}.png",
        offset,
        width,
        9,
    )
    for index, (character, offset, width) in enumerate(
        zip(
            "STARTBUTTON",
            (
                0x1F584,
                0x1F6A4,
                0x1F7C4,
                0x1F8E4,
                0x1FA04,
                0x1FB24,
                0x1FC44,
                0x1FD64,
                0x1FE84,
                0x1FF14,
                0x20034,
            ),
            (16, 16, 16, 16, 16, 16, 16, 16, 8, 16, 16),
            strict=True,
        )
    )
)

TITLE_BIN_RGB555_IMAGES = (
    ImageAsset(
        "TITLE.BIN",
        "TITLE/copyright_atlus_1995.png",
        0x20154,
        120,
        15,
    ),
    *TITLE_PRESS_START_GLYPHS,
    *TITLE_START_BUTTON_GLYPHS,
)

TITLE_BIN_IMAGES = (*TITLE_INDEXED_IMAGES, *TITLE_BIN_RGB555_IMAGES)

# TITLE.BIN loads TESTLOGO.COF to 0x00250000 at runtime from the call sequence
# starting at 0x060281D2. The source is exactly one 352x240, 32-bit direct-color
# raster containing the fully composed title artwork. Each big-endian pixel is
# 0x80BBGGRR: the leading control byte remains intact during repacking.
TITLE_FULL_RASTER_IMAGE = ImageAsset(
    "TESTLOGO.COF",
    "TITLE/full_title_screen.png",
    0,
    352,
    240,
    encoding=RGB888_ENCODING,
)

TITLE_IMAGES = (*TITLE_BIN_IMAGES, TITLE_FULL_RASTER_IMAGE)

TITLE_PALETTE_RUNTIME_LOADS = (
    # asset, source-pointer pool, destination-pointer pool, CRAM destination
    (TITLE_INDEXED_IMAGES[2], 0x7A7C, 0x7A78, 0x25F00200),
    (TITLE_INDEXED_IMAGES[1], 0x7A88, 0x7A84, 0x25F00400),
    (TITLE_INDEXED_IMAGES[0], 0x7A90, 0x7A8C, 0x25F00600),
)

TITLE_IMAGE_RECORDS = (
    (0x16060, TITLE_INDEXED_IMAGES[2]),
    (0x16070, TITLE_INDEXED_IMAGES[1]),
    (0x16080, TITLE_INDEXED_IMAGES[0]),
    (0x16480, TITLE_BIN_RGB555_IMAGES[0]),
    *(
        (0x16490 + index * 0x10, asset)
        for index, asset in enumerate(TITLE_PRESS_START_GLYPHS)
    ),
    *(
        (0x16590 + index * 0x10, asset)
        for index, asset in enumerate(TITLE_START_BUTTON_GLYPHS)
    ),
)


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def flatten_rgb(image: Image.Image) -> Image.Image:
    """Render an image over black, matching formats that cannot store alpha."""
    if "A" not in image.getbands() and "transparency" not in image.info:
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def pixel_sha256(image: Image.Image) -> str:
    rgb = flatten_rgb(image)
    digest = hashlib.sha256()
    digest.update(struct.pack(">II", rgb.width, rgb.height))
    digest.update(rgb.tobytes())
    return digest.hexdigest()


def decode_rgb555(source_data: bytes, asset: ImageAsset) -> Image.Image:
    end = asset.offset + asset.byte_length
    if asset.offset < 0 or end > len(source_data):
        raise ValueError(f"{asset.source}: image {asset.image} is outside its source")
    encoded = source_data[asset.offset : end]
    pixels = asset.width * asset.height
    output = bytearray(pixels * 3)
    for source_index in range(pixels):
        offset = source_index * 2
        value = (encoded[offset] << 8) | encoded[offset + 1]
        red = value & 0x1F
        green = (value >> 5) & 0x1F
        blue = (value >> 10) & 0x1F
        display_index = display_pixel_index(asset, source_index)
        output_offset = display_index * 3
        output[output_offset] = (red << 3) | (red >> 2)
        output[output_offset + 1] = (green << 3) | (green >> 2)
        output[output_offset + 2] = (blue << 3) | (blue >> 2)
    return Image.frombytes("RGB", (asset.width, asset.height), bytes(output))


def decode_rgb888(source_data: bytes, asset: ImageAsset) -> Image.Image:
    end = asset.offset + asset.byte_length
    if asset.offset < 0 or end > len(source_data):
        raise ValueError(f"{asset.source}: image {asset.image} is outside its source")
    encoded = source_data[asset.offset : end]
    pixels = asset.width * asset.height
    output = bytearray(pixels * 3)
    for source_index in range(pixels):
        source_offset = source_index * 4
        display_index = display_pixel_index(asset, source_index)
        output_offset = display_index * 3
        output[output_offset] = encoded[source_offset + 3]
        output[output_offset + 1] = encoded[source_offset + 2]
        output[output_offset + 2] = encoded[source_offset + 1]
    return Image.frombytes("RGB", (asset.width, asset.height), bytes(output))


def _decode_rgb555_value(value: int) -> tuple[int, int, int]:
    red = value & 0x1F
    green = (value >> 5) & 0x1F
    blue = (value >> 10) & 0x1F
    return (
        (red << 3) | (red >> 2),
        (green << 3) | (green >> 2),
        (blue << 3) | (blue >> 2),
    )


def _indexed_palette(
    source_data: bytes, asset: ImageAsset
) -> tuple[tuple[int, int, int], ...]:
    if asset.palette_offset is None or asset.palette_entries is None:
        raise ValueError(f"{asset.image}: indexed image has no palette contract")
    end = asset.palette_offset + asset.palette_entries * 2
    if asset.palette_offset < 0 or end > len(source_data):
        raise ValueError(
            f"{asset.source}: palette for {asset.image} is outside its source"
        )
    return tuple(
        _decode_rgb555_value(struct.unpack_from(">H", source_data, offset)[0])
        for offset in range(asset.palette_offset, end, 2)
    )


def decode_indexed8(source_data: bytes, asset: ImageAsset) -> Image.Image:
    end = asset.offset + asset.byte_length
    if asset.offset < 0 or end > len(source_data):
        raise ValueError(f"{asset.source}: image {asset.image} is outside its source")
    palette = _indexed_palette(source_data, asset)
    encoded = source_data[asset.offset : end]
    output = bytearray(asset.width * asset.height * 3)
    for source_index, palette_index in enumerate(encoded):
        if palette_index >= len(palette):
            raise ValueError(
                f"{asset.image}: palette index {palette_index} exceeds its "
                f"{len(palette)}-entry runtime palette"
            )
        display_index = display_pixel_index(asset, source_index)
        output_offset = display_index * 3
        output[output_offset : output_offset + 3] = bytes(palette[palette_index])
    return Image.frombytes("RGB", (asset.width, asset.height), bytes(output))


def decode_image(source_data: bytes, asset: ImageAsset) -> Image.Image:
    if asset.encoding == RGB555_ENCODING:
        return decode_rgb555(source_data, asset)
    if asset.encoding == RGB888_ENCODING:
        return decode_rgb888(source_data, asset)
    if asset.encoding == INDEXED8_RGB555_ENCODING:
        return decode_indexed8(source_data, asset)
    raise ValueError(f"{asset.image}: unsupported encoding {asset.encoding!r}")


def encode_rgb555(target: bytearray, asset: ImageAsset, image: Image.Image) -> None:
    if image.size != (asset.width, asset.height):
        raise ValueError(
            f"{asset.image}: image is {image.width}x{image.height}; "
            f"expected {asset.width}x{asset.height}"
        )
    pixels = flatten_rgb(image).tobytes()
    for source_index in range(asset.width * asset.height):
        source_offset = asset.offset + source_index * 2
        pixel_offset = display_pixel_index(asset, source_index) * 3
        original = (target[source_offset] << 8) | target[source_offset + 1]
        red = (pixels[pixel_offset] * 31 + 127) // 255
        green = (pixels[pixel_offset + 1] * 31 + 127) // 255
        blue = (pixels[pixel_offset + 2] * 31 + 127) // 255
        value = (original & 0x8000) | (blue << 10) | (green << 5) | red
        target[source_offset] = value >> 8
        target[source_offset + 1] = value & 0xFF


def encode_rgb888(target: bytearray, asset: ImageAsset, image: Image.Image) -> None:
    if image.size != (asset.width, asset.height):
        raise ValueError(
            f"{asset.image}: image is {image.width}x{image.height}; "
            f"expected {asset.width}x{asset.height}"
        )
    pixels = flatten_rgb(image).tobytes()
    for source_index in range(asset.width * asset.height):
        target_offset = asset.offset + source_index * 4
        pixel_offset = display_pixel_index(asset, source_index) * 3
        target[target_offset + 1] = pixels[pixel_offset + 2]
        target[target_offset + 2] = pixels[pixel_offset + 1]
        target[target_offset + 3] = pixels[pixel_offset]


def encode_indexed8(target: bytearray, asset: ImageAsset, image: Image.Image) -> None:
    if image.size != (asset.width, asset.height):
        raise ValueError(
            f"{asset.image}: image is {image.width}x{image.height}; "
            f"expected {asset.width}x{asset.height}"
        )
    palette = _indexed_palette(bytes(target), asset)
    palette_indexes: dict[tuple[int, int, int], int] = {}
    for index, color in enumerate(palette):
        palette_indexes.setdefault(color, index)
    pixels = image.convert("RGB").tobytes()
    unknown: set[tuple[int, int, int]] = set()
    for source_index in range(asset.width * asset.height):
        target_offset = asset.offset + source_index
        pixel_offset = display_pixel_index(asset, source_index) * 3
        color = tuple(pixels[pixel_offset : pixel_offset + 3])
        original_index = target[target_offset]
        if palette[original_index] == color:
            continue
        palette_index = palette_indexes.get(color)
        if palette_index is None:
            unknown.add(color)
            continue
        target[target_offset] = palette_index
    if unknown:
        sample = ", ".join(f"#{r:02X}{g:02X}{b:02X}" for r, g, b in sorted(unknown)[:5])
        raise ValueError(
            f"{asset.image}: {len(unknown)} color(s) are absent from its fixed palette "
            f"({sample}); sample colors from the extracted PNG"
        )


def _encode_rgb555_value(color: tuple[int, int, int]) -> int:
    red, green, blue = ((channel * 31 + 127) // 255 for channel in color)
    return red | (green << 5) | (blue << 10)


def _rgb555_distance(left: int, right: int) -> int:
    left_red = left & 0x1F
    left_green = (left >> 5) & 0x1F
    left_blue = (left >> 10) & 0x1F
    right_red = right & 0x1F
    right_green = (right >> 5) & 0x1F
    right_blue = (right >> 10) & 0x1F
    return (
        3 * (left_red - right_red) ** 2
        + 6 * (left_green - right_green) ** 2
        + 2 * (left_blue - right_blue) ** 2
    )


def _adaptive_indexed_pixels(
    image: Image.Image, asset: ImageAsset
) -> tuple[tuple[int, ...], tuple[bool, ...]]:
    if image.size != (asset.width, asset.height):
        raise ValueError(
            f"{asset.image}: image is {image.width}x{image.height}; "
            f"expected {asset.width}x{asset.height}"
        )
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    rgba = image.convert("RGBA")
    rgba_pixels = rgba.tobytes()
    colors = []
    transparent = []
    for display_index in range(asset.width * asset.height):
        offset = display_index * 4
        red, green, blue, alpha = rgba_pixels[offset : offset + 4]
        if has_alpha:
            if alpha == 0:
                colors.append(0)
                transparent.append(True)
                continue
            # TITLE.BIN cannot blend indexed pixels. Preserve the source's
            # antialiasing as opaque RGB555 shades over the title's black matte
            # instead of turning partial alpha into a visible Bayer pattern.
            color = _encode_rgb555_value(
                tuple((channel * alpha + 127) // 255 for channel in (red, green, blue))
            )
            invisible = False
        else:
            color = _encode_rgb555_value((red, green, blue))
            # Extracted indexed overlays use RGB black for transparent index 0.
            invisible = color == 0
        colors.append(color)
        transparent.append(invisible)
    return tuple(colors), tuple(transparent)


def _adaptive_palette_colors(
    counts: Counter[int], limit: int, reserved: set[int]
) -> list[int]:
    candidates = Counter(
        {color: count for color, count in counts.items() if color not in reserved}
    )
    if limit <= 0:
        if candidates:
            raise ValueError("adaptive indexed palette has no free entries")
        return []
    if len(candidates) <= limit:
        return [
            color
            for color, _count in sorted(
                candidates.items(), key=lambda row: (-row[1], row[0])
            )
        ]

    pixels = []
    for color, count in sorted(candidates.items()):
        pixels.extend([_decode_rgb555_value(color)] * count)
    strip = Image.new("RGB", (len(pixels), 1))
    strip.putdata(pixels)
    quantized = strip.quantize(
        colors=limit,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    palette = quantized.getpalette()
    usage = Counter(quantized.tobytes())
    colors = []
    seen = set(reserved)
    for index, _count in sorted(usage.items(), key=lambda row: (-row[1], row[0])):
        offset = index * 3
        color = _encode_rgb555_value(tuple(palette[offset : offset + 3]))
        if color and color not in seen:
            colors.append(color)
            seen.add(color)

    # RGB555 snapping can merge median-cut centers. Refill those slots with
    # the weighted worst-represented source colors to retain the full budget.
    while len(colors) < limit:
        remaining = [color for color in candidates if color not in seen]
        if not remaining:
            break
        centers = tuple(seen)
        color = max(
            remaining,
            key=lambda candidate: (
                candidates[candidate]
                * min(_rgb555_distance(candidate, center) for center in centers),
                candidates[candidate],
                -candidate,
            ),
        )
        colors.append(color)
        seen.add(color)
    return colors


def encode_adaptive_indexed8_group(
    target: bytearray,
    assets: Sequence[ImageAsset],
    replacements: Mapping[ImageAsset, Image.Image],
) -> None:
    """Rebuild one shared RGB555 palette while protecting unchanged consumers."""
    if not replacements:
        return
    if any(asset not in assets for asset in replacements):
        raise ValueError("adaptive indexed replacement is outside its palette group")
    sources = {asset.source for asset in assets}
    palette_offsets = {asset.palette_offset for asset in assets}
    palette_entries = {asset.palette_entries for asset in assets}
    if (
        len(sources) != 1
        or len(palette_offsets) != 1
        or None in palette_offsets
        or len(palette_entries) != 1
        or None in palette_entries
    ):
        raise ValueError("adaptive indexed assets do not share one source palette")
    if any(asset.encoding != INDEXED8_RGB555_ENCODING for asset in assets):
        raise ValueError("adaptive indexed group contains a non-indexed image")
    palette_offset = next(iter(palette_offsets))
    entry_count = next(iter(palette_entries))
    assert palette_offset is not None
    assert entry_count is not None
    if palette_offset < 0 or palette_offset + entry_count * 2 > len(target):
        raise ValueError("adaptive indexed palette is outside its source")

    original = bytes(target)
    original_palette = [
        struct.unpack_from(">H", original, palette_offset + index * 2)[0]
        for index in range(entry_count)
    ]
    reserved_indexes = {0}
    opaque_black = next(
        (index for index, value in enumerate(original_palette) if value == 0x8000),
        None,
    )
    if opaque_black is not None:
        reserved_indexes.add(opaque_black)
    for asset in assets:
        if asset in replacements:
            continue
        end = asset.offset + asset.byte_length
        if asset.offset < 0 or end > len(original):
            raise ValueError(
                f"{asset.source}: image {asset.image} is outside its source"
            )
        reserved_indexes.update(original[asset.offset : end])

    for asset, image in replacements.items():
        end = asset.offset + asset.byte_length
        source_indexes = original[asset.offset : end]
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        if (
            not has_alpha
            and opaque_black is not None
            and 0 in source_indexes
            and opaque_black in source_indexes
        ):
            raise ValueError(
                f"{asset.image}: RGBA input is required to distinguish transparent "
                "and opaque black"
            )

    available_indexes = [
        index for index in range(entry_count) if index not in reserved_indexes
    ]
    prepared = {
        asset: _adaptive_indexed_pixels(image, asset)
        for asset, image in replacements.items()
    }
    counts: Counter[int] = Counter()
    for colors, transparency in prepared.values():
        counts.update(
            color
            for color, invisible in zip(colors, transparency, strict=True)
            if not invisible
        )
    reserved_colors = {original_palette[index] & 0x7FFF for index in reserved_indexes}
    new_colors = _adaptive_palette_colors(
        counts, len(available_indexes), reserved_colors
    )

    palette_values = [0] * entry_count
    for index in reserved_indexes:
        palette_values[index] = original_palette[index]
    for index, color in zip(available_indexes, new_colors, strict=False):
        palette_values[index] = 0x8000 | color
    for index, value in enumerate(palette_values):
        struct.pack_into(">H", target, palette_offset + index * 2, value)

    opaque_palette = [
        (index, value & 0x7FFF)
        for index, value in enumerate(palette_values)
        if index != 0 and value != 0
    ]
    if not opaque_palette:
        raise ValueError("adaptive indexed palette has no opaque colors")
    exact: dict[int, int] = {}
    for index, color in opaque_palette:
        exact.setdefault(color, index)
    nearest: dict[int, int] = {}
    for asset, (colors, transparency) in prepared.items():
        for source_index in range(asset.width * asset.height):
            display_index = display_pixel_index(asset, source_index)
            color = colors[display_index]
            invisible = transparency[display_index]
            target_offset = asset.offset + source_index
            if invisible:
                target[target_offset] = 0
                continue
            palette_index = exact.get(color)
            if palette_index is None:
                palette_index = nearest.get(color)
            if palette_index is None:
                palette_index = min(
                    opaque_palette,
                    key=lambda row: (_rgb555_distance(color, row[1]), row[0]),
                )[0]
                nearest[color] = palette_index
            target[target_offset] = palette_index


def encode_image(target: bytearray, asset: ImageAsset, image: Image.Image) -> None:
    if asset.encoding == RGB555_ENCODING:
        encode_rgb555(target, asset, image)
        return
    if asset.encoding == RGB888_ENCODING:
        encode_rgb888(target, asset, image)
        return
    if asset.encoding == INDEXED8_RGB555_ENCODING:
        encode_indexed8(target, asset, image)
        return
    raise ValueError(f"{asset.image}: unsupported encoding {asset.encoding!r}")


def display_pixel_index(asset: ImageAsset, source_index: int) -> int:
    if asset.layout == "linear":
        return source_index
    if asset.layout != "tiled8":
        raise ValueError(f"{asset.image}: unsupported pixel layout {asset.layout!r}")
    if asset.width % 8 or asset.height % 8:
        raise ValueError(f"{asset.image}: tiled8 dimensions must be multiples of 8")
    tile_index, within = divmod(source_index, 64)
    tile_x = tile_index % (asset.width // 8)
    tile_y = tile_index // (asset.width // 8)
    within_y, within_x = divmod(within, 8)
    return (tile_y * 8 + within_y) * asset.width + tile_x * 8 + within_x


def _standalone_assets() -> list[ImageAsset]:
    assets = []
    for source, (offset, width, height, layout) in ROOT_RASTERS.items():
        path = EXTRACTED_ROOT / source
        expected = offset + width * height * 2
        if not path.is_file():
            raise ValueError(f"registered visual source is missing: {path}")
        if path.stat().st_size < expected:
            raise ValueError(f"{source}: too small for its registered raster")
        image = f"{Path(source).with_suffix('').as_posix()}.png"
        assets.append(ImageAsset(source, image, offset, width, height, layout))
    return assets


def _validate_title_palette_runtime(source_data: bytes) -> None:
    for (
        asset,
        source_pool,
        destination_pool,
        destination,
    ) in TITLE_PALETTE_RUNTIME_LOADS:
        assert asset.palette_offset is not None
        source_pointer = struct.unpack_from(">I", source_data, source_pool)[0]
        destination_pointer = struct.unpack_from(">I", source_data, destination_pool)[0]
        if source_pointer != TITLE_LOAD_BASE + asset.palette_offset:
            raise ValueError(
                f"TITLE.BIN: runtime palette source changed for {asset.image}"
            )
        if destination_pointer != destination:
            raise ValueError(
                f"TITLE.BIN: runtime CRAM destination changed for {asset.image}"
            )

    # Exact-copy startup loads 64 words for each small overlay and 200 for the
    # main logo. Fade processing starts its counter at two, so the main logo's
    # replacement budget is deliberately capped at indices 0..197.
    if (
        struct.unpack_from(">H", source_data, 0x78E6)[0] != 0xE640
        or struct.unpack_from(">H", source_data, 0x78EE)[0] != 0xE640
        or struct.unpack_from(">H", source_data, 0x7A6C)[0] != 200
        or struct.unpack_from(">H", source_data, 0x7A72)[0] != 128
        or struct.unpack_from(">H", source_data, 0x9DD0)[0] != 0xE602
        or struct.unpack_from(">I", source_data, 0x7A80)[0] != 0x06029DB4
        or struct.unpack_from(">I", source_data, 0x7AAC)[0] != 0x06029DCC
    ):
        raise ValueError("TITLE.BIN: runtime palette upload contract changed")


def _title_assets() -> list[ImageAsset]:
    source = EXTRACTED_ROOT / "TITLE.BIN"
    if not source.is_file():
        raise ValueError(f"registered visual source is missing: {source}")
    source_data = source.read_bytes()
    size = len(source_data)
    _validate_title_palette_runtime(source_data)
    for asset in TITLE_BIN_IMAGES:
        if asset.offset + asset.byte_length > size:
            raise ValueError(f"TITLE.BIN: too small for {asset.image}")
        if asset.encoding == INDEXED8_RGB555_ENCODING and (
            asset.palette_offset is None
            or asset.palette_entries is None
            or asset.palette_entries <= 0
            or asset.palette_entries > 256
            or asset.palette_offset + asset.palette_entries * 2 > size
        ):
            raise ValueError(f"TITLE.BIN: too small for the palette of {asset.image}")

    expected_records = {}
    for descriptor_offset, asset in TITLE_IMAGE_RECORDS:
        kind = 1 if asset.encoding == RGB555_ENCODING else 2
        expected_records[descriptor_offset] = (
            asset.width,
            asset.height,
            kind,
            0,
            TITLE_LOAD_BASE + asset.offset,
            0,
        )
    actual_records = {}
    for descriptor_offset in range(
        TITLE_DESCRIPTOR_SCAN_START,
        TITLE_DESCRIPTOR_SCAN_END,
        2,
    ):
        width, height, kind, flags, pointer, reserved = struct.unpack_from(
            ">HHHHII", source_data, descriptor_offset
        )
        multiplier = 2 if kind == 1 else 1
        image_offset = pointer - TITLE_LOAD_BASE
        if (
            0 < width <= 352
            and 0 < height <= 224
            and kind in (1, 2)
            and flags == 0
            and reserved == 0
            and 0x10000 <= image_offset
            and image_offset + width * height * multiplier <= size
        ):
            actual_records[descriptor_offset] = (
                width,
                height,
                kind,
                flags,
                pointer,
                reserved,
            )
    if actual_records != expected_records:
        missing = sorted(set(expected_records) - set(actual_records))
        unknown = sorted(set(actual_records) - set(expected_records))
        changed = sorted(
            offset
            for offset in set(actual_records) & set(expected_records)
            if actual_records[offset] != expected_records[offset]
        )
        raise ValueError(
            "TITLE.BIN image registry mismatch; "
            f"missing={[f'0x{offset:X}' for offset in missing] or 'none'}, "
            f"unknown={[f'0x{offset:X}' for offset in unknown] or 'none'}, "
            f"changed={[f'0x{offset:X}' for offset in changed] or 'none'}"
        )

    full_raster = EXTRACTED_ROOT / TITLE_FULL_RASTER_IMAGE.source
    if not full_raster.is_file():
        raise ValueError(f"registered visual source is missing: {full_raster}")
    full_raster_data = full_raster.read_bytes()
    if len(full_raster_data) != TITLE_FULL_RASTER_IMAGE.byte_length:
        raise ValueError(
            f"{TITLE_FULL_RASTER_IMAGE.source}: expected one "
            f"{TITLE_FULL_RASTER_IMAGE.width}x{TITLE_FULL_RASTER_IMAGE.height} "
            "32-bit direct-color raster"
        )
    if any(control != 0x80 for control in full_raster_data[0::4]):
        raise ValueError(
            f"{TITLE_FULL_RASTER_IMAGE.source}: unexpected direct-color control byte"
        )
    return list(TITLE_IMAGES)


def _saveload_assets() -> list[ImageAsset]:
    sources = {}
    for source in ("SAVE.BIN", "LOAD.BIN"):
        path = EXTRACTED_ROOT / source
        if not path.is_file():
            raise ValueError(f"registered visual source is missing: {path}")
        source_data = path.read_bytes()
        validate_saveload_image_records(source_data, source)
        sources[source] = source_data

    save_records = {record.key: record for record in saveload_image_records("SAVE.BIN")}
    load_records = {record.key: record for record in saveload_image_records("LOAD.BIN")}
    if save_records.keys() != load_records.keys():
        raise ValueError("SAVE/LOAD storage-selector image registries differ")
    for key in save_records:
        save_asset = save_records[key].asset
        load_asset = load_records[key].asset
        save_pixels = sources[save_asset.source][
            save_asset.offset : save_asset.offset + save_asset.byte_length
        ]
        load_pixels = sources[load_asset.source][
            load_asset.offset : load_asset.offset + load_asset.byte_length
        ]
        if save_pixels != load_pixels:
            raise ValueError(f"SAVE/LOAD storage-selector pixels differ for {key}")
    return [record.asset for record in SAVELOAD_IMAGE_RECORDS]


def _archive_assets(
    source: str,
    model: str,
    count: int,
    dimensions_offset: int,
) -> list[ImageAsset]:
    source_data = (EXTRACTED_ROOT / source).read_bytes()
    model_data = (EXTRACTED_ROOT / model).read_bytes()
    header_size = count * 8
    assets = []
    stem = Path(source).with_suffix("").as_posix()
    for index in range(count):
        row = index * 8
        declared_index, copies, address = struct.unpack_from(">HHI", source_data, row)
        if declared_index != index or copies != 1:
            raise ValueError(
                f"{source}: texture record {index} has unexpected identity/count"
            )
        offset = address - TEXTURE_LOAD_BASE
        if index == 0 and offset != header_size:
            raise ValueError(
                f"{source}: first texture starts at 0x{offset:X}, "
                f"expected 0x{header_size:X}"
            )
        width, height = struct.unpack_from(">HH", model_data, dimensions_offset + row)
        next_offset = (
            struct.unpack_from(">I", source_data, row + 12)[0] - TEXTURE_LOAD_BASE
            if index + 1 < count
            else len(source_data)
        )
        if offset < header_size or next_offset - offset != width * height * 2:
            raise ValueError(
                f"{source}: texture {index} span does not match {width}x{height}"
            )
        assets.append(
            ImageAsset(source, f"{stem}/{index:03d}.png", offset, width, height)
        )
    return assets


def _tex3d_assets() -> list[ImageAsset]:
    actual = {path.stem for path in (EXTRACTED_ROOT / "TEX3D").glob("*.BIN")}
    expected = set(TEX3D_MODELS)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"TEX3D registry mismatch; missing={missing or 'none'}, "
            f"unknown={unknown or 'none'}"
        )
    assets = []
    for texture, model in sorted(TEX3D_MODELS.items()):
        model_path = f"MDL3D/{model}.BIN"
        model_data = (EXTRACTED_ROOT / model_path).read_bytes()
        count = struct.unpack_from("<I", model_data)[0]
        assets.extend(_archive_assets(f"TEX3D/{texture}.BIN", model_path, count, 0x20))
    return assets


def _mmp_assets() -> list[ImageAsset]:
    assets = []
    for path in sorted((EXTRACTED_ROOT / "MMP").glob("*CHR.COF")):
        model = path.with_name(path.name.replace("CHR.COF", "MDL.COF"))
        if not model.is_file():
            raise ValueError(f"{path}: matching MMP model file is missing")
        model_data = model.read_bytes()
        count = struct.unpack_from(">H", model_data, 6)[0]
        assets.extend(
            _archive_assets(
                path.relative_to(EXTRACTED_ROOT).as_posix(),
                model.relative_to(EXTRACTED_ROOT).as_posix(),
                count,
                0x48,
            )
        )
    if not assets:
        raise ValueError("no MMP texture archives were found")
    return assets


def discover_assets() -> tuple[ImageAsset, ...]:
    assets = [
        *_standalone_assets(),
        *_title_assets(),
        *_saveload_assets(),
        *_tex3d_assets(),
        *_mmp_assets(),
    ]
    assets.sort(
        key=lambda row: (row.source.casefold(), row.offset, row.image.casefold())
    )
    images = [row.image.casefold() for row in assets]
    if len(images) != len(set(images)):
        raise ValueError("visual discovery produced duplicate image paths")
    return tuple(assets)


def build_manifest() -> dict[str, object]:
    assets = discover_assets()
    sources: dict[str, dict[str, object]] = {}
    source_data: dict[str, bytes] = {}
    rows = []
    for asset in assets:
        if asset.source not in source_data:
            data = (EXTRACTED_ROOT / asset.source).read_bytes()
            source_data[asset.source] = data
            sources[asset.source] = {"size": len(data), "sha256": file_sha256(data)}
        rows.append(asset.manifest_row(source_data[asset.source]))
    return {
        "version": MANIFEST_VERSION,
        "encoding": MANIFEST_ENCODING,
        "selection": (
            "proven standalone RGB555 rasters, TITLE.BIN declared title graphics "
            "and TESTLOGO.COF composed title raster, SAVE/LOAD storage-selector "
            "rasters, TEX3D model-described textures, and MMP model-described textures"
        ),
        "sources": sources,
        "assets": rows,
    }


def manifest_text(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2) + "\n"


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") not in {
        LEGACY_MANIFEST_VERSION,
        MANIFEST_VERSION,
    }:
        raise ValueError(f"{path}: unsupported visual image manifest")
    if document.get("encoding") != MANIFEST_ENCODING:
        raise ValueError(f"{path}: unsupported visual encoding")
    if not isinstance(document.get("sources"), dict) or not isinstance(
        document.get("assets"), list
    ):
        raise ValueError(f"{path}: malformed visual image manifest")
    if document["version"] == LEGACY_MANIFEST_VERSION:
        assets = []
        for row in document["assets"]:
            if not isinstance(row, dict) or "png_sha256" not in row:
                raise ValueError(f"{path}: malformed legacy visual image manifest")
            normalized = dict(row)
            del normalized["png_sha256"]
            assets.append(normalized)
        document = {**document, "version": MANIFEST_VERSION, "assets": assets}
    return document


def asset_from_row(row: object) -> ImageAsset:
    if not isinstance(row, dict):
        raise ValueError("visual manifest asset must be an object")
    required = {
        "source",
        "image",
        "encoding",
        "layout",
        "offset",
        "palette_offset",
        "palette_entries",
        "length",
        "width",
        "height",
        "pixel_sha256",
    }
    if set(row) != required or row["encoding"] not in {
        RGB555_ENCODING,
        RGB888_ENCODING,
        INDEXED8_RGB555_ENCODING,
    }:
        raise ValueError("visual manifest asset has invalid fields")
    asset = ImageAsset(
        str(row["source"]),
        str(row["image"]),
        int(row["offset"]),
        int(row["width"]),
        int(row["height"]),
        str(row["layout"]),
        str(row["encoding"]),
        None if row["palette_offset"] is None else int(row["palette_offset"]),
        None if row["palette_entries"] is None else int(row["palette_entries"]),
    )
    if asset.encoding == INDEXED8_RGB555_ENCODING:
        if (
            asset.palette_offset is None
            or asset.palette_entries is None
            or not 1 <= asset.palette_entries <= 256
        ):
            raise ValueError(f"{asset.image}: indexed palette contract is invalid")
    elif asset.palette_offset is not None or asset.palette_entries is not None:
        raise ValueError(f"{asset.image}: non-indexed asset has a palette contract")
    if row["length"] != asset.byte_length:
        raise ValueError(f"{asset.image}: manifest byte length is inconsistent")
    for value in (asset.source, asset.image):
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe visual manifest path: {value}")
    return asset
