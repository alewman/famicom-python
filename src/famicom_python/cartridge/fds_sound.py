"""The FDS's sound: the RP2C33's wavetable channel and its modulator (FDS_audio.wiki).

A 64-step, 6-bit wavetable is stepped by a 24-bit accumulator; a 32-entry
modulation table bends its pitch; two envelopes set the volume and the
modulation depth. The units follow loopy's measurements through the chip's
test registers (nesdev-forum/p232662.html, 2019), which the wiki now carries:
the wave and modulator accumulate every 16 M2 cycles from one 4-bit prescaler
that $4083 D7 holds in reset; $4083 D7 also clears the wave accumulator and
runs the envelopes 4x faster; the pitch formula is his, always in effect. The
volume is a PWM duty (gain / 32, latched while the wave is at position 0),
taken here as the linear gain it averages to. The DAC is an R-2R ladder whose
master volume grounds 2R and R through switches (Yuri213212's die schematic,
nesdev-forum/25226.html): 1, 2/3, 1/2 and 2/5, the wiki's ratios. The RAM
adapter then low-passes it, one pole near 2 kHz (rainwarrior's fit to a
recording, nesdev-forum/10233.html). $4023 D1 clear holds the unit in reset
(FDS_Registers.wiki "Audio reset").
"""

from __future__ import annotations

import math

from .connector import expansion_gain

#: A full-volume FDS square (63 steps) against a full-volume APU square:
#: rainwarrior's ``db_fds`` on an AV Famicom (nesdev-forum/17741.html), measured
#: after the RAM adapter's low-pass, so the gain below is fitted with it in place.
FDS_DB = 6.6
CUTOFF_HZ = 2000.0
CPU_HZ = 236_250_000 / 11 / 12
LOWPASS = 1 - math.exp(-2 * math.pi * CUTOFF_HZ / CPU_HZ)
#: The low-pass takes 0.61 dB off db_fds's 440 Hz 63/0 square (scripts/expansion_levels.py
#: measures it through the filter); put back so the filtered tone meets FDS_DB.
FILTER_LOSS_DB = 0.61
GAIN = expansion_gain(FDS_DB + FILTER_LOSS_DB, 63)
MASTER = (1.0, 2 / 3, 1 / 2, 2 / 5)  # $4089 D1-D0, the ladder's grounding resistors
#: Mod table entries as mod counter steps (None: reset to 0).
MOD_STEPS = (0, 1, 2, 4, None, -4, -2, -1)
MOD_READ = (0x0, 0x1, 0x2, 0x4, 0xC, 0xC, 0xE, 0xF)  # $4095's nibble, as loopy read it


class Envelope:
    """The volume ($4080) or mod depth ($4084) envelope."""

    def __init__(self) -> None:
        self.speed = 0
        self.increase = False
        self.off = True
        self.gain = 0
        self.timer = 0

    def write(self, value: int, master_speed: int) -> None:
        self.speed = value & 0x3F
        self.increase = bool(value & 0x40)
        self.off = bool(value & 0x80)
        if self.off:
            self.gain = value & 0x3F
        self.timer = self.period(master_speed)

    def period(self, master_speed: int) -> int:
        return 8 * (self.speed + 1) * (master_speed + 1)

    def tick(self) -> None:
        if self.increase:
            if self.gain < 32:
                self.gain += 1
        elif self.gain:
            self.gain -= 1


class FDSSound:
    """$4040-$408A and the readable $4090-$4097, clocked every CPU cycle."""

    def __init__(self) -> None:
        self.enabled = False  # $4023 D1
        self.wave = bytearray(64)
        self.wave_write = False  # $4089 D7: RAM writable, output held
        self.master = 0
        self.volume = Envelope()
        self.depth = Envelope()
        self.master_speed = 0  # $408A
        self.pitch = 0
        self.wave_reset = True  # $4083 D7
        self.envelopes_off = False  # $4083 D6
        self.accumulator = 0  # 24 bits: the wave position in bits 23-18
        self.mod_frequency = 0
        self.mod_halt = True  # $4087 D7
        self.mod_force = False  # $4087 D6
        self.mod_accumulator = 0  # 18 bits: the table address in bits 17-13
        self.mod_table = bytearray(32)
        self.mod_counter = 0  # 7-bit signed
        self.prescaler = 0
        self.pwm = 0
        self.out_volume = 0  # the PWM duty in force, 0-32
        self.sample = 0  # the DAC's input
        self.level = 0.0  # after the low-pass

    # -- registers ------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.accumulator = 0
            self.mod_counter = 0
            self.volume.gain = 0
            self.out_volume = 0

    def write(self, address: int, value: int) -> None:
        if address < 0x4080:
            if self.wave_write:
                self.wave[address & 0x3F] = value & 0x3F
            return
        if address == 0x4080:
            if self.enabled:
                self.volume.write(value, self.master_speed)
                if self.volume.off and not self.volume.gain:
                    self.out_volume = 0  # muting takes effect at once (the wiki)
        elif address == 0x4082:
            self.pitch = (self.pitch & 0xF00) | value
        elif address == 0x4083:
            self.pitch = (self.pitch & 0x0FF) | (value & 0x0F) << 8
            self.wave_reset = bool(value & 0x80)
            self.envelopes_off = bool(value & 0x40)
            if self.wave_reset:
                self.accumulator = 0
                self.prescaler = 0
            if self.envelopes_off:
                self.volume.timer = self.volume.period(self.master_speed)
                self.depth.timer = self.depth.period(self.master_speed)
        elif address == 0x4084:
            self.depth.write(value, self.master_speed)
        elif address == 0x4085:
            if self.enabled:
                self.mod_counter = (value & 0x7F) - ((value & 0x40) << 1)
        elif address == 0x4086:
            self.mod_frequency = (self.mod_frequency & 0xF00) | value
        elif address == 0x4087:
            self.mod_frequency = (self.mod_frequency & 0x0FF) | (value & 0x0F) << 8
            self.mod_halt = bool(value & 0x80)
            self.mod_force = bool(value & 0x40)
            if self.mod_halt:
                self.mod_accumulator &= 0x3E000  # bits 12-0 cleared, the address kept
        elif address == 0x4088:
            if self.enabled and self.mod_halt:
                self.mod_table[(self.mod_accumulator >> 13) & 0x1F] = value & 7
                self.mod_accumulator = (self.mod_accumulator + 0x2000) & 0x3FFFF
        elif address == 0x4089:
            self.wave_write = bool(value & 0x80)
            self.master = value & 3
        elif address == 0x408A:
            self.master_speed = value

    def read(self, address: int) -> int | None:
        """The byte driven for a read of ``address`` (bits left to open bus in
        the high byte, as the connector protocol has it), or None."""
        if 0x4040 <= address < 0x4080:
            position = address & 0x3F if self.wave_write else self.accumulator >> 18
            return self.wave[position] | 0xC0 << 8
        if address == 0x4090:
            return self.volume.gain | 0xC0 << 8
        if address == 0x4091:
            return (self.accumulator >> 12) & 0xFF
        if address == 0x4092:
            return self.depth.gain | 0xC0 << 8
        if address == 0x4093:
            return (self.mod_accumulator >> 5) & 0x7F | 0x80 << 8
        if address == 0x4094:
            return (self.mod_counter * self.depth.gain >> 4) & 0xFF
        if address == 0x4095:
            # The high nibble ("looks like some counter") is not modelled: 0.
            return MOD_READ[self.mod_table[(self.mod_accumulator >> 13) & 0x1F]]
        if address == 0x4096:
            value = self.wave[self.accumulator >> 18] if self.pwm < self.out_volume else 0
            return value | 0xC0 << 8
        if address == 0x4097:
            return self.mod_counter & 0x7F | 0x80 << 8
        return None

    # -- one CPU cycle --------------------------------------------------

    def clock(self) -> float:
        """Advance a cycle; returns the low-passed output in DAC steps."""
        self.pwm = (self.pwm + 1) & 31
        if self.enabled:
            if self.master_speed and not self.envelopes_off:
                step = 4 if self.wave_reset else 1
                for envelope in (self.volume, self.depth):
                    if not envelope.off:
                        envelope.timer -= step
                        if envelope.timer <= 0:
                            envelope.timer += envelope.period(self.master_speed)
                            envelope.tick()
            if not self.wave_reset:
                self.prescaler = (self.prescaler + 1) & 15
                if not self.prescaler:
                    self._tick()
            position = self.accumulator >> 18
            if not position:
                self.out_volume = min(self.volume.gain, 32)
            if not self.wave_write:
                self.sample = self.wave[position] * self.out_volume
        else:
            self.sample = 0
        target = self.sample * MASTER[self.master] / 32
        self.level += LOWPASS * (target - self.level)
        return self.level

    def _tick(self) -> None:
        """Every 16 cycles: the modulator, then the wave, steps."""
        if not self.mod_halt:
            low = (self.mod_accumulator & 0xFFF) + self.mod_frequency
            carry = low > 0xFFF or self.mod_force
            self.mod_accumulator = (self.mod_accumulator & 0x3F000) | (low & 0xFFF)
            if carry:
                entry = self.mod_table[(self.mod_accumulator >> 13) & 0x1F]
                step = MOD_STEPS[entry]
                if step is None:
                    self.mod_counter = 0
                else:
                    counter = (self.mod_counter + step) & 0x7F
                    self.mod_counter = counter - ((counter & 0x40) << 1)
                self.mod_accumulator = (self.mod_accumulator + 0x1000) & 0x3FFFF
        temp = self.mod_counter * self.depth.gain
        if temp & 0x0F and not temp & 0x800:
            temp += 0x20
        temp = ((temp + 0x400) >> 4) & 0xFF
        self.accumulator = (self.accumulator + ((self.pitch * temp) & 0xFFFFF)) & 0xFFFFFF
