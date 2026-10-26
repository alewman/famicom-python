#!/usr/bin/env python3
"""Replay a Breaknes PPU register dump into PPUSim and show where its writes land.

emu-russia/breaknes#196 (white strips under SMB's menu in the PPU Player, fine
on the full NES board) asks whether PPUSim or the dump replay is at fault. A
dump (Breaknes Common/BaseBoardLib/RegDumpProcessor.h) is 8-byte entries:
clkDelta (u32, since the previous access), reg (bit 7: read), value, padding.
Its clock is the CPU's in dumps from Breaknes's own emitter since 2023, and
PCLK (PPU dots) in the 2022 PPU Player's (``--unit pclk``).

The access models (``--model``), in master half-cycles of the CPU cycle:

  player   Breaknes PPUPlayerBoard: /DBE low and the written value on the bus
           for the whole CPU cycle (24), from PHI0's fall
  m2       the NES-001: /DBE only while M2 is high (9 to 24), as
           scripts/ppusim_board.py drives it
  pclk     the 2022 PPU Player: /DBE for one PCLK (8) from a PCLK boundary

Logs every $2006/$2007 write that lands while rendering is enabled on a
visible or pre-render line (where it collides with the fetches), and saves
the frames asked for as PNG.

    python scripts/breaknes_regdump.py DUMP ROM.nes [--unit cpu] [--model player]
        [--frames 570,571] [--every N] [--out DIR] [--stop FRAME]
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
import time
from pathlib import Path

from ppusim_board import LIBRARY, _library

from famicom_python.cartridge import load
from famicom_python.video import load_palette, to_rgb, write_png

MODELS = {"player": (0, 24), "m2": (9, 15), "pclk": (0, 8)}
SIM_PIXEL_H = 4  # PPUSim shows pixel x at H = x + 4 (ppusim_compare.py calibrate)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dump", type=Path)
    parser.add_argument("rom", type=Path, help="an NROM image for CHR and mirroring")
    parser.add_argument("--unit", choices=("cpu", "pclk"), default="cpu")
    parser.add_argument("--model", choices=sorted(MODELS), default="player")
    parser.add_argument("--skew", type=int, default=0, help="half-cycles before the first cycle")
    parser.add_argument("--frames", default="", help="frame numbers to save, comma separated")
    parser.add_argument("--every", type=int, default=0, help="also save every Nth frame")
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument("--stop", type=int, default=0, help="stop after this many frames")
    parser.add_argument("--quiet", action="store_true", help="count collisions, list none")
    args = parser.parse_args()
    if not LIBRARY.exists():
        print("build PPUSim first: python scripts/build_ppusim.py", file=sys.stderr)
        return 1

    image = load(args.rom.read_bytes()).image
    lib = _library()
    lib.ppusim_screen.argtypes = [ctypes.c_void_p]
    lib.ppusim_screen.restype = ctypes.c_void_p
    chr_data = image.chr or bytes(0x2000)
    vertical = int(image.board.mirroring == "V")
    h = lib.ppusim_new(chr_data, len(chr_data), int(not image.chr), vertical)
    lib.ppusim_reset(h, 64)
    lib.ppusim_run(h, args.skew)
    screen = (ctypes.c_uint16 * (262 * 341)).from_address(lib.ppusim_screen(h))
    palette = load_palette()
    wanted = {int(f) for f in args.frames.split(",") if f}
    args.out.mkdir(parents=True, exist_ok=True)

    before, during = MODELS[args.model]
    unit = 24 if args.unit == "cpu" else 8
    data = args.dump.read_bytes()
    clock = now = 0
    mask = 0
    frame, last_v = 0, 0
    collisions = 0
    began = time.monotonic()
    for offset in range(0, len(data) - 7, 8):
        delta, reg, value, _ = struct.unpack_from("<IBBH", data, offset)
        clock += delta
        start = clock * unit
        if start < now:
            print(f"entry {offset // 8}: overlaps the previous access", file=sys.stderr)
            return 1
        lib.ppusim_run(h, start - now)
        v, hc = lib.ppusim_v(h), lib.ppusim_h(h)
        if v < last_v:
            frame += 1
            if args.stop and frame >= args.stop:
                break
        if last_v < 240 <= v and (frame in wanted or (args.every and frame % args.every == 0)):
            picture = [screen[y * 341 + x + SIM_PIXEL_H] for y in range(240) for x in range(256)]
            name = f"{args.dump.stem}-{args.model}-{frame}.png"
            write_png(args.out / name, to_rgb(picture, palette))
        last_v = v
        read = bool(reg & 0x80)
        register = reg & 7
        if not read and register == 1:
            mask = value
        if not read and register in (6, 7) and mask & 0x18 and (v < 240 or v == 261):
            collisions += 1
            if not args.quiet:
                print(
                    f"frame {frame} entry {offset // 8}: ${0x2000 + register:04X} = ${value:02X}"
                    f" at line {v}, dot {hc} with rendering on (mask ${mask:02X})"
                )
        lib.ppusim_access(h, int(read), register, value, value, 0, before, during)
        now = start + before + during
    print(
        f"{args.dump.name}: {offset // 8 + 1:,} entries, {frame} frames, model {args.model}, "
        f"{collisions} $2006/$2007 writes while rendering ({time.monotonic() - began:.0f} s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
