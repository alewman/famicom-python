#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Milestone 6: the board against Mesen2's trace, instruction by instruction.

docs/handoff-brief.md, milestone 6: Mesen2's instruction trace (one record per
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

Mesen2 is run as a separate program: the family's mesen2-runner, machine ``nes`` with
``--trace insn``, at ``$EMU_TOOLS_GPL/tools/mesen2/run.py`` (scripts/mesen2_tool.py; exit
status 3 without ``EMU_TOOLS_GPL``). Its library must be built with the Mesen2 patch
(``mesen2-detector-fixes.patch``, a GPL file kept with the tool, which its ``build.sh``
applies), where a higher tier shows it wrong: it delays only IRQs after a taken same-
page branch, and perfect6502 shows NMIs wait too (C29); and it ignores a DMC
rate written in the timer's reload cycle, which AccuracyCoin's hardware answer
key applies (validation.md, milestone 6). The board runs with Mesen2's power-
on (``MACHINE``); Mesen2 runs with RAM zeroed and the first frame's PPU writes
ignored where the machine holds the PPU's reset, and the tool's trace
(``insn.jsonl.gz``, contract trace/insn records, ending exactly at the last frame) is
kept in ``--trace-dir`` (gitignored ``tests/mame_traces/lockstep`` by default).

``--machine vs`` still imports ``vs_judge``, which loads Mesen2's old in-process driver
(scripts/gpl_tools.py) for its own runs; only its Lua input script is used here.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import mesen2_tool
from mesen2_tool import ROOT

from famicom_python.machine import MACHINES, NES_001, Machine
from famicom_python.system import System

P_MASK = 0xCF
PASSED_OVER = "rows after a rendering-time $2007 read passed over"
# Mesen2's power-on where hardware leaves it open and the board's default
# differs: PPUSTATUS bits 7-5 clear (the board's default sets the overflow bit,
# as PPUSim does; "+0+x xxxx" allows both), and the PPU 4 dots into line 0 as
# the CPU starts (OBSERVED: found by sweeping ppu_dot over a trace, only 4
# stays in lockstep; the mechanism once read from Mesen2's source is not
# cited). The board passes every PPU and APU judge at 4, with the same
# synchronization CRCs (validation.md, milestone 6).
# The DMC's rate timer starts at a full period (DeltaModulationChannel::Reset:
# 427 CPU cycles, the board's 213 APU cycles): the only start, of 0 and
# 211-214 on either APU parity, that keeps Kirby's Adventure in step past its
# first sample.
MACHINE = replace(
    NES_001, power_on=replace(NES_001.power_on, ppustatus=0x00, ppu_dot=4, dmc_timer=213)
)
# PAL (``--machine pal``): Mesen2's DMC timer at the PAL rate 0's full period
# (398 CPU cycles, 198 APU cycles), and its PPU 4 dots and 2 master ticks in:
# swept as NTSC's 4 was (``--ppu-dot``, ``--ppu-ticks``), the only start that
# keeps Super Mario Bros. (Europe) in step (docs/validation.md milestone 10).
PAL_POWER_ON = {"ppustatus": 0x00, "dmc_timer": 198, "ppu_dot": 4, "ppu_ticks": 2}
# The Dendy: NTSC's DMC table (its UMC CPU's), the PPU start swept the same way.
DENDY_POWER_ON = {"ppustatus": 0x00, "dmc_timer": 213, "ppu_dot": 4, "ppu_ticks": 0}
DOTS, LINES = 341, 262


def lockstep_machine(name: str, ppu_dot: int | None, ppu_ticks: int | None = None) -> Machine:
    """The board as Mesen2 powers on, for ``name`` (a key of MACHINES)."""
    if name == "nes":
        machine = MACHINE
    elif name == "famicom":
        machine = replace(MACHINES["famicom"], power_on=MACHINE.power_on)
    elif name == "pal":
        base = MACHINES["pal"]
        machine = replace(base, power_on=replace(base.power_on, **PAL_POWER_ON))
    elif name == "dendy":
        base = MACHINES["dendy"]
        machine = replace(base, power_on=replace(base.power_on, **DENDY_POWER_ON))
    elif name.startswith("vs") or name == "playchoice":
        machine = replace(MACHINES[name], power_on=MACHINE.power_on)
    else:
        raise SystemExit(f"no Mesen2 power-on for {name}")
    if ppu_dot is not None:
        machine = replace(machine, power_on=replace(machine.power_on, ppu_dot=ppu_dot))
    if ppu_ticks is not None:
        machine = replace(machine, power_on=replace(machine.power_on, ppu_ticks=ppu_ticks))
    return machine


def mesen_rows(path: Path):
    """(pc, a, x, y, s, p, cycles, line, dot, frame) for each record of the tool's
    trace/insn (``insn.jsonl.gz``). Mesen2 numbers the pre-render line -1."""
    for record in mesen2_tool.insn_records(path):
        regs = record["regs"]
        line = record["line"]
        line = LINES - 1 if line < 0 else line
        yield (
            record["pc"], regs["A"], regs["X"], regs["Y"], regs["S"], regs["P"],
            record["t"], line, record["dot"], record["frame"],
        )  # fmt: skip


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
    read_2007 = [False]  # this step read $2007 while the PPU was rendering

    def observe(kind: str, address: int, value: int, t: int) -> None:
        if not fetch:
            fetch.append((board.cycles, ppu.line, ppu.dot, ppu.frame))
        elif kind == "read" and 0x2000 <= address < 0x4000 and address & 7 == 7:
            read_2007[0] = read_2007[0] or ppu.rendering_now

    system.step()  # the reset sequence
    board.bus_observers.append(observe)
    after_2007 = False  # the step that led to this row read $2007 while rendering
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
        yield regs + fetch[0] + (after_2007,)
        after_2007, read_2007[0] = read_2007[0], False


def position(line: int, dot: int) -> int:
    return line * DOTS + dot


def compare(
    rom: Path,
    trace: Path,
    context: int = 6,
    tolerate_2007: bool = False,
    machine: Machine = MACHINE,
    prepare: Callable[[System], None] | None = None,
) -> tuple[int, str]:
    """Rows that agree before the first divergence, and a report.

    ``tolerate_2007``: a row whose A, X, Y or P alone differs, right after an
    instruction that read $2007 while the PPU was rendering, is counted and
    passed over: Mesen2 does not model what the PPU bus does then, and the
    board follows PPUSim (C31). Everything else on the row must agree, and so
    must the next row.
    """
    system = System.from_rom(rom, machine)
    if prepare is not None:
        prepare(system)
    history: list[tuple[tuple, tuple]] = []
    cycle_offset = dot_offset = None
    count = 0
    tolerated: list[int] = []
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
        if (
            tolerate_2007
            and not same_cpu
            and same_cycle
            and same_dot
            and ours[10]
            and (ours[0], ours[4]) == (theirs[0], theirs[4])
            and (not tolerated or tolerated[-1] != count - 1)
        ):
            tolerated.append(count)
            count += 1
            continue
        if not (same_cpu and same_cycle and same_dot):
            checks = (("CPU", same_cpu), ("cycle", same_cycle), ("dot", same_dot))
            what = [name for name, ok in checks if not ok]
            lines = [f"first divergence after {count:,} instructions ({', '.join(what)}):"]
            if tolerated:
                lines.append(f"  ({len(tolerated)} {PASSED_OVER})")
            lines.append(f"  offsets: cycle {cycle_offset}, dot {dot_offset} (this row: {gap})")
            for a, b in history:
                lines.append("  board " + _format(a))
                lines.append("  mesen " + _format(b))
            return count, "\n".join(lines)
        count += 1
    frame = ours[9] if count else 0
    passed = f"; {len(tolerated)} {PASSED_OVER}" if tolerated else ""
    return count, (
        f"identical for all {count:,} instructions (board frame {frame}); "
        f"offsets: cycle {cycle_offset}, dot {dot_offset}{passed}"
    )


def _format(row: tuple) -> str:
    pc, a, x, y, s, p, cycles, line, dot, frame = row[:10]
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
    parser.add_argument(
        "--tolerate-2007",
        action="store_true",
        help="pass over a register differing only after a rendering-time $2007 read (C31)",
    )
    parser.add_argument(
        "--machine", choices=("nes", "famicom", "pal", "dendy", "vs"), default="nes"
    )
    parser.add_argument(
        "--vs-script",
        choices=("play", "attract"),
        default="play",
        help="--machine vs: coins and a start button for both sides (scripts/vs_judge.py)",
    )
    parser.add_argument("--ppu-dot", type=int, help="the board's power-on PPU dot (a sweep)")
    parser.add_argument("--ppu-ticks", type=int, help="... and master ticks into it (PAL)")
    args = parser.parse_args()
    global LINES
    name = args.machine
    lua = ""
    prepare = None
    if name == "vs":
        # The Vs. UniSystem with the game's PPU, and one input script for both
        # sides: Mesen2's $4016/$4017 are replaced by the mainboard's.
        import vs_judge

        chosen = System.machine_for(args.rom)
        name = next(key for key, row in MACHINES.items() if row is chosen)
        if not name.startswith("vs"):
            raise SystemExit(f"{args.rom.name} is not a Vs. System image")
        script = vs_judge.PLAY if args.vs_script == "play" else vs_judge.ATTRACT
        probe = System.from_rom(args.rom, chosen)
        lua = vs_judge.lua(script, vs_judge.held_bits(probe), vs_judge.side_of(chosen)) + lua

        def prepare(system: System) -> None:
            vs_judge.apply(system, script)

    machine = lockstep_machine(name, args.ppu_dot, args.ppu_ticks)
    LINES = machine.timing.lines
    args.trace_dir.mkdir(parents=True, exist_ok=True)
    trace = args.trace_dir / f"{args.rom.stem}.{args.machine}.{args.frames}.insn.jsonl.gz"
    if not (args.reuse and trace.exists()):
        # A fresh output folder each run (the tool keeps Mesen2's home in it): Mesen2
        # keeps battery saves there, and a save from an earlier run would be the
        # cartridge's RAM at power.
        out = Path(tempfile.mkdtemp(prefix="mesen-run-", dir=args.trace_dir))
        script = None
        if lua:
            script = out / "input.lua"
            script.write_text(lua, encoding="utf-8")
        start = time.perf_counter()
        manifest = mesen2_tool.run(
            args.rom,
            out / "run",
            args.frames,
            region=mesen2_tool.REGIONS[machine.timing.name],
            trace="insn",
            lua=script,
            ppu_reset_at_power=machine.ppu_reset_at_power,
            oam_row_corruption=machine.timing.oam_corruption,
            timeout=3600,
        )
        shutil.move(out / "run" / "insn.jsonl.gz", trace)
        wall = time.perf_counter() - start
        records = next(
            (o.get("records") for o in manifest["outputs"] if o["path"] == "insn.jsonl.gz"), None
        )
        print(
            f"Mesen2: {manifest['status']}, {wall:.0f} s, {records} instructions of trace"
            f" (Mesen2 {manifest['upstream']['commit'][:7]}, via {manifest['tool']}"
            f" {manifest['tool_version']})"
        )
    start = time.perf_counter()
    _, report = compare(
        args.rom, trace, tolerate_2007=args.tolerate_2007, machine=machine, prepare=prepare
    )
    print(report)
    print(f"compared in {time.perf_counter() - start:.0f} s")
    return 0 if report.startswith("identical") else 1


if __name__ == "__main__":
    sys.exit(main())
