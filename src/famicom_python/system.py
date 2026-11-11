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

from . import peripherals
from .board import Board
from .cartridge import BoardInfo, Loaded, load
from .cartridge.connector import Cartridge
from .joypad import START
from .machine import MACHINES, NES_001, Machine, vs_machine
from .playchoice import PlayChoiceGun, is_playchoice
from .vs import VS_DEVICES, VS_ZAPPER, VsStick, VsZapper


class System:
    """Machine + cartridge, powered on."""

    def __init__(self, cartridge: Cartridge, machine: Machine = NES_001) -> None:
        self.machine = machine
        self.cartridge = cartridge
        self.board = board = Board(machine, cartridge)
        self.cpu = cpu = RP2A03(board.read_byte, board.write_byte)
        if machine.dma_halts_on_opcode:
            # Each step begins with an opcode fetch or an interrupt entry's
            # first read: mark it for the board (Machine.dma_halts_on_opcode).
            step = cpu.step

            def marked_step() -> int:
                board.opcode_read = True
                return step()

            cpu.step = marked_step  # type: ignore[method-assign]
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

    @staticmethod
    def machine_for(rom: str | Path | bytes) -> Machine:
        """The console a cartridge asks for: a Vs. UniSystem with the game's PPU
        if the NES 2.0 header or nes20db says console type 1 (and which PPU:
        machine.VS_PPUS), a PlayChoice-10's game board for type 2; else by
        their timing (1 PAL, 3 Dendy), else a
        Famicom. Neither source tells a Famicom
        cartridge from an NES one, and the Famicom runs both: a sound chip or a
        disk reaches the mix only through its cartridge pins 45 and 46, and
        games that write the PPU too early hang on the NES-001
        (Machine.ppu_reset_at_power)."""
        loaded = load(rom)
        if loaded.image.board.console == 1:
            return vs_machine(loaded.image.board.vs_ppu)
        if is_playchoice(loaded.image):
            return MACHINES[
                "playchoice"
            ]  # the game board alone: supervisor.PlayChoice adds the Z80
        timing = loaded.image.board.timing
        if timing == 1:
            return MACHINES["pal"]
        if timing == 3:
            return MACHINES["dendy"]
        if loaded.image.board.expansion in peripherals.NES_ONLY:
            return MACHINES["nes"]  # a Four Score, Power Pad or NES Vaus needs NES ports
        return MACHINES["famicom"]

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
        if system.board.vs is not None and loaded.image.board.vs_hardware in (4, 6):
            # Vs. Ice Climber (Japan) and Vs. Raid on Bungeling Bay: the fourth
            # bit of both sticks' reports is wired on (vs.VsStick).
            for pad in system.board.pads:
                if isinstance(pad, VsStick):
                    pad.jumper = START
        return system

    def plug(self, device: int | None = None) -> object | None:
        """Put in the devices of NES 2.0 expansion number ``device`` (default: the
        cartridge's, from its header or nes20db); the one to drive, as
        :func:`.peripherals.plug` returns it."""
        if device is None:
            device = self.loaded.image.board.expansion if self.loaded is not None else 0
        if self.board.vs is not None:
            # A Vs. cabinet's controls are its own: the two sticks are on the
            # mainboard already (vs.panel says whose is whose), and its light
            # gun reports through $4016's shift register.
            if device == VS_ZAPPER:
                self.board.pads[0] = VsZapper(self.board.ppu, peripherals.palette_of(self.board))
                return self.board.pads[0]
            return None
        if device in VS_DEVICES:
            return None  # a Vs. game on a home console: standard pads
        if self.machine.playchoice:
            # The cabinet's panel is its own; a gun game's gun shares $4017
            # with player 2's shift register (playchoice.PlayChoiceGun).
            if isinstance(self.board.pads[1], PlayChoiceGun):
                return self.board.pads[1]  # plugged already
            if device == peripherals.ZAPPER:
                self.board.pads[1] = PlayChoiceGun(
                    self.board.ppu, peripherals.palette_of(self.board), self.board.pads[1]
                )
                return self.board.pads[1]
            return None
        return peripherals.plug(self.board, device, self.machine.famicom_expansion_port)

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

    def insert_coin(self, acceptor: int = 0) -> None:
        """Drop a coin into a Vs. System's coin acceptor 0 or 1 (vs.VsMainboard)."""
        if self.board.vs is None:
            raise ValueError(f"the {self.machine.name} takes no coins")
        self.board.vs.insert_coin(acceptor)

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
