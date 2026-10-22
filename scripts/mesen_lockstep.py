#!/usr/bin/env python3
"""Milestone 6: the board against Mesen2's trace, instruction by instruction.

docs/handoff-brief.md, milestone 6: Mesen2's trace logger (one line per
instruction: registers, CPU cycle count, PPU scanline and dot) against the
board's state at every instruction boundary, from power-on, no input, for
``--frames`` frames; the first divergence is printed with the lines before it.
Mesen2 is a detector (validation.md): a divergence is a question, answered by
a higher tier before either side is called wrong.

    python scripts/mesen_lockstep.py ROM --frames 3600 [--trace-dir DIR]

Alignment, fixed on the first instruction and then required constant: the
CPU cycle counts differ by an offset (each side counts power-on differently),
and the PPU positions by a number of dots (Mesen2 numbers the pre-render line
-1; the board 261). Mesen2 logs instructions only, so the board's interrupt
entries (6502-python steps them separately) are dropped: a step that pushed
three bytes, set I and landed on the NMI or IRQ vector's target without
executing BRK. P is compared without bits 5 and 4 (not flags).

The board runs with Mesen2's power-on (``MACHINE``); Mesen2 runs with
``configure_for_comparison`` (RAM zeroed, the first frame's
PPU writes ignored) and its trace goes to ``--trace-dir`` (gitignored
``tests/mame_traces/lockstep`` by default; about 80 bytes an instruction,
1.7 GB a minute).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

from mesen_run import ROOT, run_mesen

from famicom_python.machine import NES_001
from famicom_python.system import System

MESEN_LINE = re.compile(
    rb"^[0-9A-F]{4} +([0-9A-F]{4}) A:([0-9A-F]{2}) X:([0-9A-F]{2}) Y:([0-9A-F]{2}) S:([0-9A-F]{2}) "
    rb"P:([0-9A-F]{2}) CYC:(\d+) SL:(-?\d+) DOT:(\d+) FR:(\d+)"
)
P_MASK = 0xCF
# Mesen2's power-on where hardware leaves it open and the board's default
# differs: PPUSTATUS bits 7-5 clear (the board's default sets the overflow bit,
# as PPUSim does; "+0+x xxxx" allows both), and the PPU 4 dots into line 0 as
# the CPU starts (NesCpu::Reset adds a CPU divider to the master clock, and
# the PPU runs 1 tick behind it). Found by sweeping ppu_dot over a trace: only
# 4 stays in lockstep. The board passes every PPU and APU judge at 4, with the
# same synchronization CRCs (validation.md, milestone 6).
MACHINE = replace(NES_001, power_on=replace(NES_001.power_on, ppustatus=0x00, ppu_dot=4))
DOTS, LINES = 341, 262

STOP_AFTER_FRAMES = """
local frames = 0
emu.addEventCallback(function()
  frames = frames + 1
  if frames >= {frames} then emu.stop(0) end
end, emu.eventType.endFrame)
"""


def mesen_rows(path: Path):
    """(pc, a, x, y, s, p, cycles, line, dot, frame) for each line of Mesen2's trace."""
    with path.open("rb") as stream:
        for text in stream:
            m = MESEN_LINE.match(text)
            if m is None:
                continue
            pc, a, x, y, s, p = (int(m[i], 16) for i in range(1, 7))
            line = int(m[8])
            line = LINES - 1 if line < 0 else line
            yield pc, a, x, y, s, p, int(m[7]), line, int(m[9]), int(m[10])


def board_rows(system: System):
    """The same tuple for each instruction the board executes, interrupt entries left out.

    The cycle count and PPU position are taken at the opcode fetch's read, as
    Mesen2 logs: after any DMA that stalled it (the board runs OAM and DMC DMA
    inside that read, which a bus observer sees only once the read is done).
    """
    cpu, board, ppu = system.cpu, system.board, system.board.ppu
    read = board.ram.__getitem__
    cartridge = system.cartridge
    nmi_vector = irq_vector = None
    fetch: list[tuple[int, int, int, int]] = []

    def observe(kind: str, address: int, value: int, t: int) -> None:
        if not fetch:
            fetch.append((board.cycles, ppu.line, ppu.dot, ppu.frame))

    system.step()  # the reset sequence
    board.bus_observers.append(observe)
    while True:
        regs = (cpu.pc, cpu.a, cpu.x, cpu.y, cpu.s, cpu.p)
        s, opcode_pc = cpu.s, cpu.pc
        fetch.clear()
        system.step()
        if (s - cpu.s) & 0xFF == 3 and cpu.p & 0x04:
            if nmi_vector is None:
                peek = lambda a: cartridge.cpu_read(a, board.t) or 0  # noqa: E731
                nmi_vector = peek(0xFFFA) | peek(0xFFFB) << 8
                irq_vector = peek(0xFFFE) | peek(0xFFFF) << 8
            if opcode_pc >= 0x4020:
                opcode = cartridge.cpu_read(opcode_pc, board.t)
            else:
                opcode = read(opcode_pc & 0x7FF)
            if cpu.pc in (nmi_vector, irq_vector) and opcode != 0x00:
                continue  # an interrupt entry: Mesen2 logs none
        yield regs + fetch[0]


def mesen_path(rom: Path) -> Path:
    """Mesen2 opens a .zip's member as "archive\\x01member" (Utilities/VirtualFile.cpp)."""
    if rom.suffix.lower() != ".zip":
        return rom
    with zipfile.ZipFile(rom) as archive:
        (member,) = [n for n in archive.namelist() if n.lower().endswith(".nes")]
    return Path(f"{rom.resolve()}\x01{member}")


def position(line: int, dot: int) -> int:
    return line * DOTS + dot


def compare(rom: Path, trace: Path, context: int = 6) -> tuple[int, str]:
    """Rows that agree before the first divergence, and a report."""
    system = System.from_rom(rom, MACHINE)
    history: list[tuple[tuple, tuple]] = []
    cycle_offset = dot_offset = None
    count = 0
    for ours, theirs in zip(board_rows(system), mesen_rows(trace), strict=False):
        if cycle_offset is None:
            cycle_offset = theirs[6] - ours[6]
            dot_offset = (position(theirs[7], theirs[8]) - position(ours[7], ours[8])) % (
                LINES * DOTS
            )
        history = [*history[-context:], (ours, theirs)]
        same_cpu = ours[:5] == theirs[:5] and ours[5] & P_MASK == theirs[5] & P_MASK
        same_cycle = theirs[6] - ours[6] == cycle_offset
        gap = (position(theirs[7], theirs[8]) - position(ours[7], ours[8])) % (LINES * DOTS)
        same_dot = gap == dot_offset
        if not (same_cpu and same_cycle and same_dot):
            checks = (("CPU", same_cpu), ("cycle", same_cycle), ("dot", same_dot))
            what = [name for name, ok in checks if not ok]
            lines = [f"first divergence after {count:,} instructions ({', '.join(what)}):"]
            lines.append(f"  offsets: cycle {cycle_offset}, dot {dot_offset} (this row: {gap})")
            for a, b in history:
                lines.append("  board " + _format(a))
                lines.append("  mesen " + _format(b))
            return count, "\n".join(lines)
        count += 1
    frame = ours[9] if count else 0
    return count, (
        f"identical for all {count:,} instructions (board frame {frame}); "
        f"offsets: cycle {cycle_offset}, dot {dot_offset}"
    )


def _format(row: tuple) -> str:
    pc, a, x, y, s, p, cycles, line, dot, frame = row
    return (
        f"{pc:04X} A:{a:02X} X:{x:02X} Y:{y:02X} S:{s:02X} P:{p:02X} "
        f"CYC:{cycles} L:{line} D:{dot} F:{frame}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("--frames", type=int, default=3600, help="Mesen2 frames (60 s = 3600)")
    parser.add_argument("--trace-dir", type=Path, default=ROOT / "tests/mame_traces/lockstep")
    parser.add_argument("--reuse", action="store_true", help="compare an existing trace again")
    args = parser.parse_args()
    args.trace_dir.mkdir(parents=True, exist_ok=True)
    trace = args.trace_dir / f"{args.rom.stem}.{args.frames}.trace"
    if not (args.reuse and trace.exists()):
        lua = STOP_AFTER_FRAMES.replace("{frames}", str(args.frames)).encode()
        code, _, wall = run_mesen(
            mesen_path(args.rom),
            lua=lua,
            seconds=3600,
            home=args.trace_dir / "mesen-home",
            trace=trace,
            for_comparison=True,
        )
        print(f"Mesen2: stop code {code}, {wall:.0f} s, {trace.stat().st_size:,} bytes of trace")
    start = time.perf_counter()
    _, report = compare(args.rom, trace)
    print(report)
    print(f"compared in {time.perf_counter() - start:.0f} s")
    return 0 if report.startswith("identical") else 1


if __name__ == "__main__":
    sys.exit(main())
