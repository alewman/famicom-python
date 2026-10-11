"""The console board: the CPU bus, open bus, the ports, DMA, and the one clock.

**One timeline in master ticks** (docs/timing.md "The units and the one
timeline"). 6502-python calls :meth:`Board.read_byte` or :meth:`Board.write_byte`
exactly once per CPU cycle, in chip order, dummy accesses included. So each call
*is* a CPU cycle: it moves the clock on by ``cpu_divider`` ticks, runs the PPU's
dots up to the access, clocks the APU once, performs the access, and updates
the CPU's interrupt inputs as they stand at the cycle's end. ``step()``'s
returned count is never added on top; :attr:`Board.cycles` is the truth.

**DMA inside ``read_byte``** (docs/timing.md "The design"): a DMA halts the
2A03's CPU only on a read cycle, and the halted CPU repeats that read, visibly
on the bus, until the DMA is done. So when OAM DMA is due the board runs it
inside the next read: the halt cycle and any alignment cycle as repeats of the
CPU's read, the 256 get/put pairs, then the CPU's own read. The DMC DMA joins it
in milestone 3.

**Open bus** (Open_bus_behavior.wiki): one ``data_bus`` byte holds the last value
on the CPU data bus; every read except $4015's, every write and every DMA read
updates it, and an undriven read returns it.
"""

from __future__ import annotations

from collections.abc import Callable

from .apu import APU
from .cartridge.connector import Cartridge
from .joypad import StandardController
from .machine import Machine
from .ppu import PPU


class Board:
    def __init__(self, machine: Machine, cartridge: Cartridge) -> None:
        self.machine = machine
        self.cartridge = cartridge
        power = machine.power_on
        timing = machine.timing
        self.cycle_ticks = timing.cpu_divider
        self.ram = bytearray([power.ram_fill]) * 0x800
        self.ppu = PPU(timing, cartridge, power.alignment)
        self.apu = APU(power.apu_put_first)
        self.pads = [StandardController(), StandardController()]
        self.t = 0  # master ticks at the end of the last CPU cycle
        self.data_bus = 0
        # The pad whose /OE was low on the last cycle (-1: none).
        self._pad_oe = -1
        self._oe_per_cycle = machine.joypad_oe_per_cycle
        self._oam_dma_page: int | None = None
        # The CPU's interrupt inputs (set by System to the CPU's methods).
        self.request_irq: Callable[[], None] = lambda: None
        self.clear_irq: Callable[[], None] = lambda: None
        self.request_nmi: Callable[[], None] = lambda: None
        self._irq = False
        self._nmi = False
        self._snoop_reads = cartridge.snoops_cpu_reads
        self._counts_m2 = cartridge.counts_m2
        # Observers of every CPU-bus cycle, (kind, address, value, t); the trace
        # and the debugger attach here. Empty costs one truth test per cycle.
        self.bus_observers: list[Callable[[str, int, int, int], None]] = []

    @property
    def cycles(self) -> int:
        """CPU cycles since power, DMA cycles included."""
        return self.t // self.cycle_ticks

    def power(self) -> None:
        self.apu.power()

    def reset(self) -> None:
        """The reset button: the APU always, the PPU only where the console wires it."""
        self.apu.reset()
        if self.machine.reset_resets_ppu:
            self.ppu.reset()

    # -- one CPU cycle ---------------------------------------------------

    def _begin_cycle(self, address: int, reading: bool) -> int:
        t = self.t + self.cycle_ticks
        self.t = t
        self.ppu.run_to(t)
        self.apu.clock()
        oe = self._pad_oe
        if oe >= 0 and (self._oe_per_cycle or not reading or address != 0x4016 + oe):
            # /OE rose: the end of the pulse shifts the pad.
            self.pads[oe].clock()
            self._pad_oe = -1
        if self._counts_m2:
            self.cartridge.m2(t)
        return t

    def _end_cycle(self) -> None:
        irq = self.apu.irq or self.cartridge.irq
        if irq != self._irq:
            self._irq = irq
            if irq:
                self.request_irq()
            else:
                self.clear_irq()
        nmi = self.ppu.nmi
        if nmi != self._nmi:
            self._nmi = nmi
            if nmi:  # /NMI fell: the CPU's edge detector latches it
                self.request_nmi()

    # -- the CPU's bus ---------------------------------------------------

    def read_byte(self, address: int) -> int:
        if self._oam_dma_page is not None:
            self._oam_dma(address)
        t = self._begin_cycle(address, True)
        value = self._read(address, t)
        self._end_cycle()
        if self.bus_observers:
            for observer in self.bus_observers:
                observer("read", address, value, t)
        return value

    def write_byte(self, address: int, value: int) -> None:
        t = self._begin_cycle(address, False)
        self.data_bus = value
        if address < 0x2000:
            self.ram[address & 0x7FF] = value
        elif address < 0x4000:
            self.ppu.write_register(address & 7, value)
        elif address < 0x4020:
            self._write_io(address, value)
        self.cartridge.cpu_write(address, value, t)
        self._end_cycle()
        if self.bus_observers:
            for observer in self.bus_observers:
                observer("write", address, value, t)

    def _read(self, address: int, t: int) -> int:
        """The access of one read cycle: decode, drive, update open bus."""
        if address >= 0x4020:
            value = self.cartridge.cpu_read(address, t)
            if value is None:
                return self.data_bus
            self.data_bus = value
            return value
        if self._snoop_reads:
            self.cartridge.cpu_read(address, t)
        if address < 0x2000:
            value = self.ram[address & 0x7FF]
        elif address < 0x4000:
            value = self.ppu.read_register(address & 7)
        elif address == 0x4015:
            # Internal to the 2A03: bit 5 is open bus, and open bus keeps its
            # value (APU.wiki l.204-205).
            return self.apu.read_status() | (self.data_bus & 0x20)
        elif address == 0x4016 or address == 0x4017:
            port = address - 0x4016
            self._pad_oe = port
            # D0-D4 from the port (nothing on D1-D4 here); D7-D5 open bus.
            value = (self.data_bus & 0xE0) | self.pads[port].read()
        else:
            return self.data_bus  # $4000-$4014, $4018-$401F: write-only or absent
        self.data_bus = value
        return value

    def _write_io(self, address: int, value: int) -> None:
        if address == 0x4014:
            self._oam_dma_page = value
        elif address == 0x4016:
            # OUT0 is both pads' strobe. "OUT2-0 ... are updated every APU cycle"
            # (Expansion_port.wiki l.43) is UNVERIFIED by a test: applied at once.
            strobe = bool(value & 1)
            for pad in self.pads:
                pad.set_strobe(strobe)
        else:
            self.apu.write(address, value)

    # -- DMA -------------------------------------------------------------

    def _oam_dma(self, address: int) -> None:
        """OAM DMA, run inside the CPU's stalled read of ``address`` (DMA.wiki "OAM DMA").

        The halt cycle repeats the CPU's read; if the next cycle would be a put,
        one alignment cycle repeats it again, so that each DMA read lands on a
        get and each write to $2004 on a put: 513 or 514 cycles before the
        CPU's own read completes.
        """
        page = self._oam_dma_page
        assert page is not None
        self._oam_dma_page = None
        self._repeat_read(address)  # halt
        if not self.apu.put:  # the next cycle is a put: align
            self._repeat_read(address)
        base = page << 8
        for offset in range(256):
            t = self._begin_cycle(base | offset, True)  # get: DMA reads
            value = self._read(base | offset, t)
            self._end_cycle()
            t = self._begin_cycle(0x2004, False)  # put: DMA writes $2004
            self.data_bus = value
            self.ppu.oam_dma_write(value)
            self.cartridge.cpu_write(0x2004, value, t)
            self._end_cycle()

    def _repeat_read(self, address: int) -> None:
        t = self._begin_cycle(address, True)
        self._read(address, t)
        self._end_cycle()
