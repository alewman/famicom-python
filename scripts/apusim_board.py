#!/usr/bin/env python3
"""Run a test ROM on Breaknes's APUSim (the whole RP2A03G, die-derived), on a stub board.

The board around the chip (scripts/apusim/apusim_shim.cpp) has work RAM, NROM
PRG with PRG-RAM at $6000, a $2002 that sets bit 7 once a frame, and nothing
else: enough for blargg's APU tests, which report through $6000. This is how
APUSim earns (or does not earn) the judge's place for the APU's digital side
(docs/undocumented-behavior.md, open item 2): first it must pass apu_test.

    python scripts/build_apusim.py
    python scripts/apusim_board.py ROM [--seconds 10]

Also importable: :class:`APUSimBoard` records the five channels' digital
outputs at the end of every CPU cycle (``record``/``raw``) for
scripts/apusim_compare.py.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "reference" / "build-apusim" / "libapusim.so"
CPU_HZ = 1_789_773
SIGNATURE = bytes((0xDE, 0xB0, 0x61))


def _library() -> ctypes.CDLL:
    if not LIBRARY.exists():
        raise SystemExit("libapusim.so missing: python scripts/build_apusim.py")
    lib = ctypes.CDLL(str(LIBRARY))
    lib.apusim_new.restype = ctypes.c_void_p
    lib.apusim_new.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.apusim_free.argtypes = [ctypes.c_void_p]
    lib.apusim_run.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.apusim_cycles.restype = ctypes.c_uint64
    lib.apusim_cycles.argtypes = [ctypes.c_void_p]
    lib.apusim_peek.restype = ctypes.c_uint8
    lib.apusim_peek.argtypes = [ctypes.c_void_p, ctypes.c_uint16]
    lib.apusim_record.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.apusim_raw_len.restype = ctypes.c_uint64
    lib.apusim_raw_len.argtypes = [ctypes.c_void_p]
    lib.apusim_raw_copy.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint64]
    return lib


class APUSimBoard:
    def __init__(self, rom: Path) -> None:
        data = rom.read_bytes()
        prg_size = data[4] * 0x4000
        trainer = 512 if data[6] & 4 else 0
        prg = data[16 + trainer : 16 + trainer + prg_size]
        self.lib = _library()
        # The gate-level 6502 decoder caches its PLA (272 MB) as
        # Decoder6502.bin in the working directory: keep it with the build.
        with contextlib.chdir(LIBRARY.parent):
            self.h = self.lib.apusim_new(prg, len(prg))

    @property
    def cycles(self) -> int:
        return self.lib.apusim_cycles(self.h)

    def run(self, cycles: int) -> None:
        self.lib.apusim_run(self.h, cycles)

    def peek(self, address: int) -> int:
        return self.lib.apusim_peek(self.h, address)

    def record(self, on: bool) -> None:
        self.lib.apusim_record(self.h, int(on))

    def raw(self) -> bytes:
        """sqa, sqb, tri, rnd, dmc per CPU cycle since ``record(True)``."""
        n = self.lib.apusim_raw_len(self.h)
        buffer = ctypes.create_string_buffer(n)
        self.lib.apusim_raw_copy(self.h, buffer, n)
        return buffer.raw

    def text(self) -> str:
        chars = []
        for address in range(0x6004, 0x8000):
            value = self.peek(address)
            if not value:
                break
            chars.append(chr(value))
        return "".join(chars)

    def run_blargg(self, seconds: float) -> tuple[int | None, str]:
        end = self.cycles + int(seconds * CPU_HZ)
        while self.cycles < end:
            self.run(20_000)
            if bytes(self.peek(0x6001 + i) for i in range(3)) == SIGNATURE:
                status = self.peek(0x6000)
                if status < 0x80:
                    return status, self.text()
        return None, self.text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args()
    began = time.monotonic()
    board = APUSimBoard(args.rom)
    status, text = board.run_blargg(args.seconds)
    wall = time.monotonic() - began
    verdict = "no result" if status is None else ("PASS" if status == 0 else f"FAIL {status}")
    lines = " | ".join(line for line in text.splitlines() if line.strip())
    print(f"{verdict} {args.rom.name}: {lines} ({board.cycles:,} cycles, {wall:.0f} s)")
    return 0 if status == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
