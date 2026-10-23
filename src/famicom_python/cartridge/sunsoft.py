"""Sunsoft's mappers: FME-7, 5A and 5B (69).

Judged by Holy Mapperel and tepples's ``fme7acktest`` and ``fme7ramtest``
(docs/claims.md). The 5B's sound is milestone 8's.
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
