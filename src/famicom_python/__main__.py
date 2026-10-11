"""Run a cartridge headless: ``python -m famicom_python ROM [--frames N]``.

Prints how the cartridge was identified, runs it, and reports what a test ROM
says: blargg's $6000 text if present, else the first nametable as text.
``--png``/``--wav`` arrive with the PPU and APU milestones (docs/handoff-brief.md).
"""

from __future__ import annotations

import argparse
import sys
import time

from .machine import MACHINES
from .system import System
from .testrom import SIGNATURE, blargg_text, peek, run_blargg, screen_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="famicom-python", description=__doc__.splitlines()[0])
    parser.add_argument("rom", help="an iNES/NES 2.0 file, or a .zip holding one")
    parser.add_argument("--machine", choices=sorted(MACHINES), default="nes")
    parser.add_argument("--frames", type=int, default=600, help="frames to run (default 600)")
    parser.add_argument(
        "--blargg", action="store_true", help="run to blargg's $6000 result instead of --frames"
    )
    args = parser.parse_args(argv)

    system = System.from_rom(args.rom, MACHINES[args.machine])
    loaded = system.loaded
    assert loaded is not None
    board = loaded.image.board
    print(
        f"mapper {board.mapper}.{board.submapper}, mirroring {board.mirroring}, "
        f"PRG {len(loaded.image.prg) // 1024} KiB, CHR {len(loaded.image.chr) // 1024} KiB "
        f"({loaded.source})"
    )
    for line in loaded.disagreements:
        print(f"  disagreement: {line}")
    if loaded.mame:
        print(f"  MAME: {loaded.mame.get('software')} {loaded.mame.get('pcb', '')}")

    start = time.perf_counter()
    if args.blargg:
        result = run_blargg(system)
        status = "no result" if result.status is None else f"status {result.status}"
        print(f"{status}\n{result.text}")
    else:
        system.run_frames(args.frames)
        if bytes(peek(system, 0x6001 + i) for i in range(3)) == SIGNATURE:
            print(f"$6000 = {peek(system, 0x6000):02X}\n{blargg_text(system)}")
        else:
            print(screen_text(system))
    wall = time.perf_counter() - start
    print(f"{system.cycles:,} CPU cycles, {system.instructions:,} instructions, {wall:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
