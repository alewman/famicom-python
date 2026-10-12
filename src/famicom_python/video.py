"""From the PPU's 9-bit pixels to RGB, and a PNG without dependencies.

The 2C02 has no RGB anywhere: it emits composite video from a 6-bit palette
value and 3 emphasis bits (docs/start-here.md "Output format"). Colour is
therefore the frontend's choice. The default is ``2C02G_U_wiki.pal``, generated
by pally from lidnariq's measured 2C02G voltages (PPU_palettes.wiki), fetched
into ``reference/`` by ``scripts/fetch_references.py`` and read at run time,
never committed. A ``.pal`` file is 64 or 512 RGB triples; with 512 the 9-bit
value indexes it directly, emphasis included.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

from .ppu import HEIGHT, WIDTH

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PALETTE = ROOT / "reference" / "nesdev-wiki" / "images" / "2C02G_U_wiki.pal"


def load_palette(path: str | Path = DEFAULT_PALETTE) -> list[bytes]:
    """512 RGB triples, one per 9-bit pixel value (a 64-entry file ignores emphasis)."""
    data = Path(path).read_bytes()
    if len(data) not in (64 * 3, 512 * 3):
        raise ValueError(f"{path}: {len(data)} bytes, not a 64- or 512-colour .pal file")
    colours = [data[i : i + 3] for i in range(0, len(data), 3)]
    if len(colours) == 64:
        colours *= 8
    return colours


def to_rgb(picture: Sequence[int], palette: list[bytes]) -> bytes:
    """A frame of 9-bit values as packed 8-bit RGB."""
    return b"".join(palette[value] for value in picture)


def write_png(path: str | Path, rgb: bytes, width: int = WIDTH, height: int = HEIGHT) -> None:
    """Write packed RGB as an 8-bit truecolour PNG."""
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
