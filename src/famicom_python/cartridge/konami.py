"""Konami's VRC mappers: VRC1 (75), VRC2 and VRC4 (21, 22, 23, 25), VRC6 (24, 26), the VRC IRQ.

AWJ's ``vrctest`` judges the VRC2/VRC4 wiring and IRQ (docs/claims.md); no
judge ROM exists for the VRC1, whose claim rests on milestone 7's sweep
against Mesen2, a detector. The VRC6's sound level is rainwarrior's
``db_vrc6`` measurement (milestone 8).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .connector import expansion_gain
from .ines import RomImage


class VRC1(Banked):
    """Mapper 75: three 8 KiB PRG banks and the last fixed; two 4 KiB CHR banks of five bits.

    VRC1.wiki: $8000, $A000 and $C000 select PRG for their own windows; $9000
    D0 is the nametable arrangement (0 vertical, 1 horizontal; ignored when
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
