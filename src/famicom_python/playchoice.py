"""The PlayChoice-10's game board: what differs from a console around the 2A03.

Sources, by tier: Nintendo's own PCH1-CPU schematic (© 1986 Nintendo of
America, six sheets; the NESdev wiki links it from CPU_Test_Mode.wiki; pinned
as ``reference/docs/Playchoice.pdf``; **manufacturer's documentation**, read
by eye, each reading named by sheet and part); PC10_ROM-Images.wiki and
NES_2.0.wiki (specification tier); MAME's ``playch10.cpp`` (BSD-3, pinned as
``reference/mame-nes/playch10.cpp``; emulator-derived).

A PlayChoice-10 is an NES on an arcade board: an RP2A03E, an RP2C03B (RGB),
2 KiB of work RAM, 2 KiB of nametable RAM and ten game sockets ("channels"),
each a small board with the game's ROMs, its mapper, an 8 KiB INST ROM for the
supervisor and an RP5H01 security PROM. A Z80 supervisor on the same board
(``supervisor.py``) chooses the channel, holds the game's reset and stop
lines, and sells time. This module is the game's side of it:

- **The panel** (sheet 5). Two 74LS165 shift registers, 8B and 8A, stand where
  the controller ports are: loaded while OUT0 is high (through an inverter to
  their S/L), clocked by the 2A03's /INP0 and /INP1, and read through
  inverting buffers (74LS368A) on D0. Their inputs H to A are A, B, Game
  Select, Start, Up, Down, Left, Right, so a report is a controller's. The
  serial inputs are grounded, which the buffer inverts: after eight bits a
  read returns 1, as an official controller does (MAME shifts in 0:
  docs/undocumented-behavior.md C82). Player 1's Start and Game Select pass
  through OR gates (74LS32, 8C) with the supervisor's /CNTRL MASK: while it
  is low they read released. Player 2's register has nothing on its E and F
  inputs: no Select, no Start (MAME's port agrees; its comment, "wired to 1p
  select button", does not).
- **The light gun** (sheet 5, "Gun Hit", "Gun Trigger"): two lines to D3 and
  D4 of $4017 beside player 2's serial data, the trigger through an OR gate
  with /CNTRL MASK. The polarity is set by solder jumpers (CL4-CL7, SL6-SL9)
  the schematic draws both ways; MAME's is the NES Zapper's (D3 = 0 while
  light is seen, D4 = 1 while the trigger is pulled), and the games are the
  NES ones, so :class:`PlayChoiceGun` is the NES Zapper's model.
- **$4016/$4017**: the buffers drive D0-D4 (D1 and D2 have nothing on their
  inputs and read 0); D5-D7 are open bus, as on a console.
- **The image** (:func:`game_roms`): the INST ROM and the PROM's two
  recordings, after the CHR ROM.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .cartridge.ines import RomImage
from .joypad import SELECT, START, StandardController
from .peripherals import Zapper
from .ppu import PPU

INST_SIZE = 0x2000
PROM_SIZE = 16
#: "Usually constant" (PC10_ROM-Images.wiki): the RP5H01's counter bit 5 over
#: 128 clocks. What a dump without the PROM's recordings is given.
COUNTER_OUT = bytes.fromhex("00000000ffffffff00000000ffffffff")


@dataclass(frozen=True)
class GameRoms:
    """A PlayChoice-10 game board's two chips besides the game's own.

    ``inst`` is the INST ROM, at the Z80's $C000; ``prom`` and ``counter_out``
    are the RP5H01's Data and Counter Out pins recorded over 128 clocks, the
    first clock's in bit 0 of the first byte (PC10_ROM-Images.wiki). ``prom``
    is None for a dump made without it.
    """

    inst: bytes
    prom: bytes | None
    counter_out: bytes


def is_playchoice(image: RomImage) -> bool:
    """Whether ``image`` is a PlayChoice-10 game: nes20db's console type, or
    the header's own (byte 7's low bits, iNES and NES 2.0 alike). The header
    is asked too because several PlayChoice games are their home cartridges'
    PRG and CHR exactly, and nes20db, asked by those two hashes when the
    miscellaneous ROM is not one it knows, answers with the cartridge."""
    return image.board.console == 2 or image.header[7] & 0x03 == 2


def game_roms(image: RomImage) -> GameRoms | None:
    """The miscellaneous-ROM area of a PlayChoice-10 image (NES_2.0.wiki): "an
    8 KiB INST ROM, 16 bytes of PROM Data, 16 bytes of PROM Counter Out data".
    "The two required PROM sections are missing in older ROM images"
    (PC10_ROM-Images.wiki): then ``prom`` is None. None for an image without
    an INST ROM."""
    misc = image.misc
    if not is_playchoice(image) or len(misc) < INST_SIZE:
        return None
    inst, rest = misc[:INST_SIZE], misc[INST_SIZE:]
    if len(rest) < 2 * PROM_SIZE:
        return GameRoms(inst, None, COUNTER_OUT)
    return GameRoms(inst, rest[:PROM_SIZE], rest[PROM_SIZE : 2 * PROM_SIZE])


class PlayChoicePad(StandardController):
    """One player's stick and buttons on the panel's 74LS165 (module notes).

    ``masked`` is the supervisor's /CNTRL MASK held low: Start and Game Select
    read released. It is False on a game board run alone
    (``System`` on the ``playchoice`` row), as if the supervisor had let go.
    """

    def __init__(self, select_start: bool = True) -> None:
        super().__init__()
        self._wired = 0xFF if select_start else 0xFF & ~(SELECT | START)
        self.masked = False

    def _inputs(self) -> int:
        pressed = self.buttons & self._wired
        if self.masked:
            pressed &= ~(SELECT | START)
        return pressed

    def set_strobe(self, high: bool) -> None:
        if high or self.strobe:
            self.shift = self._inputs()
        self.strobe = high

    def read(self) -> int:
        return (self._inputs() if self.strobe else self.shift) & 1

    def clock(self) -> None:
        if self.strobe:
            self.shift = self._inputs()
        else:
            self.shift = (self.shift >> 1) | 0x80  # the grounded serial input, inverted


class PlayChoiceGun(Zapper):
    """The cabinet's light gun: D3 and D4 of $4017, beside player 2's D0.

    The sensor and trigger are the NES Zapper's model (module notes);
    /CNTRL MASK holds the trigger released.
    """

    def __init__(self, ppu: PPU, palette: Sequence[bytes], pad: PlayChoicePad) -> None:
        super().__init__(ppu, palette)
        self.pad = pad

    @property
    def masked(self) -> bool:
        return self.pad.masked

    @masked.setter
    def masked(self, value: bool) -> None:
        self.pad.masked = value

    def set_strobe(self, high: bool) -> None:
        self.pad.set_strobe(high)

    def clock(self) -> None:
        self.pad.clock()

    def read(self) -> int:
        gun = super().read()
        if self.pad.masked:
            gun &= ~0x10
        return gun | self.pad.read()
