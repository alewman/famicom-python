"""The MMC5's sound: two pulses and an 8-bit PCM DAC (MMC5_audio.wiki).

The pulses are the APU's (APU_Pulse.wiki) without the sweep, without the
silencing of periods under 8, and with their envelopes and length counters
clocked together at a fixed rate: every 7424 M2 cycles, the die's divider
(about 240 Hz). The PCM DAC takes $5011 writes, or in read mode every byte
read from $8000-$BFFF; a zero leaves it alone and trips the IRQ.

All of it is inverted against the APU, and equal to it in level: rainwarrior
measured a full-volume MMC5 square +1.0 dB against the APU's on an AV
Famicom (``db_mmc5``; James-F +0.05 dB on an HVC-CPU-07), and the PCM is "as
loud as the APU's DMC with the same input", its eighth bit doubling that (the
wiki; unmeasured). A mapper module may not import the APU (the connector
rule), so the pulse's pieces are its own here.
"""

from __future__ import annotations

from .connector import APU_SQUARE, Cartridge

#: The APU's length table (APU_Length_Counter.wiki), which the MMC5's equals.
LENGTHS = (
    10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
    12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30,
)  # fmt: skip

#: The duty sequences as the sequencer counting down from 0 reads them (APU_Pulse.wiki).
DUTY = (
    (0, 0, 0, 0, 0, 0, 0, 1),
    (0, 0, 0, 0, 0, 0, 1, 1),
    (0, 0, 0, 0, 1, 1, 1, 1),
    (1, 1, 1, 1, 1, 1, 0, 0),
)

FRAME_CYCLES = 7424  # M2 cycles per envelope and length clock (the die)

MMC5_DB = 1.0  # a full-volume square against the APU's (rainwarrior, AV Famicom)
PULSE_GAIN = APU_SQUARE * 10 ** (MMC5_DB / 20) / 15
# The APU's DMC near zero (APU_Mixer.wiki: 159.79 / (22638 / d + 100) per step
# d, small d), through the same resistors as the pulses.
PCM_GAIN = 159.79 / 22638 * 10 ** (MMC5_DB / 20)


class MMC5Pulse:
    def __init__(self) -> None:
        self.duty = DUTY[0]
        self.halt = False  # also the envelope's loop
        self.constant = False
        self.volume = 0  # also the envelope's period
        self.period = 0
        self.timer = 0
        self.step = 0
        self.length = 0
        self.enabled = False
        self.start = False
        self.divider = 0
        self.decay = 0

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.duty = DUTY[value >> 6]
            self.halt = bool(value & 0x20)
            self.constant = bool(value & 0x10)
            self.volume = value & 0x0F
        elif register == 2:
            self.period = (self.period & 0x700) | value
        elif register == 3:
            self.period = (self.period & 0xFF) | (value & 7) << 8
            if self.enabled:
                self.length = LENGTHS[value >> 3]
            self.step = 0
            self.start = True

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.length = 0

    def clock_timer(self) -> bool:
        """One APU cycle; True when the sequencer stepped."""
        if self.timer:
            self.timer -= 1
            return False
        self.timer = self.period
        self.step = (self.step - 1) & 7
        return True

    def clock_frame(self) -> None:
        """The envelope's clock and the length counter's, together."""
        if self.start:
            self.start = False
            self.decay = 15
            self.divider = self.volume
        elif self.divider:
            self.divider -= 1
        else:
            self.divider = self.volume
            if self.decay:
                self.decay -= 1
            elif self.halt:
                self.decay = 15
        if self.length and not self.halt:
            self.length -= 1

    def output(self) -> int:
        if not self.length or not self.duty[self.step]:
            return 0
        return self.volume if self.constant else self.decay


class MMC5Sound:
    """The registers at $5000-$5015 and the level the chip drives."""

    def __init__(self, cartridge: Cartridge) -> None:
        self.cartridge = cartridge  # whose audio_out the level goes to
        self.pulses = (MMC5Pulse(), MMC5Pulse())
        self.read_mode = False
        self.pcm_irq_enabled = False
        self.pcm_tripped = False
        # The DAC powers on at $EF or $FF on one MMC5A (the wiki): a constant
        # offset the analogue stage removes. Zero here.
        self.pcm = 0
        self.put = False  # the pulse timers count APU cycles: every other M2
        self.frame = FRAME_CYCLES

    @property
    def irq(self) -> bool:
        return self.pcm_tripped and self.pcm_irq_enabled

    def write(self, address: int, value: int) -> None:
        """A write to $5000-$5015."""
        if address < 0x5008:
            if address & 3 != 1:  # $5001/$5005: no sweep
                self.pulses[(address >> 2) & 1].write(address & 3, value)
        elif address == 0x5010:
            self.read_mode = bool(value & 1)
            self.pcm_irq_enabled = bool(value & 0x80)
        elif address == 0x5011:
            if not self.read_mode:
                self.dac(value)
        elif address == 0x5015:
            self.pulses[0].set_enabled(bool(value & 1))
            self.pulses[1].set_enabled(bool(value & 2))
        self._mix()

    def read(self, address: int) -> int | None:
        if address == 0x5010:
            value = 0x80 if self.irq else 0  # D0 0: the letterless MMC5
            self.pcm_tripped = False
            return value
        if address == 0x5015:
            return (self.pulses[0].length > 0) | (self.pulses[1].length > 0) << 1
        return None

    def dac(self, value: int) -> None:
        """A byte for the DAC: written to $5011, or read from $8000-$BFFF in read mode."""
        if value:
            self.pcm = value
            self.pcm_tripped = False
            self._mix()
        else:
            self.pcm_tripped = True

    def m2(self) -> None:
        moved = False
        put = self.put = not self.put
        if put:
            pulse1, pulse2 = self.pulses
            moved = pulse1.clock_timer() | pulse2.clock_timer()
        self.frame -= 1
        if not self.frame:
            self.frame = FRAME_CYCLES
            for pulse in self.pulses:
                pulse.clock_frame()
            moved = True
        if moved:
            self._mix()

    def _mix(self) -> None:
        pulse1, pulse2 = self.pulses
        level = (pulse1.output() + pulse2.output()) * PULSE_GAIN + self.pcm * PCM_GAIN
        self.cartridge.audio_out.expansion = -level  # inverted against the APU
