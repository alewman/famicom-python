"""MMC1 (mappers 1 and 155): five serial writes load a register.

MMC1.wiki (specification tier); judged by Holy Mapperel, ``serom`` and
``mmc1atest`` (docs/claims.md).

Modelled: the serial port with its consecutive-cycle write ignore (the reset bit
is never ignored, and a write on the cycle after *any* write is, which needs
every CPU write: the connector delivers them); control, CHR and PRG registers;
the board wirings that reuse CHR lines (MMC1.wiki "Summary"): PRG A18 for
512 KiB (SUROM, SXROM), the PRG-RAM bank for 16 KiB (SOROM, SZROM) and 32 KiB
(SXROM), SNROM's PRG-RAM disable; MMC1B's PRG-RAM disable ($E000 D4); MMC1A
(mapper 155): RAM always enabled, and D4 makes D3 drive PRG A17 past the
fixed-bank logic; SEROM/SHROM (1.5), whose PRG A14 is CPU A14.

The reused CHR lines come from the CHR register the MMC1 is outputting, which
in 4 KiB mode follows PPU A12 as the PPU renders; here they come from CHR
register 0 always, as every 4 KiB-mode board with those lines would flicker
its PRG or RAM (the wiki tells programs not to).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage

MIRRORING = (SCREEN_A, SCREEN_B, VERTICAL, HORIZONTAL)  # control bits 1-0


class MMC1(Banked):
    mmc1a = False  # mapper 155

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.fixed_32k = board.submapper == 5  # SEROM, SHROM, SH1ROM
        ram = len(self.prg_ram)
        # Which CHR register bits are not CHR lines (MMC1.wiki "Summary").
        # SZROM: 8 KiB RAM + 8 KiB NVRAM with CHR-ROM of 16 KiB or more.
        szrom = board.prg_ram == 0x2000 and board.prg_nvram == 0x2000 and len(self.chr) >= 0x4000
        if ram == 0x8000:  # SXROM: D2 -> RAM A13, D3 -> RAM A14
            self.ram_bank_shift, self.ram_bank_mask = 2, 3
        elif ram == 0x4000:  # SOROM: D3 -> RAM A13; SZROM: D4
            self.ram_bank_shift, self.ram_bank_mask = (4 if szrom else 3), 1
        else:
            self.ram_bank_shift, self.ram_bank_mask = 0, 0
        # SNROM: 8 KiB CHR-RAM, 8 KiB PRG-RAM, PRG up to 256 KiB: D4 disables the RAM.
        self.snrom = ram == 0x2000 and self.chr_writable and len(self.prg) <= 0x40000
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
        if self.fixed_32k:
            self.map_prg(0, 32, 0)
        else:
            self._update_prg(control)
        self.prg_ram_offset = ((self.chr0 >> self.ram_bank_shift) & self.ram_bank_mask) * 0x2000
        enabled = bool(self.prg_ram)
        if not self.mmc1a:
            enabled = enabled and not self.prg_bank & 0x10
        if self.snrom:
            enabled = enabled and not self.chr0 & 0x10
        self.prg_ram_enabled = enabled

    def _update_prg(self, control: int) -> None:
        # SUROM, SXROM: with 512 KiB of PRG, CHR register bit 4 is PRG A18,
        # for the whole of $8000-$FFFF ("outer bank").
        outer = (self.chr0 & 0x10) if len(self.prg) > 0x40000 else 0
        bank = (self.prg_bank & 0x0F) | outer
        mode = (control >> 2) & 3
        if mode < 2:  # 32 KiB, the low bit ignored
            self.map_prg(0, 32, bank >> 1)
            return
        # The fixed bank is 0 or 15 in A17-A14; MMC1A with D4 set passes D3 to
        # A17 itself, so the fixed bank stays in the selected 128 KiB half.
        fixed = 0 if mode == 2 else 0x0F
        if self.mmc1a and self.prg_bank & 0x10:
            fixed = (fixed & 0x07) | (self.prg_bank & 0x08)
        if mode == 2:  # first bank fixed at $8000
            self.map_prg(0, 16, outer | fixed)
            self.map_prg(2, 16, bank)
        else:  # last bank fixed at $C000
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, outer | fixed)


class MMC1A(MMC1):
    """Mapper 155: MMC1A, whose $E000 D4 leaves PRG-RAM enabled (MMC1.wiki "ASIC Revisions")."""

    mmc1a = True
