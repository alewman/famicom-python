#!/usr/bin/env python3
"""Run a test ROM with Breaknes's gate-level PPUSim in place of the board's PPU.

docs/undocumented-behavior.md open item 1: before PPUSim may judge the PPU
questions the test ROMs leave open, it must reproduce what they do pin down.
This puts it on the board: famicom-python's CPU, bus, APU and cartridge, with
PPUSim (through scripts/ppusim/ppusim_shim.cpp, built by
scripts/build_ppusim.py) answering $2000-$2007 and driving /NMI.

Each CPU access to a PPU register becomes a /DBE window while M2 is high: M2
rises 9 master half-cycles into the 24-half-cycle CPU cycle (an RP2A03G's M2 is
high for 15/24 of it, CPU_pinout.wiki) and the window closes at M2's fall, when
the CPU latches read data. ``--skew`` starts PPUSim that many master
half-cycles before the CPU (0-7), which is how the console's power-on CPU/PPU
synchronization varies (nesdev-forum/6186.html).

    python scripts/ppusim_board.py ROM [--skew 0] [--seconds 60]

NROM cartridges only (the shim owns CHR). About 0.8 PPU frames per second.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

from famicom_python.machine import NES_001
from famicom_python.system import System
from famicom_python.testrom import SIGNATURE, blargg_text, peek, screen_text

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "reference" / "build-ppusim" / "libppusim.so"
M2_RISE, M2_HIGH = 9, 15  # master half-cycles into the CPU cycle; length of M2 high
ACCESS_TICKS = 8  # board.PPU_ACCESS_TICKS: where the board stops the PPU for an access


def _library() -> ctypes.CDLL:
    lib = ctypes.CDLL(str(LIBRARY))
    lib.ppusim_new.restype = ctypes.c_void_p
    lib.ppusim_new.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    for name in ("ppusim_reset",):
        getattr(lib, name).argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ppusim_run.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.ppusim_access.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 7
    for name in ("ppusim_int", "ppusim_h", "ppusim_v", "ppusim_vbl"):
        getattr(lib, name).argtypes = [ctypes.c_void_p]
    for name in ("ppusim_ciram", "ppusim_chr"):
        getattr(lib, name).argtypes = [ctypes.c_void_p, ctypes.c_int]
    return lib


class PPUSimPPU:
    """The parts of famicom_python.ppu.PPU the board and harness use, backed by PPUSim."""

    def __init__(self, chr_data: bytes, chr_writable: bool, vertical: bool, skew: int) -> None:
        self.lib = lib = _library()
        self.h = lib.ppusim_new(chr_data, len(chr_data), int(chr_writable), int(vertical))
        lib.ppusim_reset(self.h, 64)
        lib.ppusim_run(self.h, skew)
        self.time = 0  # master ticks simulated since the CPU's power-on
        self._target = 0
        self.nmi = False
        self.frame = 0
        self.line = 0
        self.dot = 0
        self.resetting = False
        self._last_v = 0
        # The CPU's data bus at the start of a write cycle: by default the
        # written value throughout M2; ppusim_compare.py also tries the
        # "early write" open-bus value for the first ``early_halves``.
        self.early_value: int | None = None
        self.early_halves = 0

    def _update(self) -> None:
        lib, h = self.lib, self.h
        self.nmi = bool(lib.ppusim_int(h))
        v = lib.ppusim_v(h)
        if v < self._last_v:
            self.frame += 1
        self._last_v = v
        self.line, self.dot = v, lib.ppusim_h(h)

    def _settle(self, time: int) -> None:
        if time > self.time:
            self.lib.ppusim_run(self.h, 2 * (time - self.time))
            self.time = time
            self._update()

    def run_to(self, time: int) -> None:
        if time % 12:  # the board's access point: the access itself runs this cycle
            self._target = time
            return
        self._settle(time)

    def _access(self, rnw: int, register: int, value: int) -> int:
        start = self._target - ACCESS_TICKS
        self._settle(start)
        early = value if self.early_value is None else self.early_value
        result = self.lib.ppusim_access(
            self.h, rnw, register, value, early, self.early_halves, M2_RISE, M2_HIGH
        )
        self.time = start + 12
        self._update()
        return result

    def read_register(self, register: int) -> int:
        value = self._access(1, register, 0)
        if register == 2:
            # PPUSim fb7de61 drives $2002 bit 7 as the complement of the VBL
            # flip-flop: Chips/PPUSim/fsm.cpp (FSM::sim_VBlankInt) latches
            # INT_FF.get() into db_latch and drives DB7 from db_latch.nget(),
            # one inversion. The die has two: the Visual2C02 netlist, the wiki's
            # hv_fsm_int_logic.jpg and the author's HDL/PPU/fsm.v all invert
            # the flag before the latch (.d(~int_ff_q)) and again on the way out
            # (nq), so the pad carries the flag itself. Reported and verified as
            # emu-russia/breaknes#529; the fix proposed there is
            #   db_latch.set(NOT(INT_FF.get()), NOT(R2_Enable));
            # with the nget() driver kept. Until a breaknes pin carries that,
            # correct the bit here. The flag's set, clear and read-race timing
            # are upstream of the driver and untouched. Remove this XOR when
            # repinning to a fixed breaknes, or the bit inverts again.
            value ^= 0x80
        return value

    def end_read(self, register: int, value: int) -> int:
        """The board's M2-fall hook: PPUSim's pins already carry it."""
        return value

    def write_register(self, register: int, value: int) -> None:
        self._access(0, register, value)

    def oam_dma_write(self, value: int) -> None:
        self.write_register(4, value)

    def reset(self) -> None:
        self.lib.ppusim_reset(self.h, 8)

    def bus_read(self, address: int) -> int:
        """Peek a nametable byte (for screen_text): CIRAM through the shim's mirroring."""
        address &= 0x3FFF
        if address >= 0x2000:
            # The shim decodes A10 itself; mirror its choice here for peeks.
            a10 = (address >> self._a10_bit) & 1
            return self.lib.ppusim_ciram(self.h, (a10 << 10) | (address & 0x3FF))
        return self.lib.ppusim_chr(self.h, address)


def system_with_ppusim(rom: Path, skew: int) -> System:
    system = System.from_rom(rom, NES_001)
    loaded = system.loaded
    assert loaded is not None
    board = loaded.image.board
    if board.mapper != 0:
        raise SystemExit(f"mapper {board.mapper}: the PPUSim shim models NROM only")
    vertical = board.mirroring == "V"
    chr_data = loaded.image.chr or bytes(0x2000)
    ppu = PPUSimPPU(chr_data, not loaded.image.chr, vertical, skew)
    ppu._a10_bit = 10 if vertical else 11
    system.board.ppu = ppu
    return system


def run(rom: Path, skew: int, seconds: float) -> tuple[str, str]:
    system = system_with_ppusim(rom, skew)
    frames = 0
    reset_at = None
    while frames < seconds * 60:
        system.run_frames(1)
        frames += 1
        if bytes(peek(system, 0x6001 + i) for i in range(3)) == SIGNATURE:
            status = peek(system, 0x6000)
            if status == 0x81:
                reset_at = reset_at or frames + 7
                if frames >= reset_at:
                    system.reset()
                    reset_at = None
                continue
            if status < 0x80:
                return ("PASS" if status == 0 else f"FAIL {status}"), blargg_text(system)
            continue
        if frames % 30 == 0:
            text = screen_text(system)
            if "PASSED" in text:
                return "PASS", text
            if "FAIL" in text:
                return "FAIL", text
    return "timeout", blargg_text(system) or screen_text(system)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("--skew", type=int, default=0, help="master half-cycles, 0-7")
    parser.add_argument("--seconds", type=float, default=60, help="emulated seconds")
    args = parser.parse_args()
    began = time.monotonic()
    verdict, text = run(args.rom, args.skew, args.seconds)
    lines = " | ".join(line for line in text.splitlines() if line.strip())
    print(f"{verdict} {args.rom.name} skew {args.skew} ({time.monotonic() - began:.0f} s): {lines}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
