#!/usr/bin/env python3
"""Run an AccuracyCoin test on the board and on the PPUSim board in lockstep.

The two boards differ only in the PPU (scripts/ppusim_board.py, skew 3), so
their CPUs agree until something the program reads from the PPU differs. This
steps both one instruction at a time with the same button presses (timed in
CPU cycles, as the board's own menu run makes them) and stops at the first
instruction where the CPU states part, printing both sides' last PPU and APU
register reads. Power-on state that is per console is aligned first: the
board takes PPUSim's zeroed palette RAM (``PowerOn.palette``).

    python scripts/ppusim_lockstep.py "BG Serial In"

PPUSim runs at about 13,000 CPU cycles a second here, so a test deep in the
menu takes ten minutes or more. NROM only (AccuracyCoin is).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path

from ppusim_board import system_with_ppusim

from famicom_python.joypad import DOWN, RIGHT, A
from famicom_python.machine import NES_001, PowerOn
from famicom_python.system import System
from famicom_python.testrom import AccuracyCoinTest, accuracycoin_tests

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "tests" / "test_roms" / "AccuracyCoin"
ROM = HOME / "AccuracyCoin.nes"


def presses(test: AccuracyCoinTest) -> list[tuple[int, int]]:
    """(CPU cycle, buttons) of the menu run that starts ``test`` on the board."""
    system = System.from_rom(ROM)
    events: list[tuple[int, int]] = []

    def press(button: int) -> None:
        for held in (button, 0):
            system.board.pads[0].buttons = held
            events.append((system.cycles, held))
            system.run_frames(3)

    system.run_frames(60)
    for _ in range(test.page_number - 1):
        press(RIGHT)
    for _ in range(test.row):
        press(DOWN)
    press(A)
    return events


def watch_reads(system: System) -> list[tuple[int, int, int]]:
    reads: list[tuple[int, int, int]] = []

    def observe(kind: str, address: int, value: int, t: int) -> None:
        if kind == "read" and 0x2000 <= address < 0x4020:
            reads.append((system.cycles, address, value))
            if len(reads) > 64:
                del reads[:32]

    system.board.bus_observers.append(observe)
    return reads


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("test", help="the test's name as AccuracyCoin's table gives it")
    parser.add_argument("--seconds", type=float, default=2.0, help="emulated seconds after A")
    args = parser.parse_args()
    tests = accuracycoin_tests((HOME / "AccuracyCoin.asm").read_text())
    test = next((t for t in tests if t.name == args.test), None)
    if test is None:
        print(f"no test named {args.test!r}", file=sys.stderr)
        return 2
    events = presses(test)
    end = events[-1][0] + int(args.seconds * 1_789_773)
    machine = dataclasses.replace(NES_001, power_on=PowerOn(palette=bytes(32)))
    ours, sim = System.from_rom(ROM, machine), system_with_ppusim(ROM, 3)
    ours_reads, sim_reads = watch_reads(ours), watch_reads(sim)
    began, index = time.monotonic(), 0
    while ours.cycles < end:
        while index < len(events) and ours.cycles >= events[index][0]:
            ours.board.pads[0].buttons = sim.board.pads[0].buttons = events[index][1]
            index += 1
        a, b = ours.cpu, sim.cpu
        state_a = (a.pc, a.a, a.x, a.y, a.p, a.s, ours.cycles)
        state_b = (b.pc, b.a, b.x, b.y, b.p, b.s, sim.cycles)
        if state_a != state_b:
            print(f"diverge at CPU cycle {ours.cycles:,} (line {ours.board.ppu.line})")
            print("  board  ", " ".join(f"{x:X}" for x in state_a[:6]))
            print("  PPUSim ", " ".join(f"{x:X}" for x in state_b[:6]))
            for label, reads in (("board", ours_reads), ("PPUSim", sim_reads)):
                tail = ", ".join(f"{c}: ${addr:04X}=${v:02X}" for c, addr, v in reads[-4:])
                print(f"  {label} reads: {tail}")
            return 1
        ours.step()
        sim.step()
    result_a = ours.board.ram[test.address & 0x7FF]
    result_b = sim.board.ram[test.address & 0x7FF]
    print(
        f"no divergence to cycle {ours.cycles:,} ({time.monotonic() - began:.0f} s); "
        f"results board ${result_a:02X}, PPUSim ${result_b:02X}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
