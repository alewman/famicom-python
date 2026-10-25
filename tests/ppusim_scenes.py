"""The C12 sweeps as scenes, for PPUSim's answers to be replayed without PPUSim.

Each scene drives a driver through mid-line register writes, as
``scripts/ppusim_c12_probes.py`` does, and asks it to ``observe`` the lines
it traced: their pixels, the ALE addresses of one line, a PPUSTATUS read.
Two drivers run them: :class:`Board`, our PPU alone (the quick test,
test_ppusim_goldens.py), and ``scripts/ppusim_goldens.py``'s recorder, a
``ppusim_compare.Pair`` that keeps PPUSim's observations in
``ppusim_goldens.json.gz``. Both drive the PPU as the board does (run to the
access point, access, run to the cycle's end), from the same CPU cycles.

The cartridge is made here (:func:`scene_rom`), so the test needs no fetched
ROM: varied pattern tiles, with tile $FF of both tables solid colour 3.
"""

from __future__ import annotations

from collections.abc import Callable

from famicom_python.machine import NES_001
from famicom_python.system import System

CYCLE = 12  # master ticks per CPU cycle
ACCESS_TICKS = 8  # board.PPU_ACCESS_TICKS: where the board stops the PPU for an access
FRAME_CYCLES = 29781  # a little over one frame of CPU cycles


def scene_rom() -> bytes:
    """NROM, vertical mirroring, 8 KiB CHR of varied tiles; tile $FF solid in both tables."""
    chr_data = bytearray((i * 73 + (i >> 4) * 29 + (i >> 9)) & 0xFF for i in range(0x2000))
    chr_data[0x0FF0:0x1000] = bytes([0xFF] * 16)
    chr_data[0x1FF0:0x2000] = bytes([0xFF] * 16)
    prg = bytearray(0x4000)
    prg[0x3FFA:0x4000] = bytes((0x00, 0x80, 0x00, 0x80, 0x00, 0x80))
    return b"NES\x1a" + bytes((1, 1, 1, 0)) + bytes(8) + bytes(prg) + bytes(chr_data)


class Board:
    """Our PPU alone, driven as ``ppusim_compare.Pair`` drives it."""

    def __init__(self) -> None:
        system = System.from_rom(scene_rom(), NES_001)
        self.ours = ours = system.board.ppu
        ours._watch = True  # report every ALE address
        self.mark: list[tuple[int, int, int]] = []  # (line, dot, address) of each ALE
        system.board.cartridge.ppu_address = lambda a, t: self.mark.append(  # type: ignore[method-assign]
            (ours.line, ours.dot, a)
        )
        self.t = 0
        self.results: dict[str, dict] = {}

    def idle(self, cycles: int) -> None:
        self.t += cycles * CYCLE
        self.ours.run_to(self.t)

    def access(self, register: int, value: int | None = None) -> int:
        self.t += CYCLE
        ppu = self.ours
        ppu.run_to(self.t + ACCESS_TICKS - CYCLE)
        if value is None:
            result = ppu.read_register(register)
        else:
            ppu.write_register(register, value, None)
            result = value
        ppu.run_to(self.t)
        if value is None:
            result = ppu.end_read(register, result)
        return result

    def trace(self, on: bool) -> None:
        if on:
            self.mark.clear()

    def status(self) -> int:
        self.idle(3)
        return self.access(2)

    def observe(self, name: str, lines: list[int], ale_line: int | None, status=None) -> None:
        picture = self.ours.picture
        self.results[name] = observation(
            {line: list(picture[line * 256 : line * 256 + 256]) for line in lines},
            {d: a for ln, d, a in self.mark if ln == ale_line and 1 <= d < 340},
            status,
        )

    # the same as Pair's

    def write(self, register: int, value: int) -> None:
        self.idle(3)
        self.access(register, value)

    def to_line(self, line: int, dot: int = 0) -> None:
        ours = self.ours
        while (ours.line, ours.dot) != (line, dot):
            gap = (line * 341 + dot - ours.line * 341 - ours.dot) % (262 * 341)
            if gap < 3:
                break
            self.idle(max(1, gap // 3 - 1))


def observation(rows: dict[int, list[int]], ale: dict[int, int], status: int | None) -> dict:
    """What a scene compares: pixel rows, one line's ALE addresses, the sprite flags."""
    out: dict = {"rows": {str(line): row for line, row in rows.items()}}
    if ale:
        out["ale"] = {str(d): a for d, a in sorted(ale.items())}
    if status is not None:
        out["status"] = status & 0x60
    return out


def first_difference(ours: dict, sim: dict) -> str:
    """Where an observation of ours first parts from PPUSim's, in words."""
    for line, row in sim["rows"].items():
        xs = [x for x in range(256) if ours["rows"][line][x] != row[x]]
        if xs:
            x = xs[0]
            theirs = f"ours {ours['rows'][line][x]:02X}, PPUSim {row[x]:02X}"
            return f"line {line}: {len(xs)} pixels from x {x} ({theirs})"
    if ours.get("ale") != sim.get("ale"):
        a, b = ours.get("ale", {}), sim.get("ale", {})
        dots = sorted((set(a) | set(b)) - {d for d in a if a[d] == b.get(d)}, key=int)
        return f"ALE differs at dots {dots[:6]}"
    return f"PPUSTATUS ours {ours.get('status')} PPUSim {sim.get('status')}"


# -- setting up -------------------------------------------------------------


def setup_picture(d) -> None:
    """Power-up wait, then a nametable and palette (ppusim_compare.setup_picture)."""
    d.idle(2 * FRAME_CYCLES)
    d.to_line(241, 10)
    d.write(0, 0x00)
    d.write(1, 0x00)
    d.idle(3)
    d.access(2)
    d.write(6, 0x3F)
    d.write(6, 0x00)
    for i in range(32):
        d.write(7, (i * 7 + 1) & 0x3F)
    d.write(6, 0x20)
    d.write(6, 0x00)
    for i in range(0x3C0):
        d.write(7, (i * 13 + i // 32) & 0xFF)
    for i in range(0x40):
        d.write(7, (i * 37) & 0xFF)


def scroll_zero(d, control: int = 0x08) -> None:
    d.idle(3)
    d.access(2)
    d.write(5, 0)
    d.write(5, 0)
    d.write(6, 0x20)
    d.write(6, 0x00)
    d.write(0, control)


def rendered(d, mask: int) -> None:
    """The picture, scrolled to 0, rendering with ``mask`` from the next frame."""
    setup_picture(d)
    d.to_line(261, 100)
    scroll_zero(d)
    d.write(1, mask)
    d.to_line(10, 0)


def sprites(d) -> None:
    """Two or three sprites on every third line from 20 (probes' sprite_scene), in vblank."""
    d.to_line(241, 10)
    d.write(1, 0)
    d.write(3, 0)
    oam = [0xF8, 0, 0, 0] * 64
    k = 0
    for i in range(30):
        line = 20 + 3 * i
        for y, x in ((line - 2, 96 + 5 * (i % 7)), (line - 3, 160 + 3 * (i % 9))):
            if k < 64:
                oam[4 * k : 4 * k + 4] = [y, 0x41 + (k % 20), k % 4, x]
                k += 1
    for v in oam:
        d.write(4, v)
    d.to_line(261, 100)
    scroll_zero(d)
    d.write(1, 0x1E)


# -- the scenes ---------------------------------------------------------------


def toggle(d, name: str, before: int, after: int, shift: int, line: int) -> None:
    """One $2001 write ``40 + shift`` cycles into ``line``, v at $2000 (probes' toggle_case2)."""
    d.to_line(line - 1, 200)
    d.write(1, 0x00)
    d.write(6, 0x20)
    d.write(6, 0x00)
    d.write(1, before)
    d.to_line(line, 0)
    d.trace(True)
    d.idle(40 + shift)
    d.write(1, after)
    d.to_line(line + 1, 0)
    d.trace(False)
    d.observe(name, [line], line)


def phases(d) -> None:
    """Rendering off and on at all 8 fetch phases (probes' phases2)."""
    rendered(d, 0x0A)
    line = 20
    for before, after in ((0x0A, 0x00), (0x00, 0x0A), (0x1E, 0x00), (0x00, 0x1E)):
        for shift in range(8):
            toggle(d, f"phases {before:02X}>{after:02X} +{shift}", before, after, shift, line)
            line += 3


def mux(d) -> None:
    """BG and sprite enables alone over sprites (probes' mux)."""
    rendered(d, 0x1E)
    sprites(d)
    line = 20
    for before, after in ((0x1E, 0x16), (0x16, 0x1E), (0x1E, 0x0E), (0x0E, 0x1E)):
        for shift in range(8):
            toggle(d, f"mux {before:02X}>{after:02X} +{shift}", before, after, shift, line)
            line += 3
            if line > 110:
                d.to_line(10, 0)
                line = 20


def windows(mask: int) -> Callable:
    def scene(d) -> None:
        """Rendering off for 1-4 CPU cycles mid-line (probes' window)."""
        rendered(d, mask)
        line = 20
        for gap in (1, 2, 3, 4):
            for shift in range(8):
                d.to_line(line - 1, 200)
                d.write(1, 0x00)
                d.write(6, 0x20)
                d.write(6, 0x00)
                d.write(1, mask)
                d.to_line(line, 0)
                d.trace(True)
                d.idle(43 + shift)
                d.access(1, 0x00)
                d.idle(gap - 1)
                d.access(1, mask)
                d.to_line(line + 1, 0)
                d.trace(False)
                d.observe(f"window {mask:02X} gap {gap} +{shift}", [line], line)
                line += 3
                if line > 230:
                    d.to_line(10, 0)
                    line = 20

    return scene


def lanes(d) -> None:
    """Off mid-line over sprites, and off late with a restart on the next line (probes' lanes)."""
    rendered(d, 0x1E)
    sprites(d)
    cases = []
    line = 20
    for off in (90, 100, 110, 120, 150, 165, 175):
        for gap in (6, 12, 24):
            cases.append(([(line, off), (line, off + gap)], [line]))
            line += 3
    for off in (250, 258, 280, 322, 334, 336, 338):
        for on in (2, 60, 100, 150):
            cases.append(([(line, off), (line + 1, on)], [line + 1, line + 2]))
            line += 3
            if line > 225:
                line = 20
    for (first, second), lines in cases:
        if first[0] < d.ours.line:
            d.to_line(0, 10)
        d.to_line(lines[0] - 1, 340 if first[0] >= lines[0] else 0)
        d.trace(True)
        d.to_line(*first)
        d.write(1, 0x00)
        d.to_line(*second)
        d.write(1, 0x1E)
        d.to_line(lines[-1] + 1, 0)
        d.trace(False)
        d.observe(f"lanes {first} {second}", lines, None, d.status())


def flags(d) -> None:
    """PPUSTATUS read a dot at a time across line 128's sprite-0 hit and overflow
    (probes' flagset, AccuracyCoin "$2002 flag timing")."""
    setup_picture(d)
    d.write(6, 0x22)  # row 16, column 16: tile $FF, solid
    d.write(6, 0x10)
    d.write(7, 0xFF)
    d.write(3, 0)
    oam = [0x80, 0xFF, 0x00, 0x80] * 64
    oam[0] = 0x7F
    for v in oam:
        d.write(4, v)
    d.to_line(261, 100)
    scroll_zero(d, 0x18)  # BG and sprites at $1000
    d.write(1, 0x1E)
    for start in range(112, 126):  # reads at dots 123-137: both flags set at 129-130
        d.to_line(127, 300)
        d.to_line(128, start)
        d.observe(f"flags {start}", [], None, d.status())


SCENES: dict[str, Callable] = {
    "phases": phases,
    "mux": mux,
    "window 0A": windows(0x0A),
    "window 1E": windows(0x1E),
    "lanes": lanes,
    "flags": flags,
}
