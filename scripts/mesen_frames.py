#!/usr/bin/env python3
"""Compare the board's frames with Mesen2's, pixel for pixel (a detector, docs/validation.md).

Mesen2 normally hands Lua its frame as RGB through its palette. Here
scripts/mesen_run.py gives it a 512-entry identity palette instead, so its
"RGB" is the PPU's 9-bit value (palette value | emphasis << 6), the board's own
pixel format, and the comparison is exact by index, not by colour. It also
turns on Mesen2's power-up write-ignore and zero-fills its RAM, to match the
board (``configure_for_comparison``).

    python scripts/mesen_frames.py ROM --frame 300 [--png diff.png] [--machine pal]

On PAL the border (line 0, x 0-1 and 254-255) is left out: the board's is
PPUSim's (docs/validation.md milestone 10), and this is a detector.

Mesen2 counts frames from its own power-on; the board's frames within
``--window`` either side are tried and the closest reported. Needs the
hand-built MesenCore.so of scripts/mesen_run.py; nothing it writes is committed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mesen_run import REGIONS, ROOT, run_mesen

from famicom_python.machine import MACHINES, NES_001, Machine
from famicom_python.ppu import HEIGHT
from famicom_python.system import System
from famicom_python.video import load_palette, write_png

HOME = ROOT / "tests" / "mame_traces" / "mesen-home"


FRAME_LUA = """
local target, frame = %d, 0
emu.addEventCallback(function()
  frame = frame + 1
  if frame == target then
    local size = emu.getScreenSize()
    local buffer = emu.getScreenBuffer()
    emu.log(string.format("S %%d %%d", size.width, size.height))
    for y = 0, size.height - 1 do
      local parts = {}
      for x = 0, size.width - 1 do
        parts[#parts + 1] = string.format("%%06x", buffer[1 + y * size.width + x])
      end
      emu.log("R" .. table.concat(parts))
    end
    emu.log("DONE")
  end
end, emu.eventType.endFrame)
"""


def finished_picture(system: System) -> list[int]:
    """The frame just begun, once its 240 rows are drawn.

    ``run_frames`` stops inside the instruction that starts a frame, by when
    the first pixels of row 0 already belong to it; so run on to line 240.
    """
    ppu = system.board.ppu
    while not HEIGHT <= ppu.line < ppu.prerender_line:
        system.step()
    return list(ppu.picture)


def mesen_frame(rom: Path, frame: int, seconds: float, region: int = 1) -> list[list[int]]:
    code, log, _ = run_mesen(
        rom,
        lua=(FRAME_LUA % frame).encode(),
        lua_name="frame.lua",
        seconds=seconds,
        home=HOME,
        until="DONE",
        for_comparison=True,
        region=region,
    )
    rows = [line[1:] for line in log.splitlines() if line.startswith("R")]
    if code != 0 or not rows:
        raise SystemExit(f"Mesen2 gave no frame {frame} (stop code {code})")
    return [[int(row[i : i + 6], 16) for i in range(0, len(row), 6)] for row in rows]


def compare(
    rom: Path,
    frame: int,
    window: int,
    seconds: float,
    png: Path | None,
    machine: Machine = NES_001,
) -> int:
    theirs = mesen_frame(rom, frame, seconds, REGIONS[machine.timing.name])
    height, width = len(theirs), len(theirs[0])
    if (width, height) != (256, 240):
        print(f"Mesen2's frame is {width}x{height}; expected 256x240 (overscan settings?)")
        return 2
    system = System.from_rom(rom, machine)
    border = machine.timing.border
    best = None
    first = max(1, frame - window)
    system.run_frames(first)
    for ours_frame in range(first, frame + window + 1):
        picture = finished_picture(system)
        diffs = [
            (y, x)
            for y in range(240)
            for x in range(256)
            if picture[y * 256 + x] != theirs[y][x]
            and not (border and (y == 0 or x in (0, 1, 254, 255)))
        ]
        if best is None or len(diffs) < len(best[1]):
            best = (ours_frame, diffs, picture)
        system.run_frames(1)
    assert best is not None
    ours_frame, diffs, picture = best
    rows = sorted({y for y, _ in diffs})
    print(
        f"{rom.name}: Mesen2 frame {frame} vs ours {ours_frame}: "
        f"{len(diffs)} of 61440 pixels differ"
        + (f", rows {rows[0]}-{rows[-1]} ({len(rows)} rows), first at {diffs[0]}" if diffs else "")
    )
    if png:
        colours = load_palette()
        bad = set(diffs)
        out = b"".join(
            b"\xff\x00\xff" if (y, x) in bad else colours[theirs[y][x] & 0x1FF]
            for y in range(240)
            for x in range(256)
        )
        write_png(png, out)
    return 1 if diffs else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("--frame", type=int, default=300, help="Mesen2's frame count")
    parser.add_argument("--window", type=int, default=3, help="our frames tried either side")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--png", type=Path, help="Mesen2's frame, differing pixels magenta")
    parser.add_argument("--machine", choices=sorted(MACHINES), default="nes")
    args = parser.parse_args()
    machine = MACHINES[args.machine]
    return compare(args.rom, args.frame, args.window, args.seconds, args.png, machine)


if __name__ == "__main__":
    sys.exit(main())
