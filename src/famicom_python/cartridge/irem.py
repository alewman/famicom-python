"""Irem's mappers: G-101 (32), H3001 (65), LROG017 (77) and TAM-S1 (97).

No judge ROM exists (docs/cartridge.md); the claims rest on sweeps against
Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
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


class LROG017(Banked):
    """Mapper 77: Irem LROG017 (Napoleon Senki): CHR-ROM, CHR-RAM and cartridge nametables.

    INES_Mapper_077.wiki: a write to $8000-$FFFF (AND-type bus conflicts)
    sets ``CCCCPPPP``, the 32 KiB PRG bank and the 2 KiB CHR-ROM bank at PPU
    $0000. A 74138 splits the PPU's space in 2 KiB regions: $0800-$27FF is
    one 8 KiB RAM (pattern tables and the first two nametables), $2800-$2FFF
    CIRAM, and $3000-$3EFF nothing (open bus). Power-on banks unspecified: 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.rom = image.chr
        self.ram = bytearray(0x2000)  # PPU $0800-$27FF
        self.rom_offset = 0
        self.map_prg(0, 32, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        value = self.bus_conflict(address, value)
        self.map_prg(0, 32, value & 0x0F)
        self.rom_offset = ((value >> 4) * 0x800) % len(self.rom)

    def ciram_a10(self, address: int) -> int | None:
        return (address >> 10) & 1 if address & 0x1800 == 0x0800 else None

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x0800:
            return self.rom[self.rom_offset + address]
        if address < 0x2800:
            return self.ram[address - 0x0800]
        return None

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if 0x0800 <= address < 0x2800:
            self.ram[address - 0x0800] = value


class TAMS1(Banked):
    """Mapper 97: Irem TAM-S1 (Kaiketsu Yanchamaru): the last 16 KiB at $8000, $C000 switched.

    INES_Mapper_097.wiki: a write to $8000-$BFFF sets ``M..PPPPP``, the 16 KiB
    bank at $C000 and the arrangement (0 horizontal, 1 vertical); no bus
    conflicts. Power-on bank unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 16, len(self.prg) // 0x4000 - 1)
        self.map_prg(2, 16, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x8000 <= address < 0xC000:
            self.map_prg(2, 16, value & 0x1F)
            self.set_mirroring(VERTICAL if value & 0x80 else HORIZONTAL)
        else:
            super().cpu_write(address, value, t)


class H3001(Banked):
    """Mapper 65: Irem H3001: three 8 KiB PRG banks, eight 1 KiB CHR banks, a cycle counter.

    INES_Mapper_065.wiki (mask $F007): $8000 the bank at $8000, or at $C000
    when $9000 D7 is set (the second-last bank taking the other place); $A000
    the bank at $A000; the last fixed. (Disch's notes' switchable $C000 does
    not exist, the wiki's forum citation.) $B000-$B007 the CHR banks; $9001
    D7-D6 the arrangement (00 vertical, 10 horizontal, x1 one-screen A).
    $9005/$9006 the reload value's high and low bytes; $9004 copies it into
    the counter; $9003 D7 enables. Both acknowledge. Enabled, the 16-bit
    counter decrements every CPU cycle and asserts /IRQ on reaching 0, where
    it stops. Power-on: $8000 = 0 and $A000 = 1 (games rely on it, the wiki).
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_mode = 0
        self.prg0 = 0
        self.reload = 0
        self.counter = 0
        self.enabled = False
        self.map_prg(1, 8, 1)
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        self._map_prg0()

    def _map_prg0(self) -> None:
        second_last = len(self.prg) // 0x2000 - 2
        if self.prg_mode:
            self.map_prg(0, 8, second_last)
            self.map_prg(2, 8, self.prg0)
        else:
            self.map_prg(0, 8, self.prg0)
            self.map_prg(2, 8, second_last)

    def m2(self, t: int) -> None:
        if self.enabled and self.counter:
            self.counter -= 1
            if self.counter == 0:
                self.irq = True

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = address & 0xF007
        if register == 0x8000:
            self.prg0 = value
            self._map_prg0()
        elif register == 0x9000:
            self.prg_mode = value & 0x80
            self._map_prg0()
        elif register == 0x9001:
            mode = value >> 6
            self.set_mirroring(SCREEN_A if mode & 1 else HORIZONTAL if mode else VERTICAL)
        elif register == 0x9003:
            self.enabled = bool(value & 0x80)
            self.irq = False
        elif register == 0x9004:
            self.counter = self.reload
            self.irq = False
        elif register == 0x9005:
            self.reload = (self.reload & 0x00FF) | value << 8
        elif register == 0x9006:
            self.reload = (self.reload & 0xFF00) | value
        elif register == 0xA000:
            self.map_prg(1, 8, value)
        elif 0xB000 <= register <= 0xB007:
            self.map_chr(register & 7, 1, value)
