"""MMC2 (mapper 9) and MMC4 (mapper 10): CHR banks that the PPU's own fetches switch.

MMC2.wiki and MMC4.wiki; judged by Holy Mapperel (docs/claims.md), which has
no latch-timing test, so the latch's timing rests on milestone 7's sweep
against Mesen2, a detector.
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage


class MMC2(Banked):
    """Mapper 9: 8 KiB PRG at $8000 (the last three fixed), two latched pairs of 4 KiB CHR banks.

    Each pattern table has two CHR registers ($B000/$C000 for $0000-$0FFF,
    $D000/$E000 for $1000-$1FFF) and a latch choosing between them: a PPU read
    of $0FD8 sets latch 0 to $FD, $0FE8 to $FE; $1FD8-$1FDF and $1FE8-$1FEF
    set latch 1. The latch changes *after* the triggering read, so the $FD or
    $FE tile itself is drawn from the old bank (the wiki, from the forum's
    "Glitch in the Matrix" thread). $F000 D0: 0 vertical, 1 horizontal.
    Power-on: latches $FE, registers 0 (unspecified; games set them).
    """

    prg_bank_kib = 8
    latch0_range = 1  # $0FD8 only on the MMC2; $0FD8-$0FDF on the MMC4

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr_registers = [0, 0, 0, 0]  # $FD/0000, $FE/0000, $FD/1000, $FE/1000
        self.latches = [1, 1]  # 0 = $FD, 1 = $FE
        last = len(self.prg) // 0x2000 - 1
        if self.prg_bank_kib == 8:
            for window in (1, 2, 3):
                self.map_prg(window, 8, last - 3 + window)
        else:
            self.map_prg(2, 16, last // 2)
        self.map_prg(0, self.prg_bank_kib, 0)
        self._update_chr()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        region = address & 0xF000
        if region == 0xA000:
            self.map_prg(0, self.prg_bank_kib, value & 0x0F)
        elif region == 0xF000:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        elif region >= 0xB000:
            self.chr_registers[(region >> 12) - 0xB] = value & 0x1F
            self._update_chr()

    def _update_chr(self) -> None:
        r, latch = self.chr_registers, self.latches
        self.map_chr(0, 4, r[latch[0]])
        self.map_chr(4, 4, r[2 + latch[1]])

    def ppu_read(self, address: int, t: int) -> int | None:
        value = super().ppu_read(address, t)
        if address < 0x2000 and address & 0x0FF0 in (0x0FD0, 0x0FE0):
            low = address & 0x0F
            high = address >> 12
            if low >= 8 and (high or low < 8 + self.latch0_range):
                latch = 1 if address & 0x0020 else 0
                if self.latches[high] != latch:
                    self.latches[high] = latch
                    self._update_chr()
        return value


class MMC4(MMC2):
    """Mapper 10: MMC2 with 16 KiB PRG banking, 8 KiB PRG-RAM, and both latches over a range.

    MMC4.wiki: $A000 selects 16 KiB at $8000, the last 16 KiB fixed; $0FD8-$0FDF
    and $0FE8-$0FEF set latch 0, as $1FDx does latch 1.
    """

    prg_bank_kib = 16
    latch0_range = 8
