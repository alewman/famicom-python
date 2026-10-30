"""Sunsoft's mappers: Sunsoft-3 (67), Sunsoft-4 (68), FME-7, 5A and 5B (69), and the discrete
Sunsoft-1 (184) and Sunsoft-2 (89, 93).

69 is judged by Holy Mapperel and tepples's ``fme7acktest`` and
``fme7ramtest`` (docs/claims.md), and the 5B's sound is milestone 8's; the
others have no judge ROM and rest on sweeps against Mesen2, a detector.
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage


class FME7(Banked):
    """Mapper 69: a command register ($8000) and its parameter ($A000).

    Sunsoft_FME-7.wiki. Commands 0-7: the eight 1 KiB CHR banks; 8: $6000,
    D5-D0 the bank, D6 RAM (1) or ROM, D7 the RAM's enable (RAM selected but
    disabled is open bus); 9-B: 8 KiB PRG at $8000, $A000, $C000, the last
    fixed; C: the arrangement (vertical, horizontal, one-screen A, B); D: D0
    lets the counter assert /IRQ, D7 lets it count, and any write
    acknowledges (Oliveira's 2015 test, ``fme7acktest``); E/F: the counter's
    low and high bytes. Counting, the 16-bit counter decrements each CPU
    cycle, and the decrement from $0000 to $FFFF asserts /IRQ. Power-on
    registers unspecified: 0 here (ROM bank 0 at $6000).
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.command = 0
        self.low_bank = 0  # command 8
        self.counter = 0
        self.counting = self.irq_enabled = False
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter = (self.counter - 1) & 0xFFFF
            if self.counter == 0xFFFF and self.irq_enabled:
                self.irq = True

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            bank = self.low_bank
            if not bank & 0x40:
                return self.prg[(bank & 0x3F) * 0x2000 % len(self.prg) + (address & 0x1FFF)]
            if not bank & 0x80 or not self.prg_ram:
                return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            if self.low_bank & 0xC0 == 0xC0:
                super().cpu_write(address, value, t)
            return
        region = address & 0xE000
        if region == 0x8000:
            self.command = value & 0x0F
        elif region == 0xA000:
            self.parameter(self.command, value)

    def parameter(self, command: int, value: int) -> None:
        if command < 8:
            self.map_chr(command, 1, value)
        elif command == 8:
            self.low_bank = value
        elif command < 0x0C:
            self.map_prg(command - 9, 8, value & 0x3F)
        elif command == 0x0C:
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
        elif command == 0x0D:
            self.irq_enabled = bool(value & 1)
            self.counting = bool(value & 0x80)
            self.irq = False
        elif command == 0x0E:
            self.counter = (self.counter & 0xFF00) | value
        else:
            self.counter = (self.counter & 0x00FF) | value << 8


class Sunsoft2(Banked):
    """Mappers 89 (Sunsoft-2 on the Sunsoft-3 board) and 93 (on the Sunsoft-3R).

    INES_Mapper_089.wiki, _093.wiki: a write to $8000-$FFFF (AND-type bus
    conflicts) sets the 16 KiB PRG bank at $8000 from D6-D4, the last fixed.
    89: ``CPPPMCCC``, the 8 KiB CHR bank from D7 and D2-D0, and M one-screen
    A or B. 93: D0 enables the CHR-RAM; disabled, it is open bus and takes
    no writes (no game clears it). Power-on registers unspecified: 0 here,
    except 93's RAM, enabled.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.sunsoft_3r = image.board.mapper == 93
        self.chr_enabled = True
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.map_chr(0, 8, 0)
        if not self.sunsoft_3r:
            self.set_mirroring(SCREEN_A)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        value = self.bus_conflict(address, value)
        self.map_prg(0, 16, (value >> 4) & 7)
        if self.sunsoft_3r:
            self.chr_enabled = bool(value & 1)
        else:
            self.map_chr(0, 8, (value >> 4) & 8 | value & 7)
            self.set_mirroring(SCREEN_B if value & 8 else SCREEN_A)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000 and not self.chr_enabled:
            return None
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x2000 or self.chr_enabled:
            super().ppu_write(address, value, t)


class Sunsoft1(Banked):
    """Mapper 184: Sunsoft-1 on the Sunsoft-K board: two 4 KiB CHR banks from $6000-$7FFF.

    INES_Mapper_184.wiki: ``.1HH.LLL``, the bank at PPU $0000 from D2-D0 and
    the one at $1000 from D5-D4 with CHR A14 high (banks 4-7). PRG is 32 KiB,
    unbanked; no PRG-RAM (the register is where it would be). Power-on
    banks unspecified: 0 and 4 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.map_prg(0, 32, 0)
        self.map_chr(0, 4, 0)
        self.map_chr(4, 4, 4)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.map_chr(0, 4, value & 7)
            self.map_chr(4, 4, 4 | (value >> 4) & 3)


class Sunsoft3(Banked):
    """Mapper 67: Sunsoft-3: 16 KiB PRG and the last fixed, four 2 KiB CHR banks, a cycle counter.

    INES_Mapper_067.wiki (mask $F800): $8000 acknowledges; $8800/$9800/
    $A800/$B800 the CHR banks; $C800 the counter, high byte then low (the
    count itself, not a reload value); $D800 D4 counts, and resets the $C800
    toggle (no acknowledge); $E800 the arrangement (vertical, horizontal,
    one-screen A, B); $F800 the PRG bank. Counting, the 16-bit count
    decrements every CPU cycle, and its wrap from $0000 to $FFFF asserts
    /IRQ and pauses it. No bus conflicts. Power-on registers unspecified: 0.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.counter = 0
        self.counting = False
        self.high_next = True  # the $C800 toggle
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter = (self.counter - 1) & 0xFFFF
            if self.counter == 0xFFFF:
                self.counting = False
                self.irq = True

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = address & 0xF800
        if register & 0x0800 == 0:
            self.irq = False  # $8000 and its mirrors
        elif register <= 0xB800:
            self.map_chr(((register >> 12) - 8) * 2, 2, value)  # $8800 $0000 ... $B800 $1800
        elif register == 0xC800:
            if self.high_next:
                self.counter = (self.counter & 0x00FF) | value << 8
            else:
                self.counter = (self.counter & 0xFF00) | value
            self.high_next = not self.high_next
        elif register == 0xD800:
            self.counting = bool(value & 0x10)
            self.high_next = True
        elif register == 0xE800:
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
        else:
            self.map_prg(0, 16, value & 0x0F)


class Sunsoft4(Banked):
    """Mapper 68: Sunsoft-4: 16 KiB PRG and the last fixed, 2 KiB CHR banks, CHR-ROM nametables.

    INES_Mapper_068.wiki: $8000/$9000/$A000/$B000 the 2 KiB CHR banks;
    $C000/$D000 the 1 KiB CHR-ROM banks of the low and high nametable (D7
    taken as 1: the last 128 KiB); $E000 D1-D0 the arrangement (vertical,
    horizontal, one-screen low, high), D4 the nametables from CHR-ROM (1) or
    CIRAM; $F000 D3-D0 the PRG bank, D4 enables the PRG-RAM (disabled: open
    bus). No bus conflicts. Not modelled: Nantettatte!! Baseball's
    external ROM and licensing timer (its dumps hold only the internal ROM).
    Power-on registers unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.rom_nametables = False
        self.nametable_banks = [0x80, 0x80]  # 1 KiB banks
        self.prg_ram_enabled = False
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        region = address & 0xF000
        if region <= 0xB000:
            self.map_chr((region - 0x8000) >> 11, 2, value)
        elif region <= 0xD000:
            self.nametable_banks[(region >> 12) & 1] = value | 0x80
        elif region == 0xE000:
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
            self.rom_nametables = bool(value & 0x10)
        else:
            self.map_prg(0, 16, value & 0x0F)
            self.prg_ram_enabled = bool(value & 0x10) and bool(self.prg_ram)

    def ciram_a10(self, address: int) -> int | None:
        a10 = super().ciram_a10(address)
        return None if self.rom_nametables else a10

    def ppu_read(self, address: int, t: int) -> int | None:
        if address >= 0x2000:  # only with ROM nametables: CIRAM answers otherwise
            a10 = super().ciram_a10(address) or 0
            bank = self.nametable_banks[a10]
            return self.chr[(bank * 0x400 + (address & 0x3FF)) % len(self.chr)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            super().ppu_write(address, value, t)


#: M2 cycles the Nantettatte!! Baseball licensing timer runs: the game checks
#: for 107,516 to 107,575; "most likely exactly 107520 = 1024 x 105"
#: (INES_Mapper_068.wiki).
LICENSING_CYCLES = 1024 * 105


class Sunsoft4Dual(Sunsoft4):
    """Mapper 68.1: the Sunsoft Dual Cartridge System (Nantettatte!! Baseball).

    INES_Mapper_068.wiki, NES_2.0_submappers.wiki: the image is the 128 KiB
    internal ROM and then the plugged-in cassette's. $F000 D3 selects the
    internal ROM (1) or the cassette (0), D2-D0 the 16 KiB bank; $C000 is
    always the internal ROM's last bank. A write to $6000-$7FFF while the RAM
    is disabled restarts the licensing IC's timer; while it runs the cassette
    is readable, and once it expires the cassette reads are open bus.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.internal_banks = min(len(image.prg), 0x20000) // 0x4000
        self.cassette_banks = len(image.prg) // 0x4000 - self.internal_banks
        self.from_cassette = False
        self.timer = 0
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(2, 16, self.internal_banks - 1)

    def m2(self, t: int) -> None:
        if self.timer:
            self.timer -= 1

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x8000 <= address < 0xC000 and self.from_cassette and not self.timer:
            return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000 and not self.prg_ram_enabled:
            self.timer = LICENSING_CYCLES
        super().cpu_write(address, value, t)
        if address & 0xF000 == 0xF000:
            self.from_cassette = not value & 0x08
            if self.from_cassette and self.cassette_banks:
                self.map_prg(0, 16, self.internal_banks + (value & 7) % self.cassette_banks)
            else:
                self.map_prg(0, 16, value & 7)


def mapper_68(image: RomImage, cpu_cycle_ticks: int) -> Banked:
    """Mapper 68's board by submapper."""
    if image.board.submapper == 1:
        return Sunsoft4Dual(image, cpu_cycle_ticks)
    return Sunsoft4(image, cpu_cycle_ticks)
