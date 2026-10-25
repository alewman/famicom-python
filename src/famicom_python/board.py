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

**Open bus** (Open_bus_behavior.wiki): ``data_bus`` holds the last value on the
external data bus; every read except $4015's, every write and every DMA read
updates it, and an undriven read returns it. The 2A03 also has an internal data
bus, ``internal_bus``: every CPU read and write updates it, DMA reads do not,
and $4015's bit 5 comes from it (AccuracyCoin "Internal Data Bus").
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
        self.ppu.status = power.ppustatus & 0xE0
        self.ppu.dot = power.ppu_dot
        self.apu = APU(power.apu_put_first)
        self.apu.dmc.timer = power.dmc_timer
        self.apu.set_cpu_rate(timing.master_hz / timing.cpu_divider)
        self.analogue = AnalogueStage(
            self.apu.sample_rate, machine.audio_high_pass_hz, machine.audio_low_pass_hz
        )
        self.pads = [StandardController(), StandardController()]
        # Pads on the Famicom expansion port's D1 of $4016 and $4017: the
        # third and fourth players of the four-player adapters
        # (Expansion_port.wiki). None: nothing there.
        self.expansion_pads: list[StandardController | None] = [None, None]
        # The player-2 microphone's report, $4016 D2, on a machine that has one.
        self.microphone = False
        self._has_microphone = machine.microphone
        self._open_lines = (0xE0 | machine.pad_open_bus[0], 0xE0 | machine.pad_open_bus[1])
        self.t = 0  # master ticks at the end of the last CPU cycle
        self.data_bus = 0
        self.internal_bus = 0
        self._undriven = False  # the last DMA read found nothing on the bus
        # The pad whose /OE was low on the last cycle (-1: none).
        self._pad_oe = -1
        self._oe_per_cycle = machine.joypad_oe_per_cycle
        self._oam_dma_page: int | None = None
        self._strobe: bool | None = None  # a $4016 OUT0 write, until the next put
        # The CPU, told when a DMA stretched its read (6502-python's
        # ``dma_stalled``: SHA/SHX/SHY/TAS drop their AND after one). Set by System.
        self.cpu = None
        # The CPU's interrupt inputs (set by System to the CPU's methods).
        self.request_irq: Callable[[], None] = lambda: None
        self.clear_irq: Callable[[], None] = lambda: None
        self.request_nmi: Callable[[], None] = lambda: None
        self._irq = False
        self._nmi = False
        self._ppu_access = PPU_ACCESS_TICKS - self.cycle_ticks  # relative to the cycle's end
        self._snoop_reads = cartridge.snoops_cpu_reads
        self._counts_m2 = cartridge.counts_m2
        if machine.famicom_audio_through_cart and cartridge.expansion_audio:
            cartridge.audio_out = self.apu  # type: ignore[assignment]
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
        """Audio since the last call at the APU's sample rate, a cartridge's
        expansion sound mixed in cycle by cycle (Famicom pins 45/46), through
        the console's fitted analogue stage."""
        return self.analogue.process(self.apu.take_samples())

    # -- one CPU cycle ---------------------------------------------------

    def _begin_cycle(self, address: int, reading: bool) -> int:
        t = self.t + self.cycle_ticks
        self.t = t
        self.apu.clock()
        if self._strobe is not None and self.apu.put:
            # OUT0-2 update on the get -> put transition (Expansion_port.wiki
            # l.43; AccuracyCoin "Controller Strobing" 3 and 4).
            for pad in self.pads:
                pad.set_strobe(self._strobe)
            for pad in self.expansion_pads:
                if pad is not None:
                    pad.set_strobe(self._strobe)
            self._strobe = None
        oe = self._pad_oe
        if oe >= 0 and (self._oe_per_cycle or not reading or address != 0x4016 + oe):
            # /OE rose: the end of the pulse shifts the pad.
            self.pads[oe].clock()
            expansion = self.expansion_pads[oe]
            if expansion is not None:
                expansion.clock()
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
        stalled = False
        cpu = self.cpu
        if self.apu.dmc_abort:  # an aborted DMC DMA: its halt cycle only
            self.apu.dmc_abort = False
            if cpu is not None:
                cpu.note_stall()
            self._repeat_read(address)
            stalled = True
        if self._oam_dma_page is not None or self.apu.dmc_request:
            if cpu is not None and not stalled:
                cpu.note_stall()
            self._dma(address)
            stalled = True
        if cpu is not None and cpu.dma_stalled != stalled:
            cpu.dma_stalled = stalled
        t = self._begin_cycle(address, True)
        value = self._read(address, t)
        self.internal_bus = value
        self._end_cycle()
        if self.bus_observers:
            for observer in self.bus_observers:
                observer("read", address, value, t)
        return value

    def write_byte(self, address: int, value: int) -> None:
        self.apu.dmc_abort = False  # an aborted DMA meeting a write never happens
        t = self._begin_cycle(address, False)
        early = self.data_bus  # what the bus holds until the CPU drives it
        self.data_bus = self.internal_bus = value
        ppu = self.ppu
        if 0x2000 <= address < 0x4000:
            ppu.run_to(t + self._ppu_access)
            ppu.write_register(address & 7, value, early)
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
            value = ppu.end_read(address & 7, value)  # M2 falls
            if self._snoop_reads:
                self.cartridge.cpu_read(address, t)
            self.data_bus = value
            return value
        ppu.run_to(t)
        if address >= 0x4020:
            value = self.cartridge.cpu_read(address, t)
            if value is None:
                self._undriven = True
                return self.data_bus
            if value > 0xFF:  # some lines undriven: they keep the bus's charge
                value = (value & 0xFF) | (self.data_bus & (value >> 8))
            self.data_bus = value
            return value
        if self._snoop_reads:
            self.cartridge.cpu_read(address, t)
        if address < 0x2000:
            value = self.ram[address & 0x7FF]
        elif address == 0x4015:
            # Internal to the 2A03: bit 5 is the internal bus's, and the
            # external bus keeps its value (APU.wiki l.204-205; AccuracyCoin
            # "Internal Data Bus" 2 and 3).
            return self.apu.read_status() | (self.internal_bus & 0x20)
        elif address == 0x4016 or address == 0x4017:
            port = address - 0x4016
            self._pad_oe = port
            # D0-D4 from the port; D7-D5 open bus, and any line the machine
            # leaves undriven.
            value = (self.data_bus & self._open_lines[port]) | self._port_bits(port)
        else:
            return self.data_bus  # $4000-$4014, $4018-$401F: write-only or absent
        self.data_bus = value
        return value

    def _port_bits(self, port: int) -> int:
        """D0-D4 of $4016 (port 0) or $4017: the pad, the expansion port's D1, the microphone."""
        bits = self.pads[port].read()
        expansion = self.expansion_pads[port]
        if expansion is not None:
            bits |= expansion.read() << 1
        if not port and self.microphone and self._has_microphone:
            bits |= 4
        return bits

    def _write_io(self, address: int, value: int) -> None:
        if address == 0x4014:
            self._oam_dma_page = value
        elif address == 0x4016:
            # OUT0 is both pads' strobe; it reaches them at the next put.
            self._strobe = bool(value & 1)
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
                t = self._begin_cycle(_decoded(dmc_address, address), True)
                value = self._dma_read(dmc_address, address, t)
                apu.dmc_fill(value)
                self._end_cycle()
                self._halted_cycle_done()
                dmc_age = None
            elif get and oam_value is None and oam_next < 256:
                source = page << 8 | oam_next  # type: ignore[operator]
                t = self._begin_cycle(_decoded(source, address), True)
                oam_value = self._dma_read(source, address, t)
                self._end_cycle()
                self._halted_cycle_done()
                oam_next += 1
            elif not get and oam_value is not None:
                t = self._begin_cycle(0x2004, False)
                self.data_bus = oam_value
                self.ppu.run_to(t + self._ppu_access)
                self.ppu.oam_dma_write(oam_value)
                self.ppu.run_to(t)
                self.cartridge.cpu_write(0x2004, oam_value, t)
                self._end_cycle()
                self._halted_cycle_done()
                oam_value = None
            else:
                self._repeat_read(address)

    def _dma_read(self, address: int, halted: int, t: int) -> int:
        """A DMA unit's read of ``address`` while the CPU is halted reading ``halted``.

        The 2A03 decodes its own registers from bits 4-0 of the bus it drives
        and bits 15-5 of the 6502 core's address (DMA.wiki "Register
        conflicts"; Breaks APU/core.md). With the core halted on $4000-$401F,
        any DMA read also selects register $4000 | (address & $1F). $4015
        drives every bit but 5, which comes from the bus. $4016/$4017 clock a
        pad and drive its low bits onto the external bus: with nothing else
        there the DMA reads them under open bus's bits 7-5; with a device at
        ``address`` the DMA gets the device's byte while the external bus is
        left with the device's bits 7-5 and the pad's below (AccuracyCoin
        "APU Register Activation" 5-7 and "DMC DMA Bus Conflicts" 2, whose
        expected tables pin each case). With the core elsewhere, a DMA read of
        $4000-$401F selects nothing and sees open bus.
        """
        self._undriven = 0x4000 <= address < 0x4020
        external = self.data_bus if self._undriven else self._read(address, t)
        if halted & 0xFFE0 != 0x4000:
            if 0x4000 <= address < 0x4020:
                self.ppu.run_to(t)
            return external
        register = 0x4000 | (address & 0x1F)
        if register == 0x4015:
            return self.apu.read_status() | (external & 0x20)
        if register == 0x4016 or register == 0x4017:
            port = register - 0x4016
            self._pad_oe = port
            mixed = (external & self._open_lines[port]) | self._port_bits(port)
            self.data_bus = mixed
            return mixed if self._undriven else external
        return external

    def _repeat_read(self, address: int) -> None:
        t = self._begin_cycle(address, True)
        self.internal_bus = self._read(address, t)
        self._end_cycle()
        self._halted_cycle_done()

    def _halted_cycle_done(self) -> None:
        """A cycle of a stall ended: the halted CPU kept sampling /IRQ and /NMI,
        so it is told the requests at each boundary of the stall (6502-python's
        ``note_stall``; perfect6502 with RDY low; C30)."""
        if self.cpu is not None:
            self.cpu.note_stall()


def _decoded(address: int, halted: int) -> int:
    """The address the 2A03's register decode sees during a DMA access
    (``Board._dma_read``): the core's bits 15-5 with the DMA's bits 4-0 when
    the core is halted on $4000-$401F."""
    if halted & 0xFFE0 == 0x4000:
        return 0x4000 | (address & 0x1F)
    return address
