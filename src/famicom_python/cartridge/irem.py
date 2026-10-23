"""Irem's mappers: G-101 (32).

No judge ROM exists (docs/cartridge.md); the claim rests on milestone 7's
sweep against Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_B, VERTICAL, Banked
from .ines import RomImage


class G101(Banked):
    """Mapper 32: two 8 KiB PRG banks (one movable), the last two fixed; eight 1 KiB CHR banks.

    INES_Mapper_032.wiki (register mask $F000, $F007 for CHR): $8000 selects
    8 KiB at $8000, or at $C000 when $9000 D1 (the PRG mode) is set, the
    second-last bank taking the other place; $A000 selects $A000; $B000-$B007
    the CHR banks; $9000 D0 the nametable arrangement (0 vertical, 1
    horizontal). Submapper 1 (Major League): CIRAM A10 tied high, a single
    screen, and $9000 disabled. Power-on registers unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.major_league = image.board.submapper == 1
        self.prg_ram_enabled = False
        self.prg_registers = [0, 0]
        self.prg_mode = 0
        if self.major_league:
            self.set_mirroring(SCREEN_B)
        self._update_prg()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        region = address & 0xF000
        if region == 0x8000:
            self.prg_registers[0] = value & 0x1F
            self._update_prg()
        elif region == 0x9000:
            if not self.major_league:
                self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
                self.prg_mode = value & 2
                self._update_prg()
        elif region == 0xA000:
            self.prg_registers[1] = value & 0x1F
            self._update_prg()
        elif region == 0xB000:
            self.map_chr(address & 7, 1, value)

    def _update_prg(self) -> None:
        last = len(self.prg) // 0x2000 - 1
        first, third = self.prg_registers[0], last - 1
        if self.prg_mode:
            first, third = third, first
        self.map_prg(0, 8, first)
        self.map_prg(1, 8, self.prg_registers[1])
        self.map_prg(2, 8, third)
        self.map_prg(3, 8, last)
