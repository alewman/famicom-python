#!/usr/bin/env python3
"""Save states, proven complete: a run saved and loaded continues as the run that wasn't.

For each ROM: power on, run to frame A plus a few instructions (so the save falls
anywhere in a frame, between two instructions), save, then build a second system
from the same cartridge and machine, load the state into it, and run both to frame
B. Every frame after the save must be the same on both: every CPU-bus cycle
(address, value, direction, master tick), the picture, the PPU's v/t/status, the
audio samples and the CPU's registers. A third run loads the state into a system
that has run elsewhere first (to frame A / 2), to show loading overwrites
everything rather than relying on a fresh system's values.

    state_roundtrip.py ROM... [--machine KEY] [--at A] [--to B] [--input FILE]

``--input``: lines ``FRAME PAD BUTTONS`` (hex), applied on both runs.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import struct
import sys
from array import array

from famicom_python.cartridge import read_rom_file
from famicom_python.machine import MACHINES
from famicom_python.state import load_state, save_state
from famicom_python.system import System


def frame_digest(system: System, log: array) -> str:
    ppu, cpu = system.board.ppu, system.cpu
    digest = hashlib.sha1(log.tobytes())
    digest.update(ppu.picture.tobytes())
    samples = system.take_samples()
    digest.update(struct.pack(f"<{len(samples)}d", *samples))
    digest.update(
        struct.pack(
            "<8iq", cpu.a, cpu.x, cpu.y, cpu.s, cpu.pc, cpu.p, ppu.v, ppu.status, system.board.t
        )
    )
    return digest.hexdigest()


def run(system: System, frames: range, inputs: dict, log: array) -> list[str]:
    out = []
    for frame in frames:
        for pad, buttons in inputs.get(frame, ()):
            system.board.pads[pad].buttons = buttons
        del log[:]
        system.run_frames(1)
        out.append(frame_digest(system, log))
    return out


def observed(system: System) -> array:
    log = array("Q")
    append = log.append

    def observe(kind: str, address: int, value: int, t: int) -> None:
        append(t << 25 | (kind == "write") << 24 | address << 8 | value)

    system.board.bus_observers.append(observe)
    return log


def check(path: str, machine_key: str, at: int, to: int, inputs: dict, seed: int) -> str:
    data = read_rom_file(path)
    machine = MACHINES[machine_key]
    extra = random.Random(seed).randrange(0, 20000)

    first = System.from_rom(data, machine)
    log = observed(first)
    run(first, range(at), inputs, log)
    first.run_cycles(extra)  # anywhere in a frame, between two instructions
    state = save_state(first)
    expected = run(first, range(at + 1, to), inputs, log)

    second = System.from_rom(data, machine)
    log2 = observed(second)
    load_state(second, state)
    got = run(second, range(at + 1, to), inputs, log2)

    third = System.from_rom(data, machine)
    log3 = observed(third)
    run(third, range(at // 2), inputs, log3)  # somewhere else first
    load_state(third, state)
    got3 = run(third, range(at + 1, to), inputs, log3)

    for frame, (a, b, c) in enumerate(zip(expected, got, got3, strict=True), start=at + 1):
        if a != b:
            return f"differs at frame {frame} (loaded into a fresh system)"
        if a != c:
            return f"differs at frame {frame} (loaded into a system that had run)"
    span = f"frames {at + 1}-{to - 1}"
    return f"identical: {span} after a save at frame {at} + {extra} cycles ({len(state):,} bytes)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roms", nargs="+")
    parser.add_argument("--machine", default="nes")
    parser.add_argument("--at", type=int, default=120)
    parser.add_argument("--to", type=int, default=240)
    parser.add_argument("--input")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    inputs: dict[int, list[tuple[int, int]]] = {}
    if args.input:
        with open(args.input) as handle:
            for text in handle:
                parts = text.split()
                if len(parts) == 3 and not text.startswith("#"):
                    inputs.setdefault(int(parts[0]), []).append((int(parts[1]), int(parts[2], 16)))
    failed = 0
    for rom in args.roms:
        try:
            verdict = check(rom, args.machine, args.at, args.to, inputs, args.seed)
        except Exception as error:
            verdict = f"error: {type(error).__name__}: {error}"
        failed += not verdict.startswith("identical")
        print(f"{rom}: {verdict}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
