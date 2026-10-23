"""Jaleco's mappers: SS88006 (18).

No judge ROM exists (docs/cartridge.md); the claim rests on milestone 7's
sweep against Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage

# $F001: D3 overrides D2 overrides D1; none set, the counter is 16 bits.
COUNTER_MASKS = ((8, 0x000F), (4, 0x00FF), (2, 0x0FFF), (0, 0xFFFF))


class SS88006(Banked):
    """Mapper 18: three 8 KiB PRG banks and the last fixed, eight 1 KiB CHR banks, all in nibbles.

    INES_Mapper_018.wiki (register mask $F003): $8000-$9001 the PRG banks'
    low and high nibbles in pairs ($8000/1 for $8000, $8002/3 for $A000,
    $9000/1 for $C000); $9002 D0 enables PRG-RAM, D1 allows writing (the
    MMC3's sense inverted); $A000-$D003 the CHR banks' nibbles in pairs;
    $E000-$E003 the 16-bit reload value, low nibble first; $F000 reloads the
    counter and acknowledges; $F001 sets the counter's width (D3: 4 bits, D2:
    8, D1: 12) and D0 counting, and acknowledges; $F002 D1-D0 the arrangement
    (horizontal, vertical, one-screen A, one-screen B). While counting, the
    counter's low bits (the width) count down each M2 cycle, the rest left
    alone; a borrow out of them asserts /IRQ. $F003 drives the ADPCM chip
    some boards carry (not modelled). Power-on registers unspecified: 0 here.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_registers = [0, 0, 0]
        self.chr_registers = [0] * 8
        self.reload = [0, 0, 0, 0]
        self.counter = 0
        self.mask = 0xFFFF
        self.counting = False
        self.prg_ram_enabled = False
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def m2(self, t: int) -> None:
        if self.counting:
            mask = self.mask
            low = self.counter & mask
            if not low:
                self.irq = True
            self.counter = (self.counter & ~mask) | ((low - 1) & mask)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        value &= 0x0F
        register = address & 0xF003
        group, high = (register >> 12) - 8, (register & 1) * 4
        if register < 0x9002:
            bank = 2 if register >= 0x9000 else (register >> 1) & 1
            nibble = self.prg_registers[bank]
            self.prg_registers[bank] = (nibble & (0xF0 >> high)) | value << high
            self.map_prg(bank, 8, self.prg_registers[bank])
        elif register == 0x9002:
            self.prg_ram_enabled = bool(self.prg_ram) and bool(value & 1)
            self.prg_ram_writable = bool(value & 2)
        elif 0xA000 <= register < 0xE000:
            bank = (group - 2) * 2 + ((register >> 1) & 1)
            nibble = self.chr_registers[bank]
            self.chr_registers[bank] = (nibble & (0xF0 >> high)) | value << high
            self.map_chr(bank, 1, self.chr_registers[bank])
        elif register < 0xF000:
            self.reload[register & 3] = value
        elif register == 0xF000:
            r = self.reload
            self.counter = r[0] | r[1] << 4 | r[2] << 8 | r[3] << 12
            self.irq = False
        elif register == 0xF001:
            self.mask = next(mask for bit, mask in COUNTER_MASKS if value & bit or not bit)
            self.counting = bool(value & 1)
            self.irq = False
        elif register == 0xF002:
            self.set_mirroring((HORIZONTAL, VERTICAL, SCREEN_A, SCREEN_B)[value & 3])
