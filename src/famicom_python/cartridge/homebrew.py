"""Homebrew boards: Action 53 (28), the NSF subset (31) and GTROM (111).

Each from its NESdev wiki page (pinned in scripts/pinned_files.json) and judged by
its own community test ROMs (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .flash import SST39SF040
from .ines import RomImage


class NSF31(Banked):
    """Mapper 31: PRG-ROM in eight 4 KiB slots at $8000-$FFFF, as an NSF banks it.

    INES_Mapper_031.wiki: a write to $5000-$5FFF selects the 4 KiB bank of slot
    A2-A0 ($5FF8-$5FFF canonically); the register for $F000-$FFFF powers on as
    $FF, the last bank, and reset leaves it. No CHR banking (8 KiB CHR-RAM, or
    ROM), no mirroring control. The other slots' power-on banks are not given:
    0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.slots = [0] * 8  # byte offsets into PRG of each 4 KiB slot
        self._select(7, 0xFF)
        self.map_chr(0, 8, 0)

    def _select(self, slot: int, bank: int) -> None:
        self.slots[slot] = (bank << 12) % len(self.prg)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return self.prg[self.slots[(address >> 12) & 7] + (address & 0x0FFF)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            self._select(address & 7, value)
            return
        super().cpu_write(address, value, t)


class Action53(Banked):
    """Mapper 28: Damian Yerrick's multicart mapper, which simulates NROM, CNROM,
    UxROM, BNROM and AxROM (Action_53_mapper.wiki).

    $5000-$5FFF selects a register (D7 supervisor, D0 which), $8000-$FFFF writes
    it; no bus conflicts. $00: CHR-RAM bank (D1-D0) and, in a 1-screen mode,
    the screen (D4); $01: the inner PRG bank (and D4 as $00's); $80: the outer
    bank size (D5-D4), PRG mode (D3-D2) and mirroring (D1-D0: 1-screen lower,
    upper, vertical, horizontal); $81: the outer PRG bank. 32 KiB of CHR-RAM,
    as the Action 53 boards have (an iNES 1 header says 8). Power-on state
    unspecified but for the last 16 KiB at $C000: the wiki's suggested boot
    state, $81 = $FF and $80 = $02 (32 KiB mode, the last bank). Reset leaves it.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        if self.chr_writable and len(self.chr) < 0x8000:
            self.chr = bytearray(0x8000)
        self.select = 0
        self.regs = {0x00: 0, 0x01: 0, 0x80: 0x02, 0x81: 0xFF}
        self._update()

    def _update(self) -> None:
        regs = self.regs
        mode = regs[0x80]
        size, prg_mode, mirroring = (mode >> 4) & 3, (mode >> 2) & 3, mode & 3
        outer, inner = regs[0x81], regs[0x01]
        if prg_mode < 2:  # 32 KiB: the low outer bits give way to inner ones
            mask = (1 << size) - 1
            bank32 = (outer & ~mask) | (inner & mask)
            low, high = bank32 << 1, (bank32 << 1) | 1
        else:  # UxROM: one 16 KiB half switchable, the other fixed to the outer bank
            mask = (2 << size) - 1
            switched = ((outer << 1) & ~mask) | (inner & mask)
            if prg_mode == 2:  # fixed $8000 (mapper 180)
                low, high = outer << 1, switched
            else:  # fixed $C000 (mapper 2)
                low, high = switched, (outer << 1) | 1
        self.map_prg(0, 16, low)
        self.map_prg(2, 16, high)
        self.map_chr(0, 8, regs[0x00] & 3)
        self.set_mirroring((SCREEN_A, SCREEN_B, VERTICAL, HORIZONTAL)[mirroring])

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            self.select = value & 0x81
            return
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = self.select
        self.regs[register] = value
        if register in (0x00, 0x01) and self.regs[0x80] & 2 == 0:
            # A 1-screen mode: D4 is the screen, as AxROM's (the wiki's "M").
            self.regs[0x80] = (self.regs[0x80] & ~1) | ((value >> 4) & 1)
        self._update()


class GTROM(Banked):
    """Mapper 111: Membler Industries' Cheapocabra (GTROM.wiki).

    One 74377 register at $5000-$5FFF and $7000-$7FFF (latched as M2 falls
    when /ROMSEL, A14 and A12 are high), ``GRNCPPPP``: the 32 KiB PRG bank,
    the 8 KiB CHR-RAM bank, the 8 KiB nametable bank, and the red and green
    LEDs (taken, not shown). The latch clocks on reads too, so a read stores
    whatever is on the data bus (:meth:`read_data`). No bus conflicts: every
    write to $8000-$FFFF goes to the SST39SF040, at the selected bank and
    A14-A0 (its $5555 is $D555 in any bank).

    The board's 32 KiB of RAM: $0000-$1FFF of the PPU sees its first or second
    8 KiB, $2000-$3EFF its third or fourth, unmirrored (four screens, and
    $3000-$3EFF is RAM of its own: the wiki's "bonus RAM"); CIRAM is never
    enabled. The register's power-on state is not given: 0 here. The PRG is
    flash, so it is the save (:meth:`battery_ram`) whatever the header's
    battery bit says.
    """

    latches_reads = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg = bytearray(image.prg)
        self.flash = SST39SF040(self.prg)
        self.chr = bytearray(0x8000)
        self.chr_writable = True
        self.register = 0
        self.nametables = 0x4000  # where the selected nametable page begins
        self._latch(0)

    def _latch(self, value: int) -> None:
        self.register = value
        self.map_prg(0, 32, value & 0x0F)
        self.map_chr(0, 8, (value >> 4) & 1)
        self.nametables = 0x4000 + ((value >> 5) & 1) * 0x2000

    def _flash_offset(self, address: int) -> int:
        return ((self.register & 0x0F) << 15 | (address & 0x7FFF)) % len(self.prg)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.flash.id_mode and address >= 0x8000:
            return self.flash.read(self._flash_offset(address))
        return super().cpu_read(address, t)

    def read_data(self, address: int, value: int, t: int) -> None:
        if address & 0x5000 == 0x5000 and address < 0x8000:
            self._latch(value)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.flash.write(self._flash_offset(address), value)
        elif address & 0x5000 == 0x5000:
            self._latch(value)

    def ciram_a10(self, address: int) -> int | None:
        return None

    def ppu_read(self, address: int, t: int) -> int | None:
        if address >= 0x2000:
            return self.chr[self.nametables + (address & 0x1FFF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x2000:
            self.chr[self.nametables + (address & 0x1FFF)] = value
            return
        super().ppu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg)

    def _restore(self, data: bytes) -> None:
        self.prg[:] = data
