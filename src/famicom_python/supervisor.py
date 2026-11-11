"""The PlayChoice-10's supervisor: a Z80, its BIOS, its own screen, and the cabinet.

Sources, by tier (``playchoice.py`` has the game board's): Nintendo's PCH1-CPU
schematic (``reference/docs/Playchoice.pdf``, manufacturer's documentation,
read by eye: "sheet N" below, with the part's board position); MAME's
``playch10.cpp`` and ``rp5h01.cpp`` (BSD-3, pinned under
``reference/mame-nes/``; emulator-derived); PC10_ROM-Images.wiki
(specification). Where the schematic and MAME differ the schematic is
followed and the difference is a numbered contradiction
(docs/undocumented-behavior.md C82-C86).

**The Z80** (sheet 1): a Z80A on an 8 MHz crystal halved, 4 MHz
(z80-python, the family's core). Its memory::

    $0000-$3FFF  the BIOS (8T, 16 KiB)
    $8000-$87FF  RAM (8V)
    $8800-$8FFF  RAM (8W), kept by a capacitor when the power is off; its
                 A10 is ANDed with the latch's "BUP KEY", so the upper half
                 is the lower's mirror until the BIOS turns the key
    $9000-$97FF  the screen's RAM (8R): the Z80's only while SDCS is low
    $C000-$DFFF  the selected channel's INST ROM
    $E000-$FFFF  the selected channel's security PROM (/ID SEL)

and its ports (sheet 3; reads decode A0-A1, writes A0-A3)::

    read 0   CH Select, Enter, Reset, INT DETECT, 0, Coin 2, Service, Coin 1
             (bits 0 to 7, through a 74LS240)
    read 1   DIP switches A-H (SW1)      read 2   DIP switches I-P (SW2)
    read 3   /DETECT CLR: clears INT DETECT
    write 0-7, 8-F   two 74LS259 addressable latches, bit 0 of the data:
        0 SDCS          1 /CNTRL MASK    2 /DISP MASK    3 /SOUND MASK
        4 /GAME RES     5 /GAME STOP     6 -             7 -
        8 NMI EI        9 DOG DI         A /PPU RES      B-E CSEL0-3
        F BUP KEY ("backup key"; MAME reads the label as "8UP KEY")

Both latches are cleared by the Z80's reset: the game held in reset, the PPU
held in reset, picture, sound and Start masked, channel 1.

**Its screen** (sheet 2): 32 x 32 characters of 8 x 8 pixels from the screen
RAM, two bytes each (the character's low 8 bits; then bits 2-0 its high bits
and bits 7-3 its colour), three bitplanes in EPROMs 8P, 8M and 8K (bits 0, 1,
2 of the pixel), and three 82S129 PROMs (6F red, 6E green, 6D blue) addressed
by colour and pixel, four bits a channel through resistor networks (the
weights are MAME's: 0x0E, 0x1F, 0x43, 0x8F, on the PROM's inverted bits). The
counters (74LS161s from a 20.160 MHz crystal, a quarter of it the dot clock)
count 256 dots and then reload to 185: 327 dots a line; and 256 lines: 60.21
frames a second, nothing to do with the game's 60.10. The vertical blank
flip-flop (5M) sets as line 240 begins and clears as line 16 does, and it
blanks the picture: 224 lines show, rows 2 to 29 (C83: MAME shows rows 0 to
29 at 60 Hz). While SDCS is low the Z80 has the RAM and the screen is blank.

**The vertical blank** clocks two things (sheet 1). A flip-flop (74LS109, 4Y)
pulls the Z80's /NMI low when NMI EI is high, and holds it until NMI EI goes
low: the BIOS re-arms it each time. A counter (74LS161, 4R) is held at zero
while NMI EI or DOG DI is high and counts blanks otherwise; its eighth resets
the Z80 (C84: MAME resets on the first).

**The game's lines** (sheets 5 and 6). /GAME RES is the 2A03's reset, /PPU RES
the 2C03's, separately. /GAME STOP goes to the 2A03E's pin 30 (its /RDY)
through two flip-flops clocked by the PPU's /INT (its vertical blank
interrupt, a few M2 cycles delayed): the game stops, and starts again, only
just after one of its own NMIs, and never if it has not enabled them (C85:
MAME halts at once). The same pulse sets INT DETECT, which the BIOS reads and
clears: "the game is running and interrupting". /DISP MASK and /SOUND MASK
are analogue switches (4066s) in the game's RGB and sound; /CNTRL MASK is
``playchoice.PlayChoicePad.masked``.

**The security PROM** (:class:`RP5H01`; sheet 6, MAME's rp5h01.cpp): a write
to $E000-$FFFF latches D0, D3 and D4 (74LS175, 4S) as the chip's /RESET
(inverted), clock and TEST; a read returns its data on D3 and its counter
output on D4, both through inverting buffers, and 1 on the other six lines
(pull-ups). The BIOS clocks the bits out and checks them against the INST
ROM; nothing here knows the check: the BIOS runs it.

**Ten channels, one game.** The cabinet has ten sockets (CSEL0-3 through a
74LS42); this model has one game, in channel 1, and nine empty sockets whose
INST ROM and PROM read as pulled-up lines (MAME does the same).

**Two processors, three crystals** (:class:`PlayChoice`). The game board is a
:class:`~famicom_python.system.System` on the master clock; the Z80 counts its
own T-states. They are interleaved an instruction at a time, the one behind
stepping next, with the crystals taken at their nominal ratios (a Z80 T-state
is 945/176 master ticks; a screen dot 50/63 T-states). A latch write reaches
the game within one instruction of either processor, never on its cycle: the
limit of this model (and of z80-python, which reports an instruction's length,
not where in it a port is written). No source here measures better, and the
two sides share nothing faster than a latch bit and a serial PROM.
"""

from __future__ import annotations

import hashlib
import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from z80_python import Z80CPU

from .cartridge import Loaded, load
from .machine import MACHINES, Machine
from .playchoice import COUNTER_OUT, GameRoms, game_roms, is_playchoice
from .ppu import HEIGHT, WIDTH
from .system import System
from .video import rgb_palette

# The latches' outputs, by port number (module notes).
SDCS, CNTRL_MASK, DISP_MASK, SOUND_MASK, GAME_RES, GAME_STOP = range(6)
NMI_EI, DOG_DI, PPU_RES, CSEL0, CSEL1, CSEL2, CSEL3, BUP_KEY = range(8, 16)

# Port 0's bits.
CHANNEL, ENTER, RESET, INT_DETECT, _INP0_D4, COIN_2, SERVICE, COIN_1 = (1 << n for n in range(8))

Z80_HZ = 4_000_000
# The screen's time is counted in units of 1/63 T-state: a dot is 50 of them
# (5.04 MHz against 4 MHz).
UNITS_PER_T = 63
UNITS_PER_DOT = 50
DOTS_PER_LINE = 327  # 256, then the counters reload to 185 and run to 255 (sheet 2, 6L and 6K)
LINES = 256
VBLANK_FROM, VBLANK_TO = 240, 16  # the flip-flop 5M: set at line 240, cleared at line 16
FRAME_UNITS = DOTS_PER_LINE * LINES * UNITS_PER_DOT
WATCHDOG_BLANKS = 8  # the counter 4R's QD
COIN_SECONDS = 0.050  # a coin's contact, as the Vs. System's (vs.COIN_SECONDS): unmeasured here

#: The BIOS versions, as MAME names them, and the file of each (playch10.cpp
#: ``BIOS_CPU``): the SHA-1s are MAME's. "dual" is the two-monitor cabinet the
#: schematic draws; "single" is the one-monitor board's (PCK1), which has no
#: schematic here.
BIOS_PROGRAMS = {
    "dual": ("pch1-c__8t_e-2.8t", "55cabf52ae10c050c2229081a80b9fe5454ab8c5"),
    "single": ("pck1-c.8t", "3bd20bc71cac742d1b8c1430a6426d0a19db7ad0"),
}
#: The screen's EPROMs (pixel bits 2, 1, 0) and colour PROMs (red, green, blue).
BIOS_CHARACTERS = (
    ("pch1-c__8k.8k", "b814f10ef23f2ca445fabafcbf7f25e2d454ba8c"),
    ("pch1-c__8m_e-1.8m", "beaf9fa2d091a3c7f70c51e966d885b1f9f0935f"),
    ("pch1-c__8p_e-1.8p", "69166afdb2fe827c7f1919cdf4197caccbd961fa"),
)
BIOS_PROMS = (
    ("pch1-c-6f.82s129an.6f", "d2878411cda84ffe0afb2e538a67457f51bebffb"),
    ("pch1-c-6e.82s129an.6e", "a448b47c9289902e26a3d3c4c7d5a7968c385e81"),
    ("pch1-c-6d.82s129an.6d", "0ad386fc3eab5e53c0288ad1de33639a9e461b7c"),
)


@dataclass(frozen=True)
class Bios:
    """The supervisor's ROMs: its program, its characters, its colours."""

    name: str
    program: bytes  # 16 KiB
    characters: tuple[bytes, bytes, bytes]  # 8K, 8M, 8P: pixel bits 2, 1, 0
    proms: tuple[bytes, bytes, bytes]  # red, green, blue: 256 x 4 bits

    @property
    def single_monitor(self) -> bool:
        return self.name == "single"


def bios_path() -> Path:
    """Where the BIOS is: the zip (or folder) FAMICOM_PC10_BIOS names, else
    MAME's ``playch10.zip`` under MAME_ROM_DIR (default ``MAME``)."""
    named = os.environ.get("FAMICOM_PC10_BIOS")
    if named:
        return Path(named)
    return Path(os.environ.get("MAME_ROM_DIR", "MAME")) / "playch10.zip"


def load_bios(name: str = "dual", path: str | Path | None = None) -> Bios:
    """The BIOS ``name`` from MAME's ``playch10`` set at ``path`` (default
    :func:`bios_path`), each file checked against MAME's SHA-1. Never shipped:
    it is Nintendo's."""
    path = Path(path) if path is not None else bios_path()
    if not path.exists():
        raise FileNotFoundError(f"PlayChoice-10 BIOS not found at {path}: set FAMICOM_PC10_BIOS")
    if path.is_dir():
        read: Callable[[str], bytes] = lambda member: (path / member).read_bytes()  # noqa: E731
    else:
        archive = zipfile.ZipFile(path)
        read = archive.read

    def checked(entry: tuple[str, str]) -> bytes:
        member, sha1 = entry
        try:
            data = read(member)
        except (KeyError, FileNotFoundError):
            raise FileNotFoundError(f"{path} has no {member}") from None
        if hashlib.sha1(data).hexdigest() != sha1:
            raise ValueError(f"{path}: {member} is not the file MAME's playch10 set names")
        return data

    characters = tuple(checked(entry) for entry in BIOS_CHARACTERS)
    proms = tuple(checked(entry) for entry in BIOS_PROMS)
    return Bios(name, checked(BIOS_PROGRAMS[name]), characters, proms)  # type: ignore[arg-type]


class RP5H01:
    """Ricoh's serial PROM: 64 bits and a counter, read a bit at a time.

    MAME's rp5h01.cpp, as pinned (emulator-derived; the datasheet is not
    pinned): RESET high holds the counter at zero; a falling edge of the clock
    while RESET is low advances it; TEST chooses whether the data pin follows
    six bits of the counter or seven ("in 7-bit counter mode, from 64 to 127
    ... the dummy bits are read"); the counter output is the counter's bit 5.
    The image holds the two pins as they were recorded over 128 clocks
    (playchoice.GameRoms), and this plays the recordings back: the first
    clock's bit is bit 0 of the first byte.
    """

    def __init__(self, data: bytes, counter_out: bytes = COUNTER_OUT) -> None:
        self.data = data
        self.counter_out = counter_out
        self.counter = 0
        self.reset = False
        self.clock = False
        self.test = False

    def write(self, reset: bool, clock: bool, test: bool) -> None:
        """The three input pins, as the board's latch drives them."""
        if reset:
            self.counter = 0
        elif self.clock and not clock:
            self.counter = (self.counter + 1) & 0x7F
        self.reset, self.clock, self.test = reset, clock, test

    @property
    def data_out(self) -> int:
        index = self.counter & (0x7F if self.test else 0x3F)
        return self.data[index >> 3] >> (index & 7) & 1

    @property
    def counter_output(self) -> int:
        return self.counter_out[self.counter >> 3] >> (self.counter & 7) & 1


class Supervisor:
    """The Z80 and what it alone touches (module notes). ``on_line(number,
    level)`` is told each latch output that changes; the cabinet
    (:class:`PlayChoice`) owns what the game's lines do."""

    def __init__(
        self,
        bios: Bios,
        roms: GameRoms | None,
        on_line: Callable[[int, int], None] = lambda number, level: None,
    ) -> None:
        self.bios = bios
        self.rom = bios.program
        self.inst = roms.inst if roms is not None else None
        self.prom = RP5H01(roms.prom, roms.counter_out) if roms and roms.prom else None
        self.ram = bytearray(0x800)  # 8V
        self.ram_8w = bytearray(0x800)  # battery-backed
        self.video_ram = bytearray(0x800)
        self.latch = [0] * 16
        self.on_line = on_line
        #: DIP switches A-H and I-P as bits 0-7, 1 = on (MAME's SW1 and SW2).
        self.dip = [0, 0]
        #: The cabinet's buttons held now: CHANNEL, ENTER, RESET, SERVICE.
        self.buttons = 0
        # Coins: each slot's contacts, as the T-state at which one closes.
        self.coins: tuple[list[int], list[int]] = ([], [])
        self.int_detect = False
        #: The single-monitor BIOS's four time digits (MAME's ``time_w``).
        self.digits = [0, 0, 0, 0]
        self.t = 0  # T-states since power
        # The screen's counters start at line 0, dot 0; the first blank begins
        # at line 240.
        self._next_blank = VBLANK_FROM * DOTS_PER_LINE * UNITS_PER_DOT
        self.blanks = 0
        self._nmi_released = True  # the flip-flop 4Y: /NMI high
        self._watchdog = 0
        self.watchdog_resets = 0
        self.cpu = Z80CPU(
            self.read_byte, self.write_byte, read_port=self.read_port, write_port=self.write_port
        )
        self.instructions = 0
        self._tiles: dict[tuple[int, int], bytes] = {}
        self._colours = self._palette()

    # -- the Z80's memory ------------------------------------------------

    def read_byte(self, address: int) -> int:
        if address < 0x4000:
            return self.rom[address]
        if address >= 0xE000:
            # Six lines pulled up; D3 and D4 from the selected channel's PROM,
            # inverted by the buffers (an empty socket's lines float high).
            value = 0xE7
            prom = self.prom
            if prom is not None and not self.channel:
                value |= (prom.data_out ^ 1) << 3 | (prom.counter_output ^ 1) << 4
            return value
        if address >= 0xC000:
            if self.inst is not None and not self.channel:
                return self.inst[address & 0x1FFF]
            return 0xFF
        if address < 0x8000:
            return 0xFF
        if address < 0x8800:
            return self.ram[address & 0x7FF]
        if address < 0x9000:
            return self.ram_8w[address & (0x7FF if self.latch[BUP_KEY] else 0x3FF)]
        if address < 0x9800:
            return self.video_ram[address & 0x7FF]
        return 0xFF

    def write_byte(self, address: int, value: int) -> None:
        if address >= 0xE000:
            if self.prom is not None and not self.channel:
                self.prom.write(not value & 1, bool(value & 0x08), bool(value & 0x10))
        elif 0x8000 <= address < 0x8800:
            self.ram[address & 0x7FF] = value
        elif 0x8800 <= address < 0x9000:
            self.ram_8w[address & (0x7FF if self.latch[BUP_KEY] else 0x3FF)] = value
        elif 0x9000 <= address < 0x9800 and not self.latch[SDCS]:
            self.video_ram[address & 0x7FF] = value

    @property
    def channel(self) -> int:
        """The selected game socket, 0 for channel 1 (CSEL0-3)."""
        latch = self.latch
        return latch[CSEL0] | latch[CSEL1] << 1 | latch[CSEL2] << 2 | latch[CSEL3] << 3

    # -- the Z80's ports -------------------------------------------------

    def read_port(self, port: int) -> int:
        port &= 3
        if port == 0:
            value = self.buttons & (CHANNEL | ENTER | RESET | SERVICE)
            if not self.int_detect:
                value |= INT_DETECT
            for bit, coins in zip((COIN_1, COIN_2), self.coins, strict=True):
                if coins:
                    length = round(COIN_SECONDS * Z80_HZ)
                    now = self.t
                    if coins[0] + length <= now:
                        coins[:] = [start for start in coins if now < start + length]
                    if any(start <= now for start in coins):
                        value |= bit
            return value
        if port == 3:
            self.int_detect = False
            return 0xFF  # nothing drives the bus (MAME returns 0)
        return self.dip[port - 1]

    def write_port(self, port: int, value: int) -> None:
        port &= 0xFF
        if self.bios.single_monitor and 0x10 <= port <= 0x13:
            self.digits[port - 0x10] = value & 0x0F
            return
        number = port & 0x0F
        level = value & 1
        if self.latch[number] == level:
            return
        self.latch[number] = level
        if number == NMI_EI and not level:
            self._nmi_released = True  # the flip-flop's preset
        self.on_line(number, level)

    # -- the operator and the player -------------------------------------

    def insert_coin(self, slot: int = 0, at: int | None = None) -> None:
        """A coin through slot 0 (Coin 1) or 1: its contact closes at T-state
        ``at`` (default: now) for :data:`COIN_SECONDS`."""
        self.coins[slot].append(self.t if at is None else at)

    # -- running ---------------------------------------------------------

    def power(self) -> None:
        self._reset()

    def _reset(self) -> None:
        """The Z80's /RESET: the CPU, and both latches cleared."""
        for number in range(16):
            if self.latch[number]:
                self.latch[number] = 0
                self.on_line(number, 0)
        self._nmi_released = True
        self._watchdog = 0
        cpu = self.cpu
        cpu.clear_non_maskable_interrupt()
        cpu.request_reset()
        self.t += cpu.step()
        cpu.clear_reset()

    def step(self) -> int:
        """One Z80 instruction; returns its T-states."""
        t_states = self.cpu.step()
        self.t += t_states
        self.instructions += 1
        if self.t * UNITS_PER_T >= self._next_blank:
            self._next_blank += FRAME_UNITS
            self._vertical_blank()
        return t_states

    def _vertical_blank(self) -> None:
        """The blank flip-flop's rising edge: the NMI and the watchdog."""
        self.blanks += 1
        latch = self.latch
        if latch[NMI_EI] and self._nmi_released:
            self._nmi_released = False
            self.cpu.request_non_maskable_interrupt()
        if latch[NMI_EI] or latch[DOG_DI]:
            self._watchdog = 0
        else:
            self._watchdog += 1
            if self._watchdog == WATCHDOG_BLANKS:
                self.watchdog_resets += 1
                self._reset()

    # -- the screen ------------------------------------------------------

    def _palette(self) -> list[bytes]:
        """The 256 colours of (colour, pixel): the PROMs' inverted bits through
        the resistor weights (MAME's ``playch10_palette``)."""
        weights = (0x0E, 0x1F, 0x43, 0x8F)
        colours = []
        for index in range(256):
            channels = []
            for prom in self.bios.proms:
                bits = ~prom[index] & 0x0F
                channels.append(sum(w for n, w in enumerate(weights) if bits >> n & 1))
            colours.append(bytes(channels))
        return colours

    def _tile(self, code: int, colour: int) -> bytes:
        """A character's 8 rows of 8 RGB pixels."""
        key = (code, colour)
        tile = self._tiles.get(key)
        if tile is None:
            high, middle, low = self.bios.characters
            colours = self._colours
            base = colour << 3
            rows = []
            for row in range(8):
                a, b, c = high[code * 8 + row], middle[code * 8 + row], low[code * 8 + row]
                rows.append(
                    b"".join(
                        colours[base | (a >> bit & 1) << 2 | (b >> bit & 1) << 1 | (c >> bit & 1)]
                        for bit in range(7, -1, -1)
                    )
                )
            tile = self._tiles[key] = b"".join(rows)
        return tile

    @property
    def screen_blank(self) -> bool:
        """SDCS low: the Z80 has the screen's RAM and the shift registers'
        colour is held clear."""
        return not self.latch[SDCS]

    def picture(self, lines: tuple[int, int] = (VBLANK_TO, VBLANK_FROM)) -> bytes:
        """The screen as packed RGB, 256 x 240 (the game screen's size): the
        counters' lines 0 to 239, of which only ``lines`` (first, end) are
        outside the vertical blank and drawn; the rest, and everything while
        SDCS is low, is black. ``lines=(0, 240)`` draws all thirty rows, as
        MAME does."""
        black = bytes(3)
        if self.screen_blank:
            return black * (WIDTH * HEIGHT)
        ram = self.video_ram
        out = []
        first, end = lines
        for line in range(HEIGHT):
            if not first <= line < end:
                out.append(black * WIDTH)
                continue
            row, y = line >> 3, (line & 7) * 24
            base = row * 64
            for column in range(32):
                low, high = ram[base + column * 2], ram[base + column * 2 + 1]
                tile = self._tile(low | (high & 7) << 8, high >> 3)
                out.append(tile[y : y + 24])
        return b"".join(out)


#: The game screen while /DISP MASK is low: the RGB lines are switched off.
MASKED_PIXEL = 0x0F


class PlayChoice:
    """A PlayChoice-10 with one game in channel 1: ``game`` (a System on the
    ``playchoice`` row) under ``supervisor`` (module notes)."""

    def __init__(self, loaded: Loaded, bios: Bios, machine: Machine | None = None) -> None:
        self.machine = machine = machine or MACHINES["playchoice"]
        self.bios = bios
        self.game = game = System(loaded.cartridge, machine)
        game.loaded = loaded
        self.loaded = loaded
        game.plug()
        board = game.board
        self._ticks = board.cycle_ticks
        #: The 2A03 is held in reset (/GAME RES low), or stopped by its pin 30.
        self.in_reset = True
        self.stopped = False
        self._nmi = False
        self.supervisor = Supervisor(bios, game_roms(loaded.image), self._line)
        self._mask_controls(True)
        board.ppu.reset()  # /PPU RES is low out of the Z80's reset
        self.supervisor.power()

    @classmethod
    def from_rom(
        cls, rom: str | Path | bytes, bios: Bios | None = None, machine: Machine | None = None
    ) -> PlayChoice:
        """The cabinet with the PlayChoice-10 image ``rom`` in channel 1 and
        the BIOS ``bios`` (default: :func:`load_bios`'s dual-monitor one)."""
        loaded = load(rom, cpu_cycle_ticks=MACHINES["playchoice"].timing.cpu_divider)
        if not is_playchoice(loaded.image):
            raise ValueError("not a PlayChoice-10 image")
        return cls(loaded, bios if bios is not None else load_bios(), machine)

    # -- the lines from the supervisor's latches -------------------------

    def _mask_controls(self, masked: bool) -> None:
        for pad in self.game.board.pads:
            if hasattr(pad, "masked"):
                pad.masked = masked

    def _line(self, number: int, level: int) -> None:
        game = self.game
        board = game.board
        if number == GAME_RES:
            if level:
                # Released: the 2A03 runs its reset sequence. The APU was
                # reset with it, and the game board saw M2 stop.
                board.apu.reset()
                board.cartridge.m2_gap(board.t)
                game.cpu.request_reset()
                self.in_reset = False
            else:
                self.in_reset = True
                self.stopped = False  # /GAME RES presets the stop flip-flops
                board.apu.reset()
        elif number == PPU_RES:
            board.ppu.reset()  # held while low; the power-on window from its release
        elif number == CNTRL_MASK:
            self._mask_controls(not level)

    # -- running ---------------------------------------------------------

    def _game_step(self) -> None:
        game = self.game
        board = game.board
        if self.in_reset:
            board.idle_cycle()
        elif self.stopped:
            board.read_byte(game.cpu.pc)  # RDY low: the 2A03 repeats its read
        else:
            game.cpu.step()
            game.instructions += 1
        nmi = board.ppu.nmi
        if nmi != self._nmi:
            self._nmi = nmi
            if nmi:
                # The PPU's /INT fell: INT DETECT sets, and the stop flip-flop
                # takes /GAME STOP (unless /GAME RES holds it preset).
                self.supervisor.int_detect = True
                if not self.in_reset:
                    self.stopped = not self.supervisor.latch[GAME_STOP]

    def step(self) -> None:
        """One instruction (or one idle cycle of a held 2A03) on the side whose
        clock is behind: T-states x 945 against master ticks x 176."""
        supervisor = self.supervisor
        if supervisor.t * 945 <= self.game.board.t * 176:
            supervisor.step()
        else:
            self._game_step()

    def run_frames(self, frames: int) -> None:
        """Run until the game's PPU has started ``frames`` more frames."""
        supervisor, board = self.supervisor, self.game.board
        ppu = board.ppu
        z80_step, game_step = supervisor.step, self._game_step
        target = ppu.frame + frames
        while ppu.frame < target:
            if supervisor.t * 945 <= board.t * 176:
                z80_step()
            else:
                game_step()

    def run_seconds(self, seconds: float) -> None:
        """Run for ``seconds`` of the Z80's clock."""
        supervisor, board = self.supervisor, self.game.board
        z80_step, game_step = supervisor.step, self._game_step
        end = supervisor.t + round(seconds * Z80_HZ)
        while supervisor.t < end:
            if supervisor.t * 945 <= board.t * 176:
                z80_step()
            else:
                game_step()

    # -- the cabinet -----------------------------------------------------

    def insert_coin(self, slot: int = 0) -> None:
        self.supervisor.insert_coin(slot)

    def press(self, button: int, seconds: float = 0.1) -> None:
        """Hold a cabinet button (CHANNEL, ENTER, RESET, SERVICE) for
        ``seconds``, running meanwhile."""
        self.supervisor.buttons |= button
        self.run_seconds(seconds)
        self.supervisor.buttons &= ~button

    @property
    def game_shown(self) -> bool:
        """/DISP MASK is high: the game's picture reaches its monitor."""
        return bool(self.supervisor.latch[DISP_MASK])

    @property
    def sound_on(self) -> bool:
        return bool(self.supervisor.latch[SOUND_MASK])

    def game_picture(self) -> list[int]:
        """The game monitor's picture, as the PPU's pixel values: black while
        /DISP MASK is low."""
        if self.game_shown:
            return self.game.board.ppu.picture
        return [MASKED_PIXEL] * (WIDTH * HEIGHT)

    def game_rgb(self) -> bytes:
        """The game monitor's picture as packed RGB (the RP2C03's colours)."""
        palette = rgb_palette(self.machine.timing.palette)
        return b"".join(palette[value] for value in self.game_picture())

    def take_samples(self) -> list[float]:
        """The game's sound, silent while /SOUND MASK is low."""
        samples = self.game.take_samples()
        if not self.sound_on:
            return [0.0] * len(samples)
        return samples
