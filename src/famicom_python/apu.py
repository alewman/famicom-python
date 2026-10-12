"""The 2A03's sound unit: five channels, the frame counter, $4015, the DMC's DMA request.

Sources, in the order this file follows them: the nesdev wiki's APU pages
(APU.wiki, APU_Frame_Counter, APU_Length_Counter, APU_Envelope, APU_Sweep,
APU_Pulse, APU_Triangle, APU_Noise, APU_DMC, APU_Mixer; specification tier),
corrected where blargg's hardware-captured tests say otherwise
(``blargg_apu_2005.07.30/readme.txt``, ``apu_test``, ``apu_reset``), and the
DMA timing of DMA.wiki (docs/timing.md "DMA").

**Clocks.** The board calls :meth:`clock` once per CPU cycle, before the
cycle's access. Each CPU cycle is half of an APU cycle: a *get* (the first
half, apu_clk1) or a *put* (the second); :attr:`put` says which the current
cycle is. The pulse, noise and DMC timers count APU cycles and are clocked on
gets; the triangle's timer counts CPU cycles; the frame counter counts CPU
cycles from its last reset. Which half clocks the pulse and noise timers no
test here can see (only their phase moves); the DMC's half is fixed by its DMA
timing, which tests do see.

**DMA.** The DMC does not read memory itself. When its sample buffer needs a
byte it raises :attr:`dmc_request`; the board halts the CPU (on the next read
cycle), performs the read and hands the byte to :meth:`dmc_fill`
(``board.py`` "DMA").

**Output.** Each CPU cycle adds the mixer's level (blargg's formula,
APU_Mixer.wiki) to an accumulator; every host-rate sample period the board's
:meth:`take_samples` gets their box-filtered average. The analogue stage after
it (``AnalogueStage``) is labelled "fitted": first-order filters at the corner
frequencies of APU_Mixer.wiki, not a measured response.

The interface is pin-shaped so the APU can later leave as its own core:
:meth:`clock`, :meth:`write`, :meth:`read_status`, :attr:`irq`,
:attr:`dmc_request` / :meth:`dmc_fill`, :meth:`take_samples`.
"""

from __future__ import annotations

import math

# APU_Length_Counter.wiki.
LENGTHS = (
    10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
    12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30,
)  # fmt: skip

# APU_Pulse.wiki "Duty Cycle Sequences": the lookup tables, read at index
# 0, 7, 6, ... 1 because the sequencer counts down from 0.
DUTY = (
    (0, 0, 0, 0, 0, 0, 0, 1),
    (0, 0, 0, 0, 0, 0, 1, 1),
    (0, 0, 0, 0, 1, 1, 1, 1),
    (1, 1, 1, 1, 1, 1, 0, 0),
)

# APU_Triangle.wiki: the 32-step sequence.
TRIANGLE = tuple(range(15, -1, -1)) + tuple(range(16))

# APU_Noise.wiki and APU_DMC.wiki (NTSC): periods in CPU cycles. All even: both
# timers count APU cycles, half as many.
NOISE_PERIODS = (4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068)
DMC_RATES = (428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54)

# Frame counter events, in CPU cycles after it resets (APU_Frame_Counter.wiki;
# docs/timing.md "Frame counter").
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


class Envelope:
    """APU_Envelope.wiki: a divider and a decay level, clocked on quarter frames."""

    def __init__(self) -> None:
        self.start = False
        self.loop = False  # the length counter's halt bit doubles as the loop flag
        self.constant = False
        self.period = 0  # also the constant volume
        self.divider = 0
        self.decay = 0

    def set(self, value: int) -> None:
        """Bits 5-0 of $4000/$4004/$400C."""
        self.loop = bool(value & 0x20)
        self.constant = bool(value & 0x10)
        self.period = value & 0x0F

    def quarter(self) -> None:
        if self.start:
            self.start = False
            self.decay = 15
            self.divider = self.period
        elif self.divider:
            self.divider -= 1
        else:
            self.divider = self.period
            if self.decay:
                self.decay -= 1
            elif self.loop:
                self.decay = 15

    @property
    def volume(self) -> int:
        return self.period if self.constant else self.decay


class LengthCounter:
    """APU_Length_Counter.wiki, with blargg's two races (``10.len_halt_timing``,
    ``11.len_reload_timing``): a halt write takes effect after this cycle's
    length clock, and a load in the cycle of a length clock that decremented
    the counter is ignored."""

    def __init__(self) -> None:
        self.value = 0
        self.halt = False
        self.enabled = False
        self.new_halt = False
        self.load = 0  # a length to load at the end of this cycle; 0: none
        self.before = 0  # the counter when the load was written

    def write_halt(self, halt: bool) -> None:
        self.new_halt = halt

    def write_load(self, index: int) -> None:
        if self.enabled:
            self.load = LENGTHS[index]
            self.before = self.value

    def half(self) -> None:
        if self.value and not self.halt:
            self.value -= 1

    def settle(self) -> None:
        """The end of a CPU cycle with a write to this channel."""
        if self.load:
            if self.value == self.before:  # no length clock took it away
                self.value = self.load
            self.load = 0
        self.halt = self.new_halt

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.value = 0
            self.load = 0


class Pulse:
    """APU_Pulse.wiki and APU_Sweep.wiki. ``ones_complement``: pulse 1's sweep
    negates as -c - 1, pulse 2's as -c."""

    def __init__(self, ones_complement: bool) -> None:
        self.ones_complement = ones_complement
        self.envelope = Envelope()
        self.length = LengthCounter()
        self.duty = DUTY[0]
        self.step = 0
        self.period = 0
        self.timer = 0
        self.sweep_enabled = False
        self.sweep_period = 0
        self.sweep_negate = False
        self.sweep_shift = 0
        self.sweep_divider = 0
        self.sweep_reload = False
        self.target = 0
        self.output = 0

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.duty = DUTY[value >> 6]
            self.envelope.set(value)
            self.length.write_halt(bool(value & 0x20))
        elif register == 1:
            self.sweep_enabled = bool(value & 0x80)
            self.sweep_period = (value >> 4) & 7
            self.sweep_negate = bool(value & 0x08)
            self.sweep_shift = value & 7
            self.sweep_reload = True
        elif register == 2:
            self.period = (self.period & 0x700) | value
        else:
            self.period = (self.period & 0xFF) | (value & 7) << 8
            self.length.write_load(value >> 3)
            self.step = 0
            self.envelope.start = True
        self._update_target()

    def _update_target(self) -> None:
        """The sweep's target period, computed continuously (APU_Sweep.wiki)."""
        change = self.period >> self.sweep_shift
        if self.sweep_negate:
            change = -change - self.ones_complement
        self.target = max(0, self.period + change)
        self.update_output()

    def clock_timer(self) -> bool:
        """One APU cycle; True when the sequencer stepped."""
        if self.timer:
            self.timer -= 1
            return False
        self.timer = self.period
        self.step = (self.step - 1) & 7
        return True

    def half(self) -> None:
        if (
            self.sweep_divider == 0
            and self.sweep_enabled
            and self.sweep_shift
            and self.period >= 8
            and self.target <= 0x7FF
        ):
            self.period = self.target
            self._update_target()
        if self.sweep_divider == 0 or self.sweep_reload:
            self.sweep_divider = self.sweep_period
            self.sweep_reload = False
        else:
            self.sweep_divider -= 1

    def update_output(self) -> None:
        # Muted by the sweep (period < 8 or target > $7FF, whether or not the
        # sweep is enabled), by the length counter, or by the sequencer.
        if self.period < 8 or self.target > 0x7FF or not self.length.value:
            self.output = 0
        else:
            self.output = self.duty[self.step] and self.envelope.volume


class Triangle:
    """APU_Triangle.wiki. The timer counts CPU cycles; at ultrasonic periods the
    sequencer runs as on hardware (no silencing)."""

    def __init__(self) -> None:
        self.length = LengthCounter()
        self.control = False
        self.linear_period = 0
        self.linear = 0
        self.linear_reload = False
        self.period = 0
        self.timer = 0
        self.step = 0
        self.output = TRIANGLE[0]

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.control = bool(value & 0x80)
            self.linear_period = value & 0x7F
            self.length.write_halt(self.control)
        elif register == 2:
            self.period = (self.period & 0x700) | value
        elif register == 3:
            self.period = (self.period & 0xFF) | (value & 7) << 8
            self.length.write_load(value >> 3)
            self.linear_reload = True

    def clock_timer(self) -> bool:
        """One CPU cycle; True when the sequencer stepped."""
        if self.timer:
            self.timer -= 1
            return False
        self.timer = self.period
        if self.linear and self.length.value:
            self.step = (self.step + 1) & 31
            self.output = TRIANGLE[self.step]
            return True
        return False

    def quarter(self) -> None:
        if self.linear_reload:
            self.linear = self.linear_period
        elif self.linear:
            self.linear -= 1
        if not self.control:
            self.linear_reload = False


class Noise:
    """APU_Noise.wiki: a 15-bit LFSR clocked by a timer counting APU cycles."""

    def __init__(self) -> None:
        self.envelope = Envelope()
        self.length = LengthCounter()
        self.mode_bit = 1  # the feedback tap: 1, or 6 in periodic mode
        self.period = NOISE_PERIODS[0] // 2 - 1
        self.timer = 0
        self.shift = 1
        self.output = 0

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.envelope.set(value)
            self.length.write_halt(bool(value & 0x20))
        elif register == 2:
            self.mode_bit = 6 if value & 0x80 else 1
            self.period = NOISE_PERIODS[value & 0x0F] // 2 - 1
        elif register == 3:
            self.length.write_load(value >> 3)
            self.envelope.start = True
        self.update_output()

    def clock_timer(self) -> bool:
        """One APU cycle; True when the shift register moved."""
        if self.timer:
            self.timer -= 1
            return False
        self.timer = self.period
        shift = self.shift
        feedback = (shift ^ (shift >> self.mode_bit)) & 1
        self.shift = (shift >> 1) | (feedback << 14)
        return True

    def update_output(self) -> None:
        if self.shift & 1 or not self.length.value:
            self.output = 0
        else:
            self.output = self.envelope.volume


class DMC:
    """APU_DMC.wiki: the memory reader, sample buffer, output unit and IRQ flag.

    The reader's fetches are the board's DMA; see :meth:`APU.dmc_fill`.
    """

    def __init__(self) -> None:
        self.irq_enabled = False
        self.loop = False
        self.period = DMC_RATES[0] // 2 - 1
        self.timer = 0
        self.output = 0  # the 7-bit output level
        self.sample_address = 0xC000
        self.sample_length = 1
        self.address = 0xC000
        self.remaining = 0  # bytes remaining
        self.buffer: int | None = None  # the sample buffer; None: empty
        self.shift = 0
        self.bits = 8  # bits remaining in the output cycle
        self.silence = True
        self.irq = False

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.irq_enabled = bool(value & 0x80)
            if not self.irq_enabled:
                self.irq = False
            self.loop = bool(value & 0x40)
            self.period = DMC_RATES[value & 0x0F] // 2 - 1
        elif register == 1:
            self.output = value & 0x7F
        elif register == 2:
            self.sample_address = 0xC000 | value << 6
        else:
            self.sample_length = (value << 4) | 1

    def restart(self) -> None:
        self.address = self.sample_address
        self.remaining = self.sample_length

    def clock_timer(self) -> bool:
        """One APU cycle; True when the sample buffer was just emptied into the shifter."""
        if self.timer:
            self.timer -= 1
            return False
        self.timer = self.period
        if not self.silence:
            level = self.output
            if self.shift & 1:
                if level <= 125:
                    self.output = level + 2
            elif level >= 2:
                self.output = level - 2
        self.shift >>= 1
        self.bits -= 1
        if self.bits:
            return False
        self.bits = 8  # the output cycle ends; a new one starts
        if self.buffer is None:
            self.silence = True
            return False
        self.silence = False
        self.shift = self.buffer
        self.buffer = None
        return True


class APU:
    def __init__(self, put_first: bool = False, sample_rate: int = 44100) -> None:
        # Whether the current CPU cycle is an APU put; clock() flips it first.
        self.put = not put_first
        self.pulse1 = Pulse(ones_complement=True)
        self.pulse2 = Pulse(ones_complement=False)
        self.triangle = Triangle()
        self.noise = Noise()
        self.dmc = DMC()
        self.channels = (self.pulse1, self.pulse2, self.triangle, self.noise)
        self.lengths = tuple(channel.length for channel in self.channels)
        self.frame_irq = False
        self.irq = False
        self.steps = STEPS_4
        self.mode5 = False
        self.inhibit = False
        self.frame_cycle = 0
        self.pending_frame_write: int | None = None
        self.pending_delay = 0
        self.last_frame_write = 0x00
        # DMC DMA: a request the board serves at the CPU's next read cycle, and
        # the countdown of a load DMA (DMA.wiki "DMC DMA").
        self.dmc_request = False
        self._load_countdown = 0
        # Length counters written this cycle, settled at the next clock.
        self._unsettled: list[LengthCounter] = []
        # The mixer: a box filter at the host rate (see take_samples).
        self.sample_rate = sample_rate
        self._cpu_hz = 1_789_773  # NTSC (39,375,000 * 6 / 11 / 12): set by the board
        self._level = 0.0
        self._level_dirty = True
        self._accumulated = 0.0
        self._accumulated_cycles = 0
        self._phase = 0  # Bresenham: CPU cycles * sample_rate
        self._samples: list[float] = []

    def set_cpu_rate(self, cpu_hz: float) -> None:
        self._cpu_hz = round(cpu_hz)

    def power(self) -> None:
        """Power: $4015 = 0; $4017 as if $00 were written just before the CPU starts.

        blargg ``apu_reset/4017_timing`` puts that write 9-12 CPU cycles before
        the first instruction; the reset sequence is 7, so the counter starts at
        the CPU's first cycle, 3-4 cycles after the write.
        """
        self.write(0x4015, 0)
        self._apply_frame_write(0x00)

    def reset(self) -> None:
        """Reset: $4015 = 0, the frame IRQ flag cleared, $4017 rewritten with its
        last value (blargg ``apu_reset``: ``4015_cleared``, ``irq_flag_cleared``,
        ``4017_written``). The triangle is untouched (``len_ctrs_enabled``)."""
        self.write(0x4015, 0)
        self.frame_irq = False
        self.write(0x4017, self.last_frame_write)

    # -- the clock -------------------------------------------------------

    def clock(self) -> None:
        """One CPU cycle."""
        put = self.put = not self.put
        if self._load_countdown:
            self._load_countdown -= 1
            if not self._load_countdown and self.dmc.buffer is None and self.dmc.remaining:
                self.dmc_request = True
        self._clock_frame_counter()
        if self._unsettled:
            # Length writes of the last cycle land after this cycle's length
            # clock (blargg 10.len_halt_timing, 11.len_reload_timing).
            for length in self._unsettled:
                length.settle()
            self._unsettled.clear()
            self._level_dirty = True
        if self.triangle.clock_timer():
            self._level_dirty = True
        if not put:
            if self.pulse1.clock_timer() | self.pulse2.clock_timer() | self.noise.clock_timer():
                self._level_dirty = True
            dmc = self.dmc
            if not dmc.timer:
                self._level_dirty = True
            if dmc.clock_timer() and dmc.remaining:
                # A reload DMA: it halts on this APU cycle's put (DMA.wiki).
                self.dmc_request = True
        # The mixer, one CPU cycle's worth.
        if self._level_dirty:
            self._level = self._mix()
        self._accumulated += self._level
        self._accumulated_cycles += 1
        self._phase += self.sample_rate
        if self._phase >= self._cpu_hz:
            self._phase -= self._cpu_hz
            self._samples.append(self._accumulated / self._accumulated_cycles)
            self._accumulated = 0.0
            self._accumulated_cycles = 0

    def _clock_frame_counter(self) -> None:
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
            if event & QUARTER:
                self._quarter_frame()
            if event & HALF:
                self._half_frame()
            if event & WRAP:
                self.frame_cycle = 0

    def _quarter_frame(self) -> None:
        self.pulse1.envelope.quarter()
        self.pulse2.envelope.quarter()
        self.noise.envelope.quarter()
        self.triangle.quarter()
        self._level_dirty = True

    def _half_frame(self) -> None:
        for length in self.lengths:
            length.half()
        self.pulse1.half()
        self.pulse2.half()
        self._level_dirty = True

    def _apply_frame_write(self, value: int) -> None:
        self.mode5 = bool(value & 0x80)
        self.steps = STEPS_5 if self.mode5 else STEPS_4
        self.frame_cycle = 0
        if self.mode5:  # bit 7 clocks quarter and half at once
            self._quarter_frame()
            self._half_frame()

    # -- the mixer -------------------------------------------------------

    def _mix(self) -> float:
        """APU_Mixer.wiki, blargg's formula: 0.0 to about 1.0."""
        self._level_dirty = False
        pulse1, pulse2, noise = self.pulse1, self.pulse2, self.noise
        pulse1.update_output()
        pulse2.update_output()
        noise.update_output()
        pulses = pulse1.output + pulse2.output
        level = 95.88 / (8128 / pulses + 100) if pulses else 0.0
        tnd = self.triangle.output / 8227 + noise.output / 12241 + self.dmc.output / 22638
        if tnd:
            level += 159.79 / (1 / tnd + 100)
        return level

    def take_samples(self) -> list[float]:
        """The mixer's output since the last call, box-filtered to ``sample_rate``."""
        samples, self._samples = self._samples, []
        return samples

    # -- the DMC's DMA ---------------------------------------------------

    @property
    def dmc_address(self) -> int:
        return self.dmc.address

    def dmc_fill(self, value: int) -> None:
        """The DMA's byte arrives: fill the buffer, advance the reader (APU_DMC.wiki
        "Memory reader"); the IRQ is set when the last byte is *fetched*."""
        dmc = self.dmc
        self.dmc_request = False
        dmc.buffer = value
        dmc.address = (dmc.address + 1) & 0xFFFF or 0x8000
        dmc.remaining -= 1
        if not dmc.remaining:
            if dmc.loop:
                dmc.restart()
            elif dmc.irq_enabled:
                dmc.irq = True
                self.irq = True

    # -- registers -------------------------------------------------------

    def write(self, address: int, value: int) -> None:
        register = address & 3
        if address < 0x4004:
            self._channel_write(self.pulse1, register, value)
        elif address < 0x4008:
            self._channel_write(self.pulse2, register, value)
        elif address < 0x400C:
            self._channel_write(self.triangle, register, value)
        elif address < 0x4010:
            self._channel_write(self.noise, register, value)
        elif address < 0x4014:
            self.dmc.write(register, value)
        elif address == 0x4015:
            self._write_status(value)
        elif address == 0x4017:
            self.last_frame_write = value
            self.inhibit = bool(value & 0x40)
            if self.inhibit:
                self.frame_irq = False
            # The new mode takes effect 3 CPU cycles after the write cycle if it
            # falls during an APU cycle, 4 if between (APU_Frame_Counter.wiki).
            # "During" is a write on a put: the other reading moves the frame
            # IRQ by one cycle against OAM DMA's get/put alignment, and
            # cpu_interrupts_v2 4-irq_and_dma then prints "9 +526" where
            # hardware prints "8 +526" (docs/validation.md, milestone 3).
            self.pending_frame_write = value
            self.pending_delay = 3 if self.put else 4
        self._level_dirty = True
        self.irq = self.frame_irq or self.dmc.irq

    def _channel_write(self, channel, register: int, value: int) -> None:
        channel.write(register, value)
        if register == 0 or register == 3:
            self._unsettled.append(channel.length)

    def _write_status(self, value: int) -> None:
        for bit, length in enumerate(self.lengths):
            length.set_enabled(bool(value & (1 << bit)))
        dmc = self.dmc
        dmc.irq = False
        if not value & 0x10:
            dmc.remaining = 0
            self.dmc_request = False
            self._load_countdown = 0
        elif not dmc.remaining:
            dmc.restart()
            if dmc.buffer is None:
                # A load DMA halts on the get of the second APU cycle after this
                # one: the 4th CPU cycle after a write on a get, the 3rd after
                # one on a put (DMA.wiki "DMC DMA").
                self._load_countdown = 2 if self.put else 3

    def read_status(self) -> int:
        """$4015: DMC IRQ, frame IRQ, DMC active, length > 0; clears the frame IRQ flag."""
        lengths = self.lengths
        value = (
            (self.dmc.irq << 7)
            | (self.frame_irq << 6)
            | (self.dmc.remaining > 0) << 4
            | (lengths[3].value > 0) << 3
            | (lengths[2].value > 0) << 2
            | (lengths[1].value > 0) << 1
            | (lengths[0].value > 0)
        )
        self.frame_irq = False
        self.irq = self.dmc.irq
        return value


class AnalogueStage:
    """The console's filters after the DAC, **fitted**: first-order sections at
    the corner frequencies APU_Mixer.wiki gives (NES: high-pass 90 Hz and 440 Hz,
    low-pass 14 kHz; Famicom: high-pass 37 Hz), not a measured response."""

    def __init__(self, sample_rate: int, high_passes: tuple[float, ...], low_pass: float | None):
        dt = 1 / sample_rate
        self._highs = [(rc := 1 / (2 * math.pi * f), rc / (rc + dt)) for f in high_passes]
        self._high_state = [(0.0, 0.0) for _ in high_passes]  # (last in, last out)
        self._low = None if low_pass is None else dt / (1 / (2 * math.pi * low_pass) + dt)
        self._low_out = 0.0

    def process(self, samples: list[float]) -> list[float]:
        out = []
        for x in samples:
            if self._low is not None:
                self._low_out += self._low * (x - self._low_out)
                x = self._low_out
            for i, (_, alpha) in enumerate(self._highs):
                last_in, last_out = self._high_state[i]
                y = alpha * (last_out + x - last_in)
                self._high_state[i] = (x, y)
                x = y
            out.append(x)
        return out
