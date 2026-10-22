"""A whole console: 6502-python's RP2A03 on a :class:`~famicom_python.board.Board`.

The CPU is embedded through 6502-python's callables contract: its two bus
callables are the board's, and every device advances inside them
(``board.py``). The board raises IRQ and NMI from inside those callbacks, and
the core polls them at the end of each instruction's second-to-last cycle, as
the chip does (6502-python PRs #3 and #4; docs/timing.md "Interrupts").
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sixfiveohtwo import RP2A03

from .board import Board
from .cartridge import BoardInfo, Loaded, load
from .cartridge.connector import Cartridge
from .machine import NES_001, Machine


class System:
    """Machine + cartridge, powered on."""

    def __init__(self, cartridge: Cartridge, machine: Machine = NES_001) -> None:
        self.machine = machine
        self.cartridge = cartridge
        self.board = board = Board(machine, cartridge)
        self.cpu = cpu = RP2A03(board.read_byte, board.write_byte)
        board.request_irq = cpu.request_maskable_interrupt
        board.clear_irq = cpu.clear_maskable_interrupt
        board.request_nmi = cpu.request_non_maskable_interrupt
        board.cpu = cpu
        self.instructions = 0
        self.loaded: Loaded | None = None  # how from_rom identified the cartridge
        # ANE and LXA's constant varies from chip to chip (6502-python
        # docs/undocumented-behavior.md); the machine says this console's.
        cpu.ane_constant = machine.ane_constant
        cpu.lxa_constant = machine.lxa_constant
        self.power()

    @classmethod
    def from_rom(
        cls,
        rom: str | Path | bytes,
        machine: Machine = NES_001,
        *,
        override: BoardInfo | None = None,
    ) -> System:
        """Load ``rom`` (identified as :func:`.cartridge.load` does, or as ``override``)."""
        loaded = load(rom, cpu_cycle_ticks=machine.timing.cpu_divider, override=override)
        system = cls(loaded.cartridge, machine)
        system.loaded = loaded
        return system

    # -- power and reset -------------------------------------------------

    def power(self) -> None:
        """Switch on: registers from the machine's power-on parameters, then the reset sequence.

        A, X, Y = the parameters (0 by default); S = 0 and I set, so the reset
        sequence leaves S = $FD and P = $24 (CPU_power_up_state.wiki).
        """
        power = self.machine.power_on
        cpu = self.cpu
        cpu.a, cpu.x, cpu.y, cpu.s = power.a, power.x, power.y, 0
        self.board.power()
        cpu.request_reset()

    def reset(self) -> None:
        """The reset button."""
        self.board.reset()
        self.cpu.request_reset()

    def take_samples(self) -> list[float]:
        """Audio since the last call (Board.take_samples)."""
        return self.board.take_samples()

    # -- running ---------------------------------------------------------

    @property
    def cycles(self) -> int:
        return self.board.cycles

    def step(self) -> int:
        """One instruction, interrupt entry or reset sequence; returns CPU cycles, DMA included."""
        before = self.board.t
        self.cpu.step()
        self.instructions += 1
        return (self.board.t - before) // self.board.cycle_ticks

    def run_cycles(self, cycles: int) -> None:
        """Run whole instructions until at least ``cycles`` more CPU cycles have passed."""
        end = self.board.t + cycles * self.board.cycle_ticks
        board, step = self.board, self.cpu.step
        count = 0
        while board.t < end:
            step()
            count += 1
        self.instructions += count

    def run_frames(self, frames: int) -> None:
        """Run until the PPU has started ``frames`` more frames."""
        ppu, step = self.board.ppu, self.cpu.step
        target = ppu.frame + frames
        count = 0
        while ppu.frame < target:
            step()
            count += 1
        self.instructions += count

    def run_until(
        self, done: Callable[[], bool], *, max_cycles: int, check_every: int = 1000
    ) -> bool:
        """Run until ``done()`` (checked every ``check_every`` instructions); False on timeout."""
        board, step = self.board, self.cpu.step
        end = board.t + max_cycles * board.cycle_ticks
        while board.t < end:
            for _ in range(check_every):
                step()
            self.instructions += check_every
            if done():
                return True
        return False
