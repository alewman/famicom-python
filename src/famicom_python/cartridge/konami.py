"""Konami's VRC mappers: VRC1 (75).

No judge ROM exists for the VRC1 (docs/cartridge.md); its claim rests on
milestone 7's sweep against Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
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
