"""Discrete-logic boards: NROM (0), UxROM (2), CNROM (3), AxROM (7), CPROM (13), UNROM 512
(30), BNROM and NINA-001 (34), GxROM (66), J87 (87), UN1ROM (94), UNROM with a fixed first
bank (180) and CNROM with copy-protection diodes (185).

Judged in milestone 5 by Holy Mapperel, rainwarrior's ``2_test``,
``3_test``, ``7_test`` and ``34_test``, and tepples's ``bntest``
(docs/claims.md); 66 by Holy Mapperel; 87 and 185 have no judge (milestone 7's
sweep against Mesen2, a detector); 30, milestone 8's homebrew board, by its
own tests (tests/test_mappers.py); 13, 94 and 180 have no judge ROM (sweeps
against Mesen2).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .flash import SST39SF040
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


class GxROM(Banked):
    """Mapper 66: a write to $8000-$FFFF selects the 32 KiB PRG bank (D5-D4) and 8 KiB CHR (D1-D0).

    GxROM.wiki: a 74HC161 latch, always with AND-type bus conflicts. Power-on
    banks unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        value = self.bus_conflict(address, value)
        self.map_prg(0, 32, (value >> 4) & 3)
        self.map_chr(0, 8, value & 3)


class J87(NROM):
    """Mapper 87: a write to $6000-$7FFF selects the 8 KiB CHR bank, its two bits swapped.

    INES_Mapper_087.wiki: D0 is CHR A14 and D1 CHR A13; no bus conflicts (the
    register is not in ROM space). Power-on bank unspecified: 0 here.
    """

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.map_chr(0, 8, ((value & 1) << 1) | ((value >> 1) & 1))


class CNROMProtected(NROM):
    """Mapper 185: CNROM with 8 KiB of CHR, enabled only by the right chip-select bits.

    CNROM.wiki "Mapper 185": a write to $8000-$FFFF (always AND-type bus
    conflicts) sets CS1/CS2 from D1-D0; submappers 4-7 name the value (0-3)
    that enables CHR-ROM. Every licensed dump has one; submapper 0 (value
    unknown) is left unprotected. A disabled CHR-ROM leaves the PPU bus
    undriven: the address's low byte, with D0 pulled up (the wiki: Mighty
    Bomb Jack's 10k pull-up, which its first revision needs to boot). The
    latch powers on enabled, as Mesen2 has it (Mappers/Nintendo/CnromProtect.h).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        submapper = image.board.submapper
        self.enabling = submapper - 4 if 4 <= submapper <= 7 else None
        self.chr_enabled = True

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.enabling is not None:
            self.chr_enabled = self.bus_conflict(address, value) & 3 == self.enabling

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000 and not self.chr_enabled:
            return (address & 0xFF) | 1
        return super().ppu_read(address, t)


class UN1ROM(UxROM):
    """Mapper 94: HVC-UN1ROM (Senjou no Ookami): UxROM with the bank in D4-D2.

    INES_Mapper_094.wiki: always AND-type bus conflicts.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bus_conflicts = True

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        self.map_prg(0, 16, (self.bus_conflict(address, value) >> 2) & 7)


class UNROM180(NROM):
    """Mapper 180: UNROM with an AND gate (Crazy Climber): the first 16 KiB fixed, $C000 switched.

    INES_Mapper_180.wiki: D2-D0 select the bank at $C000. The page says
    nothing of bus conflicts: as UxROM, by submapper (2 has them).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bus_conflicts = image.board.submapper == 2
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.bus_conflicts:
            value = self.bus_conflict(address, value)
        self.map_prg(2, 16, value & 7)


class CPROM(NROM):
    """Mapper 13: NES-CPROM (Videomation): 16 KiB of CHR-RAM in 4 KiB pages.

    CPROM.wiki: PPU $0000-$0FFF is the first page; a write to $8000-$FFFF
    (AND-type bus conflicts) selects the page at $1000 from D1-D0. Power-on
    page unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr = bytearray(0x4000)
        self.chr_writable = True
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        self.map_chr(4, 4, self.bus_conflict(address, value) & 3)


class AOROMMulticart(AxROM):
    """NES 2.0 mapper 470: INX_007T_V01 (Retro-Bit's Battletoads and Double Dragon).

    NES_2.0_Mapper_470.wiki: AOROM with a register at $5000-$5FFF selecting
    the 256 KiB outer bank, which a reset clears (:meth:`m2_gap`).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = self.inner = 0
        super().__init__(image, cpu_cycle_ticks)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            self.outer = value
            self.map_prg(0, 32, self.inner)
            return
        super().cpu_write(address, value, t)

    def m2_gap(self, t: int) -> None:
        self.outer = 0
        self.map_prg(0, 32, self.inner)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        self.inner = bank & 7
        super().map_prg(window, size_kib, self.outer << 3 | self.inner)


def mapper_34(image: RomImage, cpu_cycle_ticks: int) -> Banked:
    """Mapper 34's board by submapper; without one, CHR over 8 KiB means NINA-001 (the wiki)."""
    submapper = image.board.submapper
    if submapper == 1 or (submapper != 2 and len(image.chr) > 0x2000):
        return NINA001(image, cpu_cycle_ticks)
    return BNROM(image, cpu_cycle_ticks)


class UNROM512(Banked):
    """Mapper 30: UNROM 512, RetroUSB's and InfiniteNESLives' homebrew board.

    UNROM_512.wiki: a write sets ``NCCPPPPP``: the 16 KiB PRG bank at $8000
    ($C000 the last), the 8 KiB CHR-RAM bank (32 KiB) and, with one-screen
    nametables, which screen. Header byte 6 D3/D0 wire the nametables:
    vertical arrangement, horizontal, one-screen switchable, or four screens
    of cartridge VRAM, the CHR-RAM's last 8 KiB. Submapper 3 switches
    horizontal and vertical with N instead (Mega Man II 30th Anniversary).

    Bus conflicts on submapper 2, and on 0 without the battery bit; there the
    register answers all of $8000-$FFFF. On the others it is at $C000-$FFFF,
    and with the battery bit $8000-$BFFF is the flash's command port
    (:class:`~.flash.SST39SF040`), the flash address made of the latched
    bank and A13-A0; the flash is the save (:meth:`battery_ram`). The
    submapper-4 LEDs take their writes and show nothing.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.submapper = board.submapper
        flags6 = (
            image.header[6]
            if len(image.header) > 6
            else (0x08 if board.mirroring == "4" else 0x01 if board.mirroring == "V" else 0)
        )
        self.one_screen = flags6 & 0x09 == 0x08 and self.submapper != 3
        self.cart_vram = flags6 & 0x09 == 0x09 and self.submapper != 3
        self.bus_conflicts = self.submapper == 2 or (self.submapper == 0 and not board.battery)
        self.flashable = board.battery and self.submapper in (0, 1, 4)
        self.prg = bytearray(image.prg)
        if not image.chr and not (image.nes2 and board.chr_ram + board.chr_nvram):
            self.chr = bytearray(0x8000)  # iNES says nothing: 32 KiB (the wiki)
        self.four_screen = False
        self.latch = 0
        self.flash = SST39SF040(self.prg)
        last = len(self.prg) // 0x4000 - 1
        self.map_prg(2, 16, last)
        self._apply(0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.bus_conflicts:
            self._apply(self.bus_conflict(address, value))
        elif address >= 0xC000:
            self._apply(value)
        elif self.flashable:
            self.flash.write(self._flash_offset(address), value)

    def _apply(self, value: int) -> None:
        self.latch = value
        self.map_prg(0, 16, value & 0x1F)
        self.map_chr(0, 8, (value >> 5) & 3)
        if self.one_screen:
            self.set_mirroring(SCREEN_B if value & 0x80 else SCREEN_A)
        elif self.submapper == 3:
            self.set_mirroring(VERTICAL if value & 0x80 else HORIZONTAL)

    def _flash_offset(self, address: int) -> int:
        """The flash address of a CPU address in $8000-$BFFF."""
        return ((self.latch & 0x1F) << 14 | (address & 0x3FFF)) % len(self.prg)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.flash.id_mode and address >= 0x8000:
            offset = self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)
            return self.flash.read(offset)
        return super().cpu_read(address, t)

    def ciram_a10(self, address: int) -> int | None:
        if self.cart_vram:
            return None
        return super().ciram_a10(address)

    def ppu_read(self, address: int, t: int) -> int | None:
        if self.cart_vram and address >= 0x2000:
            return self.chr[len(self.chr) - 0x2000 + (address & 0x1FFF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if self.cart_vram and address >= 0x2000:
            self.chr[len(self.chr) - 0x2000 + (address & 0x1FFF)] = value
            return
        super().ppu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg) if self.flashable else None

    def _restore(self, data: bytes) -> None:
        self.prg[:] = data
