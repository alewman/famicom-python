"""kevtris's nestest in automation mode against nestest.log (docs/handoff-brief.md, milestone 1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from famicom_python.system import System

ROMS = Path(__file__).resolve().parent / "test_roms" / "nes-test-roms"
NESTEST = ROMS / "other" / "nestest.nes"
NESTEST_LOG = ROMS / "other" / "nestest.log"
LINE = re.compile(
    r"^(?P<pc>[0-9A-F]{4}) .*A:(?P<a>[0-9A-F]{2}) X:(?P<x>[0-9A-F]{2}) Y:(?P<y>[0-9A-F]{2}) "
    r"P:(?P<p>[0-9A-F]{2}) SP:(?P<s>[0-9A-F]{2}) "
    r"PPU:\s*(?P<line>\d+),\s*(?P<dot>\d+) CYC:(?P<cyc>\d+)"
)
P_MASK = 0xCF  # bits 5 and 4 are not flags: PHP/BRK push them, nothing holds them


@dataclass(frozen=True)
class Row:
    pc: int
    a: int
    x: int
    y: int
    p: int
    s: int
    cycles: int
    line: int
    dot: int

    def key(self) -> tuple[int, ...]:
        return (self.pc, self.a, self.x, self.y, self.p & P_MASK, self.s, self.cycles)


def read_log(path: Path = NESTEST_LOG) -> list[Row]:
    rows = []
    for text in path.read_text().splitlines():
        m = LINE.match(text)
        assert m, text
        hexes = {k: int(m[k], 16) for k in ("pc", "a", "x", "y", "p", "s")}
        rows.append(Row(**hexes, cycles=int(m["cyc"]), line=int(m["line"]), dot=int(m["dot"])))
    return rows


def run(count: int) -> tuple[System, list[Row]]:
    """Power on, run the reset sequence, start at $C000; one Row per instruction boundary.

    Power-on values for lines 1-2: A = X = Y = 0 and S = 0 before the reset
    sequence, which leaves S = $FD, P = $24 and the cycle count at 7.
    """
    system = System.from_rom(NESTEST)
    system.step()  # the reset sequence
    cpu, board, ppu = system.cpu, system.board, system.board.ppu
    cpu.pc = 0xC000
    rows = []
    for _ in range(count):
        rows.append(Row(cpu.pc, cpu.a, cpu.x, cpu.y, cpu.p, cpu.s, board.cycles, ppu.line, ppu.dot))
        system.step()
    return system, rows
