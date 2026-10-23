"""Konami's VRC mappers: VRC1 (75), VRC2 and VRC4 (21, 22, 23, 25), and the VRC IRQ.

AWJ's ``vrctest`` judges the VRC2/VRC4 wiring and IRQ (docs/claims.md); no
judge ROM exists for the VRC1, whose claim rests on milestone 7's sweep
against Mesen2, a detector.
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage


class VRC1(Banked):
    """Mapper 75: three 8 KiB PRG banks and the last fixed; two 4 KiB CHR banks of five bits.

    VRC1.wiki: $8000, $A000 and $C000 select PRG for their own windows; $9000
    D0 is the nametable arrangement (0 vertical, 1 horizontal; ignored when
    the board has four-screen VRAM) and D1/D2 the CHR banks' high bits;
    $E000 and $F000 their low four bits. Each register decodes $x000-$xFFF.
    Power-on registers unspecified: 0 here.
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
            self.map_prg((region - 0x8000) >> 13, 8, value & 0x0F)
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
