"""Taito's mappers: TC0190 (33).

No judge ROM exists (docs/cartridge.md); the claim rests on milestone 7's
sweep against Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage


class TC0190(Banked):
    """Mapper 33: two 8 KiB PRG banks and the last two fixed; CHR 2 KiB x 2 and 1 KiB x 4.

    INES_Mapper_033.wiki (register mask $A003): $8000 D5-D0 selects $8000 and
    D6 the arrangement (0 vertical, 1 horizontal); $8001 selects $A000;
    $8002/$8003 the 2 KiB CHR banks at $0000/$0800, numbered in 2 KiB units
    (unlike the MMC3's); $A000-$A003 the 1 KiB banks at $1000-$1C00. No IRQ,
    no PRG-RAM. Power-on registers unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        last = len(self.prg) // 0x2000 - 1
        self.map_prg(2, 8, last - 1)
        self.map_prg(3, 8, last)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not 0x8000 <= address < 0xC000:
            return
        register = address & 0xA003
        if register == 0x8000:
            self.map_prg(0, 8, value & 0x3F)
            self.set_mirroring(HORIZONTAL if value & 0x40 else VERTICAL)
        elif register == 0x8001:
            self.map_prg(1, 8, value & 0x3F)
        elif register in (0x8002, 0x8003):
            self.map_chr((register & 1) * 2, 2, value)
        else:
            self.map_chr(4 + (register & 3), 1, value)
