#!/usr/bin/env python3
"""Put the board's PPU and PPUSim through the same register accesses and compare pins.

docs/undocumented-behavior.md open item 1: with PPUSim shown to reproduce
``ppu_vbl_nmi`` (docs/validation.md, milestone 2; skew 3), it judges what no
test ROM pins: the PPUMASK latency (C12), the odd-frame skip's enable bit
(C13), the sprite garbage fetches (C15), the empty-slot row, the $2006 delay
(C21), the $2007 increment (C22) and the render-start OAM copy (C32,
``oam_start``).

Both PPUs are driven exactly as the board drives one (board.py: run to the
access point, access, run to the cycle's end), from the same list of CPU
cycles, without a CPU. Ours reports fetches through the connector and pixels
through ``picture``; PPUSim through the shim's pin trace (ALE, /RD, the
address, RAW video, /INT per master half-cycle). Times are master ticks since
power-on in both.

    python scripts/ppusim_compare.py [experiment ...]
    python scripts/ppusim_compare.py frame ROM N [MACHINE]   # a whole frame, CPU included

NROM only, through scripts/ppusim_board.py; builds nothing (run
scripts/build_ppusim.py first).
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from pathlib import Path

from ppusim_board import LIBRARY, PPUSimPPU, system_with_ppusim

from famicom_python.cartridge import Cartridge
from famicom_python.machine import MACHINES, NES_001, Machine
from famicom_python.ppu import BORDER, HEIGHT
from famicom_python.system import System

ROOT = Path(__file__).resolve().parents[1]
# Any NROM image will do; this one has blargg's font in CHR, so pictures vary.
ROM = (
    ROOT
    / "tests"
    / "test_roms"
    / "nes-test-roms"
    / "ppu_vbl_nmi"
    / "rom_singles"
    / "01-vbl_basics.nes"
)
SKEW = 3  # the one skew where PPUSim passes all of ppu_vbl_nmi
# PAL's: where the board, with Timing.ppu_access_ticks 9, comes closest to
# PPUSim's RP2C07-0 (docs/validation.md milestone 10); no PAL ROM pins it.
PAL_SKEW = 1


def skew_for(machine: Machine) -> int:
    return PAL_SKEW if machine.timing.name == "PAL" else SKEW


RESET_HALVES = 64  # PPUSimPPU holds /RES for 64 half-cycles before time 0
CYCLE = 12  # master ticks per CPU cycle
FRAME_CYCLES = 29781  # a little over one frame of CPU cycles


class TraceEntry(ctypes.Structure):
    _fields_ = [
        ("half", ctypes.c_uint64),
        ("h", ctypes.c_uint16),
        ("v", ctypes.c_uint16),
        ("address", ctypes.c_uint16),
        ("video", ctypes.c_uint16),
        ("pins", ctypes.c_uint8),
        ("inner", ctypes.c_uint8 * 5),  # internal signals (ppusim_shim.cpp)
        ("background", ctypes.c_uint8 * 8),  # the background path (ppusim_shim.cpp)
    ]


class Pair:
    """Our PPU and PPUSim, fed the same CPU cycles."""

    def __init__(
        self, rom: Path = ROM, skew: int | None = None, machine: Machine = NES_001
    ) -> None:
        ours = System.from_rom(rom, machine)
        skew = skew_for(machine) if skew is None else skew
        timing = machine.timing
        self.cycle = timing.cpu_divider  # master ticks per CPU cycle
        self.frame_cycles = timing.lines * 341 * timing.dot_divider // timing.cpu_divider + 1
        self.lines = timing.lines
        self.dots_per_cycle = timing.cpu_divider / timing.dot_divider
        self.ours = ours.board.ppu
        self.cartridge: Cartridge = ours.board.cartridge
        self.ours._watch = True  # report ALE addresses too
        self.fetches: list[tuple[int, int]] = []  # (time, address) of each /RD
        self.ales: list[tuple[int, int]] = []
        original_read = self.cartridge.ppu_read
        self.cartridge.ppu_address = lambda a, t: self.ales.append((t, a))  # type: ignore[method-assign]

        def read(address: int, time: int) -> int:
            self.fetches.append((time, address))
            return original_read(address, time)

        self.cartridge.ppu_read = read  # type: ignore[method-assign]

        image = ours.loaded.image if ours.loaded else None
        assert image is not None and image.board.mapper == 0
        self.skew = skew
        self.sim = PPUSimPPU(
            image.chr or bytes(0x2000),
            not image.chr,
            image.board.mirroring == "V",
            skew,
            timing.name == "PAL",
            timing.ppu_access_ticks,
        )
        self.access_ticks = timing.ppu_access_ticks
        self.sim._a10_bit = 10 if image.board.mirroring == "V" else 11
        _trace_api(self.sim.lib)
        self.t = 0  # master ticks at the end of the last CPU cycle
        self.line_start = 0  # self.t when the traced line began

    # -- driving ----------------------------------------------------------

    def idle(self, cycles: int) -> None:
        self.t += cycles * self.cycle
        for ppu in (self.ours, self.sim):
            ppu.run_to(self.t)

    def access(self, register: int, value: int | None = None) -> tuple[int, int]:
        """One CPU cycle accessing $2000 + register (a read if value is None)."""
        self.t += self.cycle
        results = []
        for ppu in (self.ours, self.sim):
            ppu.run_to(self.t + self.access_ticks - self.cycle)
            if value is None:
                results.append(ppu.read_register(register))
            elif ppu is self.ours:
                access = self.t + self.access_ticks - self.cycle
                ppu.write_register(register, value, self.sim.early_value, ppu.time - access)
                results.append(value)
            else:
                ppu.write_register(register, value)
                results.append(value)
            ppu.run_to(self.t)
            if value is None:  # what passes through to M2's fall, as on the board
                results[-1] = ppu.end_read(register, results[-1])
        return results[0], results[1]

    def write(self, register: int, value: int) -> None:
        """A write as ``STA $200x`` makes it: the access is the last of 4 cycles.

        Back-to-back accesses on consecutive cycles are not something a 6502
        can make, and PPUSim's $2007 write sequence takes longer than one
        cycle (consecutive writes collide).
        """
        self.idle(3)
        self.access(register, value)

    def to_line(self, line: int, dot: int = 0) -> None:
        """Idle until our PPU is at or just past (line, dot), on a cycle boundary."""
        ours = self.ours
        while (ours.line, ours.dot) != (line, dot):
            target = line * 341 + dot
            now = ours.line * 341 + ours.dot
            gap = (target - now) % (self.lines * 341)
            if gap < self.dots_per_cycle:
                break
            self.idle(max(1, int(gap / self.dots_per_cycle) - 1))

    # -- observing --------------------------------------------------------

    def trace(self, on: bool) -> None:
        self.sim.lib.ppusim_trace(self.sim.h, int(on))
        if on:
            self.fetches.clear()
            self.ales.clear()

    def sim_trace(self) -> list[TraceEntry]:
        lib, h = self.sim.lib, self.sim.h
        n = lib.ppusim_trace_len(h)
        array = (TraceEntry * n).from_address(lib.ppusim_trace_data(h))
        return list(array)

    def half_to_time(self, half: int) -> float:
        return (half - RESET_HALVES - self.skew) / 2

    def sim_fetches(self) -> list[tuple[float, int]]:
        """(time, address) at each /RD fall in the trace."""
        out, low = [], False
        for e in self.sim_trace():
            rd = bool(e.pins & 2)
            if rd and not low:
                out.append((self.half_to_time(e.half), e.address))
            low = rd
        return out

    def sim_ales(self) -> list[tuple[float, int]]:
        """(time, address) at each ALE rise in the trace."""
        out, high = [], False
        for e in self.sim_trace():
            ale = bool(e.pins & 1)
            if ale and not high:
                out.append((self.half_to_time(e.half), e.address))
            high = ale
        return out

    def sim_pixels(self) -> dict[tuple[int, int], int]:
        """RAW video by (V, H), the last half-cycle's value of each dot."""
        return {(e.v, e.h): e.video for e in self.sim_trace()}


def setup_picture(pair: Pair) -> None:
    """Power-up wait, then the same nametable and palette in both."""
    pair.idle(2 * FRAME_CYCLES)
    pair.to_line(241, 10)
    pair.write(0, 0x00)
    pair.write(1, 0x00)
    pair.idle(3)
    pair.access(2)
    pair.write(6, 0x3F)
    pair.write(6, 0x00)
    for i in range(32):
        pair.write(7, (i * 7 + 1) & 0x3F)
    pair.write(6, 0x20)
    pair.write(6, 0x00)
    for i in range(0x3C0):
        pair.write(7, (i * 13 + i // 32) & 0xFF)
    for i in range(0x40):
        pair.write(7, (i * 37) & 0xFF)


def scroll_zero(pair: Pair) -> None:
    pair.idle(3)
    pair.access(2)
    pair.write(5, 0)
    pair.write(5, 0)
    pair.write(6, 0x20)
    pair.write(6, 0x00)
    pair.write(0, 0x08)  # sprites at $1000


# -- experiments -----------------------------------------------------------


def calibrate(pair: Pair) -> None:
    """A rendered frame: fetch sequences and pixels must agree, at fixed offsets."""
    setup_picture(pair)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    pair.to_line(20, 0)
    pair.trace(True)
    pair.to_line(22, 0)
    pair.trace(False)
    # The connector sees pattern fetches as reads; nametable reads go to CIRAM.
    ours = [f for f in pair.fetches if f[1] < 0x2000]
    sim = [f for f in pair.sim_fetches() if f[1] < 0x2000]
    print(f"pattern fetches: ours {len(ours)}, PPUSim {len(sim)} over lines 20-21")
    n = min(len(ours), len(sim))
    same = sum(1 for i in range(n) if ours[i][1] == sim[i][1])
    offsets = sorted({sim[i][0] - ours[i][0] for i in range(n)})
    print(f"  addresses equal in order: {same} of {n}; time offsets (PPUSim - ours): {offsets[:6]}")
    for i in range(n):
        if ours[i][1] != sim[i][1]:
            print(f"  first difference at fetch {i}: ours {ours[i][1]:04X} PPUSim {sim[i][1]:04X}")
            break
    pixels = pair.sim_pixels()
    picture = pair.ours.picture
    for shift in range(-4, 8):
        match = sum(1 for x in range(256) if pixels.get((20, x + shift)) == picture[20 * 256 + x])
        print(f"  pixels of line 20 equal with PPUSim H = x + {shift}: {match} of 256")


SIM_PIXEL_H = 4  # PPUSim shows pixel x at H = x + 4 (calibrate)


def rendered(pair: Pair, mask: int = 0x0A) -> None:
    """The picture, scrolled to 0, rendering with ``mask`` from the next frame."""
    setup_picture(pair)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, mask)
    pair.to_line(10, 0)


BUS_MODELS = {
    "clean": (None, 0),  # the written value for all of M2
    "early": (0x20, 8),  # open bus ($20, STA $20xx's high byte) for the first dot
}


def compare_line(pair: Pair, line: int) -> str:
    """Pixels and ALE addresses of a traced ``line``: where ours and PPUSim part."""
    ours_row = list(pair.ours.picture[line * 256 : line * 256 + 256])
    pixels = pair.sim_pixels()
    sim_row = [pixels.get((line, x + SIM_PIXEL_H), -1) for x in range(256)]
    xs = [x for x in range(256) if ours_row[x] != sim_row[x]]
    ours, sim = overlap(pair.ales, [(t + 4, a) for t, a in pair.sim_ales()])
    ours_at, sim_at = dict(ours), dict(sim)
    times = sorted(t for t in set(ours_at) | set(sim_at) if ours_at.get(t) != sim_at.get(t))
    text = f"pixels differ at x {xs[0]}-{xs[-1]} ({len(xs)})" if xs else "pixels equal"
    if xs and xs[-1] - xs[0] < 8:
        window = range(max(0, xs[0] - 2), min(256, xs[-1] + 3))
        text += f" [from x {window.start}: ours "
        text += " ".join(f"{ours_row[x]:02X}" for x in window) + " / PPUSim "
        text += " ".join(f"{sim_row[x]:02X}" for x in window) + "]"
    if times:
        start = pair.line_start
        dots = sorted({int(t - start) // 4 for t in times})
        text += f"; ALE differs at dots {dots[:6]}{'...' if len(dots) > 6 else ''}"
    elif ours or sim:
        text += "; ALE equal"
    return text


def mid_line_case(
    pair: Pair, line: int, cycles: int, writes: list[tuple[int, int]], before: list[tuple[int, int]]
) -> int:
    """Trace ``line`` with ``writes`` starting ``cycles`` into it; returns our first access dot.

    ``before`` runs at the end of the previous line, to set the state up.
    """
    pair.to_line(line - 1, 300)
    for register, value in before:
        pair.write(register, value)
    pair.to_line(line, 0)
    pair.line_start = pair.t
    pair.trace(True)
    pair.idle(cycles)
    dot = None
    for register, value in writes:
        if value is None:
            pair.idle(3)
            pair.access(register)
        else:
            pair.write(register, value)
        if dot is None:
            dot = pair.ours.dot - 1  # the access is a dot before the cycle's end
    pair.to_line(line + 1, 0)
    pair.trace(False)
    assert dot is not None
    return dot


def run_cases(
    pair: Pair, cases: list[tuple[str, list[tuple[int, int]], list[tuple[int, int]]]]
) -> None:
    line = 20
    for model, (early, halves) in BUS_MODELS.items():
        pair.sim.early_value, pair.sim.early_halves = early, halves
        print(f"bus: {model}")
        for name, before, writes in cases:
            print(f"  {name}")
            for _ in range(3):  # 341 = 2 mod 3: each line puts the write on another dot phase
                dot = mid_line_case(pair, line, 40, writes, before)
                result = compare_line(pair, line)
                print(f"    first access at dot {dot} (dot mod 3 = {dot % 3}): {result}")
                line += 1
                if line > 236:
                    pair.to_line(10, 0)
                    line = 20


def c12(pair: Pair) -> None:
    """PPUMASK mid-line: emphasis, greyscale, BG off and on."""
    rendered(pair, 0x0A)
    run_cases(
        pair,
        [
            ("emphasis on ($0A -> $2A)", [(1, 0x0A)], [(1, 0x2A)]),
            ("greyscale on ($0A -> $0B)", [(1, 0x0A)], [(1, 0x0B)]),
            ("BG off ($0A -> $00)", [(1, 0x0A)], [(1, 0x00)]),
            ("BG on ($00 -> $0A)", [(1, 0x00)], [(1, 0x0A)]),
        ],
    )


def c21_c22(pair: Pair) -> None:
    """$2006 and $2007 mid-line with rendering off: the backdrop shows palette[v]."""
    setup_picture(pair)
    pair.to_line(10, 0)
    run_cases(
        pair,
        [
            ("$2006 $3F,$05 after v = $3F00 (C21)", [(6, 0x3F), (6, 0x00)], [(6, 0x3F), (6, 0x05)]),
            ("$2007 write at v = $3F01 (C22)", [(6, 0x3F), (6, 0x01)], [(7, 0x16)]),
            ("$2007 read at v = $3F01", [(6, 0x3F), (6, 0x01)], [(7, None)]),
            ("$2007 read at v = $3F1F", [(6, 0x3F), (6, 0x1F)], [(7, None)]),
        ],
    )


def c21_rendering(pair: Pair) -> None:
    """A second $2006 write mid-line with rendering on: when do fetches use it (C21)?"""
    rendered(pair, 0x0A)
    run_cases(pair, [("$2006 $21,$08 mid-line", [], [(6, 0x21), (6, 0x08)])])


def fetches(pair: Pair) -> None:
    """Every ALE address of three lines with BG and sprites: C15 and the empty-slot row.

    Sprites: three on lines 40-47 (slots 0-2; slots 3-7 empty), OAM[63] at
    Y = 30 so "line - OAM[63].Y" and "row 0" give different rows.
    """
    setup_picture(pair)
    pair.write(3, 0)
    oam = [0xF8] * 256
    oam[0:12] = [39, 0x41, 0x00, 16, 39, 0x42, 0x01, 40, 39, 0x43, 0x02, 64]
    oam[252:256] = [30, 0x44, 0x00, 200]
    for value in oam:
        pair.write(4, value)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    for line in (39, 43, 60):
        pair.to_line(line, 0)
        pair.trace(True)
        pair.to_line(line + 1, 0)
        pair.trace(False)
        ours, sim = overlap(pair.ales, [(t + 4, a) for t, a in pair.sim_ales()])
        print(f"line {line}: {len(ours)} ALE addresses in both windows", end="")
        report_differences(ours, sim)


def overlap(
    ours: list[tuple[int, int]], sim: list[tuple[float, int]]
) -> tuple[list[tuple[int, int]], list[tuple[float, int]]]:
    """The two (time, address) lists cut to the time range both cover."""
    if not ours or not sim:
        return ours, sim
    first = max(ours[0][0], sim[0][0])
    last = min(ours[-1][0], sim[-1][0])
    return (
        [f for f in ours if first <= f[0] <= last],
        [f for f in sim if first <= f[0] <= last],
    )


def report_differences(ours: list[tuple[int, int]], sim: list[tuple[float, int]]) -> None:
    sim_at = dict(sim)
    ours_at = dict(ours)
    differ = [
        (t, ours_at.get(t), sim_at.get(t))
        for t in sorted(set(ours_at) | set(sim_at))
        if ours_at.get(t) != sim_at.get(t)
    ]
    print(f"; {len(differ)} differ" + (":" if differ else ""))
    for t, a, b in differ[:12]:
        print(f"  t {t}: ours {a and f'{a:04X}'}, PPUSim {b and f'{b:04X}'}")


def c13(pair: Pair) -> None:
    """The odd-frame skip with only BG or only sprites enabled: do the PPUs stay in step?"""
    setup_picture(pair)
    for mask in (0x08, 0x10, 0x00):
        pair.to_line(241, 10)
        pair.write(1, mask)
        rows = []
        for _ in range(4):
            pair.idle(FRAME_CYCLES // 2)
            pair.to_line(100, 0)
            ours, sim = pair.ours, pair.sim
            rows.append((ours.frame, ours.line, ours.dot, sim.line, sim.dot))
        print(f"$2001 = ${mask:02X}: (frame, ours line/dot, PPUSim V/H) at our line 100")
        for frame, line, dot, v, h in rows:
            print(f"  frame {frame}: ours {line}/{dot}, PPUSim {v}/{h}")


def oam_start(pair: Pair) -> None:
    """OAMADDR at render start: is row OAMADDR & $F8 copied over OAM[0-7] (Errata.wiki)?

    Sprite 0 and 1 are off-screen; row $80 holds a sprite over the opaque
    background. OAMADDR is left at the start value by writing OAM through
    $2004 (no $2003 write, which has its own corruption); after a rendered
    frame, $2002 bit 6 says whether a sprite 0 hit happened.
    """
    setup_picture(pair)
    for row, start in ((0, 0), (0x80, 0x80), (0x80, 0x84), (0x80, 0x04)):
        oam = [0xF8] * 256
        oam[row : row + 4] = [39, 0x41, 0x00, 16]
        pair.to_line(241, 10)
        pair.write(1, 0x00)
        pair.write(3, 0)
        for value in oam + oam[:start]:
            pair.write(4, value)
        pair.to_line(261, 100)
        scroll_zero(pair)
        pair.write(0, 0x00)  # 8x8 sprites from $0000, where the font is
        pair.write(1, 0x1E)
        pair.to_line(100, 0)
        ours, sim = pair.access(2)
        print(
            f"sprite in row ${row:02X}, OAMADDR ${start:02X} at render start: "
            f"$2002 ours ${ours:02X}, PPUSim ${sim:02X}"
        )


EXPERIMENTS: dict[str, Callable[[Pair], None]] = {
    "oam_start": oam_start,
    "c13": c13,
    "calibrate": calibrate,
    "fetches": fetches,
    "c12": c12,
    "c21_c22": c21_c22,
    "c21_rendering": c21_rendering,
}


def oam_vblank(machine: str, lines: tuple[int, ...]) -> None:
    """$2004 in vblank and on the pre-render line, rendering on and off, then OAM
    read back the next frame: the 2C07's forced OAM refresh (lines 265-310,
    PPU_OAM.wiki) against the PAL row, or the same probes on NTSC. Every access
    is four cycles after the last, as LDA/STA $2004 make them."""

    def read(pair: Pair) -> tuple[int, int]:
        pair.idle(3)
        return pair.access(4)

    for mask in (0x18, 0x00):
        pair = Pair(machine=MACHINES[machine])
        pair.idle(2 * pair.frame_cycles)  # the power-up wait
        pair.to_line(242)
        pair.write(1, 0x00)
        pair.write(3, 0x00)
        for i in range(256):
            pair.write(4, i)
        pair.write(1, mask)
        report = []
        for line in lines:
            pair.to_line(line, 10)
            pair.write(3, 0x40)
            reads = [read(pair) for _ in range(4)]
            pair.write(4, 0xA5)
            pair.write(4, 0x5A)
            reads.append(read(pair))
            report.append((line, reads))
        pair.to_line(245)
        pair.write(1, 0x00)
        oam = []
        for i in range(256):
            pair.write(3, i)
            oam.append(read(pair))
        print(f"{machine}, $2001 = ${mask:02X}:")
        for line, reads in report:
            mark = "" if all(o == s_ for o, s_ in reads) else "   <- differ"
            print(f"  line {line}: (ours, PPUSim) {reads}{mark}")
        bad = [(i, o, s_) for i, (o, s_) in enumerate(oam) if o != s_]
        filled = [i & 0xE3 if i & 3 == 2 else i for i in range(256)]  # as the fill left it
        written = [(i, s_) for i, (_, s_) in enumerate(oam) if s_ != filled[i]]
        print(f"  OAM after: {len(bad)} bytes differ {bad[:10]}; changed in PPUSim {written[:10]}")


def pal_oam(_pair: Pair) -> None:
    oam_vblank("pal", (250, 270, 300, 311))


def ntsc_oam(_pair: Pair) -> None:
    oam_vblank("nes", (250, 261))


EXPERIMENTS["ntsc_oam"] = ntsc_oam


def pal_w3(_pair: Pair) -> None:
    """The 2C07's delayed $2003 write and its OAM refresh, as a 6502 meets them:
    OAM filled with its own indices, then $2003 = $40 and five $2004 reads four
    cycles apart (LDA $2004), from start dots spread over the five CPU/dot
    phases, outside the refresh (line 250) and inside (270, 300)."""
    pair = Pair(machine=MACHINES["pal"])
    pair.idle(2 * pair.frame_cycles)
    pair.to_line(242)
    pair.write(3, 0x00)
    for i in range(256):
        pair.write(4, i)
    bad = 0
    for line in (250, 270, 300):
        for k in range(10):
            pair.to_line(line, 10 + 23 * k)
            pair.write(3, 0x40)
            reads = []
            for _ in range(5):
                pair.idle(3)
                reads.append(pair.access(4))
            if any(o != s_ for o, s_ in reads):
                bad += 1
                print(f"  line {line} dot {10 + 23 * k}: (ours, PPUSim) {reads}   <- differ")
    print(f"pal_w3: {bad} of 30 sequences differ")


EXPERIMENTS["pal_w3"] = pal_w3


def vbl_race(_pair: Pair, machine: str = "pal") -> None:
    """$2002 read at each CPU cycle around the VBL set (241, 1), then again four
    cycles later: the flag, its suppression, and the NMI, ours against PPUSim."""
    bad = 0
    for k in range(40):
        pair = Pair(machine=MACHINES[machine])
        pair.idle(2 * pair.frame_cycles + k)
        pair.write(0, 0x80)
        pair.to_line(240, 300)
        pair.idle(k % 16)
        start = (pair.ours.line, pair.ours.dot)
        first = pair.access(2)
        pair.idle(3)
        second = pair.access(2)
        same = first[0] == first[1] and second[0] == second[1]
        bad += not same
        print(
            f"  k {k:2d} from {start}: (ours, PPUSim) {first}, {second}{'' if same else '   <- differ'}"
        )
    print(f"vbl_race {machine}: {bad} of 40 differ")


EXPERIMENTS["vbl_race"] = vbl_race


def pal_fetches(_pair: Pair) -> None:
    """The PPU bus on PAL: each ALE address of three rendered lines, ours against
    PPUSim's RP2C07-0, as the spread of (PPUSim time - ours) in master ticks over
    the addresses both put out. One value: the same sub-dot timing throughout."""
    from collections import Counter

    pair = Pair(machine=MACHINES["pal"])
    setup_picture(pair)
    pair.write(3, 0)
    oam = [0xF8] * 256
    oam[0:12] = [39, 0x41, 0x00, 16, 39, 0x42, 0x01, 40, 39, 0x43, 0x02, 64]
    for value in oam:
        pair.write(4, value)
    pair.to_line(pair.ours.prerender_line, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    for line in (39, 43, 60):
        pair.to_line(line, 0)
        pair.trace(True)
        pair.to_line(line + 1, 0)
        pair.trace(False)
        sim = pair.sim_ales()
        spread: Counter[float] = Counter()
        unmatched = 0
        for t, address in pair.ales:
            near = [st for st, sa in sim if sa == address and abs(st - t) < 20]
            if near:
                spread[min(near, key=lambda st: abs(st - t)) - t] += 1
            else:
                unmatched += 1
        print(
            f"  line {line}: {len(pair.ales)} ALEs; PPUSim - ours: {dict(spread)}; unmatched {unmatched}"
        )


EXPERIMENTS["pal_fetches"] = pal_fetches
EXPERIMENTS["pal_oam"] = pal_oam


def finished_picture(system: System) -> list[int]:
    """The frame just begun, once its 240 rows are drawn.

    ``run_frames`` stops inside the instruction that starts a frame, by when
    the first pixels of row 0 already belong to it; so run on to line 240.
    """
    ppu = system.board.ppu
    while not HEIGHT <= ppu.line < ppu.prerender_line:
        system.step()
    return list(ppu.picture)


def compare_frame(rom: Path, frame: int, machine: Machine = NES_001) -> int:
    """Frame ``frame`` of ``rom`` on the board with PPUSim (CPU and all) against ours.

    Ours is tried at frames ``frame`` - 2 to + 2 (the two count frames from
    different points); the closest is reported. ``machine`` "pal" puts the
    RP2C07-0 against the PAL row.
    """
    system = system_with_ppusim(rom, skew_for(machine), machine)
    sim_ppu = system.board.ppu
    lib = sim_ppu.lib
    _trace_api(lib)
    system.run_frames(frame - 1)
    lib.ppusim_trace(sim_ppu.h, 1)
    system.run_frames(2)
    lib.ppusim_trace(sim_ppu.h, 0)
    n = lib.ppusim_trace_len(sim_ppu.h)
    # The frame from the first V wrap in the trace to the next.
    pixels: dict[tuple[int, int], int] = {}
    wraps, last_v = 0, None
    for e in (TraceEntry * n).from_address(lib.ppusim_trace_data(sim_ppu.h)):
        if last_v is not None and e.v < last_v:
            wraps += 1
        last_v = e.v
        if wraps == 2:
            break
        if wraps == 1 and e.v < 240 and SIM_PIXEL_H <= e.h < 256 + SIM_PIXEL_H:
            # The dot's last half-cycle: RAW settles during the dot.
            pixels[(e.v, e.h - SIM_PIXEL_H)] = e.video
    sim = [pixels.get((y, x), -1) for y in range(240) for x in range(256)]
    if machine.timing.border:
        # PPUSim's RAW is 0 where the picture is blanked ("no picture"); the
        # board draws PAL's border as BORDER there. Map only where RAW is 0.
        for i in range(256 * 240):
            if (i < 256 or i % 256 in (0, 1, 254, 255)) and sim[i] == 0:
                sim[i] = BORDER
    ours = System.from_rom(rom, machine)
    ours.run_frames(frame - 2)
    best: tuple[int, list[int], list[int]] | None = None
    for ours_frame in range(frame - 2, frame + 3):
        picture = finished_picture(ours)
        differ = [i for i in range(256 * 240) if picture[i] != sim[i]]
        if best is None or len(differ) < len(best[1]):
            best = (ours_frame, differ, picture)
        ours.run_frames(1)
    assert best is not None
    ours_frame, differ, picture = best
    where = ", ".join(
        f"({i // 256}, {i % 256}) ours {picture[i]:02X} PPUSim {sim[i]:02X}" for i in differ[:6]
    )
    print(
        f"{rom.name}: PPUSim frame {frame} vs ours {ours_frame}: "
        f"{len(differ)} of 61440 pixels differ" + (f", first at (y, x) {where}" if differ else "")
    )
    return 1 if differ else 0


def _trace_api(lib: ctypes.CDLL) -> None:
    lib.ppusim_trace.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ppusim_trace_len.argtypes = [ctypes.c_void_p]
    lib.ppusim_trace_len.restype = ctypes.c_uint64
    lib.ppusim_trace_data.argtypes = [ctypes.c_void_p]
    lib.ppusim_trace_data.restype = ctypes.c_void_p


def main() -> int:
    if not LIBRARY.exists():
        print("build PPUSim first: python scripts/build_ppusim.py", file=sys.stderr)
        return 1
    if sys.argv[1:2] == ["frame"]:
        machine = MACHINES[sys.argv[4]] if len(sys.argv) > 4 else NES_001
        return compare_frame(Path(sys.argv[2]), int(sys.argv[3]), machine)
    names = sys.argv[1:] or list(EXPERIMENTS)
    for name in names:
        print(f"== {name}")
        EXPERIMENTS[name](Pair())
    return 0


if __name__ == "__main__":
    sys.exit(main())
