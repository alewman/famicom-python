"""The 2A03's sound unit: frame counter, length counters, status and IRQ.

**Milestone 1 scope.** The APU here keeps time and answers $4015: the frame
counter in both modes with its IRQ (APU_Frame_Counter.wiki, docs/timing.md "The
APU"), and the length counters of the pulse, triangle and noise channels with
their halt flags and the $4015 enables (APU_Length_Counter.wiki). blargg's
timing tests synchronise to the length counters, so those are exact as
documented. Not yet: the channels' timers, envelopes, sweeps and sequencers,
the DMC (its $4015 bit reads 0 and it raises no IRQ), the mixer, and the
documented races (the $4015 clear at the next put-get transition, length loads
on a length clock, the 3-or-4-cycle $4017 delay's exact phase). Milestone 3
adds them against ``apu_test`` and ``blargg_apu_2005``.

The interface is pin-shaped so the APU can later leave as its own core: the
board calls :meth:`clock` once per CPU cycle, :meth:`write` and
:meth:`read_status` for the registers, and reads :attr:`irq`.
"""

from __future__ import annotations

# APU_Length_Counter.wiki.
LENGTHS = (
    10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
    12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30,
)  # fmt: skip

# Frame counter events, in CPU cycles after it resets (APU_Frame_Counter.wiki;
# docs/timing.md): (cycle, quarter, half, irq, wrap).
QUARTER, HALF, IRQ, WRAP = 1, 2, 4, 8
STEPS_4 = {
    7457: QUARTER,
    14913: QUARTER | HALF,
    22371: QUARTER,
    29828: IRQ,
    29829: QUARTER | HALF | IRQ,
    29830: IRQ | WRAP,
}
STEPS_5 = {
    7457: QUARTER,
    14913: QUARTER | HALF,
    22371: QUARTER,
    37281: QUARTER | HALF,
    37282: WRAP,
}

# The halt bit of each channel's first register: pulse 1, pulse 2, triangle, noise.
HALT_BIT = {0x4000: 0x20, 0x4004: 0x20, 0x4008: 0x80, 0x400C: 0x20}
LENGTH_REGISTER = {0x4003: 0, 0x4007: 1, 0x400B: 2, 0x400F: 3}


class APU:
    def __init__(self, put_first: bool = False) -> None:
        # Whether the current CPU cycle is an APU put; clock() flips it first.
        self.put = not put_first
        self.lengths = [0, 0, 0, 0]
        self.halted = [False] * 4
        self.enabled = [False] * 4
        self.frame_irq = False
        self.dmc_irq = False
        self.irq = False
        self.steps = STEPS_4
        self.mode5 = False
        self.inhibit = False
        self.frame_cycle = 0
        self.pending_frame_write: int | None = None
        self.pending_delay = 0
        self.last_frame_write = 0x00

    def power(self) -> None:
        """Power: $4015 = 0; $4017 as if $00 were written just before the CPU starts.

        blargg ``apu_reset/4017_timing`` puts that write 9-12 CPU cycles before
        the first instruction; the reset sequence is 7, so the counter starts at
        the CPU's first cycle, 3-4 cycles after the write.
        """
        self.write(0x4015, 0)
        self._apply_frame_write(0x00)

    def reset(self) -> None:
        """Reset: $4015 = 0 and $4017 rewritten with its last value (blargg ``apu_reset``)."""
        self.write(0x4015, 0)
        self.write(0x4017, self.last_frame_write)

    # -- the clock -------------------------------------------------------

    def clock(self) -> None:
        """One CPU cycle."""
        self.put = not self.put
        if self.pending_frame_write is not None:
            self.pending_delay -= 1
            if self.pending_delay == 0:
                self._apply_frame_write(self.pending_frame_write)
                self.pending_frame_write = None
                return
        cycle = self.frame_cycle + 1
        self.frame_cycle = cycle
        event = self.steps.get(cycle)
        if event:
            if event & IRQ and not self.inhibit:
                self.frame_irq = True
                self.irq = True
            if event & HALF:
                self._half_frame()
            if event & WRAP:
                self.frame_cycle = 0

    def _half_frame(self) -> None:
        lengths, halted = self.lengths, self.halted
        for channel in range(4):
            if lengths[channel] and not halted[channel]:
                lengths[channel] -= 1

    def _apply_frame_write(self, value: int) -> None:
        self.mode5 = bool(value & 0x80)
        self.steps = STEPS_5 if self.mode5 else STEPS_4
        self.frame_cycle = 0
        if self.mode5:
            self._half_frame()  # bit 7 clocks quarter and half at once

    # -- registers -------------------------------------------------------

    def write(self, address: int, value: int) -> None:
        if address in HALT_BIT:
            self.halted[(address - 0x4000) >> 2] = bool(value & HALT_BIT[address])
        elif address in LENGTH_REGISTER:
            channel = LENGTH_REGISTER[address]
            if self.enabled[channel]:
                self.lengths[channel] = LENGTHS[value >> 3]
        elif address == 0x4010:
            if not value & 0x80:
                self.dmc_irq = False
        elif address == 0x4015:
            for channel in range(4):
                self.enabled[channel] = bool(value & (1 << channel))
                if not self.enabled[channel]:
                    self.lengths[channel] = 0
            self.dmc_irq = False
        elif address == 0x4017:
            self.last_frame_write = value
            self.inhibit = bool(value & 0x40)
            if self.inhibit:
                self.frame_irq = False
            # The new mode takes effect 3 CPU cycles after the write cycle if it
            # falls during an APU cycle, 4 if between (APU_Frame_Counter.wiki);
            # which half counts as "during" is settled in milestone 3.
            self.pending_frame_write = value
            self.pending_delay = 3 if not self.put else 4
        self.irq = self.frame_irq or self.dmc_irq

    def read_status(self) -> int:
        """$4015: DMC IRQ, frame IRQ, DMC active, length > 0; clears the frame IRQ flag."""
        lengths = self.lengths
        value = (
            (self.dmc_irq << 7)
            | (self.frame_irq << 6)
            | (lengths[3] > 0) << 3
            | (lengths[2] > 0) << 2
            | (lengths[1] > 0) << 1
            | (lengths[0] > 0)
        )
        self.frame_irq = False
        self.irq = self.dmc_irq
        return value
