#!/usr/bin/env python3
"""One register schedule on three PPUs: the board's, PPUSim and Visual 2C02.

Visual 2C02 (Quietust's transistor netlist, scripts/visual2c02/v2c02.js) is a
die model independent of PPUSim (Breaknes's schematics), so where PPUSim and
the board disagree it can say which matches the die. A scenario is a list of
CPU accesses in master half-cycles from a pre-render line's dot 0 (rendering
off there), each a CPU cycle whose /DBE window is its 9th to 23rd half-cycle
as Visual 2C02's cpucmd.js makes it, plus CHR contents and the lines whose
pixels to report. Each PPU prints the values its reads returned, the pixels
of those lines (palette index) and, per pre-render line, whether it skipped
dot 340.

    python scripts/visual2c02/compare.py SCENARIO [board] [ppusim] [v2c02]
    python scripts/visual2c02/compare.py diff A-signals.txt B-signals.txt

Visual 2C02 runs about 20 s a line here, so scenarios stay a few lines long.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HERE = Path(__file__).resolve().parent
DOT = 8
LINE = 341 * DOT
# Sprite-evaluation signals by PPUSim (Breaks) name, with the Visual 2C02 node
# the BreakingNESWiki maps each to (PPU/visual2c02.md); the bit order of the
# shim's ppusim_eval_probe.
SIGNALS = [
    ("OSTEP", 735),
    ("OBJ_READ", 328),
    ("/H2'", 638),
    ("OAMCTR2", 300),
    ("ORES", 743),
    ("I/OAM2", 357),
    ("/EVAL", 708),
    ("OMFG", 118),
    ("H0'", 614),
    ("PCLK", 106),
]
# Then the secondary OAM address (OAM_Temp 0-4, Visual 2C02 spr_ptr0-4) and OAM8 (spr_ptr5).
COUNTER = [4631, 4632, 4633, 4634, 4635, 37]
# The $2001 path to rendering (ppusim_regs_probe's bit order).
# Sprite lane 0 (ppusim_fifo_probe's bit order): #0/H, PCLK, the lane's X counter
# (Visual 2C02 spr0_p0-7) and its output bits (spr0_/l7, spr0_/h7: the shifters'
# inverted MSBs; PPUSim's lane /ZCOL0, /ZCOL1).
FIFO = [
    ("#0/H", 1681),
    ("PCLK", 106),
    ("X0", 10526),
    ("X1", 10415),
    ("X2", 10300),
    ("X3", 10200),
    ("X4", 10107),
    ("X5", 10043),
    ("X6", 9976),
    ("X7", 9900),
    ("/ZCOL0", 2037),
    ("/ZCOL1", 2038),
    # ZH_FF (spr0_active), the lane enable (+spr0_active_and_++in_visible_frame...), /VIS,
    # and the shift enable (SR_EN; Visual 2C02 names it with pclk1).
    ("ZH_FF", 9804),
    ("EN", 9771),
    ("/VIS", 283),
    ("SR_EN", 1838),
]
# Line 0's visible-area term (ppusim_vis_probe's order): VB (in_vblank|vpos_gt_239),
# /VIS, BLNK (not_rendering), PCLK, V counter bit 0.
VIS = [("VB", 1100), ("/VIS", 283), ("BLNK", 1030), ("PCLK", 106), ("V0", 210)]
# The OAM buffer path (ppusim_ob_probe's order): OB 0-7 (spr_d0-7), OAM8 (spr_ptr5),
# PCLK, I/OAM2, /WE (oam_write_disable).
OB = [
    ("OB0", 818),
    ("OB1", 856),
    ("OB2", 864),
    ("OB3", 870),
    ("OB4", 871),
    ("OB5", 691),
    ("OB6", 566),
    ("OB7", 359),
    ("OAM8", 37),
    ("PCLK", 106),
    ("I/OAM2", 357),
    ("/WE", 334),
]
REGS = [
    ("/DBE", 77),
    ("/W1", 481),
    ("CTRL1[3]", 6040),
    ("BGE", 1280),
    ("BLACK", 1133),
    ("BLNK", 1030),
    ("OBJ_READ", 328),
    ("PCLK", 106),
]


def at(line: int, dot: int) -> int:
    """Half-cycles from the pre-render line's dot 0 to (line, dot), no skipped dot."""
    return (341 + line * 341 + dot) * DOT if line != 261 else dot * DOT


class Schedule:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int, int]] = []
        self.chr: dict[int, int] = {}
        self.lines: list[int] = []
        self.probe: list[int] = []  # lines whose OAM address and data to record per dot
        # (line, from dot, to dot), or a list of them: SIGNALS (or REGS, FIFO) per half-cycle
        self.signals: tuple[int, int, int] | list[tuple[int, int, int]] | None = None
        self.signal_set = "eval"  # or "regs", "fifo": REGS, FIFO instead
        # PPUSim and the board start this many frames later, to match Visual 2C02's frame parity.
        self.ppusim_frames = 0
        self.end = 0
        self.t = 16 * DOT

    def _at(self, when: int | None) -> None:
        if when is not None:
            if when < self.t:
                raise ValueError(f"access at {when} overlaps the one before (free from {self.t})")
            self.t = when

    def write(self, register: int, value: int, when: int | None = None) -> None:
        self._at(when)
        self.events.append((self.t, 0, register, value))
        self.t += 24 if when is not None else 48  # a run of accesses: every other cycle

    def read(self, register: int, when: int | None = None) -> None:
        self._at(when)
        self.events.append((self.t, 1, register, 0))
        self.t += 24 if when is not None else 48  # a run of accesses: every other cycle

    def oam(self, data: bytes) -> None:
        self.write(3, 0)
        for value in data:
            self.write(4, value)

    def windows(self) -> list[tuple[int, int, int]]:
        if self.signals is None:
            return []
        return self.signals if isinstance(self.signals, list) else [self.signals]

    def json(self) -> str:
        return json.dumps(
            {
                "events": self.events,
                "chr": sorted(self.chr.items()),
                "lines": self.lines,
                "probe": self.probe,
                "signals": self.signals
                and {
                    "windows": self.windows(),
                    "nodes": [n for _, n in SIGNALS] + COUNTER
                    if self.signal_set == "eval"
                    else [
                        n
                        for _, n in {"regs": REGS, "fifo": FIFO, "vis": VIS, "ob": OB}[
                            self.signal_set
                        ]
                    ],
                },
                "end": self.end,
            }
        )


# -- scenarios ---------------------------------------------------------------


def scanline0() -> Schedule:
    """scanline0.py's schedule (AccuracyCoin "Sprites On Scanline 0" 3): sprite
    0 (Y 0, one pixel at column 0 of row 5, X $80) loaded by the pre-render
    fetch, two frames; sprite lane 0 traced over the end of the pre-render
    line and the start of line 0. From Visual 2C02's saved even pre-render
    state the second frame's pre-render line skips its last dot."""
    from scanline0 import TILE, schedule

    s = Schedule()
    s.events = schedule(2)
    s.chr = {TILE * 16 + 5: int(os.environ.get("S0_ROW", "0x80"), 0)}  # $81: columns 0 and 7
    s.lines = [0]
    s.signals = [(261, 320, 340), (0, 0, 140)]
    s.signal_set = "fifo"
    s.ppusim_frames = 1  # so that its second frame skips too
    s.end = 2 * 262 * LINE + 2 * LINE
    return s


def stress2004(key: int) -> Schedule:
    """AccuracyCoin "$2004 Stress Test" (key 1: error 2, key 2: error 3): OAM as
    the test sets it, rendering on from line 5 dot 320, $2004 read every CPU
    cycle across line 128 from dot STRESS_OFFSET (0-2; three runs cover every
    dot). The test's answer keys are hardware results, one byte per dot."""
    s = Schedule()
    if key == 1:
        oam = bytes(range(255, -1, -1))
    else:
        table = [
            0x80,
            0x00,
            0x00,
            0xFF,
            0x7F,
            0x01,
            0x20,
            0xEE,
            0x7E,
            0x02,
            0x40,
            0xDD,
            0x7D,
            0x03,
            0x60,
            0xCC,
            0x7C,
            0x04,
            0x80,
            0xBB,
            0x7B,
            0x05,
            0xA0,
            0xAA,
            0x7A,
            0x06,
            0xC0,
            0x99,
            0x79,
            0x07,
            0xE0,
            0x88,
        ]  # Test_2004_Stress_OAM
        oam = bytes(
            table + list(range(0xE0))
        )  # TEST_2004_Stress_Prep3 runs X from 32 until it wraps
    s.write(1, 0x00)
    s.oam(oam)
    s.write(1, 0x18, at(5, 320))
    if os.environ.get("STRESS_PROBE"):  # no reads: the OAM address per dot of line 128
        s.probe = [128]
    else:
        for dot in range(int(os.environ.get("STRESS_OFFSET", "0")), 341, 3):
            s.read(4, at(128, dot))
    s.end = at(129, 8)
    return s


def sprite_x() -> Schedule:
    """Sprites at X 0, 5 and 40 on an ordinary line (8; Y 7): each a pixel in
    columns 0 and 7 (tile 1 rows $81). Where does each model draw them, and
    when does /VIS come? (scanline0 found PPUSim's /VIS a dot after Visual
    2C02's.)"""
    s = Schedule()
    s.chr = {16 + row: 0x81 for row in range(8)}
    s.write(1, 0x00)
    s.oam(bytes([7, 1, 0, 0, 7, 1, 0, 5, 7, 1, 0, 40] + [0xF8] * (256 - 12)))
    for address, value in ((0x3F11, 0x16), (0x3F00, 0x0F)):
        s.write(6, address >> 8)
        s.write(6, address & 0xFF)
        s.write(7, value)
    s.write(6, 0x00)
    s.write(6, 0x00)
    s.write(1, 0x1E, at(6, 10))
    s.lines = [8]
    s.signals = (8, 0, 12)
    s.signal_set = "fifo"
    s.end = at(9, 8)
    return s


def line0_vis() -> Schedule:
    """Rendering on from the pre-render line's dot 20; VB, /VIS and BLNK traced
    over the end of the pre-render line and the start of line 0 (scanline0
    found PPUSim's /VIS on line 0 a dot after Visual 2C02's, and not on line 8)."""
    s = Schedule()
    s.write(1, 0x18, at(261, 20))
    s.signals = [(261, 334, 340), (0, 0, 4)]
    s.signal_set = "vis"
    s.end = at(0, 6)
    return s


def copy2004() -> Schedule:
    """stress2004(2)'s eight sprites moved to line 8 (Y 8 down to 1), the copy
    phase of evaluation (dots 65-128) read with $2004 every CPU cycle from dot
    STRESS_OFFSET + 60, and the OAM address and data probed each dot: the
    hardware key reads the byte being copied on every dot of it."""
    s = Schedule()
    table = []
    for n in range(8):
        table += [8 - n, n, n << 5, 0xFF - 0x11 * n]
    s.write(1, 0x00)
    s.oam(bytes(table + list(range(0xE0))))
    s.write(1, 0x18, at(5, 30))
    if os.environ.get("COPY_TRACE"):  # no reads: the OAM buffer path per half-cycle
        s.signals = (8, 64, 72)
        s.signal_set = "ob"
    else:
        for dot in range(60 + int(os.environ.get("STRESS_OFFSET", "0")), 84, 3):
            s.read(4, at(8, dot))
    s.probe = [8]
    s.end = at(8, 100)
    return s


def enable_latency() -> Schedule:
    """Rendering off, then $2001 = $1E written mid-line (line 7, dot 286, as
    misaligned_oam2's re-enable): when do the register bit, BGE, BLNK and
    OBJ_READ follow the write?"""
    s = Schedule()
    s.write(1, 0x00)
    # ENABLE_SHIFT half-cycles later moves where /DBE rises against PCLK.
    s.write(1, 0x1E, at(7, 286) + int(os.environ.get("ENABLE_SHIFT", "0")))
    s.signals = (7, 280, 300)
    s.signal_set = "regs"
    s.end = at(7, 310)
    return s


def oam2_index0() -> Schedule:
    """AccuracyCoin "Misaligned OAM2 Address" 3: OAM all $FF but sprite 63's Y
    ($5A); with nothing in range, evaluation leaves $5A in OAM2[0] (C35), and
    $2004 read on dots 321-340 should return OAM2[0]. Line 7 rendered, $2004
    read every CPU cycle across its dots 250-340."""
    s = Schedule()
    s.write(1, 0x00)
    s.oam(bytes([0xFF] * 0xFC + [0x5A, 0xFF, 0xFF, 0xFF]))
    s.write(1, 0x1E, at(6, 10))
    for dot in range(250, 341, 3):
        s.read(4, at(7, dot))
    s.probe = [7]
    s.end = at(8, 0)
    return s


def oam2_trace() -> Schedule:
    """oam2_index0 with one $2004 read (dot 324, as AccuracyCoin's), so the
    per-dot OAM probes of line 7 are not interrupted by accesses."""
    s = Schedule()
    s.write(1, 0x00)
    s.oam(bytes([0xFF] * 0xFC + [0x5A, 0xFF, 0xFF, 0xFF]))
    s.write(1, 0x1E, at(6, 10))
    s.read(4, at(7, 324))
    s.probe = [7]
    s.signals = (7, 0, 340)
    s.end = at(8, 0)
    return s


def misaligned_oam2() -> Schedule:
    """AccuracyCoin "Misaligned OAM2 Address" 4: OAM2 filled by eight in-range
    sprites (the test's table), rendering off on dot 268 and on again on dot
    286 of that line, then $2004 read across dots 300-340 (the test expects
    $06 after its 12-cycle slide: OAM2 address $18)."""
    s = Schedule()
    table = []
    for n in range(8):
        table += [n, (n << 5) | 1, (n << 5) | 2, (n << 5) | 3]
    s.write(1, 0x00)
    s.oam(bytes(table + [0xFF] * (256 - len(table))))
    s.write(1, 0x1E, at(5, 30))  # line 7 evaluates all eight (Y 0-7), as the test's 877-cycle wait
    s.write(1, 0x00, at(7, 268))
    # At dot 286 the write's /DBE rises on a PCLK edge (see enable_latency); ENABLE_SHIFT moves it.
    s.write(1, 0x1E, at(7, 286) + int(os.environ.get("ENABLE_SHIFT", "0")))
    for dot in range(300, 341, 3):
        s.read(4, at(7, dot))
    s.signals = (7, 0, 340)
    s.end = at(8, 0)
    return s


def overflow9() -> Schedule:
    """Nine sprites in range of line 7 (Y 0-8 -> all but the last cover it):
    evaluation fills OAM2, then the overflow scan. No reads; the line's
    half-cycle trace is the comparison."""
    s = Schedule()
    table = []
    for n in range(9):
        table += [n % 8, n, 0, n * 8]
    s.write(1, 0x00)
    s.oam(bytes(table + [0xFF] * (256 - len(table))))
    s.write(1, 0x1E, at(5, 30))
    s.signals = (7, 0, 340)
    s.end = at(8, 0)
    return s


SCENARIOS = {
    "copy2004": copy2004,
    "line0_vis": line0_vis,
    "sprite_x": sprite_x,
    "stress2004_1": lambda: stress2004(1),
    "stress2004_2": lambda: stress2004(2),
    "scanline0": scanline0,
    "enable_latency": enable_latency,
    "oam2_index0": oam2_index0,
    "oam2_trace": oam2_trace,
    "misaligned_oam2": misaligned_oam2,
    "overflow9": overflow9,
}


# -- the three PPUs ----------------------------------------------------------


def run_board(s: Schedule) -> dict:
    from famicom_python.board import PPU_ACCESS_TICKS
    from famicom_python.system import System

    chr_data = bytearray(0x2000)
    for address, value in s.chr.items():
        chr_data[address] = value
    image = b"NES\x1a\x01\x01\x01\x00" + bytes(8) + bytes(0x4000) + bytes(chr_data)
    ppu = System.from_rom(image).board.ppu
    for _ in range(2 + s.ppusim_frames):  # past the power-on reset flag (and the parity shift)
        ppu.run_to(ppu.time + 4)
        while not (ppu.line == 261 and ppu.dot == 0):
            ppu.run_to(ppu.time + 1)
    origin = ppu.time
    reads: list[int] = []
    lines: dict[str, list[int]] = {}
    skips: list[bool] = []
    previous = (ppu.line, ppu.dot)

    def advance(to: int) -> None:
        nonlocal previous
        while ppu.time < to:
            ppu.run_to(min(ppu.time + 4, to))
            position = (ppu.line, ppu.dot)
            if position != previous:
                if previous[0] == 261 and position[0] == 0:
                    skips.append(previous[1] < 340)
                if position[0] == previous[0] + 1 and previous[0] in s.lines:
                    row = previous[0] * 256
                    key = str(previous[0])
                    while key in lines:  # a later frame's same line
                        key += "+"
                    lines[key] = [p & 0x3F for p in ppu.picture[row : row + 256]]
                previous = position

    for when, rnw, register, value in s.events:
        advance(origin + when // 2 + PPU_ACCESS_TICKS)
        if rnw:
            result = ppu.read_register(register)
            advance(origin + (when + 24) // 2)
            reads.append(ppu.end_read(register, result))
        else:
            ppu.write_register(register, value)
    advance(origin + s.end // 2)
    return {"reads": reads, "lines": lines, "skips": skips}


def run_ppusim(s: Schedule) -> dict:
    from ppusim_board import _library

    lib = _library()
    lib.ppusim_screen.argtypes = [ctypes.c_void_p]
    lib.ppusim_screen.restype = ctypes.c_void_p
    chr_data = bytearray(0x2000)
    for address, value in s.chr.items():
        chr_data[address] = value
    h = lib.ppusim_new(bytes(chr_data), len(chr_data), 0, 1)
    lib.ppusim_reset(h, 64)
    for _ in range(2 + s.ppusim_frames):  # past the reset flag, as the board
        lib.ppusim_run(h, 8)
        while not (lib.ppusim_v(h) == 261 and lib.ppusim_h(h) == 0):
            lib.ppusim_run(h, 1)
    screen = (ctypes.c_uint16 * (262 * 341)).from_address(lib.ppusim_screen(h))
    lib.ppusim_oam_probe.argtypes = [ctypes.c_void_p]
    lib.ppusim_eval_probe.argtypes = [ctypes.c_void_p]
    lib.ppusim_regs_probe.argtypes = [ctypes.c_void_p]
    lib.ppusim_fifo_probe.argtypes = [ctypes.c_void_p]
    lib.ppusim_vis_probe.argtypes = [ctypes.c_void_p]
    lib.ppusim_ob_probe.argtypes = [ctypes.c_void_p]
    probe_signals = {
        "eval": lib.ppusim_eval_probe,
        "regs": lib.ppusim_regs_probe,
        "fifo": lib.ppusim_fifo_probe,
        "vis": lib.ppusim_vis_probe,
        "ob": lib.ppusim_ob_probe,
    }[s.signal_set]
    windows = s.windows()
    signals: list[list[int]] = []
    reads: list[int] = []
    lines: dict[str, list[int]] = {}
    skips: list[bool] = []
    probes: dict[str, list[int]] = {}
    previous = (261, 0)
    now = 0

    def advance(to: int) -> None:
        nonlocal now, previous
        while now < to:
            lib.ppusim_run(h, 1)
            now += 1
            position = (lib.ppusim_v(h), lib.ppusim_h(h))
            if any(w[0] == position[0] and w[1] <= position[1] <= w[2] for w in windows):
                signals.append([position[1], probe_signals(h)])
            if position[0] in s.probe:
                # Each dot's last half-cycle: OAM address, I_OAM2, the OAM buffer.
                bits = lib.ppusim_oam_probe(h)
                probes[f"{position[0]}:{position[1]}"] = [bits & 0x1FF, bits >> 10, bits >> 9 & 1]
            if position != previous:
                if previous[0] == 261 and position[0] == 0:
                    skips.append(previous[1] == 339)
                if position[0] == previous[0] + 1 and previous[0] in s.lines:
                    base = previous[0] * 341 + 4
                    key = str(previous[0])
                    while key in lines:  # a later frame's same line
                        key += "+"
                    lines[key] = [screen[base + x] & 0x3F for x in range(256)]
                previous = position

    for when, rnw, register, value in s.events:
        advance(when)
        reads_value = lib.ppusim_access(h, rnw, register, value, value, 0, 8, 15)
        now += 23
        if rnw:
            reads.append(reads_value)
    advance(s.end)
    return {"reads": reads, "lines": lines, "skips": skips, "probes": probes, "signals": signals}


def run_v2c02(s: Schedule) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(s.json())
    out = subprocess.run(
        ["node", str(HERE / "run.js"), f.name], capture_output=True, text=True, check=True
    )
    Path(f.name).unlink()
    return json.loads(out.stdout.strip().splitlines()[-1])


def diff(a: Path, b: Path) -> int:
    """Half-cycles where two saved signal traces differ in the counter, OSTEP or
    OAMCTR2, matched by (dot, half-cycle within the dot): PPUSim records nothing
    during its accesses' half-cycles."""

    def load(path: Path) -> dict[tuple[int, int], str]:
        rows: dict[tuple[int, int], str] = {}
        seen: dict[int, int] = {}
        for row in path.read_text().splitlines():
            h = int(row.split()[0])
            seen[h] = seen.get(h, -1) + 1
            rows[(h, seen[h])] = row
        return rows

    def keep(row: str) -> tuple[str, ...]:
        parts = row.split()
        return parts[1], parts[4], row.split("OAM2 ")[1]

    x, y = load(a), load(b)
    shown = 0
    for key in sorted(set(x) & set(y)):
        if keep(x[key]) != keep(y[key]):
            if shown < 12:
                print(f"dot {key[0]} half {key[1]}:")
                print(f"  {a.name:32} {x[key]}\n  {b.name:32} {y[key]}")
            shown += 1
    print(f"{shown} of {len(set(x) & set(y))} common half-cycles differ")
    return 1 if shown else 0


def main() -> int:
    name = sys.argv[1]
    if name == "diff":
        return diff(Path(sys.argv[2]), Path(sys.argv[3]))
    which = sys.argv[2:] or ["board", "ppusim", "v2c02"]
    s = SCENARIOS[name]()
    for ppu in which:
        result = {"board": run_board, "ppusim": run_ppusim, "v2c02": run_v2c02}[ppu](s)
        reads = " ".join(f"{v:02X}" for v in result["reads"])
        print(f"{name} {ppu:7}: reads {reads}; skips {result['skips']}", flush=True)
        order = sorted(result["lines"], key=lambda key: (int(key.rstrip("+")), key))
        for line, row in ((key, result["lines"][key]) for key in order):
            backdrop = max(set(row), key=row.count)
            lit = [x for x, c in enumerate(row) if c != backdrop]
            print(f"  line {line}: x not the line's commonest colour: {lit[:24]}", flush=True)
        if result.get("signals"):
            out = Path(f"{name}-{ppu}-signals.txt")
            names = [
                n
                for n, _ in {"eval": SIGNALS, "regs": REGS, "fifo": FIFO, "vis": VIS, "ob": OB}[
                    s.signal_set
                ]
            ]

            def row(h: int, bits: int, names: list[str] = names) -> str:
                text = f"{h:3} " + " ".join(
                    n if bits >> i & 1 else "." * len(n) for i, n in enumerate(names)
                )
                if s.signal_set == "eval":
                    text += f" OAM2 {bits >> len(SIGNALS) & 0x1F:02X}"
                    text += " OAM8" if bits >> (len(SIGNALS) + 5) & 1 else ""
                return text

            rows = [row(h, bits) for h, bits in result["signals"]]
            Path(f"{name}-{ppu}-signals.json").write_text(json.dumps(result["signals"]))
            out.write_text("\n".join(rows) + "\n")
            print(f"  signals: {out}", flush=True)
        if result.get("probes"):
            out = Path(f"{name}-{ppu}-probes.json")
            out.write_text(json.dumps(result["probes"]))
            print(f"  probes: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
