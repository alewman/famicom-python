"""Tengen's RAMBO-1 (64): the MMC3 with more banks and a CPU-cycle counter mode.

RAMBO-1.wiki. No judge ROM exists; the claim rests on sweeps against Mesen2,
a detector whose counter is tuned per game (its source names Hard Drivin',
Skull & Crossbones and Klax), where this one follows the wiki's description.
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL
from .ines import RomImage
from .mmc3 import MMC3

#: CPU cycles from the counter reaching 0 to /IRQ (RAMBO-1.wiki: "until M2
#: falls twice after the PPU A12 rise" in scanline mode, "one M2 cycle later"
#: in CPU cycle mode).
SCANLINE_IRQ_DELAY, CYCLE_IRQ_DELAY = 2, 1


class RAMBO1(MMC3):
    """Mapper 64: Tengen RAMBO-1.

    $8000 ``CPKxRRRR`` selects one of sixteen registers (R0-R9 and RF), K
    makes $0000-$0FFF four 1 KiB banks (R0, R8, R1, R9) instead of two 2 KiB
    ones, P swaps R6 and RF (the banks at $8000 and $C000; R7 at $A000, the
    last fixed), C inverts CHR A12; $8001 writes it, all eight bits. $A000
    D0 the arrangement (1 horizontal). $C000 the reload value; $C001 D0 the
    counter's clock (0: PPU A12, filtered as the MMC3's; 1: every 4 CPU
    cycles, the prescaler restarting) and a reload at the next clock;
    $E000 disables and acknowledges, $E001 enables.

    A clock reloads the counter after a $C001 write (with D0 set if the value
    is not 0: the wiki's "extra kick", which Klax needs), or when it is 0, and
    otherwise decrements it; reaching 0 while enabled asserts /IRQ
    :data:`SCANLINE_IRQ_DELAY` or :data:`CYCLE_IRQ_DELAY` CPU cycles later.
    Power-on registers unspecified: 0 here.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.cycle_mode = False
        self.prescaler = 0
        self.irq_delay = 0
        super().__init__(image, cpu_cycle_ticks)
        self.registers = [0] * 16
        self.prg_ram_enabled = False
        self._update()

    def _update(self) -> None:
        r = self.registers
        if len(r) < 16:  # MMC3.__init__'s first call, before ours
            return
        select = self.bank_select
        last = len(self.prg) // 0x2000 - 1
        low, high = (r[15], r[6]) if select & 0x40 else (r[6], r[15])
        self.map_prg(0, 8, low)
        self.map_prg(1, 8, r[7])
        self.map_prg(2, 8, high)
        self.map_prg(3, 8, last)
        a12 = 4 if select & 0x80 else 0
        if select & 0x20:  # four 1 KiB banks
            for i, bank in enumerate((r[0], r[8], r[1], r[9])):
                self.map_chr(a12 + i, 1, bank)
        else:  # two 2 KiB banks; D0 ignored
            self.map_chr(a12, 2, r[0] >> 1)
            self.map_chr(a12 + 2, 2, r[1] >> 1)
        for i in range(4):
            self.map_chr((a12 ^ 4) + i, 1, r[2 + i])

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            return
        register = address & 0xE001
        if register == 0x8000:
            self.bank_select = value
            self._update()
        elif register == 0x8001:
            self.registers[self.bank_select & 0x0F] = value
            self._update()
        elif register == 0xA000:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        elif register == 0xC000:
            self.latch = value
        elif register == 0xC001:
            self.cycle_mode = bool(value & 1)
            self.prescaler = 0
            self.reload = True
        elif register == 0xE000:
            self.irq_enabled = False
            self.irq = False
            self.irq_delay = 0
        else:
            self.irq_enabled = True

    def ppu_address(self, address: int, t: int) -> None:
        if not self.cycle_mode:
            super().ppu_address(address, t)

    def clock_counter(self) -> None:
        if self.reload:
            self.counter = self.latch | 1 if self.latch else 0
            self.reload = False
        elif self.counter == 0:
            self.counter = self.latch
        else:
            self.counter -= 1
        if self.counter == 0 and self.irq_enabled:
            self.irq_delay = CYCLE_IRQ_DELAY if self.cycle_mode else SCANLINE_IRQ_DELAY

    def m2(self, t: int) -> None:
        if self.irq_delay:
            self.irq_delay -= 1
            if self.irq_delay == 0:
                self.irq = True
        if self.cycle_mode:
            self.prescaler = (self.prescaler + 1) & 3
            if self.prescaler == 0:
                self.clock_counter()
