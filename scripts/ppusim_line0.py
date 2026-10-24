#!/usr/bin/env python3
"""Line 0's stale sprite slot 0, on the board's PPU and PPUSim.

Milestone 7's sweep: ten games differ from Mesen2 at one pixel, (255, 0),
where the board draws an empty slot's tile $FF. With no sprite in range of
line 239, evaluation still writes each sprite's Y into secondary OAM slot 0
(its tile, attribute and X stay $FF); the pre-render line's fetches check
every slot against line 261 & 255 = 5 (AccuracyCoin "Sprites On Scanline
0"), so a last Y of 0-5 puts slot 0's tile $FF at X $FF on line 0.

OAM: every sprite at Y $F8 but sprite 63 (Y $00, $03 or $F8); CHR: blargg's
font with tile $FF made solid; sprites only (attribute $FF is behind the
background). Prints line 0, x 248-255, and the pre-render line's first
sprite pattern addresses from both PPUs.

    python scripts/ppusim_line0.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ppusim_compare import ROM, SIM_PIXEL_H, Pair, scroll_zero, setup_picture


def main() -> int:
    data = ROM.read_bytes()
    prg_size = data[4] * 0x4000
    chr_ = bytearray(data[16 + prg_size : 16 + prg_size + 0x2000])
    chr_[0xFF0:0x1000] = b"\xff" * 16  # tile $FF at $0000 solid, colour 3
    with tempfile.TemporaryDirectory() as directory:
        rom = Path(directory) / "line0.nes"
        rom.write_bytes(data[: 16 + prg_size] + bytes(chr_))
        for y63 in (0x00, 0x03, 0xF8):
            pair = Pair(rom)
            setup_picture(pair)
            pair.write(3, 0)
            oam = [0xF8, 0x41, 0x00, 0x80] * 64
            oam[252:256] = [y63, 0x41, 0x00, 0x80]
            for value in oam:
                pair.write(4, value)
            pair.write(6, 0x3F)
            pair.write(6, 0x1C)
            for value in (0x0F, 0x16, 0x27, 0x30):  # sprite palette 3
                pair.write(7, value)
            pair.to_line(261, 100)
            scroll_zero(pair)
            pair.write(0, 0x00)
            pair.write(1, 0x14)
            pair.to_line(239, 300)  # a frame rendered; trace the next pre-render line and line 0
            pair.to_line(261, 240)
            pair.trace(True)
            pair.to_line(1, 0)
            pair.trace(False)
            sim = pair.sim_pixels()
            ours = pair.ours.picture
            print(f"sprite 63 at Y ${y63:02X}:")
            print(
                "  line 0, x 248-255: ours  ", " ".join(f"{ours[x]:02X}" for x in range(248, 256))
            )
            print(
                "                     PPUSim",
                " ".join(f"{sim.get((0, x + SIM_PIXEL_H), -1):02X}" for x in range(248, 256)),
            )
            ours_f = [a for _, a in pair.fetches if a < 0x2000][:8]
            sim_f = [a for _, a in pair.sim_fetches() if a < 0x2000][:8]
            print("  pattern fetches: ours  ", " ".join(f"{a:04X}" for a in ours_f))
            print("                   PPUSim", " ".join(f"{a:04X}" for a in sim_f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
