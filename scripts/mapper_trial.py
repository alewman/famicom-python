#!/usr/bin/env python3
"""Run a dump on a board of your choice and show what its game asks the cartridge for.

    python scripts/mapper_trial.py ROM.nes [--as MAPPER[.SUB]] [--frames N] [--mask HEX]
                                   [--png OUT.png] [--hot]

With ``--as`` the dump runs on another mapper's board, usually its nearest relative:
the writes then show the registers it wants, and how far it gets shows how close
that was. Prints the cartridge writes and reads by address (under ``--mask``), the
first of them in order, and the final PC. ``--hot`` disassembles where it is spinning,
which is how the protection checks in C68 and C69 were read. Needs PyPy to be quick.
"""

from __future__ import annotations

import argparse
import collections
from dataclasses import replace
from pathlib import Path

from disasm6502 import disassemble

import famicom_python.cartridge as cartridges
from famicom_python.ppu import HEIGHT
from famicom_python.system import System
from famicom_python.video import load_palette, write_png


def impersonate(rom: Path, target: str) -> None:
    """Point the dump's mapper number at the board ``target`` (``4`` or ``23.3``)."""
    mapper, _, submapper = target.partition(".")
    number, sub = int(mapper), int(submapper or 0)
    head = rom.read_bytes()[:16]
    own = head[6] >> 4 | head[7] & 0xF0 | (head[8] & 0x0F) << 8
    board = cartridges.MAPPERS[number]

    def factory(image, ticks):
        return board(image.with_board(replace(image.board, mapper=number, submapper=sub)), ticks)

    cartridges.MAPPERS[own] = factory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("--as", dest="target")
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--mask", type=lambda text: int(text, 16), default=0xF00F)
    parser.add_argument("--png", type=Path)
    parser.add_argument("--hot", action="store_true")
    args = parser.parse_args()
    if args.target:
        impersonate(args.rom, args.target)
    system = System.from_rom(args.rom)
    cart = system.cartridge
    writes: collections.Counter[int] = collections.Counter()
    values: dict[int, collections.Counter[int]] = collections.defaultdict(collections.Counter)
    reads: collections.Counter[int] = collections.Counter()
    first: list[str] = []
    cpu_write, cpu_read = cart.cpu_write, cart.cpu_read

    def write(address: int, value: int, t: int) -> None:
        if address >= 0x4020:
            writes[address & args.mask] += 1
            values[address & args.mask][value] += 1
            if len(first) < 60:
                first.append(f"{address:04X}={value:02X}")
        cpu_write(address, value, t)

    def read(address: int, t: int) -> int | None:
        if 0x4020 <= address < 0x8000:
            reads[address] += 1
        return cpu_read(address, t)

    cart.cpu_write, cart.cpu_read = write, read
    system.run_frames(args.frames)
    for address, count in writes.most_common(16):
        print(f"{address:04X} {count}", [f"{v:02X}" for v, _ in values[address].most_common(10)])
    print("reads", [(f"{a:04X}", n) for a, n in reads.most_common(8)])
    print(" ".join(first))
    print(f"pc {system.cpu.pc:04X} PPUMASK {system.board.ppu.mask:02X}")
    if args.hot:
        seen: collections.Counter[int] = collections.Counter()
        for _ in range(4000):
            seen[system.cpu.pc] += 1
            system.cpu.step()
        start = min(pc for pc, _ in seen.most_common(14))
        code = bytes(system.board.read_byte(start + i) for i in range(64))
        print("\n".join(disassemble(code, start)))
    if args.png:
        colours = load_palette()
        picture = system.board.ppu.picture[: 256 * HEIGHT]
        write_png(args.png, b"".join(colours[p & 0x1FF] for p in picture))


if __name__ == "__main__":
    main()
