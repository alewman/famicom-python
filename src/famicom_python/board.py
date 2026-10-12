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
on the bus, until the DMA is done. So when OAM DMA or a DMC fetch is due the
board runs it inside the next read: the halt, dummy and alignment cycles as
repeats of the CPU's read, the DMA's own gets and puts, then the CPU's read.

**Open bus** (Open_bus_behavior.wiki): one ``data_bus`` byte holds the last value
on the CPU data bus; every read except $4015's, every write and every DMA read
updates it, and an undriven read returns it.
"""

from __future__ import annotations

from collections.abc import Callable

from .apu import APU, AnalogueStage
from .cartridge.connector import Cartridge
from .joypad import StandardController
from .machine import Machine
from .ppu import PPU

# When the PPU sees a register read or write: two dots (8 master ticks) into
# its CPU cycle, inside M2's high phase. The cycle's other effects (the
# cartridge, RAM, the APU) and the CPU's sampling of /NMI and /IRQ fall at its
# end, M2's fall. Of the three possible dot positions for reads and for writes,
# only this pair passes ppu_vbl_nmi and vbl_nmi_timing (docs/validation.md,
# milestone 2): hardware-corrected, in blargg's preferred synchronization.
PPU_ACCESS_TICKS = 8


class Board:
    def __init__(self, machine: Machine, cartridge: Cartridge) -> None:
        self.machine = machine
        self.cartridge = cartridge
        power = machine.power_on
        timing = machine.timing
        self.cycle_ticks = timing.cpu_divider
        self.ram = bytearray([power.ram_fill]) * 0x800
        self.ppu = PPU(timing, cartridge, machine.ppu_latch_decay_seconds)
        self.ppu.palette[:] = power.palette
        self.apu = APU(power.apu_put_first)
        self.apu.set_cpu_rate(timing.master_hz / timing.cpu_divider)
        self.analogue = AnalogueStage(
            self.apu.sample_rate, machine.audio_high_pass_hz, machine.audio_low_pass_hz
        )
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
        self._ppu_access = PPU_ACCESS_TICKS - self.cycle_ticks  # relative to the cycle's end
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

    def set_sample_rate(self, rate: int) -> None:
        """The host rate for :meth:`take_samples` (44,100 Hz by default)."""
        self.apu.sample_rate = rate
        machine = self.machine
        self.analogue = AnalogueStage(rate, machine.audio_high_pass_hz, machine.audio_low_pass_hz)

    def take_samples(self) -> list[float]:
        """Audio since the last call at the APU's sample rate, through the
        cartridge (Famicom pins 45/46) and the console's fitted analogue stage.

        The cartridge sees each sample with the current time only: expansion
        sound that must be mixed cycle by cycle arrives with milestone 8.
        """
        samples = self.apu.take_samples()
        if self.machine.famicom_audio_through_cart:
            audio, t = self.cartridge.audio, self.t
            samples = [audio(sample, t) for sample in samples]
        return self.analogue.process(samples)

    # -- one CPU cycle ---------------------------------------------------

    def _begin_cycle(self, address: int, reading: bool) -> int:
        t = self.t + self.cycle_ticks
        self.t = t
        self.apu.clock()
        oe = self._pad_oe
        if oe >= 0 and (self._oe_per_cycle or not reading or address != 0x4016 + oe):
            # /OE rose: the end of the pulse shifts the pad.
            self.pads[oe].clock()
            self._pad_oe = -1
        return t

    def _end_cycle(self) -> None:
        """M2 falls: the cartridge's cycle count, then /IRQ and /NMI as the CPU samples them."""
        if self._counts_m2:
            self.cartridge.m2(self.t)
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
        if self._oam_dma_page is not None or self.apu.dmc_request:
            self._dma(address)
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
        ppu = self.ppu
        if 0x2000 <= address < 0x4000:
            ppu.run_to(t + self._ppu_access)
            ppu.write_register(address & 7, value)
        ppu.run_to(t)
        if address < 0x2000:
            self.ram[address & 0x7FF] = value
        elif 0x4000 <= address < 0x4020:
            self._write_io(address, value)
        self.cartridge.cpu_write(address, value, t)
        self._end_cycle()
        if self.bus_observers:
            for observer in self.bus_observers:
                observer("write", address, value, t)

    def _read(self, address: int, t: int) -> int:
        """The access of one read cycle: decode, drive, update open bus.

        Runs the PPU to the cycle's end ``t``, stopping for a PPU register
        read at the point inside the cycle where the PPU sees it.
        """
        ppu = self.ppu
        if 0x2000 <= address < 0x4000:
            ppu.run_to(t + self._ppu_access)
            value = ppu.read_register(address & 7)
            ppu.run_to(t)
            if self._snoop_reads:
                self.cartridge.cpu_read(address, t)
            self.data_bus = value
            return value
        ppu.run_to(t)
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

    def _dma(self, address: int) -> None:
        """OAM and DMC DMA, run inside the CPU's stalled read of ``address``.

        DMA.wiki "Behavior" and "DMC DMA during OAM DMA", cycle by cycle. The
        first cycle halts the CPU, which repeats its read of ``address`` on
        every cycle in which no DMA reads or writes. Then, on each cycle:

        - a DMC fetch reads on a get, after its halt cycle and one dummy cycle;
          a fetch requested while the CPU is already halted (during OAM DMA)
          counts the cycle it appears in as its halt cycle;
        - OAM DMA reads its next byte on a get the DMC does not take, and
          writes it to $2004 on the following put;
        - any other cycle is an idle repeat of the CPU's read: the "alignment"
          cycles.

        This reproduces every example in DMA.wiki: OAM 513/514 cycles, DMC load
        3 and reload 4, DMC during OAM 2 (1 or 3 at its end).
        """
        apu = self.apu
        page = self._oam_dma_page
        self._oam_dma_page = None
        oam_next = 0 if page is not None else 256  # the next OAM byte to read
        oam_value: int | None = None  # read on a get, waiting for its put
        # The DMC fetch: None idle, else cycles since its halt cycle.
        dmc_age: int | None = 0 if apu.dmc_request else None
        self._repeat_read(address)  # the halt cycle
        while True:
            if dmc_age is not None:
                dmc_age += 1
            elif apu.dmc_request:
                dmc_age = 0  # halted already: this cycle is the DMC's halt cycle
            if oam_next == 256 and oam_value is None and dmc_age is None:
                return
            get = apu.put  # the next cycle is a get if this one was a put
            if get and dmc_age is not None and dmc_age >= 2:
                dmc_address = apu.dmc_address
                t = self._begin_cycle(dmc_address, True)
                value = self._read(dmc_address, t)
                apu.dmc_fill(value)
                self._end_cycle()
                dmc_age = None
            elif get and oam_value is None and oam_next < 256:
                source = page << 8 | oam_next  # type: ignore[operator]
                t = self._begin_cycle(source, True)
                oam_value = self._read(source, t)
                self._end_cycle()
                oam_next += 1
            elif not get and oam_value is not None:
                t = self._begin_cycle(0x2004, False)
                self.data_bus = oam_value
                self.ppu.run_to(t + self._ppu_access)
                self.ppu.oam_dma_write(oam_value)
                self.ppu.run_to(t)
                self.cartridge.cpu_write(0x2004, oam_value, t)
                self._end_cycle()
                oam_value = None
            else:
                self._repeat_read(address)

    def _repeat_read(self, address: int) -> None:
        t = self._begin_cycle(address, True)
        self._read(address, t)
        self._end_cycle()
