"""Jaleco's mappers: SS88006 (18) and the discrete JF boards: JF-17/19 (72, 92),
JF-16 (78), JF-13 (86) and JF-11/14 (140).

No judge ROM exists (docs/cartridge.md); the claims rest on sweeps against
Mesen2, a detector (docs/claims.md). The µPD7756C speech chip of 72 and 86
(Moero!! Pro Tennis, Moero!! Pro Yakyuu) needs its mask ROM's samples, which
are not available: its register writes are taken and nothing sounds.
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


class JF17(Banked):
    """Mappers 72 (JF-17) and 92 (JF-19): banks loaded on a command bit's rise.

    INES_Mapper_072.wiki, _092.wiki: a 74161 latches D7-D4 of every write to
    $8000-$FFFF (AND-type bus conflicts); a rise of D7 loads D3-D0 into the
    PRG bank, a rise of D6 into the 8 KiB CHR bank, so a game writes the
    command and then clears it. 72: 16 KiB at $8000, the last fixed (three
    bits); 92: the first 16 KiB fixed, $C000 switched (four bits). D5-D4 drive
    the speech chip (not modelled). The latch's power-on value is unspecified:
    0 here, so the first command loads.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.fixed_first = image.board.mapper == 92
        self.latch = 0
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        value = self.bus_conflict(address, value)
        rises = value & ~self.latch
        self.latch = value
        if rises & 0x80:
            if self.fixed_first:
                self.map_prg(2, 16, value & 0x0F)
            else:
                self.map_prg(0, 16, value & 0x07)
        if rises & 0x40:
            self.map_chr(0, 8, value & 0x0F)


class JF16(Banked):
    """Mapper 78: Jaleco JF-16 (Uchuusen Cosmo Carrier) and Irem's Holy Diver board.

    INES_Mapper_078.wiki: a write to $8000-$FFFF (AND-type bus conflicts)
    sets ``CCCCMPPP``: the 16 KiB PRG bank at $8000 (the last fixed), the
    8 KiB CHR bank and M, one-screen A or B on Cosmo Carrier (submapper 1),
    horizontal or vertical on Holy Diver (submapper 3). An iNES header says
    which by its four-screen bit, set for Holy Diver (the wiki). Power-on
    banks unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.holy_diver = board.submapper == 3 or (board.submapper == 0 and self.four_screen)
        self.four_screen = False
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self._latch(0)

    def _latch(self, value: int) -> None:
        self.map_prg(0, 16, value & 7)
        self.map_chr(0, 8, value >> 4)
        if self.holy_diver:
            self.set_mirroring(VERTICAL if value & 8 else HORIZONTAL)
        else:
            self.set_mirroring(SCREEN_B if value & 8 else SCREEN_A)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        self._latch(self.bus_conflict(address, value))


class JF13(Banked):
    """Mapper 86: Jaleco JF-13 (Moero!! Pro Yakyuu), registers at $6000-$7FFF.

    INES_Mapper_086.wiki: $6000-$6FFF ``.CPP..CC``, the 32 KiB PRG bank and
    the 8 KiB CHR bank (D6 its high bit); $7000-$7FFF the speech chip (not
    modelled). No PRG-RAM, no bus conflicts. Not modelled: the copies the
    wiki finds at $E000-$FFFF (decoded while M2 is low, so what the latch
    takes there is not known). Power-on banks unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x7000:
            self.map_prg(0, 32, (value >> 4) & 3)
            self.map_chr(0, 8, (value >> 4) & 4 | value & 3)


class JF11(Banked):
    """Mapper 140: Jaleco JF-11/JF-14, GNROM with its register at $6000-$7FFF.

    INES_Mapper_140.wiki: ``..PPCCCC``, the 32 KiB PRG bank and the 8 KiB
    CHR bank. No PRG-RAM, no bus conflicts. Power-on banks unspecified: 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.map_prg(0, 32, (value >> 4) & 3)
            self.map_chr(0, 8, value & 0x0F)
