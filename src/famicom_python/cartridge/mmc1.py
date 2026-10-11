"""MMC1 (mapper 1): five serial writes load a register.

MMC1.wiki (specification tier). Certification is milestone 5 (Holy Mapperel,
``serom``, ``mmc1atest``); here it carries the blargg multi-test ROMs, which are
SNROM-style MMC1 boards.

Modelled: the serial port with its consecutive-cycle write ignore (the reset bit
is never ignored, and a write on the cycle after *any* write is, which needs
every CPU write: the connector delivers them); control, CHR and PRG registers;
PRG-RAM enable (MMC1B); SUROM's PRG A18 from the CHR register's bit 4. Not yet:
SOROM/SXROM PRG-RAM banking, MMC1A (155), the 32 KiB SEROM wiring of 1.5.
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage

MIRRORING = (SCREEN_A, SCREEN_B, VERTICAL, HORIZONTAL)  # control bits 1-0


class MMC1(Banked):
    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.shift = 0
        self.count = 0
        self.last_write_t = -1
        # Power-on: PRG mode 3, the last bank fixed at $C000 ("seems to reliably
        # power on in the last bank", MMC1.wiki l.137; contradiction C19).
        self.control = 0x0C
        self.chr0 = 0
        self.chr1 = 0
        self.prg_bank = 0
        self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        consecutive = t - self.last_write_t == self.cpu_cycle_ticks
        self.last_write_t = t
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if value & 0x80:
            self.shift = 0
            self.count = 0
            self.control |= 0x0C
            self._update()
            return
        if consecutive:
            return
        self.shift |= (value & 1) << self.count
        self.count += 1
        if self.count < 5:
            return
        register = (address >> 13) & 3
        if register == 0:
            self.control = self.shift
        elif register == 1:
            self.chr0 = self.shift
        elif register == 2:
            self.chr1 = self.shift
        else:
            self.prg_bank = self.shift
        self.shift = 0
        self.count = 0
        self._update()

    def _update(self) -> None:
        control = self.control
        self.set_mirroring(MIRRORING[control & 3])
        if control & 0x10:  # two 4 KiB CHR banks
            self.map_chr(0, 4, self.chr0)
            self.map_chr(4, 4, self.chr1)
        else:
            self.map_chr(0, 8, self.chr0 >> 1)
        # SUROM: with 512 KiB of PRG, CHR register bit 4 is PRG A18.
        outer = (self.chr0 & 0x10) if len(self.prg) > 0x40000 else 0
        bank = (self.prg_bank & 0x0F) | outer
        mode = (control >> 2) & 3
        if mode < 2:  # 32 KiB, the low bit ignored
            self.map_prg(0, 32, bank >> 1)
        elif mode == 2:  # first bank fixed at $8000
            self.map_prg(0, 16, outer)
            self.map_prg(2, 16, bank)
        else:  # last bank fixed at $C000
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, outer | 0x0F)
        self.prg_ram_enabled = bool(self.prg_ram) and not self.prg_bank & 0x10
