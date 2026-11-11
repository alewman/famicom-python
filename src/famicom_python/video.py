"""From the PPU's 9-bit pixels to RGB, and a PNG without dependencies.

The 2C02 has no RGB anywhere: it emits composite video from a 6-bit palette
value and 3 emphasis bits (docs/start-here.md "Output format"). Colour is
therefore the frontend's choice. The default is ``2C02G_U_wiki.pal``, generated
by pally from lidnariq's measured 2C02G voltages (PPU_palettes.wiki), fetched
into ``reference/`` by ``scripts/fetch_references.py`` and read at run time,
never committed. A ``.pal`` file is 64 or 512 RGB triples; with 512 the 9-bit
value indexes it directly, emphasis included.

The arcade RGB PPUs (2C03, 2C04, 2C05) do have colours of their own: a ROM of
three 3-bit DAC values per palette index (:data:`RGB_DAC`), so their palettes
are built here, with no file (:func:`rgb_palette`).
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

from .machine import Timing
from .ppu import HEIGHT, WIDTH

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / "reference" / "nesdev-wiki" / "images"
DEFAULT_PALETTE = IMAGES / "2C02G_U_wiki.pal"


# The RGB PPUs' colour ROMs, as PPU_palettes.wiki prints them ("2C03 and 2C05",
# "RP2C04-0001" to "-0004"): one octal digit each for red, green and blue per
# palette index. The four RP2C04s hold one 64-colour master palette in four
# permutations, a copy protection; the RC2C05s have the RP2C03's
# (tests/test_vs_system.py reads the pinned page and its 2C03_wiki.pal against
# these). Specification tier: the wiki's tables, from dumped chips
# (nesdev-forum p=98955, not pinned here).
# fmt: off
RGB_DAC: dict[str, tuple[int, ...]] = {
    "RP2C03": (
        0o333, 0o014, 0o006, 0o326, 0o403, 0o503, 0o510, 0o420,
        0o320, 0o120, 0o031, 0o040, 0o022, 0o000, 0o000, 0o000,
        0o555, 0o036, 0o027, 0o407, 0o507, 0o704, 0o700, 0o630,
        0o430, 0o140, 0o040, 0o053, 0o044, 0o000, 0o000, 0o000,
        0o777, 0o357, 0o447, 0o637, 0o707, 0o737, 0o740, 0o750,
        0o660, 0o360, 0o070, 0o276, 0o077, 0o000, 0o000, 0o000,
        0o777, 0o567, 0o657, 0o757, 0o747, 0o755, 0o764, 0o772,
        0o773, 0o572, 0o473, 0o276, 0o467, 0o000, 0o000, 0o000,
    ),
    "RP2C04-0001": (
        0o755, 0o637, 0o700, 0o447, 0o044, 0o120, 0o222, 0o704,
        0o777, 0o333, 0o750, 0o503, 0o403, 0o660, 0o320, 0o777,
        0o357, 0o653, 0o310, 0o360, 0o467, 0o657, 0o764, 0o027,
        0o760, 0o276, 0o000, 0o200, 0o666, 0o444, 0o707, 0o014,
        0o003, 0o567, 0o757, 0o070, 0o077, 0o022, 0o053, 0o507,
        0o000, 0o420, 0o747, 0o510, 0o407, 0o006, 0o740, 0o000,
        0o000, 0o140, 0o555, 0o031, 0o572, 0o326, 0o770, 0o630,
        0o020, 0o036, 0o040, 0o111, 0o773, 0o737, 0o430, 0o473,
    ),
    "RP2C04-0002": (
        0o000, 0o750, 0o430, 0o572, 0o473, 0o737, 0o044, 0o567,
        0o700, 0o407, 0o773, 0o747, 0o777, 0o637, 0o467, 0o040,
        0o020, 0o357, 0o510, 0o666, 0o053, 0o360, 0o200, 0o447,
        0o222, 0o707, 0o003, 0o276, 0o657, 0o320, 0o000, 0o326,
        0o403, 0o764, 0o740, 0o757, 0o036, 0o310, 0o555, 0o006,
        0o507, 0o760, 0o333, 0o120, 0o027, 0o000, 0o660, 0o777,
        0o653, 0o111, 0o070, 0o630, 0o022, 0o014, 0o704, 0o140,
        0o000, 0o077, 0o420, 0o770, 0o755, 0o503, 0o031, 0o444,
    ),
    "RP2C04-0003": (
        0o507, 0o737, 0o473, 0o555, 0o040, 0o777, 0o567, 0o120,
        0o014, 0o000, 0o764, 0o320, 0o704, 0o666, 0o653, 0o467,
        0o447, 0o044, 0o503, 0o027, 0o140, 0o430, 0o630, 0o053,
        0o333, 0o326, 0o000, 0o006, 0o700, 0o510, 0o747, 0o755,
        0o637, 0o020, 0o003, 0o770, 0o111, 0o750, 0o740, 0o777,
        0o360, 0o403, 0o357, 0o707, 0o036, 0o444, 0o000, 0o310,
        0o077, 0o200, 0o572, 0o757, 0o420, 0o070, 0o660, 0o222,
        0o031, 0o000, 0o657, 0o773, 0o407, 0o276, 0o760, 0o022,
    ),
    "RP2C04-0004": (
        0o430, 0o326, 0o044, 0o660, 0o000, 0o755, 0o014, 0o630,
        0o555, 0o310, 0o070, 0o003, 0o764, 0o770, 0o040, 0o572,
        0o737, 0o200, 0o027, 0o747, 0o000, 0o222, 0o510, 0o740,
        0o653, 0o053, 0o447, 0o140, 0o403, 0o000, 0o473, 0o357,
        0o503, 0o031, 0o420, 0o006, 0o407, 0o507, 0o333, 0o704,
        0o022, 0o666, 0o036, 0o020, 0o111, 0o773, 0o444, 0o707,
        0o757, 0o777, 0o320, 0o700, 0o760, 0o276, 0o777, 0o467,
        0o000, 0o750, 0o637, 0o567, 0o360, 0o657, 0o077, 0o120,
    ),
}
# fmt: on


def rgb_palette(chip: str) -> list[bytes]:
    """An RGB PPU's 512 colours: "C = 255 * DAC / 7" per channel, and each
    emphasis bit "sets the corresponding channel to full brightness" rather
    than dimming the others (PPU_palettes.wiki "2C03 and 2C05"; the picture's
    bits 6, 7 and 8 are $2001's red, green and blue). Greyscale is the PPU's
    own AND $30 on the index, already in the picture."""
    dac = RGB_DAC[chip]
    colours = []
    for emphasis in range(8):
        for value in dac:
            channels = [(value >> shift) & 7 for shift in (6, 3, 0)]
            for channel in range(3):
                if emphasis >> channel & 1:
                    channels[channel] = 7
            colours.append(bytes(round(255 * level / 7) for level in channels))
    return colours


def palette_for(timing: Timing) -> Path:
    """The pally palette of a video standard (machine.Timing.palette)."""
    return IMAGES / timing.palette


def machine_palette(timing: Timing, path: str | Path | None = None) -> list[bytes]:
    """A machine's 512 colours: the file ``path`` if given, else an RGB PPU's
    own (:func:`rgb_palette`), else the pally palette of the video standard."""
    if path is None and timing.rgb:
        return rgb_palette(timing.palette)
    return load_palette(path or palette_for(timing), timing.swapped_emphasis)


def load_palette(path: str | Path = DEFAULT_PALETTE, swapped_emphasis: bool = False) -> list[bytes]:
    """512 RGB triples, one per 9-bit pixel value (a 64-entry file ignores emphasis).

    ``swapped_emphasis``: the picture's bits 6 and 7 ($2001's 5 and 6, as
    written) tint the palette's green and red, as on the 2C07 and the Dendy's
    PPU (machine.Timing.swapped_emphasis).
    """
    data = Path(path).read_bytes()
    if len(data) not in (64 * 3, 512 * 3):
        raise ValueError(f"{path}: {len(data)} bytes, not a 64- or 512-colour .pal file")
    colours = [data[i : i + 3] for i in range(0, len(data), 3)]
    if len(colours) == 64:
        colours *= 8
    if swapped_emphasis:
        swap = [(i & ~0xC0) | (i & 0x40) << 1 | (i & 0x80) >> 1 for i in range(512)]
        colours = [colours[swap[i]] for i in range(512)]
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
