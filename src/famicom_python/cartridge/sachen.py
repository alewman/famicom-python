"""Sachen's boards: the 8259 family (137, 138, 139, 141), the "74LS374N" ASIC (150, 243) and
the discrete latches (133, 143, 145, 148, 149).

Each from its NESdev wiki page (Sachen_8259.wiki, INES_Mapper_137/150/243/
133/143/145/148/149.wiki), which for 137-141 the wiki itself says came mostly
from FCEU-mm. No judge ROM exists; the claims rest on sweeps against Mesen2, a
detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .discrete import NROM
from .ines import RomImage

L_SHAPED = "L"  # one quadrant on the other CIRAM page: (0, 1, 1, 1) or (0, 0, 0, 1)


class SachenRegisterFile(Banked):
    """An index register at $4100 and eight 3-bit data registers at $4101 (mask $C101)."""

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.index = 0
        self.regs = [0] * 8
        self.l_pages = (0, 1, 1, 1)
        self._update()

    def _update(self) -> None:
        raise NotImplementedError

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0xC101
        if register == 0x4100:
            self.index = value & 7
        elif register == 0x4101:
            self.regs[self.index] = value & 7
            self._update()
        else:
            super().cpu_write(address, value, t)

    def ciram_a10(self, address: int) -> int | None:
        if self.mirroring == L_SHAPED:
            return self.l_pages[(address >> 10) & 3]
        return super().ciram_a10(address)


class Sachen8259(SachenRegisterFile):
    """Mappers 138 (8259B), 141 (8259A) and 139 (8259C): a 32 KiB PRG bank, four 2 KiB CHR banks.

    Registers 0-3: CHR A13-A11 of the four 2 KiB windows (register 0 for all
    four in simple mode); 4: the CHR bank's upper three bits; 5: the 32 KiB
    PRG bank; 7 ``.mms``: simple mode (and vertical mirroring), else the
    mirroring (vertical, horizontal, quadrants 0,1,1,1, one-screen A). The A
    and C boards shift the CHR bank up by 1 or 2 bits and pass PPU A11 (A12)
    through below it. 141 with CHR-RAM (Q-Boy) has 8 KiB unbanked.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.shift = {138: 0, 141: 1, 139: 2}[image.board.mapper]
        self.banked_chr = bool(image.chr)
        super().__init__(image, cpu_cycle_ticks)

    def _update(self) -> None:
        r = self.regs
        simple = r[7] & 1
        self.map_prg(0, 32, r[5])
        if simple:
            self.set_mirroring(VERTICAL)
        else:
            self.set_mirroring((VERTICAL, HORIZONTAL, L_SHAPED, SCREEN_A)[(r[7] >> 1) & 3])
        if not self.banked_chr:
            self.map_chr(0, 8, 0)
            return
        for window in range(4):
            bank = r[4] << 3 | r[0 if simple else window]
            for half in range(2):
                ppu_1k = window * 2 + half
                passed = ppu_1k & ((1 << (self.shift + 1)) - 1)  # the PPU lines passed through
                self.map_chr(ppu_1k, 1, (bank << (self.shift + 1)) | passed)


class Sachen8259D(SachenRegisterFile):
    """Mapper 137: Sachen 8259D (The Great Wall): four 1 KiB CHR banks, $1000 the last 4 KiB.

    INES_Mapper_137.wiki: registers 0-3 the 1 KiB banks' low three bits; 4 D0,
    D1, D2 bit 4 of banks 1, 2, 3; 6 D0 bit 3 of bank 3; 5 the 32 KiB PRG
    bank; 7 ``.mms``: the mirroring (horizontal, vertical, 0,1,1,1, one-screen
    A), or in simple mode horizontal with register 0's low bits for every
    bank (the wiki's deduction).
    """

    def _update(self) -> None:
        r = self.regs
        simple = r[7] & 1
        self.map_prg(0, 32, r[5])
        if simple:
            self.set_mirroring(HORIZONTAL)
        else:
            self.set_mirroring((HORIZONTAL, VERTICAL, L_SHAPED, SCREEN_A)[(r[7] >> 1) & 3])
        top = (0, (r[4] & 1) << 4, (r[4] & 2) << 3, (r[4] & 4) << 2 | (r[6] & 1) << 3)
        for i in range(4):
            self.map_chr(i, 1, top[i] | r[0 if simple else i])
        self.map_chr(4, 4, len(self.chr) // 0x1000 - 1)


class SachenLS374N(SachenRegisterFile):
    """Mappers 150 (SA-015/SA-630) and 243 (SA-020A): the ASIC marked "74LS374N".

    INES_Mapper_150.wiki, _243.wiki: all eight registers are readable at $4101.
    150: R4 D0 CHR A15, R5 D1-D0 PRG A16-A15, R6 D1-D0 CHR A14-A13. 243: R2 D0
    CHR A13, R4 D0 CHR A14, R5 PRG, R6 D1-D0 CHR A16-A15. R7 D2-D1: quadrants
    0,0,0,1, horizontal, vertical, one-screen B. The solder pad is in the
    D2-connected position (Shōgi Gakuen shows "Sachen").
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.honey_peach = image.board.mapper == 243
        super().__init__(image, cpu_cycle_ticks)
        self.l_pages = (0, 0, 0, 1)

    def _update(self) -> None:
        r = self.regs
        self.map_prg(0, 32, r[5] & 3)
        if self.honey_peach:
            bank = (r[2] & 1) | (r[4] & 1) << 1 | (r[6] & 3) << 2
        else:
            bank = (r[6] & 3) | (r[4] & 1) << 2
        self.map_chr(0, 8, bank)
        self.set_mirroring((L_SHAPED, HORIZONTAL, VERTICAL, SCREEN_B)[(r[7] >> 1) & 3])

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xC101 == 0x4101:
            return self.regs[self.index] | 0xF8 << 8  # D2-D0 driven
        return super().cpu_read(address, t)


class SachenLatch(Banked):
    """Sachen's latches: 133 (SA-72008), 145 (SA-72007), 148 (SA-008-A), 149 (SA-0036).

    INES_Mapper_133.wiki: $4100 (mask $E100) ``.....PCC``. _145: $4100 D7 the
    8 KiB CHR bank. _148: $8000-$FFFF ``....PCCC`` with AND-type bus
    conflicts. _149: $8000-$FFFF D7 the CHR bank, with conflicts. Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.kind = image.board.mapper
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        kind = self.kind
        if kind in (133, 145) and address & 0xE100 == 0x4100:
            if kind == 133:
                self.map_prg(0, 32, (value >> 2) & 1)
                self.map_chr(0, 8, value & 3)
            else:
                self.map_chr(0, 8, value >> 7)
        elif kind in (148, 149) and address >= 0x8000:
            value = self.bus_conflict(address, value)
            if kind == 148:
                self.map_prg(0, 32, (value >> 3) & 1)
                self.map_chr(0, 8, value & 7)
            else:
                self.map_chr(0, 8, value >> 7)
        else:
            super().cpu_write(address, value, t)


class Sachen143(Banked):
    """Mapper 143: NROM with a protection read (Dancing Blocks, Magical Mathematics).

    INES_Mapper_143.wiki: a read of $4100-$5FFF with A8 set (mask $E100)
    returns the inverse of A5-A0 in D5-D0, D7-D6 open bus.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        for window in range(4):
            self.map_prg(window, 8, window)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xE100 == 0x4100:
            return (~address & 0x3F) | 0xC0 << 8
        return super().cpu_read(address, t)


class Sachen3014(Banked):
    """Mapper 533: the Sachen 3014: CNROM whose latch reads back.

    NES_2.0_Mapper_533.wiki: a write to $8000-$FFFF (bus conflicts) latches D7-D4,
    D4 the 8 KiB CHR bank; a read of $E000-$EFFF gives the ROM's high nibble
    and the latch in the low one. The page has the latch fight the ROM (the
    game reads it ten times); here the latch wins at once.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.latch = 0
        self.map_prg(0, 32, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        value = super().cpu_read(address, t)
        if address & 0xF000 == 0xE000 and value is not None:
            return (value & 0xF0) | self.latch
        return value

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.latch = self.bus_conflict(address, value) >> 4
            self.map_chr(0, 8, self.latch & 1)


class Sachen3013(NROM):
    """Mapper 553: Sachen's 3013 board (Dong Dongnao 1): NROM-128 with a 74LS244 and a
    TC40H139P making $8000-$BFFF read $3A instead of a mirror of $C000-$FFFF
    (NES_2.0_Mapper_553.wiki)."""

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x8000 <= address < 0xC000:
            return 0x3A
        return super().cpu_read(address, t)
