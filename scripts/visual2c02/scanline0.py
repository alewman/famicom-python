#!/usr/bin/env python3
"""Line 0's sprite after the odd-frame skip: PPUSim against Visual 2C02, same writes.

AccuracyCoin "Sprites On Scanline 0" error 3 (composite PPUs): when the
pre-render line skips its last dot, the sprite the pre-render fetch loaded
(stale secondary OAM, checked against line 261 & 255 = 5) shows its first
pixel at x = 0 instead of its X. PPUSim fails the test there; the board and
AccuracyCoin's hardware answer key pass. This drives both die models with one
register schedule, in master half-cycles from the pre-render line's dot 0:

  pre-render (rendering off): OAM sprite 0 = Y 0, tile $C6 (one pixel, row 5,
  column 0), attribute 0, X $80; sprite palette 0 colour 1 = $16; backdrop $0F.
  Then, every frame: rendering on ($1E, as AccuracyCoin) at the pre-render
  line's dot 70, so its fetch loads secondary OAM slot 0 and the odd-frame
  skip is live; line 0's evaluation reloads slot 0 with sprite 0 (Y 0 is in
  range); rendering off at line 0's dot 330, after the fetches, so the slot
  survives to the next pre-render.

Prints, for each frame's line 0, whether its pre-render line skipped dot 340,
and the dots (pixel x) that are not backdrop.

    python scripts/visual2c02/scanline0.py ppusim [--frames 3]
    python scripts/visual2c02/scanline0.py schedule [--frames 3]   # JSON for scanline0.js
"""

from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DOT = 8  # master half-cycles a dot
LINE = 341 * DOT
TILE = 0xC6
ENABLE, MASK = 70, 0x1E  # AccuracyCoin: "$1E ... briefly after dot 66 on the pre-render line"


def schedule(frames: int) -> list[tuple[int, int, int, int]]:
    """(half-cycle, rnw, register, value) of each access, from the pre-render line's dot 0."""
    out: list[tuple[int, int, int, int]] = []
    t = 16 * DOT

    def write(register: int, value: int) -> None:
        nonlocal t
        out.append((t, 0, register, value))
        t += 24 * 2  # an access every other CPU cycle

    write(0, 0x00)
    write(1, 0x00)
    write(3, 0x00)
    for value in (0x00, TILE, 0x00, 0x80):
        write(4, value)
    for address, value in ((0x3F11, 0x16), (0x3F00, 0x0F)):
        write(6, address >> 8)
        write(6, address & 0xFF)
        write(7, value)
    write(6, 0x00)
    write(6, 0x00)
    for frame in range(frames):
        start = frame * 262 * LINE  # this frame's pre-render line, ignoring skipped dots
        # Frame 0's enable waits for the set-up writes; it only loads secondary OAM.
        out.append((max(start + ENABLE * DOT, t), 0, 1, MASK))
        out.append((start + LINE + 330 * DOT, 0, 1, 0x00))
    return out


def ppusim(frames: int) -> int:
    from ppusim_board import _library

    lib = _library()
    chr_data = bytearray(0x2000)
    chr_data[TILE * 16 + 5] = 0x80  # tile $C6, plane 0, row 5: column 0
    h = lib.ppusim_new(bytes(chr_data), len(chr_data), 0, 1)
    lib.ppusim_reset(h, 64)
    # Align to a pre-render line's dot 0 (any frame; three frames cover both parities).
    while not (lib.ppusim_v(h) == 261 and lib.ppusim_h(h) == 0):
        lib.ppusim_run(h, 1)
    lib.ppusim_screen.argtypes = [ctypes.c_void_p]
    lib.ppusim_screen.restype = ctypes.c_void_p
    screen = (ctypes.c_uint16 * (262 * 341)).from_address(lib.ppusim_screen(h))
    now = 0
    events = schedule(frames)
    end = frames * 262 * LINE + 2 * LINE
    index = 0
    previous = (261, 0)
    skipped = False
    while now < end:
        if index < len(events) and events[index][0] == now:
            _, rnw, register, value = events[index]
            lib.ppusim_access(h, rnw, register, value, value, 0, 8, 15)
            now += 23
            index += 1
            continue
        lib.ppusim_run(h, 1)
        now += 1
        position = (lib.ppusim_v(h), lib.ppusim_h(h))
        if position != previous:
            if previous[0] == 261 and position[0] == 0:
                skipped = previous[1] == 339
            if previous[0] == 0 and position[0] == 1:
                row = [screen[x + 4] & 0x3F for x in range(256)]
                lit = [x for x in range(256) if row[x] != 0x0F]
                print(f"PPUSim line 0: pre-render skipped dot 340: {skipped}; lit x: {lit}")
            previous = position
        if index < len(events) and events[index][0] < now:
            raise SystemExit("schedule overlaps")
    return 0


def board(frames: int) -> int:
    """The same schedule on famicom-python's PPU: each access at the board's
    access point, PPU_ACCESS_TICKS into its CPU cycle (master ticks are two
    half-cycles)."""
    from famicom_python.board import PPU_ACCESS_TICKS
    from famicom_python.system import System

    chr_data = bytearray(0x2000)
    chr_data[TILE * 16 + 5] = 0x80
    image = b"NES\x1a\x01\x01\x01\x00" + bytes(8) + bytes(0x4000) + bytes(chr_data)
    ppu = System.from_rom(image).board.ppu
    # The second pre-render line: the power-on reset flag (writes ignored) has cleared.
    for _ in range(2):
        ppu.run_to(ppu.time + 4)
        while not (ppu.line == 261 and ppu.dot == 0):
            ppu.run_to(ppu.time + 1)
    origin = ppu.time
    for at, _, register, value in schedule(frames):
        while ppu.time < origin + at // 2 + PPU_ACCESS_TICKS:
            ppu.run_to(min(ppu.time + 4, origin + at // 2 + PPU_ACCESS_TICKS))
            _report(ppu, frames)
        ppu.write_register(register, value)
    while ppu.time < origin + (frames * 262 + 2) * LINE // 2:
        ppu.run_to(ppu.time + 4)
        _report(ppu, frames)
    return 0


_seen: set[int] = set()


def _report(ppu, frames: int) -> None:
    # Line 0 is finished once line 1 has begun; report each frame once.
    if ppu.line == 1 and ppu.frame not in _seen:
        _seen.add(ppu.frame)
        row = [ppu.picture[x] & 0x3F for x in range(256)]
        lit = [x for x in range(256) if row[x] != 0x0F]
        print(f"board line 0 (frame {ppu.frame}, odd {bool(ppu.frame & 1)}): non-backdrop x: {lit}")


def main() -> int:
    frames = int(sys.argv[sys.argv.index("--frames") + 1]) if "--frames" in sys.argv else 3
    if sys.argv[1] == "schedule":
        print(json.dumps(schedule(frames)))
        return 0
    if sys.argv[1] == "board":
        return board(frames)
    return ppusim(frames)


if __name__ == "__main__":
    sys.exit(main())
