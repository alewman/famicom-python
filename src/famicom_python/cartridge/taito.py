"""Taito's mappers: TC0190 (33), TC0690 (48), X1-005 (80, 207) and X1-017 (82, 552).

No judge ROM exists (docs/cartridge.md); the claims rest on sweeps against
Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage
from .mmc3 import MMC3

#: TC0690's /IRQ lags the MMC3's: "about 4 CPU cycles" (INES_Mapper_048.wiki,
#: Disch's notes). Not measured; Mesen2 uses 22.
TC0690_IRQ_DELAY = 4


class TC0190(Banked):
    """Mapper 33: two 8 KiB PRG banks and the last two fixed; CHR 2 KiB x 2 and 1 KiB x 4.

    INES_Mapper_033.wiki (register mask $A003): $8000 D5-D0 selects $8000 and
    D6 the arrangement (0 vertical, 1 horizontal); $8001 selects $A000;
    $8002/$8003 the 2 KiB CHR banks at $0000/$0800, numbered in 2 KiB units
    (unlike the MMC3's); $A000-$A003 the 1 KiB banks at $1000-$1C00. No IRQ,
    no PRG-RAM. Power-on registers unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        last = len(self.prg) // 0x2000 - 1
        self.map_prg(2, 8, last - 1)
        self.map_prg(3, 8, last)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not 0x8000 <= address < 0xC000:
            return
        register = address & 0xA003
        if register == 0x8000:
            self.map_prg(0, 8, value & 0x3F)
            self.set_mirroring(HORIZONTAL if value & 0x40 else VERTICAL)
        elif register == 0x8001:
            self.map_prg(1, 8, value & 0x3F)
        elif register in (0x8002, 0x8003):
            self.map_chr((register & 1) * 2, 2, value)
        else:
            self.map_chr(4 + (register & 3), 1, value)


class TC0690(MMC3):
    """Mapper 48: Taito TC0690: TC0190's banks, the MMC3's scanline counter, a later /IRQ.

    INES_Mapper_048.wiki (mask $E003): $8000/$8001 the 8 KiB PRG banks at
    $8000/$A000 (the last two fixed); $8002/$8003 the 2 KiB CHR banks in 2 KiB
    units; $A000-$A003 the 1 KiB banks at $1000-$1C00; $C000 the reload value,
    inverted; $C001 as the MMC3's $C001, $C002 as its $E001, $C003 as its
    $E000; $E000 D6 the arrangement (0 vertical, 1 horizontal). The counter
    is the MMC3's, its /IRQ :data:`TC0690_IRQ_DELAY` CPU cycles later.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.irq_delay = 0
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False

    def _update(self) -> None:
        r = self.registers
        last = len(self.prg) // 0x2000 - 1
        self.map_prg(0, 8, r[0] & 0x3F)
        self.map_prg(1, 8, r[1] & 0x3F)
        self.map_prg(2, 8, last - 1)
        self.map_prg(3, 8, last)
        self.map_chr(0, 2, r[2])
        self.map_chr(2, 2, r[3])
        for i in range(4):
            self.map_chr(4 + i, 1, r[4 + i])

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            return
        register = address & 0xE003
        if register < 0xC000:
            index = (register & 3) + (4 if register >= 0xA000 else 0)
            self.registers[index] = value
            self._update()
        elif register == 0xC000:
            self.latch = value ^ 0xFF
        elif register == 0xC001:
            self.counter = 0
            self.reload = True
        elif register == 0xC002:
            self.irq_enabled = True
        elif register == 0xC003:
            self.irq_enabled = False
            self.irq = False
            self.irq_delay = 0
        elif register == 0xE000:
            self.set_mirroring(HORIZONTAL if value & 0x40 else VERTICAL)

    def clock_counter(self) -> None:
        was_pending = self.irq
        super().clock_counter()
        if self.irq and not was_pending:
            self.irq = False
            self.irq_delay = TC0690_IRQ_DELAY

    def m2(self, t: int) -> None:
        if self.irq_delay:
            self.irq_delay -= 1
            if self.irq_delay == 0:
                self.irq = True


class X1005(Banked):
    """Mappers 80 and 207: Taito X1-005: 8 KiB PRG banks, 2 KiB and 1 KiB CHR, 128 bytes of RAM.

    Taito_X1-005.wiki: write-only registers at $7EF0-$7EFF, mirrored at
    $7E70-$7E7F (CPU A7 ignored): $7EF0/$7EF1 the 2 KiB CHR banks (D0
    ignored), $7EF2-$7EF5 the 1 KiB ones; $7EF6 (not at $7EF7) D0 CIRAM A10
    from PPU A10 (1, vertical) or A11 (0) (the page names them the other way
    round beside the pins; the pins, and Mesen2, as here); $7EF8/$7EF9 = $A3
    enables the RAM; $7EFA/B, $7EFC/D, $7EFE/F the 8 KiB banks at $8000,
    $A000, $C000 (the last fixed). The RAM: 128 bytes at $7F00, mirrored to
    $7FFF, open bus while disabled, battery-backed when the header says.
    207 (INES_Mapper_207.wiki, Fudou Myouou Den): D7 of $7EF0 and $7EF1 is
    CIRAM A10 for $2000-$27FF and $2800-$2FFF, and $7EF6 does nothing.
    Power-on registers unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.cart_nametables = image.board.mapper == 207
        self.ram = bytearray(128)
        self.ram_enabled = False
        self.prg_ram_enabled = False
        self.screens = [0, 0]
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x7F00 <= address < 0x8000:
            return self.ram[address & 0x7F] if self.ram_enabled else None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x7F00 <= address < 0x8000:
            if self.ram_enabled:
                self.ram[address & 0x7F] = value
            return
        if address & 0xFF70 != 0x7E70:
            return
        register = address & 0x0F
        if register < 2:
            self.map_chr(register * 2, 2, (value & 0x7F if self.cart_nametables else value) >> 1)
            self.screens[register] = value >> 7
        elif register < 6:
            self.map_chr(register + 2, 1, value)
        elif register == 6:
            if not self.cart_nametables:
                self.set_mirroring(VERTICAL if value & 1 else HORIZONTAL)
        elif register in (8, 9):
            self.ram_enabled = value == 0xA3
        elif register >= 0x0A:
            self.map_prg((register - 0x0A) >> 1, 8, value & 0x3F)

    def ciram_a10(self, address: int) -> int | None:
        if self.cart_nametables:
            return self.screens[(address >> 11) & 1]
        return super().ciram_a10(address)

    def battery_ram(self) -> bytes | None:
        return bytes(self.ram) if self.battery else None

    def _restore(self, data: bytes) -> None:
        self.ram[:] = data


class X1017(Banked):
    """Mappers 82 and 552: Taito X1-017: 8 KiB PRG banks, CHR with A12 inversion, 5 KiB of RAM.

    Taito_X1-017.wiki: write-only registers at $7EF0-$7EFF: $7EF0/$7EF1 the
    2 KiB CHR banks (D0 ignored), $7EF2-$7EF5 the 1 KiB ones; $7EF6 D0 the
    arrangement (as the X1-005's, 1 vertical) and D1 swaps the 2 KiB and
    1 KiB halves; $7EF7/8/9 enable the RAM at $6000-$67FF ($CA), $6800-$6FFF
    ($69) and $7000-$73FF ($84); $7EFA/B/C the 8 KiB banks at $8000, $A000,
    $C000 (the last fixed): on 82 PRG A16-A13 from D5-D2, on 552 (the mask
    ROM as wired) A13-A18 from D5-D0, reversed. The ASIC's strong pull-downs
    make every undriven read of $4020-$7FFF 0, here (the 2A03's own open
    bus bits are the board's, and stay open bus). The RAM is battery-backed
    when the header says.

    The IRQ (no game uses it; reverse-engineered by Krzysiobal, the wiki):
    $7EFD the latch; $7EFE D0 counts (clearing it reloads the counter with
    (latch + 2) x 16, or 17 for a latch of 0), D1 lets it assert /IRQ, D2
    stops counting; $7EFF acknowledges and reloads it with (latch + 1) x 16,
    or 1. Counting, it decrements every CPU cycle to 0, where /IRQ asserts
    while D1 is set (the wiki says no more). Power-on registers unspecified:
    0 here.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.reversed_prg = image.board.mapper == 552
        self.ram = bytearray(0x1400)
        self.ram_enables = [False, False, False]
        self.prg_ram_enabled = False
        self.chr_registers = [0] * 6
        self.chr_mode = 0
        self.latch = 0
        self.control = 0
        self.counter = 0
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        self._map_chr()

    def _map_chr(self) -> None:
        r = self.chr_registers
        low = 4 if self.chr_mode else 0
        self.map_chr(low, 2, r[0] >> 1)
        self.map_chr(low + 2, 2, r[1] >> 1)
        for i in range(4):
            self.map_chr((low ^ 4) + i, 1, r[2 + i])

    def _ram_index(self, address: int) -> int | None:
        if 0x6000 <= address < 0x7400 and self.ram_enables[min((address - 0x6000) >> 11, 2)]:
            return address - 0x6000
        return None

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return super().cpu_read(address, t)
        index = self._ram_index(address)
        return 0 if index is None else self.ram[index]

    def cpu_write(self, address: int, value: int, t: int) -> None:
        index = self._ram_index(address)
        if index is not None:
            self.ram[index] = value
            return
        if not 0x7EF0 <= address <= 0x7EFF:
            return
        register = address & 0x0F
        if register < 6:
            self.chr_registers[register] = value
            self._map_chr()
        elif register == 6:
            self.set_mirroring(VERTICAL if value & 1 else HORIZONTAL)
            self.chr_mode = value & 2
            self._map_chr()
        elif register <= 9:
            self.ram_enables[register - 7] = value == (0xCA, 0x69, 0x84)[register - 7]
        elif register <= 0x0C:
            self.map_prg(register - 0x0A, 8, self._prg_bank(value))
        elif register == 0x0D:
            self.latch = value
        elif register == 0x0E:
            self.control = value & 7
            if not value & 1:
                self.counter = (self.latch + 2) * 16 if self.latch else 17
            self.irq = bool(self.irq and value & 2)
        else:
            self.irq = False
            self.counter = (self.latch + 1) * 16 if self.latch else 1

    def _prg_bank(self, value: int) -> int:
        if self.reversed_prg:  # D5 is A13 ... D0 is A18
            return sum(((value >> bit) & 1) << (5 - bit) for bit in range(6))
        return (value >> 2) & 0x0F  # D5-D2: A16-A13

    def m2(self, t: int) -> None:
        if self.control & 5 == 1 and self.counter:
            self.counter -= 1
            if self.counter == 0 and self.control & 2:
                self.irq = True

    def battery_ram(self) -> bytes | None:
        return bytes(self.ram) if self.battery else None

    def _restore(self, data: bytes) -> None:
        self.ram[:] = data
