"""Cartridge conversions of Famicom Disk System games.

Mappers 347, 368, 415, 418, 535, 538, 539, 548, 549, 554, 557.

Most from their NESdev wiki pages (NES_2.0_Mapper_*.wiki), others as their class says. A disk
game expects 32 KiB of RAM at
$6000-$DFFF and these boards spend as little as they can on it, so ROM and a
few KiB of RAM are quilted across the CPU's space. None has a judge ROM; the
claims rest on sweeps against Mesen2, a detector, or on looking where it refuses them
(docs/mappers.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage


class Conversion(Banked):
    """What these boards share: a ROM window at $6000 and hard-wired mirroring."""

    mirroring_wired: str | None = None

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bank6000 = 0
        if self.mirroring_wired:
            self.set_mirroring(self.mirroring_wired)
        self.map_chr(0, 8, 0)

    def read_6000(self, address: int) -> int:
        return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.read_6000(address)
        return super().cpu_read(address, t)


class Board0353(Conversion):
    """Mapper 415: the 0353 board (Lucky Rabbit, the FDS's Roger Rabbit).

    NES_2.0_Mapper_415.wiki: a latch at $8000-$FFFF: D3-D0 the 8 KiB bank at
    $6000, D4 the mirroring (0 vertical, 1 horizontal); the last 32 KiB fixed.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, len(self.prg) // 0x8000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.bank6000 = value & 0x0F
            self.set_mirroring(HORIZONTAL if value & 0x10 else VERTICAL)
        else:
            super().cpu_write(address, value, t)


class KS7010(Conversion):
    """Mapper 554: Kaiser's KS-7010 (Akumajou Dracula): banks switched by reads.

    Fixed 8 KiB banks 10, 11, 6, 7 at $8000-$FFFF; a read of a magic address
    selects the bank at $6000 and the 8 KiB CHR bank from its A5-A2. The
    page knows no mask, only the addresses that trigger: $CAB6-$CAD6, $EBE2,
    $EE32, $FFFC.
    """

    mirroring_wired = VERTICAL

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        for window, bank in enumerate((10, 11, 6, 7)):
            self.map_prg(window, 8, bank)

    def cpu_read(self, address: int, t: int) -> int | None:
        value = super().cpu_read(address, t)
        if 0xCAB6 <= address <= 0xCAD6 or address in (0xEBE2, 0xEE32, 0xFFFC):
            self.bank6000 = (address >> 2) & 0x0F
            self.map_chr(0, 8, self.bank6000)
        return value


class CTC15(Banked):
    """Mapper 548: Co Tung's CTC-15 (Almana no Kiseki).

    $4800 (mask $F800) latches A5, A3, A2; A2 also controls the IRQ (0
    counting, 1 stopped, acknowledged and cleared). A write to $5000 (mask
    $F800) applies the latch XOR 5 as the 16 KiB bank at $8000; $C000 is bank
    3; the power-on latch and bank are 7. Counting, the counter steps every
    M2 and /IRQ is asserted while (counter / 640) & 37 = 37. 8 KiB of PRG-RAM.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram = bytearray(max(len(self.prg_ram), 0x2000))
        self.prg_ram_enabled = True
        self.prg_ram_mask = 0x1FFF
        self.set_mirroring(HORIZONTAL)
        self.latch = 7
        self.counter = 0
        self.counting = False
        self.map_prg(0, 16, 7)
        self.map_prg(2, 16, 3)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF800 == 0x4800:
            self.latch = ((address >> 5) & 1) << 2 | (address >> 2) & 3
            self.counting = not address & 4
            if not self.counting:
                self.counter = 0
                self.irq = False
        elif address & 0xF800 == 0x5000:
            self.map_prg(0, 16, self.latch ^ 5)
        else:
            super().cpu_write(address, value, t)

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter += 1
            self.irq = (self.counter // 640) & 37 == 37


#: Mapper 539's RAM over the CPU's space: (first, last, offset in the 8 KiB). The page lists the
#: ranges, not how the board folds them into the chip; they fit without overlapping
#: (6 KiB in all), and each was its own RAM on the disk system, so here they stay apart.
PALTHENA_RAM = (
    (0xC000, 0xD1FF, 0x0000),
    (0x6000, 0x60FF, 0x1200),
    (0x6200, 0x62FF, 0x1300),
    (0x6400, 0x65FF, 0x1400),
    (0x8200, 0x82FF, 0x1600),
    (0xDF00, 0xDFFF, 0x1700),
)


class Palthena539(Conversion):
    """Mapper 539: a bootleg of the disk Kid Icarus: 8 KiB of RAM laid over ROM in slices.

    Fixed 8 KiB banks $D at $6000, $C at $8000, $E at $C000, $F at $E000;
    $A000 (mask unknown; the $A000-$BFFF region here) D3-D0 the bank at
    $A000; $FFFF D3 the mirroring (0 vertical, 1 horizontal).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram = bytearray(0x2000)
        self.bank6000 = 0x0D
        self.map_prg(0, 8, 0x0C)
        self.map_prg(1, 8, 0)
        self.map_prg(2, 8, 0x0E)
        self.map_prg(3, 8, 0x0F)

    @staticmethod
    def _ram(address: int) -> int | None:
        for first, last, offset in PALTHENA_RAM:
            if first <= address <= last:
                return offset + address - first
        return None

    def cpu_read(self, address: int, t: int) -> int | None:
        ram = self._ram(address)
        return super().cpu_read(address, t) if ram is None else self.prg_ram[ram]

    def cpu_write(self, address: int, value: int, t: int) -> None:
        ram = self._ram(address)
        if ram is not None:
            self.prg_ram[ram] = value
        elif address & 0xE000 == 0xA000:
            self.map_prg(1, 8, value & 0x0F)
        elif address == 0xFFFF:
            self.set_mirroring(HORIZONTAL if value & 8 else VERTICAL)


class LH53(Conversion):
    """Mapper 535: Whirlwind Manu's LH53 (Nazo no Murasamejou).

    The last 32 KiB at $8000, 8 KiB of RAM over it at $B800-$D7FF, an 8 KiB
    bank at $6000 from $F000 (mask $F000). $E000 (mask $F000) acknowledges,
    clears the counter and takes D1 as the enable; counting, the counter
    steps every M2 and reaching 7560 asserts /IRQ (the page has the number
    from FCEUX; no other source).
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram = bytearray(0x2000)
        self.counter = 0
        self.counting = False
        self.map_prg(0, 32, len(self.prg) // 0x8000 - 1)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0xB800 <= address < 0xD800:
            return self.prg_ram[address - 0xB800]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0xB800 <= address < 0xD800:
            self.prg_ram[address - 0xB800] = value
        elif address & 0xF000 == 0xE000:
            self.irq = False
            self.counter = 0
            self.counting = bool(value & 2)
        elif address & 0xF000 == 0xF000:
            self.bank6000 = value

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter += 1
            if self.counter == 7560:
                self.irq = True


#: Mapper 368's bank at $C000 for each value of D2-D0.
YUNG08_BANKS = (4, 3, 5, 3, 6, 3, 7, 3)


class Yung08(Conversion):
    """Mapper 368: the Yung-08 conversion of the disk Super Mario Bros. 2.

    Fixed 8 KiB banks 2 at $6000, 1, 0, a switchable one, 8 from $8000. $4022
    (mask $F1FF) D2-D0 pick the switchable bank through a table. $4122 keeps
    D5, D4, D2, D0, reading back ``10LL1L1L``; its D0 enables the IRQ (0:
    acknowledged, disabled, counter cleared); the 12-bit counter steps every
    M2 while enabled and overflowing asserts /IRQ.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bank6000 = 2
        self.latch = 0
        self.counter = 0
        self.counting = False
        self.map_prg(0, 8, 1)
        self.map_prg(1, 8, 0)
        self.map_prg(2, 8, YUNG08_BANKS[0])
        self.map_prg(3, 8, 8)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xF1FF == 0x4122:
            return 0x8A | self.latch & 0x35
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF1FF == 0x4022:
            self.map_prg(2, 8, YUNG08_BANKS[value & 7])
        elif address & 0xF1FF == 0x4122:
            self.latch = value
            self.counting = bool(value & 1)
            if not self.counting:
                self.counter = 0
                self.irq = False

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter = (self.counter + 1) & 0xFFF
            if self.counter == 0:
                self.irq = True


class SoccerChampion538(Conversion):
    """Mapper 538: the 60-1064-16L board (Super Soccer Champion, the disk Exciting Soccer).

    A write to $C000-$DFFF sets, from its low nibble N, the 8 KiB banks N | 1
    at $6000 and, at $8000, 10 if N is odd below 8, else N & ~1. Banks 13,
    14, 15 are fixed above.
    """

    mirroring_wired = VERTICAL

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self._select(0)
        for window, bank in ((1, 13), (2, 14), (3, 15)):
            self.map_prg(window, 8, bank)

    def _select(self, value: int) -> None:
        self.bank6000 = value | 1
        self.map_prg(0, 8, 10 if value & 1 and not value & 8 else value & ~1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE000 == 0xC000:
            self._select(value & 0x0F)


class KS7030(Banked):
    """Mapper 347: Kaiser's KS-7030 (UNL-KS7030, Yume Koujou: Doki Doki Panic).

    Over the CPU's space, in order: 3 KiB of RAM at $6000, 1 KiB of ROM at
    $6C00, 4 KiB at $7000, the fixed ROM to $B7FF, 2 KiB of RAM at $B800,
    3 KiB of ROM at $C000, 3 KiB of RAM at $CC00, the fixed ROM to the end:
    the same 8 KiB of RAM, read in order. By address: $8000-$8FFF: A2-A0 the
    4 KiB bank at $7000 from the second part of the file, A3 the mirroring (0
    vertical); $9000-$9FFF: A3-A0 a 4 KiB bank of the file's first part. The page gives
    the chip's true layout: 64 KiB of those banks (3 KiB at $C000, then 1 KiB
    at $6C00), 32 KiB of the other, the last 32 KiB fixed.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram = bytearray(0x2000)
        self.bank7000 = self.bank_c000 = 0
        self.fixed = len(self.prg) - 0x8000
        self.map_chr(0, 8, 0)

    def _place(self, address: int) -> tuple[bool, int] | None:
        """(is RAM, offset) for a CPU address, or None for the unmapped."""
        if address < 0x6000:
            return None
        if address < 0x6C00:
            return True, address - 0x6000
        if address < 0x7000:
            return False, self.bank_c000 * 0x1000 + 0xC00 + (address & 0x3FF)
        if address < 0x8000:
            return False, 0x10000 + self.bank7000 * 0x1000 + (address & 0xFFF)
        if 0xB800 <= address < 0xC000:
            return True, 0xC00 + address - 0xB800
        if 0xC000 <= address < 0xCC00:
            return False, self.bank_c000 * 0x1000 + (address & 0xFFF)
        if 0xCC00 <= address < 0xD800:
            return True, 0x1400 + address - 0xCC00
        return False, self.fixed + (address & 0x7FFF)

    def cpu_read(self, address: int, t: int) -> int | None:
        place = self._place(address)
        if place is None:
            return None
        ram, offset = place
        return self.prg_ram[offset] if ram else self.prg[offset % len(self.prg)]

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF000 == 0x8000:
            self.bank7000 = address & 7
            self.set_mirroring(HORIZONTAL if address & 8 else VERTICAL)
        elif address & 0xF000 == 0x9000:
            self.bank_c000 = address & 0x0F
        else:
            place = self._place(address)
            if place is not None and place[0]:
                self.prg_ram[place[1]] = value


class LH42(Banked):
    """Mappers 418 (LH42, Highway Star) and 557 (LG25, NTDEC 2718, Moero TwinBee).

    MAME's bootleg.cpp (BSD-3); the wiki has a schematic and a name. A cut-down
    MMC3's two ports, mask $E001: $8000 D2-D0 selects, $8001 writes: 6 and 7
    the 8 KiB banks at $8000 and $A000 (D3-D0), 5 the mirroring (D0 on 418, D5
    on 557: 1 horizontal). The last 16 KiB fixed, 8 KiB of CHR-RAM. 557 adds
    8 KiB of RAM at $6000.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.mirror_bit = 5 if image.board.mapper == 557 else 0
        self.select = 0
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
        elif address & 0xE001 == 0x8000:
            self.select = value & 7
        elif address & 0xE001 == 0x8001:
            if self.select == 5:
                self.set_mirroring(HORIZONTAL if (value >> self.mirror_bit) & 1 else VERTICAL)
            elif self.select >= 6:
                self.map_prg(self.select & 1, 8, value & 0x0F)


class KS7016B(Conversion):
    """Mapper 549 (Meikyuu Jiin Dababa): Kaiser's KS-7016B: the address banks $6000.

    A write to $8000-$FFFF latches A5-A2, with bank numbers $08-$0B reading as $0C-$0F:
    PRG A15 inverted when A16 is set (krzysiobal's analysis, forum t=19303;
    MAME's kaiser.cpp, BSD-3). $8000-$FFFF is the 32 KiB at banks 8-11.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, 2)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            bank = (address >> 2) & 0x0F
            self.bank6000 = bank | 4 if bank & 8 else bank
        else:
            super().cpu_write(address, value, t)
