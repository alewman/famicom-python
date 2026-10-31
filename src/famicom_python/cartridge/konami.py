"""Konami's VRC mappers: VRC1 (75), VRC2 and VRC4 (21, 22, 23, 25), VRC3 (73), VRC6 (24, 26),
the VRC IRQ.

AWJ's ``vrctest`` judges the VRC2/VRC4 wiring and IRQ (docs/claims.md); no
judge ROM exists for the VRC1, whose claim rests on milestone 7's sweep
against Mesen2, a detector. The VRC6's sound level is rainwarrior's
``db_vrc6`` measurement (milestone 8).
"""

from __future__ import annotations

from dataclasses import replace

from ym2413_python import DS1001, OPLL

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .connector import expansion_gain
from .eeprom import Microwire93C56
from .ines import RomImage


class VRC1(Banked):
    """Mapper 75: three 8 KiB PRG banks and the last fixed; two 4 KiB CHR banks of five bits.

    VRC1.wiki: $8000, $A000 and $C000 select PRG for their own windows; $9000
    D0 is the mirroring (0 vertical, 1 horizontal; ignored when
    the board has four-screen VRAM) and D1/D2 the CHR banks' high bits;
    $E000 and $F000 their low four bits. Each register decodes $x000-$xFFF.
    Power-on registers unspecified: 0 here.

    The PRG registers have four bits (128 KiB); here every bit written
    selects, the bank wrapping at the image's size, so images of 128 KiB or
    less see exactly the chip. The one larger licensed dump, *Ninja JaJaMaru*
    (Retro Collection, 256 KiB), writes banks past $0F and runs only so, as
    Mesen2's "oversized PRG" does: no hardware runs it, an extension.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.chr_banks = [0, 0]
        for window in range(3):
            self.map_prg(window, 8, 0)
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        self._update_chr()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        region = address & 0xF000
        if region in (0x8000, 0xA000, 0xC000):
            self.map_prg((region - 0x8000) >> 13, 8, value)
        elif region == 0x9000:
            if not self.four_screen:
                self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
            self.chr_banks = [
                (self.chr_banks[0] & 0x0F) | (value & 2) << 3,
                (self.chr_banks[1] & 0x0F) | (value & 4) << 2,
            ]
            self._update_chr()
        elif region in (0xE000, 0xF000):
            half = (region >> 12) & 1
            self.chr_banks[half] = (self.chr_banks[half] & 0x10) | (value & 0x0F)
            self._update_chr()

    def _update_chr(self) -> None:
        self.map_chr(0, 4, self.chr_banks[0])
        self.map_chr(4, 4, self.chr_banks[1])


class VRC3(Banked):
    """Mapper 73: VRC3 (Salamander): 16 KiB PRG and the last fixed, 8 KiB CHR-RAM, a cycle counter.

    VRC3.wiki: $8000-$BFFF the reload value's four nibbles, low first; $C000
    ``.MEA``: M the 8-bit mode, E enables, A the enable an acknowledge
    restores, and with E set the write reloads all 16 bits; $D000 copies A
    to E; both acknowledge. $F000 D2-D0 the PRG bank. Enabled, the counter
    increments every CPU cycle; its overflow from $FFFF (in 8-bit mode the
    low byte's, from $FF) asserts /IRQ and reloads it (in 8-bit mode the low
    byte only). PRG-RAM at $6000 if the board has it. Power-on registers
    unspecified: 0 here.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.reload = 0
        self.counter = 0
        self.control = 0
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.map_chr(0, 8, 0)

    def m2(self, t: int) -> None:
        if not self.control & 2:
            return
        if self.control & 4:
            low = (self.counter & 0xFF) + 1
            if low > 0xFF:
                low = self.reload & 0xFF
                self.irq = True
            self.counter = (self.counter & 0xFF00) | low
        else:
            self.counter += 1
            if self.counter > 0xFFFF:
                self.counter = self.reload
                self.irq = True

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        region = address & 0xF000
        if region < 0xC000:
            shift = (region - 0x8000) >> 10  # $8000 0, $9000 4, $A000 8, $B000 12
            self.reload = (self.reload & ~(0xF << shift)) | (value & 0xF) << shift
        elif region == 0xC000:
            self.control = value & 7
            if value & 2:
                self.counter = self.reload
            self.irq = False
        elif region == 0xD000:
            self.control = (self.control & ~2) | (self.control & 1) << 1
            self.irq = False
        elif region == 0xF000:
            self.map_prg(0, 16, value & 7)


class VRCIrq:
    """The VRC4/VRC6/VRC7 IRQ (VRC_IRQ.wiki): an 8-bit up-counter, clocked by CPU cycles.

    In scanline mode (control D2 clear) a prescaler divides cycles by 114,
    114, 113 (the wiki's "start at 341, subtract 3 each cycle, add 341 at or
    below 0"); in cycle mode every cycle clocks. A clock at $FF reloads the
    latch and asserts /IRQ. Writing the control acknowledges, resets the
    prescaler, takes D0 as the enable to restore on acknowledge and D1 as
    the enable, and with D1 set reloads the counter. Writing the acknowledge
    register acknowledges and copies D0 to the enable. Disabled, neither
    counts.
    """

    irq = False

    def irq_reset(self) -> None:
        self.irq_latch = self.irq_counter = 0
        self.irq_prescaler = 341
        self.irq_enabled = self.irq_after_ack = self.irq_cycle_mode = False

    def m2(self, t: int) -> None:
        if not self.irq_enabled:
            return
        if not self.irq_cycle_mode:
            self.irq_prescaler -= 3
            if self.irq_prescaler > 0:
                return
            self.irq_prescaler += 341
        if self.irq_counter == 0xFF:
            self.irq_counter = self.irq_latch
            self.irq = True
        else:
            self.irq_counter += 1

    def irq_control(self, value: int) -> None:
        self.irq = False
        self.irq_prescaler = 341
        self.irq_after_ack = bool(value & 1)
        self.irq_enabled = bool(value & 2)
        self.irq_cycle_mode = bool(value & 4)
        if self.irq_enabled:
            self.irq_counter = self.irq_latch

    def irq_acknowledge(self) -> None:
        self.irq = False
        self.irq_enabled = self.irq_after_ack


# The CPU address lines each board wires to the chip's A0 and A1
# (NES_2.0_submappers.wiki, "021/023/025"), by (mapper, submapper); submapper 0
# of 21/23/25 answers both of its mapper's wirings at once.
VRC_WIRING = {
    (21, 1): ((1,), (2,)),  # VRC4a
    (21, 2): ((6,), (7,)),  # VRC4c
    (21, 0): ((1, 6), (2, 7)),
    (22, 0): ((1,), (0,)),  # VRC2a
    (23, 1): ((0,), (1,)),  # VRC4f
    (23, 2): ((2,), (3,)),  # VRC4e
    (23, 3): ((0,), (1,)),  # VRC2b
    (23, 0): ((0, 2), (1, 3)),
    (25, 1): ((1,), (0,)),  # VRC4b
    (25, 2): ((3,), (2,)),  # VRC4d
    (25, 3): ((1,), (0,)),  # VRC2c
    (25, 0): ((1, 3), (0, 2)),
}


class VRC24(VRCIrq, Banked):
    """Mappers 21, 22, 23, 25: VRC2 and VRC4, told apart and wired by mapper and submapper.

    VRC2_and_VRC4.wiki, registers named for VRC2b/VRC4f wiring ($x000-$x003):

    - $8000 PRG at $8000 (or, VRC4 swap mode, at $C000, the second-last bank
      taking $8000); $A000 PRG at $A000; the last 8 KiB fixed (and on VRC2
      the second-last).
    - $9000: the arrangement, D1-D0 on VRC4 (vertical, horizontal, one-screen
      A, B), D0 alone on VRC2 (Wai Wai World needs the missing one-screen
      modes absent). VRC4 has it at $9000/$9001 only: $9002 D1 is the swap
      mode and D0 the PRG-RAM enable; $9003 drives nothing on these boards.
    - $B000-$E003: the eight CHR banks, low nibble then high five bits (four
      on VRC2); VRC2a (22) drops the bank number's low bit.
    - $F000-$F003 (VRC4): latch low and high nibbles, control, acknowledge.
    - VRC2 without RAM: $6000-$6FFF is a 1-bit latch read back on D0, the
      other lines undriven (Contra (J) and Ganbare Goemon 2 need it);
      $7000-$7FFF undriven.

    Power-on registers unspecified: 0 here.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.vrc2 = board.mapper == 22 or board.submapper == 3
        self.counts_m2 = not self.vrc2  # the VRC2 has no IRQ
        self.halve_chr = board.mapper == 22
        self.lines0, self.lines1 = VRC_WIRING[(board.mapper, board.submapper)]
        self.prg_registers = [0, 0]
        self.swap = False
        self.chr_registers = [0] * 8
        self.latch_bit = 0
        self.prg_ram_enabled = self.vrc2 and bool(self.prg_ram)
        self.irq_reset()
        self._update_prg()

    def _register(self, address: int) -> int:
        low = any(address >> line & 1 for line in self.lines0)
        high = any(address >> line & 1 for line in self.lines1)
        return low | high << 1

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.vrc2 and not self.prg_ram and 0x6000 <= address < 0x7000:
            return self.latch_bit | 0xFE << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            if self.vrc2 and not self.prg_ram:
                if 0x6000 <= address < 0x7000:
                    self.latch_bit = value & 1
                return
            super().cpu_write(address, value, t)
            return
        region, register = address & 0xF000, self._register(address)
        if region == 0x8000 or region == 0xA000:
            self.prg_registers[region == 0xA000] = value & 0x1F
            self._update_prg()
        elif region == 0x9000:
            if self.vrc2:
                self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
            elif register < 2:
                self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
            elif register == 2:
                self.prg_ram_enabled = bool(self.prg_ram) and bool(value & 1)
                self.swap = bool(value & 2)
                self._update_prg()
        elif region < 0xF000:
            bank = ((region - 0xB000) >> 11) | register >> 1
            old = self.chr_registers[bank]
            if register & 1:
                old = (old & 0x0F) | (value & (0x0F if self.vrc2 else 0x1F)) << 4
            else:
                old = (old & 0x1F0) | (value & 0x0F)
            self.chr_registers[bank] = old
            self.map_chr(bank, 1, old >> 1 if self.halve_chr else old)
        elif not self.vrc2:
            if register == 0:
                self.irq_latch = (self.irq_latch & 0xF0) | (value & 0x0F)
            elif register == 1:
                self.irq_latch = (self.irq_latch & 0x0F) | (value & 0x0F) << 4
            elif register == 2:
                self.irq_control(value)
            else:
                self.irq_acknowledge()

    def _update_prg(self) -> None:
        last = len(self.prg) // 0x2000 - 1
        first, third = self.prg_registers[0], last - 1
        if self.swap:
            first, third = third, first
        self.map_prg(0, 8, first)
        self.map_prg(1, 8, self.prg_registers[1])
        self.map_prg(2, 8, third)
        self.map_prg(3, 8, last)


class VRC6Pulse:
    """VRC6_audio.wiki: a 12-bit divider clocking a 16-step duty generator, 15 down to 0."""

    def __init__(self) -> None:
        self.control = 0  # MDDD VVVV
        self.period = 0
        self.enabled = False
        self.counter = 0
        self.step = 15

    def output(self) -> int:
        control = self.control
        if self.enabled and (control & 0x80 or self.step <= (control >> 4) & 7):
            return control & 0x0F
        return 0

    def clock(self, shift: int) -> bool:
        """One CPU cycle; True when the output may have moved."""
        if self.counter:
            self.counter -= 1
            return False
        self.counter = self.period >> shift
        self.step = (self.step - 1) & 15
        return True


class VRC6Saw:
    """VRC6_audio.wiki: the same divider clocking an accumulator that adds its
    rate on every second clock, six times, and clears on the fourteenth."""

    def __init__(self) -> None:
        self.rate = 0
        self.period = 0
        self.enabled = False
        self.counter = 0
        self.step = 0
        self.accumulator = 0

    def output(self) -> int:
        return self.accumulator >> 3 if self.enabled else 0

    def clock(self, shift: int) -> bool:
        if self.counter:
            self.counter -= 1
            return False
        self.counter = self.period >> shift
        if not self.enabled:
            return False  # the divider runs on; the accumulator holds zero
        step = self.step + 1
        if step == 14:
            self.step = 0
            self.accumulator = 0
            return True
        self.step = step
        if not step & 1:
            self.accumulator = (self.accumulator + self.rate) & 0xFF
            return True
        return False


#: The VRC6's level, measured: a full-volume square +0.2 dB against the APU's
#: (rainwarrior's db_vrc6 on an AV Famicom, nesdev-forum/17741.html; James-F
#: measured -1.11 dB on an HVC-CPU-07: boards and consoles differ). Its DAC
#: sums the three channels linearly.
VRC6_DB = 0.2


class VRC6(VRCIrq, Banked):
    """Mappers 24 (VRC6a) and 26 (VRC6b, A0 and A1 swapped), with the sound.

    VRC6.wiki, registers as wired on mapper 24 ($x000-$x003, decoded by A0,
    A1 and A12-A15):

    - $8000: 16 KiB PRG at $8000; $C000: 8 KiB at $C000; the last 8 KiB fixed.
    - $9000-$9003, $A000-$A002, $B000-$B002: the sound (VRC6_audio.wiki).
    - $B003: PRG-RAM enable (D7), the CHR banking mode (D1-D0, with D5's
      passing of PPU A10 through 2 KiB banks) and the nametable arrangement
      (D3-D2: vertical, horizontal, one-screen A, B). Only CIRAM nametables
      are modelled, with D5 set, as Konami's three games use them: ROM
      nametables (D4) and the D5-clear arrangements are not.
    - $D000-$E003: R0-R7, the CHR banks.
    - $F000 IRQ latch, $F001 control, $F002 acknowledge (VRC_IRQ.wiki).

    Power-on registers unspecified: 0 here.
    """

    counts_m2 = True
    expansion_audio = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.swap_lines = image.board.mapper == 26
        self.prg_ram_enabled = False
        self.banking = 0
        self.chr_registers = [0] * 8
        self.pulses = (VRC6Pulse(), VRC6Pulse())
        self.saw = VRC6Saw()
        self.halt = False
        self.shift = 0
        self.gain = expansion_gain(VRC6_DB, 15)
        self.irq_reset()
        self.map_prg(0, 16, 0)
        self.map_prg(2, 8, 0)
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        self._update_chr()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        region, register = address & 0xF000, address & 3
        if self.swap_lines:
            register = (register & 1) << 1 | register >> 1
        if region == 0x8000:
            self.map_prg(0, 16, value & 0x0F)
        elif region == 0xC000:
            self.map_prg(2, 8, value & 0x1F)
        elif region == 0xD000 or region == 0xE000:
            self.chr_registers[(region == 0xE000) << 2 | register] = value
            self._update_chr()
        elif region == 0xF000:
            if register == 0:
                self.irq_latch = value
            elif register == 1:
                self.irq_control(value)
            elif register == 2:
                self.irq_acknowledge()
        elif region == 0xB000 and register == 3:
            self.prg_ram_enabled = bool(self.prg_ram) and bool(value & 0x80)
            self.banking = value & 0x3F
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[(value >> 2) & 3])
            self._update_chr()
        elif region in (0x9000, 0xA000, 0xB000):
            self._sound_write(region, register, value)

    def _sound_write(self, region: int, register: int, value: int) -> None:
        if region == 0x9000 and register == 3:
            self.halt = bool(value & 1)
            self.shift = 8 if value & 4 else 4 if value & 2 else 0
            return
        channel = self.saw if region == 0xB000 else self.pulses[region == 0xA000]
        if register == 0:
            if channel is self.saw:
                channel.rate = value & 0x3F
            else:
                channel.control = value
        elif register == 1:
            channel.period = (channel.period & 0xF00) | value
        else:
            channel.period = (channel.period & 0x0FF) | (value & 0x0F) << 8
            channel.enabled = bool(value & 0x80)
            if not channel.enabled:
                # The duty generator restarts from the beginning; the saw's
                # accumulator holds zero (its divider runs on).
                if channel is self.saw:
                    channel.accumulator = channel.step = 0
                else:
                    channel.step = 15
        self._mix()

    def m2(self, t: int) -> None:
        VRCIrq.m2(self, t)
        if self.halt:
            return
        shift = self.shift
        pulse1, pulse2 = self.pulses
        moved = pulse1.enabled and pulse1.clock(shift)
        if pulse2.enabled and pulse2.clock(shift):
            moved = True
        if self.saw.clock(shift):
            moved = True
        if moved:
            self._mix()

    def _mix(self) -> None:
        pulse1, pulse2 = self.pulses
        level = pulse1.output() + pulse2.output() + self.saw.output()
        self.audio_out.expansion = level * self.gain

    def _update_chr(self) -> None:
        r = self.chr_registers
        mode = self.banking & 3
        if mode == 0:
            for window in range(8):
                self.map_chr(window, 1, r[window])
            return

        # 2 KiB banks: with D5 set PPU A10 picks the half (the register's
        # low bit ignored); clear, both halves are the register's 1 KiB bank.
        def two(window: int, bank: int) -> None:
            if self.banking & 0x20:
                self.map_chr(window, 2, bank >> 1)
            else:
                self.map_chr(window, 1, bank)
                self.map_chr(window + 1, 1, bank)

        if mode == 1:
            for i in range(4):
                two(2 * i, r[i])
        else:
            for window in range(4):
                self.map_chr(window, 1, r[window])
            two(4, r[4])
            two(6, r[5])


#: The VRC7's level, measured: a full-volume square-like custom instrument +11.3 dB
#: against a full-volume APU square (rainwarrior's db_vrc7 on an AV Famicom,
#: nesdev-forum/17741.html; James-F +10.88 dB on an HVC-CPU-07). The gain below is
#: fitted so db_vrc7 measures that through the board (scripts/expansion_levels.py):
VRC7_DB = 11.3
#: 468.8: db_vrc7's tone in summed MO words (one sample's 18), in RMS terms.
VRC7_GAIN = expansion_gain(VRC7_DB, 1) / 468.8
#: The sound's own resonator runs at 3.58 MHz, twice the NTSC CPU clock but not
#: locked to it (VRC7_audio.wiki): taken here as two of its clocks per CPU cycle.
FM_CLOCKS_PER_CPU_CYCLE = 2
FM_CPU_CYCLES_PER_SAMPLE = 72 // FM_CLOCKS_PER_CPU_CYCLE

#: The address line that selects a VRC7 register's second half, by submapper
#: (VRC7.wiki): VRC7b A3 ($x008, *Tiny Toon Adventures 2*), VRC7a A4 ($x010,
#: *Lagrange Point*); submapper 0 answers both.
VRC7_SELECT = {1: 0x08, 2: 0x10, 0: 0x18}


class VRC7(VRCIrq, Banked):
    """Mapper 85: the VRC7's banking and IRQ (VRC7.wiki).

    - $8000, $8008/$8010, $9000: 8 KiB PRG at $8000, $A000, $C000; the last 8 KiB fixed.
    - $A000-$D008/$D010: the eight 1 KiB CHR banks, two per $x000 page.
    - $E000: D7 PRG-RAM enable, D6 sound silenced, D1-D0 vertical, horizontal,
      one-screen lower, upper.
    - $E008/$E010 IRQ latch, $F000 control, $F008/$F010 acknowledge (VRC_IRQ.wiki).
    - $9010 and $9030: the sound chip's address and data ports (VRC7_audio.wiki):
      the DS1001, a YM2413 derivative, from ym2413-python. It is run lazily, a
      sample's 72 clocks at a time and before each write, and drives the expansion
      level with the average of its MO words over its last sample, which the
      multiplexed DAC's output averages to. $E000 D6 holds it in reset (rainwarrior's
      db_vrc7: "disable audio (resets LFO)").

    Power-on registers unspecified: 0 here.
    """

    counts_m2 = True
    expansion_audio = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.select = VRC7_SELECT.get(image.board.submapper, 0x18)
        self.fm = OPLL(DS1001)
        self.fm_pending = 0  # CPU cycles the chip has not run yet
        self.fm_words = [0] * 18  # its last sample's MO words
        self.prg_ram_enabled = False
        self.sound_silenced = False
        self.irq_reset()
        for window in range(3):
            self.map_prg(window, 8, 0)
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        for window in range(8):
            self.map_chr(window, 1, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        region, second = address & 0xF000, bool(address & self.select)
        if region == 0x8000:
            self.map_prg(1 if second else 0, 8, value & 0x3F)
        elif region == 0x9000:
            if not second and not address & 0x30:
                self.map_prg(2, 8, value & 0x3F)
            elif address & 0x20 or second:
                self._run_fm()
                self.fm.write(1 if address & 0x20 else 0, value)
        elif 0xA000 <= region <= 0xD000:
            self.map_chr(((region - 0xA000) >> 11) | second, 1, value)
        elif region == 0xE000:
            if second:
                self.irq_latch = value
            else:
                self.prg_ram_enabled = bool(self.prg_ram) and bool(value & 0x80)
                self._run_fm()
                if value & 0x40 and not self.sound_silenced:
                    self.fm.reset()
                    self.fm_words = [0] * 18
                    self.audio_out.expansion = 0.0
                self.sound_silenced = bool(value & 0x40)
                self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
        elif region == 0xF000:
            if second:
                self.irq_acknowledge()
            else:
                self.irq_control(value)

    def m2(self, t: int) -> None:
        VRCIrq.m2(self, t)
        self.fm_pending += 1
        if self.fm_pending >= FM_CPU_CYCLES_PER_SAMPLE:
            self._run_fm()

    def _run_fm(self) -> None:
        """Bring the sound chip up to this CPU cycle and the expansion level with it."""
        pending, self.fm_pending = self.fm_pending, 0
        if self.sound_silenced or not pending:
            return
        self.fm.run(pending * FM_CLOCKS_PER_CPU_CYCLE)
        words = [mo for mo, _ in self.fm.take_outputs()]
        self.fm_words = (self.fm_words + words)[-18:]
        self.audio_out.expansion = sum(self.fm_words) * VRC7_GAIN


class TH2131(VRC24):
    """NES 2.0 mapper 308: the TH2131-1 board (NTDEC's Batman): a VRC2 with its own IRQ.

    NES_2.0_Mapper_308.wiki: the VRC2's registers (taken as VRC2b's wiring,
    A0/A1, which the page does not state); $F000 (mask $F003) acknowledges,
    stops counting and clears the low counter; $F001 starts it; $F003 D7-D4
    the high counter. Counting, the 12-bit low counter steps every M2 cycle;
    on reaching 2048 the high counter decrements; /IRQ is asserted while
    the high counter is 0 and the low counter below 2048.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(
            image.with_board(replace(image.board, mapper=23, submapper=3)), cpu_cycle_ticks
        )
        self.counts_m2 = True
        self.low = self.high = 0
        self.counting = False

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0xF003
        if register == 0xF000:
            self.counting = False
            self.low = 0
            self.irq = False
        elif register == 0xF001:
            self.counting = True
        elif register == 0xF003:
            self.high = value >> 4
        elif register < 0xF000:
            super().cpu_write(address, value, t)

    def m2(self, t: int) -> None:
        if not self.counting:
            return
        self.low = (self.low + 1) & 0xFFF
        if self.low == 2048:
            self.high = (self.high - 1) & 0x0F
        self.irq = self.high == 0 and self.low < 2048


class TF1201(VRC24):
    """NES 2.0 mapper 298 (UNL-TF1201: Lethal Weapon, a Lethal Enforcers backport): a VRC4b clone.

    NES_2.0_Mapper_298.wiki: VRC4b's wiring (CPU A1 to A0, A0 to A1); its
    $F003 only acknowledges, without the VRC4's copy of the A bit to E (the
    game writes $F003 right after enabling with $F002).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(
            image.with_board(replace(image.board, mapper=25, submapper=1)), cpu_cycle_ticks
        )

    def irq_acknowledge(self) -> None:
        self.irq = False


class ShuiGuan183(VRC24):
    """Mapper 183 (Shui Guan Pipe, a Gimmick! bootleg): VRC4e with an 8 KiB bank at $6000.

    INES_Mapper_183.wiki: a VRC4 clone wired as VRC4e (A0 = CPU A2, A1 = CPU
    A3); a write to $6000-$7FFF selects, by its address's A3-A0, the 8 KiB
    PRG bank read at $6000 (banks 0-15). (The early $A000 register at $C000
    is not on the cartridge.)
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(
            image.with_board(replace(image.board, mapper=23, submapper=2)), cpu_cycle_ticks
        )
        self.bank6000 = 0
        self.prg_ram_enabled = False

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.bank6000 = address & 0x0F
        else:
            super().cpu_write(address, value, t)


#: VRC4e's wiring, the clones below start from.
VRC4E = {"mapper": 23, "submapper": 2}


class CityFighter266(VRC24):
    """Mapper 266 (UNL-CITYFIGHT): City Fighter IV, a VRC4e clone with A13 and A14 exchanged.

    NES_2.0_Mapper_266.wiki: so $A/$B/$D/$E hold the CHR banks at PPU $0800, $1000, $0000,
    $1800. $900C (mask $F80C): D3-D2 a 32 KiB PRG bank in place of the
    VRC4's; $980C: D3-D0 a 4-bit DAC, not modelled (the speech is silent).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.prg32 = 0
        super().__init__(image.with_board(replace(image.board, **VRC4E)), cpu_cycle_ticks)

    def _update_prg(self) -> None:
        self.map_prg(0, 32, self.prg32)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
        elif address & 0xF80C == 0x900C:
            self.prg32 = (value >> 2) & 3
            self._update_prg()
        elif address & 0xF000 == 0x9000:
            if not address & 0x0C:
                super().cpu_write(address, value, t)
        elif address & 0xF000 != 0x8000:
            a13, a14 = (address >> 13) & 1, (address >> 14) & 1
            super().cpu_write((address & 0x9FFF) | a14 << 13 | a13 << 14, value, t)


class Ninja222(VRC24):
    """Mapper 222: pirate VRC2b boards: Dragon Ninja (222.1, CTC-31) and Super Bros. 8 (222.2).

    From the forum's reading of the CTC-31's schematic (t=12654; the page has none):
    $F000 (mask $F003) sets load mode, $F002 count mode, $F001 (mask $F001)
    acknowledges and, in load mode, takes the count. Counting, the '4020 runs
    and each rise of its 64s bit clocks two 74161s: the low one, and when it
    reaches 15 the high one (so $0E goes to $1F, then $10). When the high one
    reaches 15, /IRQ asserts and holds the '4020 at 0. 222.2 writes a whole
    CHR bank to both $B000 and $B001 and the board takes it (forum, and the game).
    The submapper numbers are those of the dumps' headers; no page defines them.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.whole_chr = image.board.submapper == 2
        board = replace(image.board, mapper=23, submapper=3)
        super().__init__(image.with_board(board), cpu_cycle_ticks)
        self.counts_m2 = True
        self.loading = True
        self.count = self.divider = 0

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if self.whole_chr and 0xB000 <= address < 0xF000:
            if not address & 1:
                super().cpu_write(address, value & 0x0F, t)
                super().cpu_write(address | 1, value >> 4, t)
        elif address & 0xF003 == 0xF000:
            self.loading = True
        elif address & 0xF003 == 0xF002:
            self.loading = False
        elif address & 0xF001 == 0xF001:
            self.irq = False
            if self.loading:
                self.count = value
        else:
            super().cpu_write(address, value, t)

    def m2(self, t: int) -> None:
        if self.loading or self.irq:
            self.divider = 0
            return
        self.divider = (self.divider + 1) & 0x3FFF
        if self.divider & 0x7F == 0x40:
            low, high = ((self.count & 0x0F) + 1) & 0x0F, self.count >> 4
            if low == 15:
                high = (high + 1) & 0x0F
            self.count = high << 4 | low
            if high == 15:
                self.irq = True


class KidDracula272(VRC24):
    """Mapper 272: a bootleg Akumajou Special: a VRC2b clone with a PAL for IRQs and mirroring.

    From lidnariq's and krzysiobal's analyses of the PAL (forum t=15302; the page has none),
    the extra registers on mask $C00C beside the VRC2's on $F003, so a write
    to $9004 reaches both: $8004 D1 one-screen in place of the VRC2's
    arrangement, D0 which; $C004 acknowledges; $C008 lets the counter run;
    $C00C acknowledges and holds it at 0; $800C forces the IRQ. The counter
    counts PPU A13's falls and at 86 (two scanlines) clears itself and asserts
    /IRQ. krzysiobal found 84 looks better on a line-based emulator; this is
    not one, so the PAL's 86.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        board = replace(image.board, mapper=23, submapper=3)
        super().__init__(image.with_board(board), cpu_cycle_ticks)
        self.arrangement = VERTICAL
        self.extended = 0
        self.a13 = self.count = 0
        self.running = False

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            extra = address & 0xC00C
            if extra == 0x8004:
                self.extended = value & 3
            elif extra == 0x800C:
                self.irq = True
            elif extra == 0xC004:
                self.irq = False
            elif extra == 0xC008:
                self.running = True
            elif extra == 0xC00C:
                self.irq = self.running = False
                self.count = 0
            if address & 0xF003 == 0x9000:
                self.arrangement = HORIZONTAL if value & 1 else VERTICAL
        super().cpu_write(address, value, t)
        if address >= 0x8000:
            if self.extended & 2:
                self.set_mirroring(SCREEN_B if self.extended & 1 else SCREEN_A)
            else:
                self.set_mirroring(self.arrangement)

    def ppu_address(self, address: int, t: int) -> None:
        a13 = address & 0x2000
        if self.a13 and not a13 and self.running:
            self.count += 1
            if self.count == 86:
                self.count = 0
                self.irq = True
        self.a13 = a13


def swap_bits(value: int, a: int, b: int) -> int:
    """``value`` with bits ``a`` and ``b`` exchanged."""
    if (value >> a ^ value >> b) & 1:
        return value ^ (1 << a | 1 << b)
    return value


class AX5705(VRC24):
    """Mapper 530 (UNL-AX5705): Super Mario Bros. Pocker Mali, a scrambled VRC4f clone.

    NES_2.0_Mapper_530.wiki: a VRC4 with A0/A1 (VRC4f, 23.1) whose PRG A14 and A16
    are exchanged, and CHR A15 and A16. The game decides what the page leaves
    out: it writes $8008, $A008, $C008 and $E008 for the VRC4's $9000, $B000,
    $D000 and $F000, so A3 stands in for A12 (C66).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        board = replace(image.board, mapper=23, submapper=1)
        super().__init__(image.with_board(board), cpu_cycle_ticks)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            address = (address & 0xE003) | (address & 8) << 9
        super().cpu_write(address, value, t)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        super().map_prg(window, size_kib, swap_bits(bank, 1, 3))

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        super().map_chr(window, size_kib, swap_bits(bank, 5, 6))


class T230(VRC24):
    """Mapper 529 (UNL-T-230): bootleg Dragon Ball Z: a VRC4e clone with 16 KiB banking.

    NES_2.0_Mapper_529.wiki: $800x does nothing; $A00x selects the 16 KiB bank at $8000
    (the last is fixed at $C000). With PRG-NVRAM in the header, a 93C56 on
    $8800 (mask $8800, also the VRC4's): D2 CS, D1 CLK, D0 DI, and $5000 (mask
    $F000) reads DO on D0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image.with_board(replace(image.board, **VRC4E)), cpu_cycle_ticks)
        self.eeprom = Microwire93C56() if image.board.prg_nvram else None
        self.prg_ram = bytearray()
        self.prg_ram_enabled = False

    def _update_prg(self) -> None:
        self.map_prg(0, 16, self.prg_registers[1])
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.eeprom and address & 0xF000 == 0x5000:
            return self.eeprom.output | 0xFE << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if self.eeprom and address & 0x8800 == 0x8800:
            self.eeprom.lines((value >> 2) & 1, (value >> 1) & 1, value & 1)
        if address & 0xF000 != 0x8000:
            super().cpu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.eeprom.memory) if self.eeprom else None

    def _restore(self, data: bytes) -> None:
        if self.eeprom:
            self.eeprom.memory[:] = data


#: Mapper 544's CHR-RAM window by the value written to CHR-ROM (D7, D6, D3, D1): (first bank,
#: banks), compared with the bank's low 8 bits; None for ROM only.
FS306_WINDOWS = {
    0x80: (0x28, 4),
    0x82: (0x00, 4),
    0x88: (0x4C, 4),
    0x8A: (0x64, 4),
    0xC0: (0x46, 2),
    0xC2: (0x7C, 2),
    0xC8: (0x04, 2),
    0xCA: None,
}


class FS306(VRC24):
    """Mapper 544: Waixing's FS306 (Bawang de Dalu): a VRC4 clone with a third PRG bank.

    NES_2.0_Mapper_544.wiki: the clone's A0 and A1 are CPU A10 and A11. Its External
    Select, $9C00 in that wiring: with A2 clear D4-D0 the 8 KiB bank at $C000;
    with A2 set D0 the CIRAM page for the nametable A1-A0 names. A write to
    a CHR-ROM bank numbered with D7 set moves 2 KiB of CHR-RAM, the bank's
    number and not the data choosing where (the page's ``CHRB~``;
    :data:`FS306_WINDOWS`, D4: ROM only). 8 KiB of battery RAM at $6000 always. The page's IRQ "one
    M2 later than a VRC4" is not modelled.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.prg_c000 = 0
        self.rom = image.chr
        self.chr_ram = bytearray(0x800)
        self.chr_ram_window = [False] * 8
        self.chr_banks = [0] * 8
        self.ram_range: tuple[int, int] | None = FS306_WINDOWS[0x80]
        super().__init__(image.with_board(replace(image.board, **VRC4E)), cpu_cycle_ticks)
        self.lines0, self.lines1 = (10,), (11,)
        self.ciram = [0, 1, 0, 1] if self.mirroring == VERTICAL else [0, 0, 1, 1]
        self.prg_ram = bytearray(max(len(self.prg_ram), 0x2000))
        self.prg_ram_mask = 0x1FFF
        self.prg_ram_enabled = True
        self._remap()

    def _update_prg(self) -> None:
        self.map_prg(0, 8, self.prg_registers[0])
        self.map_prg(1, 8, self.prg_registers[1])
        self.map_prg(2, 8, self.prg_c000)
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        self.chr_banks[window] = bank
        self._remap()

    def _remap(self) -> None:
        for window, bank in enumerate(self.chr_banks):
            low = bank & 0xFF
            first, count = self.ram_range or (0, 0)
            ram = first <= low < first + count
            self.chr_ram_window[window] = ram
            self.chr_offsets[window] = (
                (low - first) % 2 * 0x400 if ram else bank * 0x400 % len(self.rom)
            )

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF000 != 0x9000:
            super().cpu_write(address, value, t)
        elif address & 0x0C00 == 0x0C00:
            if address & 4:
                self.ciram[address & 3] = value & 1
            else:
                self.prg_c000 = value & 0x1F
                self._update_prg()

    def ciram_a10(self, address: int) -> int | None:
        return self.ciram[(address >> 10) & 3]

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            window = address >> 10
            memory = self.chr_ram if self.chr_ram_window[window] else self.rom
            return memory[self.chr_offsets[window] + (address & 0x3FF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x2000:
            super().ppu_write(address, value, t)
            return
        window = address >> 10
        if self.chr_ram_window[window]:
            self.chr_ram[self.chr_offsets[window] + (address & 0x3FF)] = value
        elif self.chr_banks[window] & 0x80:
            bank = self.chr_banks[window]
            self.ram_range = None if bank & 0x10 else FS306_WINDOWS[bank & 0xCA]
            self._remap()
