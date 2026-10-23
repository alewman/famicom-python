#!/usr/bin/env python3
"""Sort the sweep's differing dumps by what the board did where the pixels differ.

For each dump ``compat_sweep.py`` found differing, the board runs again to the
first differing frame, logging every PPUMASK write that changes the rendering
enables (bits 3-4) while the PPU is on a visible line, and the frame is
compared with Mesen2's again. A dump whose differing pixels all lie on lines
where rendering was switched mid-line is "mid-line rendering toggle": the
rendering-enable latency (C12), where Mesen2 (1 dot) is not the judge and
PPUSim is. One whose differing lines all had a $2000/$2005/$2006/$2007 access
while rendering is "mid-line register write": the write latencies milestone 2
settled on PPUSim (C13, C15) and the $2007 collision (C31), where Mesen2
differs. Everything else is listed for diagnosis by hand (lockstep first).

    nice pypy3 scripts/sweep_triage.py RESULTS.jsonl [--jobs 8] > triage.jsonl
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
import tempfile
from pathlib import Path

from compat_sweep import BASE, finished_picture, mesen_frames
from mesen_lockstep import MACHINE

from famicom_python.system import System


def triage(entry: dict) -> dict:
    first = next(f for f in entry["frames"] if f.get("diff"))
    frame = first["frame"]
    rom = BASE / entry["set"] / entry["rom"]
    with tempfile.TemporaryDirectory(prefix="mesen-home-") as home:
        theirs = mesen_frames(rom, [frame], Path(home))[frame]
    system = System.from_rom(rom, MACHINE)
    board, ppu = system.board, system.board.ppu
    system.run_frames(frame - 2)
    toggles: list[tuple[int, int]] = []
    splits: list[tuple[int, int, int]] = []  # mid-line $2000/$2005/$2006/$2007 accesses
    write, read = board.write_byte, board.read_byte

    def watch(address: int, value: int) -> None:
        register = address & 0xE007
        if ppu.line < 240 and register in (0x2001, 0x2000, 0x2005, 0x2006, 0x2007):
            if register == 0x2001:
                if (value ^ ppu.mask) & 0x18:
                    toggles.append((ppu.line, ppu.dot))
            elif ppu.mask & 0x18:
                splits.append((ppu.line, ppu.dot, register & 7))
        write(address, value)

    def watch_read(address: int) -> int:
        if (address & 0xE007) == 0x2007 and ppu.line < 240 and ppu.mask & 0x18:
            splits.append((ppu.line, ppu.dot, 7))
        return read(address)

    board.write_byte = system.cpu.write_byte = watch  # the CPU holds its own reference
    board.read_byte = system.cpu.read_byte = watch_read
    system.run_frames(1)
    toggles.clear()  # the frame drawn is the one begun now
    splits.clear()
    ours = finished_picture(system)
    rows = sorted({i // 256 for i in range(len(ours)) if ours[i] != theirs[i]})
    toggled = {line for line, _ in toggles}
    written = {line for line, _, _ in splits} | toggled

    def near(lines: set[int]) -> bool:
        return bool(rows) and all(r in lines or r - 1 in lines for r in rows)

    if toggles and near(toggled):
        cause = "mid-line rendering toggle"
    elif splits and near(written):
        cause = "mid-line register write"
    else:
        cause = "to diagnose"
    return {
        "rom": entry["rom"],
        "mapper": entry.get("mapper"),
        "frame": frame,
        "pixels": first["diff"],
        "rows": rows[:12],
        "toggles": toggles[:12],
        "splits": splits[:12],
        "cause": cause,
    }


def worker(entry: dict) -> str:
    try:
        return json.dumps(triage(entry))
    except Exception as error:  # recorded; the triage goes on
        return json.dumps({"rom": entry["rom"], "cause": f"triage error: {error!r}"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    entries = [json.loads(line) for line in args.results.read_text().splitlines() if line]
    differing = [
        e for e in entries if e["status"] == "differs" and any(f.get("diff") for f in e["frames"])
    ]
    context = multiprocessing.get_context("spawn")
    with context.Pool(args.jobs, maxtasksperchild=1) as pool:
        for line in pool.imap_unordered(worker, differing):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
