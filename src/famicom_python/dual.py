"""The Vs. DualSystem: both sides of the mainboard running, on one clock.

Vs._System.wiki (specification tier): "The Vs. DualSystem has a main CPU, main
PPU, sub CPU, and sub PPU. All four are fed by the same clock, and all four are
released from reset by the watchdog at the same time. The RGB PPUs ... never
have the missing dot ... so it is never possible for the two PPUs to not be
anything but perfectly synchronized." Each side is a whole
:class:`~famicom_python.system.System` on a Vs. row of ``machine.py``, and this
module is the wiring between the two:

- **The shared RAM** at $6000-$7FFF: one :class:`~famicom_python.vs.SharedRAM`.
  "On the primary CPU only, [OUT1] controls which CPU can access [it]. When 1:
  the primary CPU has access and the secondary CPU sees open bus. When 0: the
  secondary CPU has access." OUT1 is 0 out of reset, so the secondary side
  starts with it.
- **The cross interrupt**: each side's OUT1 is the other side's /IRQ, "when 0:
  asserts an IRQ request. When 1: releases" it. Both are asserted out of reset
  until each program writes a 1.
- **The watchdog**: "the secondary CPU ... must be instructed to read from
  $4017 at least every 1.2 seconds, or else the watchdog timer will reset both
  CPUs, both PPUs, and both CPUs' bit at $4020". MAME measured "between 1.23s
  and 1.33s in hardware tests, exact timing unknown" and uses 1.3 s
  (vsnes.cpp), as this does.

**One clock, an instruction at a time.** 6502-python runs whole instructions,
so the two CPUs are interleaved by instruction: the side whose clock is behind
steps next (the primary on a tie). A write on one side therefore reaches the
other within one instruction's length, at most 7 CPU cycles plus any DMA, never
on the exact cycle. MAME interleaves the same way (``set_perfect_quantum``).
The PPUs need no such care: each is exact on its own side, and the two frames
begin on the same master tick.

**The image** (NES_2.0.wiki "PRG-ROM Area", "CHR-ROM Area"): "the first half
block of the specified PRG-ROM size belongs to the first unit, and the second
half block ... to the second unit"; 32 KiB of CHR are 16 KiB each, and with 16
KiB or less "both units use the same" CHR. The first unit is the primary side
(MAME's main CPU, sockets 1A-1D and 2A-2B). *Vs. Raid on Bungeling Bay*
(hardware type 6) is the exception both ways: 32 KiB for the first unit and 8
KiB for the second, at $E000, and its first unit, the game, is the *secondary*
side: it expects $4016 D7 = 1, and MAME's set names its EPROMs for sockets
6A-6D and the 8 KiB one for 1A.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .cartridge import Loaded, load, read_rom_file
from .cartridge.ines import RomImage, parse
from .joypad import START
from .machine import Machine, vs_machine
from .system import System
from .vs import SharedRAM, VsStick

WATCHDOG_SECONDS = 1.3

#: NES 2.0 Vs. hardware types that are DualSystem boards.
DUAL_HARDWARE = (5, 6)


def is_dual(rom: str | Path | bytes) -> bool:
    """Whether ``rom`` is a Vs. DualSystem image (by its header or nes20db)."""
    board = load(rom).image.board
    return board.console == 1 and board.vs_hardware in DUAL_HARDWARE


def split(image: RomImage) -> tuple[RomImage, RomImage]:
    """The (primary, secondary) sides' images of a DualSystem image (module notes)."""
    prg, chr_ = image.prg, image.chr
    if image.board.vs_hardware == 6 and len(prg) == 0xA000:
        first_prg, second_prg = prg[:0x8000], prg[0x8000:]
    else:
        half = len(prg) // 2
        first_prg, second_prg = prg[:half], prg[half:]
    if len(chr_) == 0x8000:
        first_chr, second_chr = chr_[:0x4000], chr_[0x4000:]
    else:
        first_chr = second_chr = chr_
    first = replace(image, prg=first_prg, chr=first_chr)
    second = replace(image, prg=second_prg, chr=second_chr)
    if image.board.vs_hardware == 6:
        return second, first  # the game is the secondary side's
    return first, second


class VsDualSystem:
    """A DualSystem cabinet: ``primary`` and ``secondary``, each a System."""

    def __init__(self, primary: Loaded, secondary: Loaded, machine: Machine) -> None:
        self.machine = machine
        self.primary = System(primary.cartridge, replace(machine, vs_side="primary"))
        self.secondary = System(secondary.cartridge, replace(machine, vs_side="secondary"))
        self.primary.loaded, self.secondary.loaded = primary, secondary
        self.sides = (self.primary, self.secondary)
        self.ram = SharedRAM("secondary", switched=True)
        self.watchdog_resets = 0
        first, second = self.primary.board, self.secondary.board
        assert first.vs is not None and second.vs is not None
        first.vs.ram = second.vs.ram = self.ram
        first.vs.other_irq = second.set_external_irq
        second.vs.other_irq = first.set_external_irq
        self._watchdog_ticks = round(WATCHDOG_SECONDS * machine.timing.master_hz)
        self._fed = 0  # the master tick of the secondary side's last $4017 read
        second.bus_observers.append(self._watch)
        self._out_of_reset()

    @classmethod
    def from_rom(cls, rom: str | Path | bytes) -> VsDualSystem:
        """Both sides of the DualSystem image ``rom``, with the PPUs its header
        or nes20db names."""
        whole = load(rom)
        board = whole.image.board
        if board.console != 1 or board.vs_hardware not in DUAL_HARDWARE:
            raise ValueError("not a Vs. DualSystem image")
        data = rom if isinstance(rom, bytes) else read_rom_file(rom)
        image = parse(data).with_board(board)
        first, second = (
            Loaded(type(whole.cartridge)(side, 12), side, whole.source, whole.disagreements, {})
            for side in split(image)
        )
        system = cls(first, second, vs_machine(board.vs_ppu))
        if board.vs_hardware == 6:  # Raid on Bungeling Bay's jumpers (vs.VsStick)
            for side in system.sides:
                for pad in side.board.pads:
                    if isinstance(pad, VsStick):
                        pad.jumper = START
        return system

    # -- the wiring ------------------------------------------------------

    def _out_of_reset(self) -> None:
        """Both OUT1s are 0: each side requests the other's interrupt, and the
        secondary side has the RAM."""
        for side in self.sides:
            side.board.set_external_irq(True)
        self.ram.owner = "secondary"
        self._fed = self.secondary.board.t

    def _watch(self, kind: str, address: int, value: int, t: int) -> None:
        if address == 0x4017 and kind == "read":
            self._fed = t

    def reset(self) -> None:
        """The watchdog's reset (there is no button): both CPUs, both PPUs."""
        for side in self.sides:
            side.reset()
        self._out_of_reset()

    def insert_coin(self, side: int = 0, acceptor: int = 0) -> None:
        """A coin into side 0's (the primary's) or side 1's acceptor 0 or 1."""
        self.sides[side].insert_coin(acceptor)

    # -- running ---------------------------------------------------------

    def step(self) -> None:
        """One instruction on the side whose clock is behind."""
        first, second = self.primary, self.secondary
        if first.board.t <= second.board.t:
            first.step()
        else:
            second.step()

    def run_frames(self, frames: int) -> None:
        """Run until both PPUs have started ``frames`` more frames."""
        first, second = self.primary, self.secondary
        board_1, board_2 = first.board, second.board
        step_1, step_2 = first.cpu.step, second.cpu.step
        ppu_1, ppu_2 = board_1.ppu, board_2.ppu
        target_1, target_2 = ppu_1.frame + frames, ppu_2.frame + frames
        count_1 = count_2 = 0
        limit = self._watchdog_ticks
        while ppu_1.frame < target_1 or ppu_2.frame < target_2:
            if board_1.t <= board_2.t:
                step_1()
                count_1 += 1
            else:
                step_2()
                count_2 += 1
                if board_2.t - self._fed > limit:
                    self.watchdog_resets += 1
                    self.reset()
        first.instructions += count_1
        second.instructions += count_2

    @property
    def pictures(self) -> tuple[list[int], list[int]]:
        """The two screens, the primary side's first."""
        return self.primary.board.ppu.picture, self.secondary.board.ppu.picture
