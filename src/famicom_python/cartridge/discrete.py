"""Discrete-logic boards: NROM (mapper 0), UxROM (mapper 2) and CNROM (mapper 3).

Certification of each mapper is milestone 5 (Holy Mapperel, rainwarrior's
``2_test``/``3_test``); milestones 1 and 2 need them only to run their test
ROMs (the CPU tests; the 240p Test Suite is UxROM).
"""

from __future__ import annotations

from .banked import Banked
from .ines import RomImage


class NROM(Banked):
    """Mapper 0: 16 or 32 KiB of PRG (16 KiB mirrored), 8 KiB of CHR, no registers.

    NROM.wiki. 8 KiB PRG images exist and mirror four times.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        for window in range(4):
            self.map_prg(window, 8, window)
        self.map_chr(0, 8, 0)


class UxROM(NROM):
    """Mapper 2: a write to $8000-$FFFF selects the 16 KiB bank at $8000; $C000 is the last.

    UxROM.wiki. The register is taken as a full 8-bit bank number, as
    emulators of iNES mapper 2 do (UxROM.wiki "Variants"). Submapper 2 has
    AND-type bus conflicts; 1 has none; 0 is "unknown" and treated as 1
    (NES_2.0_submappers.wiki).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bus_conflicts = image.board.submapper == 2
        last = len(image.prg) // 0x4000 - 1
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, last)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.bus_conflicts:
            value &= self.prg[self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)]
        self.map_prg(0, 16, value)


class CNROM(NROM):
    """Mapper 3: a write to $8000-$FFFF selects the 8 KiB CHR bank.

    INES_Mapper_003.wiki. Submapper 2 has AND-type bus conflicts (the CPU's value
    ANDed with the ROM byte at the written address); 1 has none; 0 says nothing,
    and is treated as 1 here (NES_2.0_submappers.wiki).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bus_conflicts = image.board.submapper == 2

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.bus_conflicts:
            value &= self.prg[self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)]
        self.map_chr(0, 8, value)
