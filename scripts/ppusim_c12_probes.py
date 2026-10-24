"""The C12 probes: mid-line rendering toggles on the board's PPU and PPUSim.

Each mode drives a ``ppusim_compare.Pair`` through a scenario and prints
where the two differ, or PPUSim's internal signals (the shim's FSM, sprite
FIFO and BG colour records) around it. They settled the C12 model in
docs/undocumented-behavior.md; docs/validation.md ("C12") lists the sweeps
and their results.

    python scripts/ppusim_c12_probes.py window 0A 1E
    python scripts/ppusim_c12_probes.py lanes
    python scripts/ppusim_c12_probes.py flagset 110 126

Arguments are per mode (``sys.argv[2:]``); see each ``mode_*``. Exploratory
code, kept so the record can be rerun. Needs the PPUSim build
(scripts/build_ppusim.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ppusim_compare import Pair, scroll_zero, setup_picture

from famicom_python.ppu import REVERSE

OCTAL = None
NAMES = ["BLNK", "ZHPOS", "nVIS", "OBJRD", "PCLK", "nFO", "/S0H", "/EVAL"]


def show(pair, lines, only_changes=True, hs=None):
    prev = None
    for e in pair.sim_trace():
        if e.v not in lines:
            continue
        if hs and not (hs[0] <= e.h <= hs[1]):
            continue
        i = list(e.inner)
        key = (i[0] & ~0x10, i[1], i[2], i[3], i[4])
        if only_changes and key == prev:
            continue
        prev = key
        flags = " ".join(n for b, n in enumerate(NAMES) if i[0] >> b & 1 and n != "PCLK")
        print(
            f"v{e.v:3d} h{e.h:3d} half{e.half % 8} pclk{i[0] >> 4 & 1} cnt{i[1]:3d} "
            f"act{i[2]:08b} en{i[3]:08b} x4={i[4]:06b} vid{e.video:03X} [{flags}]"
        )


def scenario(name, writes, oam0, trace_lines):
    pair = Pair()
    setup_picture(pair)
    pair.write(3, 0)
    oam = [0xF8, 0, 0, 0xFF] * 64
    oam[0:4] = oam0
    for value in oam:
        pair.write(4, value)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    pair.to_line(2, 0)
    for line, dot, value in writes:
        pair.to_line(line, dot)
        if (line, dot) == writes[0][:2]:
            pair.trace(True)
        pair.write(1, value)
    pair.to_line(trace_lines[-1] + 1, 0)
    pair.trace(False)
    print(f"== {name}")
    return pair


if __name__ == "__main__":
    which = sys.argv[1]
    if which == "base":
        # sprite 0 at Y 4, X $30: drawn on lines 5-12; trace lines 4-5
        pair = Pair()
        setup_picture(pair)
        pair.write(3, 0)
        oam = [0xF8, 0, 0, 0xFF] * 64
        oam[0:4] = [4, 0x41, 0, 0x30]
        for value in oam:
            pair.write(4, value)
        pair.to_line(261, 100)
        scroll_zero(pair)
        pair.write(1, 0x1E)
        pair.to_line(4, 200)
        pair.trace(True)
        pair.to_line(6, 0)
        pair.trace(False)
        show(pair, {4, 5})


def show_flags(pair, lines):
    prev = None
    for e in pair.sim_trace():
        if e.v not in lines:
            continue
        i = list(e.inner)
        key = (i[0] & ~0x10, i[2], i[3], i[4] & 0b10011)
        if key == prev:
            continue
        prev = key
        flags = " ".join(n for b, n in enumerate(NAMES) if i[0] >> b & 1 and n != "PCLK")
        print(
            f"v{e.v:3d} h{e.h:3d} half{e.half % 8} cnt{i[1]:3d} act{i[2]:08b} en{i[3]:08b} "
            f"black{i[4] & 1} sccnt{i[4] >> 1 & 1} load{i[4] >> 4 & 1} [{flags}]"
        )


def mode_offon() -> None:
    # rendering off on line 4 dot 100, on again on line 5 dot 100
    pair = Pair()
    setup_picture(pair)
    pair.write(3, 0)
    oam = [0xF8, 0, 0, 0xFF] * 64
    oam[0:4] = [4, 0x41, 0, 0x30]
    for value in oam:
        pair.write(4, value)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    off, on = (int(a) for a in sys.argv[2:4])
    pair.to_line(4, 0)
    pair.trace(True)
    pair.to_line(4 + off // 341, off % 341)
    pair.write(1, 0x00)
    pair.to_line(4 + on // 341, on % 341)
    pair.write(1, 0x1E)
    pair.to_line(4 + on // 341 + 2, 0)
    pair.trace(False)
    show_flags(pair, set(range(4, 4 + on // 341 + 2)))


def mode_latency() -> None:
    # Where BLACK changes after a $2001 write, against the access's dot in both PPUs.
    from ppusim_board import ACCESS_TICKS

    pair = Pair()
    setup_picture(pair)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    for line, dot, value in [
        (20, 100, 0),
        (21, 100, 0x1E),
        (22, 101, 0),
        (23, 101, 0x1E),
        (24, 102, 0),
        (25, 102, 0x1E),
    ]:
        pair.to_line(line, dot)
        pair.trace(True)
        pair.idle(3)
        access = pair.t + ACCESS_TICKS  # the next cycle's access point
        pair.access(1, value)
        ours_dot = pair.ours.dot - 1
        sim_h = None
        prev = None
        change = None
        for e in pair.sim_trace():
            t = pair.half_to_time(e.half)
            if sim_h is None and t >= access:
                sim_h = (e.h, e.half % 8)
        pair.to_line(line, dot + 40)
        for e in pair.sim_trace():
            black = e.inner[4] & 1
            if prev is not None and black != prev and change is None:
                change = (e.h, e.half % 8)
            prev = black
        pair.trace(False)
        print(
            f"write ${value:02X}: ours access dot {ours_dot}; PPUSim at access h{sim_h}; BLACK "
            f"changes at h{change}"
        )


def mode_bgon() -> None:
    # Per dot around a mid-line $2001 write: ALE addresses of both, PPUSim's BLACK/nFO, pixels.
    from ppusim_compare import SIM_PIXEL_H, rendered

    before, after = int(sys.argv[2], 16), int(sys.argv[3], 16)
    shift = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    pair = Pair()
    rendered(pair, before if before & 0x18 else 0x0A)
    line = 20
    pair.to_line(line - 1, 300)
    pair.write(1, before)
    pair.to_line(line, 0)
    pair.line_start = pair.t
    pair.trace(True)
    pair.idle(40 + shift)
    pair.idle(3)
    pair.access(1, after)
    access_dot = pair.ours.dot - 1
    pair.to_line(line + 1, 0)
    pair.trace(False)
    start = pair.line_start
    ours_ale = {}
    for t, a in pair.ales:
        ours_ale[(t - start) // 4] = a
    sim_ale = {}
    for t, a in pair.sim_ales():
        sim_ale[int(t + 4 - start) // 4] = a
    sig = {}
    for e in pair.sim_trace():
        if e.v == line and e.half % 8 == 7:
            sig[e.h] = e.inner
    pix = pair.sim_pixels()
    ours_row = pair.ours.picture[line * 256 : line * 256 + 256]
    print(f"access at our dot {access_dot}")
    for d in range(access_dot - 4, access_dot + 30):
        i = sig.get(d + 1, [0] * 5)
        x = d - 2
        print(
            f"dot {d:3d} (h{d + 1}): ours ALE {ours_ale.get(d, 0):04X} sim ALE "
            f"{sim_ale.get(d, 0):04X} "
            "| "
            f"BLACK{i[4] & 1} nFO{i[0] >> 5 & 1} nVIS{i[0] >> 2 & 1} | pixel x{x}: ours "
            f"{ours_row[x]:02X} "
            f"sim {pix.get((line, x + SIM_PIXEL_H), -1):02X}"
        )


def toggle_case(before, after, shift, line=20, pair=None):
    """A mid-line $2001 write; returns (pair, access dot, ALE diffs, pixel diffs)."""
    from ppusim_compare import SIM_PIXEL_H, rendered

    if pair is None:
        pair = Pair()
        rendered(pair, 0x0A)
    pair.to_line(line - 1, 300)
    pair.write(1, before)
    pair.to_line(line, 0)
    start = pair.t
    pair.trace(True)
    pair.idle(40 + shift)
    pair.idle(3)
    pair.access(1, after)
    access_dot = pair.ours.dot - 1
    pair.to_line(line + 1, 0)
    pair.trace(False)
    ours_ale = {(t - start) // 4: a for t, a in pair.ales}
    sim_ale = {int(t + 4 - start) // 4: a for t, a in pair.sim_ales()}
    ale = [
        (d, ours_ale.get(d), sim_ale.get(d))
        for d in range(1, 341)
        if ours_ale.get(d) != sim_ale.get(d)
    ]
    pix = pair.sim_pixels()
    row = pair.ours.picture[line * 256 : line * 256 + 256]
    pixels = [
        (x, row[x], pix.get((line, x + SIM_PIXEL_H), -1))
        for x in range(256)
        if row[x] != pix.get((line, x + SIM_PIXEL_H), -1)
    ]
    return pair, access_dot, ale, pixels


def mode_phases() -> None:
    before, after = int(sys.argv[2], 16), int(sys.argv[3], 16)
    pair = None
    line = 20
    for shift in range(8):
        pair, dot, ale, pixels = toggle_case(before, after, shift, line, pair)
        line += 2
        a = " ".join(f"{d}:{o and f'{o:04X}'}/{s and f'{s:04X}'}" for d, o, s in ale[:6])
        p = " ".join(f"{x}:{o:02X}/{s:02X}" for x, o, s in pixels[:10])
        print(
            f"access dot {dot} (phase {(dot - 1) & 7}): ALE ours/sim [{a}] pixels ours/sim "
            f"[{p}]{' ...' if len(pixels) > 10 else ''}"
        )


def toggle_case2(before, after, shift, line, pair, register=1):
    """As toggle_case, but v reset to $2000 before the line, and dots from each
    PPU's own counter."""
    from ppusim_compare import SIM_PIXEL_H, rendered

    if pair is None:
        pair = Pair()
        rendered(pair, 0x0A)
        mark = []
        pair.cartridge.ppu_address = lambda a, t: mark.append((pair.ours.line, pair.ours.dot, a))
        pair.mark = mark
    pair.to_line(line - 1, 200)
    pair.write(1, 0x00)
    if OCTAL is not None:
        pair.write(6, 0x20)
        pair.write(6, OCTAL)
        pair.idle(3)
        pair.access(7)  # ALE and /RD at $20xx: the octal latch takes xx
    pair.write(6, 0x20)
    pair.write(6, 0x00)
    pair.write(1, before)
    pair.to_line(line, 0)
    pair.mark.clear()
    pair.trace(True)
    pair.idle(40 + shift)
    pair.idle(3)
    pair.access(register, after)
    access_dot = pair.ours.dot - 1
    pair.to_line(line + 1, 0)
    pair.trace(False)
    ours_ale = {d: a for ln, d, a in pair.mark if ln == line}
    sim_ale = {}
    high = False
    for e in pair.sim_trace():
        ale = bool(e.pins & 1)
        if ale and not high and e.v == line:
            sim_ale[e.h] = e.address
        high = ale
    ale = [
        (d, ours_ale.get(d), sim_ale.get(d))
        for d in range(1, 340)
        if ours_ale.get(d) != sim_ale.get(d)
    ]
    pix = pair.sim_pixels()
    row = pair.ours.picture[line * 256 : line * 256 + 256]
    pixels = [
        (x, row[x], pix.get((line, x + SIM_PIXEL_H), -1))
        for x in range(256)
        if row[x] != pix.get((line, x + SIM_PIXEL_H), -1)
    ]
    return pair, access_dot, ale, pixels


def mode_phases2() -> None:
    before, after = int(sys.argv[2], 16), int(sys.argv[3], 16)
    pair = None
    line = 20
    for shift in range(8):
        pair, dot, ale, pixels = toggle_case2(before, after, shift, line, pair)
        line += 3
        a = " ".join(f"{d}:{o and f'{o:04X}'}/{s and f'{s:04X}'}" for d, o, s in ale[:8])
        p = " ".join(f"{x}:{o:02X}/{s:02X}" for x, o, s in pixels[:10])
        print(
            f"access dot {dot} (phase {(dot - 1) & 7}): ALE ours/sim "
            f"[{a}]{' ...' if len(ale) > 8 else ''} "
            f"pixels ours/sim [{p}]{' ...' if len(pixels) > 10 else ''}"
        )


def mode_seq() -> None:
    before, after, shift = int(sys.argv[2], 16), int(sys.argv[3], 16), int(sys.argv[4])
    pair, dot, _ale, _pixels = toggle_case2(before, after, shift, 20, None)
    ours_ale = {d: a for ln, d, a in pair.mark if ln == 20}
    sim_ale = {}
    sig = {}
    high = False
    for e in pair.sim_trace():
        a = bool(e.pins & 1)
        if a and not high and e.v == 20:
            sim_ale[e.h] = e.address
        high = a
        if e.v == 20 and e.half % 8 == 7:
            sig[e.h] = e.inner
    from ppusim_compare import SIM_PIXEL_H

    pix = pair.sim_pixels()
    row = pair.ours.picture[20 * 256 : 20 * 256 + 256]
    print(f"access dot {dot}")
    for d in range(dot - 3, dot + 28):
        i = sig.get(d + 1, [0] * 5)
        o, s = ours_ale.get(d), sim_ale.get(d)
        x = d - 2
        print(
            f"dot {d:3d} ph{(d - 1) & 7}: ours {(o and f'{o:04X}') or '    '} sim "
            f"{(s and f'{s:04X}') or '    '}{'  <>' if o != s else '    '} "
            f"| h{d + 1} BLACK{i[4] & 1} nFO{i[0] >> 5 & 1} | x{x}: ours {row[x]:02X} sim "
            f"{pix.get((20, x + SIM_PIXEL_H), -1):02X}"
        )


def mode_seqall() -> None:
    before, after = int(sys.argv[2], 16), int(sys.argv[3], 16)
    pair = None
    line = 20
    for shift in range(8):
        pair, dot, _ale, pixels = toggle_case2(before, after, shift, line, pair)
        ours_ale = {d: a for ln, d, a in pair.mark if ln == line}
        sim_ale = {}
        high = False
        for e in pair.sim_trace():
            a = bool(e.pins & 1)
            if a and not high and e.v == line:
                sim_ale[e.h] = e.address
            high = a
        print(f"access {dot} (BLACK changes on dot {dot + 1}, phase {dot & 7})")
        print(
            "   ours: "
            + " ".join(f"{d}:{ours_ale[d]:04X}" for d in range(dot - 8, dot + 26) if d in ours_ale)
        )
        print(
            "   sim:  "
            + " ".join(f"{d}:{sim_ale[d]:04X}" for d in range(dot - 8, dot + 26) if d in sim_ale)
        )
        p = " ".join(f"{x}:{o:02X}/{s:02X}" for x, o, s in pixels[:12])
        print(f"   pixels ours/sim [{p}]{' ...' if len(pixels) > 12 else ''}")
        line += 3


def mode_rd() -> None:
    global OCTAL
    if len(sys.argv) > 5:
        OCTAL = int(sys.argv[5], 16)
    before, after = int(sys.argv[2], 16), int(sys.argv[3], 16)
    pair = None
    line = 20
    for shift in [int(s) for s in sys.argv[4].split(",")]:
        pair, dot, _ale, _pixels = toggle_case2(before, after, shift, line, pair)
        sim_ev = []
        prev = 0
        for e in pair.sim_trace():
            if e.v != line:
                prev = e.pins
                continue
            if e.pins & 1 and not prev & 1:
                sim_ev.append((e.h, "A", e.address))
            if e.pins & 2 and not prev & 2:
                sim_ev.append((e.h, "R", e.address))
            prev = e.pins
        ours_ev = [(d, "A", a) for ln, d, a in pair.mark if ln == line]
        print(f"access {dot}, D = {dot + 1}")
        print(
            "   sim:  "
            + " ".join(f"{h}{k}{a:04X}" for h, k, a in sim_ev if dot - 2 <= h <= dot + 12)
        )
        print(
            "   ours: "
            + " ".join(f"{h}{k}{a:04X}" for h, k, a in ours_ev if dot - 2 <= h <= dot + 12)
        )
        line += 3


def mode_prerender() -> None:
    pair = Pair()
    setup_picture(pair)
    pair.write(3, 0)
    oam = [0xF8, 0, 0, 0xFF] * 64
    oam[0:4] = [4, 0x41, 0, 0x30]
    for value in oam:
        pair.write(4, value)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    pair.to_line(259, 300)
    pair.trace(True)
    pair.to_line(1, 0)
    pair.trace(False)
    show_flags(pair, {259, 260, 261, 0})


def sprite_scene(pair):
    """Two or three sprites on every traced line (20, 23, ...), font tiles."""
    pair.write(1, 0)
    pair.write(3, 0)
    oam = [0xF8, 0, 0, 0] * 64
    k = 0
    for i in range(30):
        line = 20 + 3 * i
        for y, x in ((line - 2, 96 + 5 * (i % 7)), (line - 3, 160 + 3 * (i % 9))):
            if k < 64:
                oam[4 * k : 4 * k + 4] = [y, 0x41 + (k % 20), k % 4, x]
                k += 1
    for v in oam:
        pair.write(4, v)
    pair.write(1, 0x1E)


def mode_mux() -> None:
    from ppusim_compare import rendered

    before, after = int(sys.argv[2], 16), int(sys.argv[3], 16)
    pair = Pair()
    rendered(pair, 0x1E)
    mark = []
    pair.cartridge.ppu_address = lambda a, t: mark.append((pair.ours.line, pair.ours.dot, a))
    pair.mark = mark
    pair.to_line(241, 10)
    sprite_scene(pair)
    pair.to_line(261, 100)
    from ppusim_compare import scroll_zero

    scroll_zero(pair)
    pair.write(1, 0x1E)
    line = 20
    for shift in range(8):
        pair, dot, ale, pixels = toggle_case2(before, after, shift, line, pair)
        a = " ".join(f"{d}:{o and f'{o:04X}'}/{s and f'{s:04X}'}" for d, o, s in ale[:6])
        p = " ".join(f"{x}:{o:02X}/{s:02X}" for x, o, s in pixels[:12])
        print(
            f"access {dot} (D {dot + 1}): ALE [{a}] pixels ours/sim "
            f"[{p}]{' ...' if len(pixels) > 12 else ''}"
        )
        line += 3


def mode_oam2() -> None:
    from ppusim_compare import rendered, scroll_zero

    pair = Pair()
    rendered(pair, 0x1E)
    pair.mark = []
    pair.to_line(241, 10)
    sprite_scene(pair)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    line = 20
    pair.to_line(line - 1, 200)
    pair.write(1, 0x00)
    pair.write(6, 0x20)
    pair.write(6, 0x00)
    print("before re-enable: ours", pair.ours.line, pair.ours.dot)
    pair.write(1, 0x1E)
    print("after re-enable: ours", pair.ours.line, pair.ours.dot)
    pair.to_line(line, 270)
    lib, h = pair.sim.lib, pair.sim.h
    print("ours oam2:", bytes(pair.ours.oam2).hex(" "))
    print("sim  oam2:", bytes(lib.ppusim_temp_oam(h, i) for i in range(32)).hex(" "))
    print("ours index", pair.ours._oam2_index, "frozen", pair.ours._oam2_frozen)


def mode_attr() -> None:
    before, after, upto = int(sys.argv[2], 16), int(sys.argv[3], 16), int(sys.argv[4])
    pair = None
    line = 20
    for shift in range(upto + 1):
        if shift == upto:
            rec = []
            ours = pair.ours
            orig = ours._step

            def step(orig=orig, ours=ours, rec=rec):
                orig()
                rec.append(
                    (
                        ours.line,
                        ours.dot,
                        ours.at_lo,
                        ours.at_hi,
                        ours.at_latch,
                        ours.v,
                        ours._on,
                        ours.bg_hi,
                        ours.hi_latch,
                    )
                )

            ours._step = step
        pair, dot, _ale, pixels = toggle_case2(before, after, shift, line, pair)
        if shift == upto:
            ours._step = orig
            break
        line += 3
    print(
        f"access {dot}, D {dot + 1}; pixels ours/sim "
        f"{[(x, f'{o:02X}', f'{s:02X}') for x, o, s in pixels]}"
    )
    sim = {}
    for e in pair.sim_trace():
        if e.v == line and e.half % 8 == 7:
            sim[e.h] = (list(e.background), e.inner[4] & 1)
    ours_at = {d: r for r in rec if r[0] == line for d in [r[1]]}
    for d in range(dot - 6, dot + 24):
        b, black = sim.get(d + 1, ([0] * 8, 0))
        r = ours_at.get(d)
        o = (
            f"at_lo {r[2] >> 8:08b}.{r[2] & 255:08b} latch {r[4]} on{int(r[6])} bg_hi "
            f"{r[7] >> 8:08b}.{r[7] & 255:08b} "
            f"hi_latch {r[8]:08b}"
            if r
            else ""
        )
        print(
            f"dot {d} ph{(d - 1) & 7} | sim h{d + 1} BLACK{black} SRLOAD{b[0] & 1} "
            f"STEP2{b[0] >> 1 & 1} "
            f"PD_SEL{b[0] >> 2 & 1} H01{b[0] >> 4 & 1} THO1{b[4] >> 5 & 1} TVO1{b[4] >> 4 & 1} "
            f"latch{b[0] >> 5 & 1}{b[0] >> 6 & 1} sr2 {b[1]:08b} at {b[3]:08b} bgc1sr2 {b[5]:08b} "
            f"STEP{b[0] >> 7 & 1} | ours {o}"
        )


def window_case(pair, line, shift, gap, off=0x00, on=0x0A):
    """Rendering off then on again ``gap`` CPU cycles later, mid-line."""
    from ppusim_compare import SIM_PIXEL_H

    pair.to_line(line - 1, 200)
    pair.write(1, 0x00)
    pair.write(6, 0x20)
    pair.write(6, 0x00)
    pair.write(1, on)
    pair.to_line(line, 0)
    pair.mark.clear()
    pair.trace(True)
    pair.idle(40 + shift)
    pair.idle(3)
    pair.access(1, off)
    dot = pair.ours.dot - 1
    pair.idle(gap - 1)
    pair.access(1, on)
    pair.to_line(line + 1, 0)
    pair.trace(False)
    ours_ale = {d: a for ln, d, a in pair.mark if ln == line}
    sim_ale = {}
    high = False
    for e in pair.sim_trace():
        a = bool(e.pins & 1)
        if a and not high and e.v == line:
            sim_ale[e.h] = e.address
        high = a
    ale = [
        (d, ours_ale.get(d), sim_ale.get(d))
        for d in range(1, 340)
        if ours_ale.get(d) != sim_ale.get(d)
    ]
    pix = pair.sim_pixels()
    row = pair.ours.picture[line * 256 : line * 256 + 256]
    pixels = [
        (x, row[x], pix.get((line, x + SIM_PIXEL_H), -1))
        for x in range(256)
        if row[x] != pix.get((line, x + SIM_PIXEL_H), -1)
    ]
    return dot, ale, pixels


def mode_window() -> None:
    from ppusim_compare import rendered

    on = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x0A
    pair = Pair()
    rendered(pair, on)
    pair.mark = []
    pair.cartridge.ppu_address = lambda a, t: pair.mark.append((pair.ours.line, pair.ours.dot, a))
    line = 20
    bad = 0
    for gap in (1, 2, 3, 4):
        for shift in range(8):
            dot, ale, pixels = window_case(pair, line, shift, gap, 0x00, on)
            a = " ".join(f"{d}:{o and f'{o:04X}'}/{s and f'{s:04X}'}" for d, o, s in ale[:4])
            p = " ".join(f"{x}:{o:02X}/{s:02X}" for x, o, s in pixels[:8])
            if ale or pixels:
                bad += 1
            print(
                f"gap {gap} access {dot} (phase {dot & 7}): ALE [{a}] pixels "
                f"[{p}]{' ...' if len(pixels) > 8 else ''}"
            )
            line += 3
            if line > 230:
                pair.to_line(10, 0)
                line = 20
    print(f"{bad} of 32 differ")


def mode_wtrace() -> None:
    from ppusim_compare import rendered

    gap, shift = int(sys.argv[2]), int(sys.argv[3])
    pair = Pair()
    rendered(pair, 0x0A)
    pair.mark = []
    pair.cartridge.ppu_address = lambda a, t: pair.mark.append((pair.ours.line, pair.ours.dot, a))
    rec = []
    ours = pair.ours
    orig = ours._step

    def step():
        orig()
        rec.append(
            (ours.line, ours.dot, ours.bg_lo, ours.bg_hi, ours.lo_latch, ours.hi_latch, ours._on)
        )

    ours._step = step
    line = 20
    dot, _ale, pixels = window_case(pair, line, shift, gap)
    print(f"off access {dot}; pixels {[(x, f'{o:02X}', f'{s:02X}') for x, o, s in pixels]}")
    sim = {}
    for e in pair.sim_trace():
        if e.v == line and e.half % 8 == 7:
            b = e.background
            sim[e.h] = (
                REVERSE[b[5]] << 8 | REVERSE[b[2]],
                REVERSE[b[6]] << 8 | REVERSE[b[7]],
                e.inner[4] & 1,
                b[0] & 1,
                b[0] >> 1 & 1,
            )
    o = {r[1]: r for r in rec if r[0] == line}
    for d in range(dot - 2, dot + 34):
        hi, lo, black, srload, step2 = sim.get(d + 1, (0, 0, 0, 0, 0))
        r = o.get(d)
        mark = (
            ""
            if not r
            else ("" if (r[3] >> 8) == (hi >> 8) and (r[2] >> 8) == (lo >> 8) else "  <> current")
        )
        print(
            f"dot {d} ph{(d - 1) & 7} | sim BLACK{black} SRLOAD{srload} STEP2{step2} hi "
            f"{hi >> 8:08b}.{hi & 255:08b} "
            f"lo {lo >> 8:08b}.{lo & 255:08b} | ours on{int(r[6]) if r else '-'} hi "
            f"{r[3] >> 8:08b}.{r[3] & 255:08b} "
            f"lo {r[2] >> 8:08b}.{r[2] & 255:08b} latches {r[4]:08b} {r[5]:08b}{mark}"
            if r
            else f"dot {d}"
        )


def sequence_case(pair, writes, lines):
    """Writes [(line, dot, register, value)] then compare ``lines`` and $2002."""
    from ppusim_compare import SIM_PIXEL_H

    pair.to_line(lines[0] - 1, 340 if writes[0][0] >= lines[0] else 0)
    pair.trace(True)
    pair.dots = []
    for line, dot, register, value in writes:
        pair.to_line(line, dot)
        pair.write(register, value)
        pair.dots.append((pair.ours.line, pair.ours.dot - 1))
    pair.to_line(lines[-1] + 1, 0)
    pair.trace(False)
    pix = pair.sim_pixels()
    out = []
    for line in lines:
        row = pair.ours.picture[line * 256 : line * 256 + 256]
        out += [
            (line, x, row[x], pix.get((line, x + SIM_PIXEL_H), -1))
            for x in range(256)
            if row[x] != pix.get((line, x + SIM_PIXEL_H), -1)
        ]
    pair.idle(3)
    s = pair.access(2)
    return out, (s[0] & 0x40, s[1] & 0x40)


def mode_lanes() -> None:
    from ppusim_compare import rendered, scroll_zero

    pair = Pair()
    rendered(pair, 0x1E)
    pair.to_line(241, 10)
    sprite_scene(pair)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    cases = []
    line = 20
    # mid-line windows over the sprites (X 96-131 and 160-190)
    for off in (90, 100, 110, 120, 150, 165, 175):
        for gap in (6, 12, 24):
            cases.append(([(line, off, 1, 0x00), (line, off + gap, 1, 0x1E)], [line]))
            line += 3
    # off late on a line, on again on the next
    for off in (250, 258, 280, 322, 334, 336, 338):
        for on in (2, 60, 100, 150):
            cases.append(([(line, off, 1, 0x00), (line + 1, on, 1, 0x1E)], [line + 1, line + 2]))
            line += 3
            if line > 225:
                line = 20
    bad = 0
    for writes, lines in cases:
        if writes[0][0] < pair.ours.line:
            pair.to_line(0, 10)
        diffs, s0 = sequence_case(pair, writes, lines)
        if diffs or s0[0] != s0[1]:
            bad += 1
            print(
                writes,
                "pixels",
                [(ln, x, f"{o:02X}", f"{s:02X}") for ln, x, o, s in diffs[:8]],
                "..." if len(diffs) > 8 else "",
                "spr0",
                s0,
            )
    print(f"{bad} of {len(cases)} differ")


def solid_sprite_pair():
    """A Pair on a copy of the ROM whose sprite tile $FF ($1FF0) is solid colour 3."""
    import tempfile
    from pathlib import Path

    from ppusim_compare import ROM

    data = ROM.read_bytes()
    prg = data[4] * 0x4000
    chr_ = bytearray(data[16 + prg : 16 + prg + 0x2000])
    chr_[0x1FF0:0x2000] = b"\xff" * 16
    d = tempfile.mkdtemp()
    rom = Path(d) / "solid.nes"
    rom.write_bytes(data[: 16 + prg] + bytes(chr_))
    return Pair(rom)


def mode_sprblank() -> None:
    from ppusim_compare import SIM_PIXEL_H

    pair = solid_sprite_pair()
    setup_picture(pair)
    pair.write(3, 0)
    oam = [0xF8, 0, 0, 0] * 64
    for _k in range(
        8
    ):  # a band on lines 20-235: rows of 8 sprites every 8 lines? one band per 8 lines
        pass
    oam = []
    for band in range(8):
        for k in range(8):
            oam += [19 + 8 * band * 3, 0xFF, 0x00, 64 + 8 * k]
    oam += [0xF8, 0, 0, 0] * (64 - len(oam) // 4)
    for v in oam:
        pair.write(4, v)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x14)
    mode = sys.argv[2]  # "off", "on", or "BB,AA" (hex PPUMASK values)
    for band in range(8):
        line = 20 + 8 * band * 3 + 2
        if "," in mode:
            before, after = (int(h, 16) for h in mode.split(","))
        else:
            before = 0x14 if mode == "off" else 0x00
            after = 0x00 if mode == "off" else 0x14
        pair.to_line(line - 2, 0)
        pair.write(1, before)
        pair.to_line(line, 0)
        pair.trace(True)
        pair.idle(20 + band)
        pair.idle(3)
        pair.access(1, after)
        dot = pair.ours.dot - 1
        pair.to_line(line + 1, 0)
        pair.trace(False)
        pix = pair.sim_pixels()
        row = pair.ours.picture[line * 256 : line * 256 + 256]
        xs = range(dot - 6, dot + 8)
        print(f"access {dot} (D {dot + 1})")
        print("   x:    " + " ".join(f"{x:3d}" for x in xs))
        print("   ours: " + " ".join(f" {row[x]:02X}" for x in xs))
        print("   sim:  " + " ".join(f" {pix.get((line, x + SIM_PIXEL_H), -1):02X}" for x in xs))


def mode_seqtrace() -> None:
    from ppusim_compare import rendered, scroll_zero

    pair = Pair()
    rendered(pair, 0x1E)
    pair.to_line(241, 10)
    sprite_scene(pair)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(1, 0x1E)
    l1, d1, l2, d2 = (int(a) for a in sys.argv[2:6])
    if len(sys.argv) > 10:
        pl1, pd1, pl2, pd2 = (int(a) for a in sys.argv[10:14])
        sequence_case(pair, [(pl1, pd1, 1, 0), (pl2, pd2, 1, 0x1E)], [pl2, pl2 + 1])
    rec = []
    ours = pair.ours
    orig = ours._step

    def step():
        orig()
        rec.append(
            (
                ours.line,
                ours.dot,
                ours.bg_lo,
                ours.bg_hi,
                ours.lo_latch,
                ours.hi_latch,
                ours._on,
                ours.v,
            )
        )

    ours._step = step
    diffs, s0 = sequence_case(pair, [(l1, d1, 1, 0), (l2, d2, 1, 0x1E)], [l2, l2 + 1])
    print(diffs, s0, pair.dots)
    sim = {}
    for e in pair.sim_trace():
        if e.half % 8 == 7:
            b = e.background
            sim[(e.v, e.h)] = (
                REVERSE[b[5]] << 8 | REVERSE[b[2]],
                REVERSE[b[6]] << 8 | REVERSE[b[7]],
                e.inner[4] & 1,
                b[0] & 1,
            )
    o = {(r[0], r[1]): r for r in rec}
    for line, rng in (
        (l1, range(int(sys.argv[6]), int(sys.argv[7]))),
        (l2, range(int(sys.argv[8]), int(sys.argv[9]))),
    ):
        for d in rng:
            hi, lo, black, srload = sim.get((line, d + 1), (0, 0, 0, 0))
            r = o.get((line, d))
            ours_s = (
                f"on{int(r[6])} hi {r[3] >> 8:08b}.{r[3] & 255:08b} lo "
                f"{r[2] >> 8:08b}.{r[2] & 255:08b} "
                f"latches {r[4]:08b} {r[5]:08b} v {r[7]:04X}"
                if r
                else "-"
            )
            print(
                f"{line}:{d} ph{(d - 1) & 7} | sim BLACK{black} SRLOAD{srload} hi "
                f"{hi >> 8:08b}.{hi & 255:08b} "
                f"lo {lo >> 8:08b}.{lo & 255:08b} | ours {ours_s}"
            )


def mode_pairs() -> None:
    from ppusim_compare import rendered, scroll_zero

    seqs = [
        [((83, 250, 1, 0), (84, 150, 1, 0x1E)), ((86, 250, 1, 0), (87, 60, 1, 0x1E))],
        [((95, 258, 1, 0), (96, 2, 1, 0x1E)), ((98, 258, 1, 0), (99, 60, 1, 0x1E))],
        [((107, 280, 1, 0), (108, 2, 1, 0x1E)), ((110, 280, 1, 0), (111, 60, 1, 0x1E))],
    ]
    for seq in seqs:
        pair = Pair()
        rendered(pair, 0x1E)
        pair.to_line(241, 10)
        sprite_scene(pair)
        pair.to_line(261, 100)
        scroll_zero(pair)
        pair.write(1, 0x1E)
        for writes in seq:
            diffs, s0 = sequence_case(pair, list(writes), [writes[1][0], writes[1][0] + 1])
            print(
                writes,
                "accesses",
                pair.dots,
                [(ln, x, f"{o:02X}", f"{s:02X}") for ln, x, o, s in diffs[:6]],
                s0,
            )
        print()


def mode_flagset() -> None:
    # AccuracyCoin "$2002 flag timing" 2: every sprite at Y $80, X $80, sprite 0
    # a line higher, over a solid tile at (128, 128); read $2002 each dot near
    # the sets on line 128 in both PPUs.
    pair = solid_sprite_pair()
    setup_picture(pair)
    pair.write(
        6, 0x22
    )  # nametable byte at row 16, column 16: tile $FF (solid in the sprite table only)
    pair.write(6, 0x10)
    pair.write(7, 0xFF)
    pair.write(3, 0)
    oam = [0x80, 0xFF, 0x00, 0x80] * 64
    oam[0] = 0x7F
    for v in oam:
        pair.write(4, v)
    pair.to_line(261, 100)
    scroll_zero(pair)
    pair.write(0, 0x18)  # BG and sprites both at $1000, where tile $FF is solid
    pair.write(1, 0x1E)
    for start in range(int(sys.argv[2]), int(sys.argv[3])):
        pair.to_line(127, 300)
        pair.to_line(128, start)
        pair.idle(3)
        o, s = pair.access(2)
        print(f"read at our dot {pair.ours.dot - 1}: ours {o & 0x60:02X} sim {s & 0x60:02X}")


MODES = {
    "offon": mode_offon,
    "latency": mode_latency,
    "bgon": mode_bgon,
    "phases": mode_phases,
    "phases2": mode_phases2,
    "seq": mode_seq,
    "seqall": mode_seqall,
    "rd": mode_rd,
    "prerender": mode_prerender,
    "mux": mode_mux,
    "oam2": mode_oam2,
    "attr": mode_attr,
    "window": mode_window,
    "wtrace": mode_wtrace,
    "lanes": mode_lanes,
    "sprblank": mode_sprblank,
    "seqtrace": mode_seqtrace,
    "pairs": mode_pairs,
    "flagset": mode_flagset,
}


if __name__ == "__main__":
    MODES[sys.argv[1]]()
