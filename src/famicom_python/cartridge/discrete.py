"""Discrete-logic boards: NROM (0), UxROM (2), CNROM (3), AxROM (7), BNROM and NINA-001 (34).

Judged in milestone 5 by Holy Mapperel, rainwarrior's ``2_test``,
``3_test``, ``7_test`` and ``34_test``, and tepples's ``bntest``
(docs/claims.md).
"""

from __future__ import annotations

from .banked import SCREEN_A, SCREEN_B, Banked
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
            value = self.bus_conflict(address, value)
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
            value = self.bus_conflict(address, value)
        self.map_chr(0, 8, value)


class AxROM(Banked):
    """Mapper 7: a write to $8000-$FFFF selects the 32 KiB PRG bank and the screen (D4).

    AxROM.wiki: D2-D0 select the bank; D3 is taken too, as PRG A18 for
    oversize images. Submapper 2 has AND-type bus conflicts (AMROM, some
    AOROM); 1 and 0 have none, 0 because ANROM games rely on their absence
    (NES_2.0_submappers.wiki). The latch's power-on value is unspecified:
    bank 0 and screen A here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bus_conflicts = image.board.submapper == 2
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)
        self.set_mirroring(SCREEN_A)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.bus_conflicts:
            value = self.bus_conflict(address, value)
        self.map_prg(0, 32, value & 0x0F)
        self.set_mirroring(SCREEN_B if value & 0x10 else SCREEN_A)


class BNROM(Banked):
    """Mapper 34.2: a write to $8000-$FFFF selects the 32 KiB PRG bank; CHR is fixed.

    INES_Mapper_034.wiki "BNROM": D1-D0 on the board, every bit taken for
    oversize images (as ``bntest`` finds emulators do); always AND-type bus
    conflicts. Power-on bank unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        self.map_prg(0, 32, self.bus_conflict(address, value))


class NINA001(Banked):
    """Mapper 34.1: registers at $7FFD-$7FFF, written through to the PRG-RAM beneath.

    INES_Mapper_034.wiki "NINA-001/NINA-002": $7FFD D0 selects the 32 KiB PRG
    bank, $7FFE and $7FFF the 4 KiB CHR banks at PPU $0000 and $1000; no bus
    conflicts. Power-on banks unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        super().cpu_write(address, value, t)
        if address == 0x7FFD:
            self.map_prg(0, 32, value)
        elif address == 0x7FFE:
            self.map_chr(0, 4, value)
        elif address == 0x7FFF:
            self.map_chr(4, 4, value)


def mapper_34(image: RomImage, cpu_cycle_ticks: int) -> Banked:
    """Mapper 34's board by submapper; without one, CHR over 8 KiB means NINA-001 (the wiki)."""
    submapper = image.board.submapper
    if submapper == 1 or (submapper != 2 and len(image.chr) > 0x2000):
        return NINA001(image, cpu_cycle_ticks)
    return BNROM(image, cpu_cycle_ticks)
