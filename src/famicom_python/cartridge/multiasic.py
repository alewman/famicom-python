"""Multicarts that switch whole mapper ASICs: 394, 351 and Mindkids' FPGA (446).

Each from its NESdev wiki page. One die holds an MMC3 clone and a J.Y. Company ASIC, or
an MMC3, an MMC1 and a VRC4, and the board's registers say which one answers.
Here each is the ordinary class with its banks translated through the board's
outer registers. No judge ROM exists; the claims rest on sweeps against
Mesen2, a detector, and on looking (docs/claims.md).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage
from .irem import H3001
from .jycompany import JYCompany
from .konami import VRC24
from .mmc1 import MMC1
from .mmc3 import MMC3


class Translated:
    """A mapper whose bank numbers the host board rewrites (mixed in before the mapper)."""

    host: Any

    def __init__(self, host: Any, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.host = host
        super().__init__(image, cpu_cycle_ticks)  # type: ignore[call-arg]

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        count = size_kib // 8
        for i in range(count):
            eighth = self.host.prg_bank(self, window + i, bank * count + i)
            self.prg_offsets[window + i] = eighth * 0x2000 % len(self.prg)  # type: ignore[attr-defined]

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            one = self.host.chr_bank(self, bank * size_kib + i)
            self.chr_offsets[window + i] = one * 0x400 % len(self.chr)  # type: ignore[attr-defined]


class HostMMC3(Translated, MMC3):
    def refresh(self) -> None:
        self._update()


class HostMMC1(Translated, MMC1):
    def refresh(self) -> None:
        self._update()


class HostJY(Translated, JYCompany):
    def _map_chr(self, window: int, size_kib: int, bank: int) -> None:
        self.map_chr(window, size_kib, bank)

    def refresh(self) -> None:
        self._update()


class HostH3001(Translated, H3001):
    def __init__(self, host: Any, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.prg_banks: dict[int, int] = {}
        super().__init__(host, image, cpu_cycle_ticks)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        self.prg_banks[window] = bank
        super().map_prg(window, size_kib, bank)

    def refresh(self) -> None:
        for window, bank in list(self.prg_banks.items()):
            self.map_prg(window, 8, bank)


class HostVRC4(Translated, VRC24):
    """The XB's VRC4: A0, A1 from CPU A2, A3, exchanged when A11 is set."""

    def __init__(self, host: Any, image: RomImage, cpu_cycle_ticks: int) -> None:
        board = replace(image.board, mapper=21, submapper=1)
        super().__init__(host, image.with_board(board), cpu_cycle_ticks)

    def _register(self, address: int) -> int:
        low, high = (address >> 2) & 1, (address >> 3) & 1
        return high | low << 1 if address & 0x800 else low | high << 1

    def refresh(self) -> None:
        self._update_prg()
        for window, bank in enumerate(self.chr_registers):
            self.map_chr(window, 1, bank)


class Composite(Banked):
    """Forwards the connector to the ASIC in charge (``self.asic``), or none."""

    counts_m2 = True
    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.asic: Any = None

    def cpu_read(self, address: int, t: int) -> int | None:
        return self.asic.cpu_read(address, t) if self.asic else super().cpu_read(address, t)

    def forward_write(self, address: int, value: int, t: int) -> None:
        if self.asic:
            self.asic.cpu_write(address, value, t)
            self.irq = self.asic.irq

    def ciram_a10(self, address: int) -> int | None:
        return self.asic.ciram_a10(address) if self.asic else super().ciram_a10(address)

    def ppu_read(self, address: int, t: int) -> int | None:
        return self.asic.ppu_read(address, t) if self.asic else super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if self.asic:
            self.asic.ppu_write(address, value, t)
        else:
            super().ppu_write(address, value, t)

    def ppu_address(self, address: int, t: int) -> None:
        if self.asic:
            self.asic.ppu_address(address, t)
            self.irq = self.asic.irq

    def m2(self, t: int) -> None:
        if self.asic:
            self.asic.m2(t)
            self.irq = self.asic.irq


class HSK007(Composite):
    """Mapper 394: Realtec's HSK007: BNROM, an MMC3 clone or a J.Y. Company ASIC.

    NES_2.0_Mapper_394.wiki: $5009 (masks unknown, A3 set) ``...MMCBA``: A PRG A18,
    B PRG and CHR A19, MM 0 BNROM, 1 MMC3, 2-3 J.Y.; CHR A18 is A on submapper
    0, C on 1. $500B ``cC.pPBB.``: BB PRG A16-A15 in BNROM mode, P PRG A17
    where p is 0 (p: from the MMC3), C CHR A17 where c is 0 (c: from the
    MMC3). Power-on $0F, $90.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.submapper = image.board.submapper
        self.mode_register = 0x0F
        self.outer = 0x90
        self.jy: Any = None
        self.mmc3 = HostMMC3(self, image, cpu_cycle_ticks)
        self.jy = HostJY(self, image, cpu_cycle_ticks)
        self._select()

    def _high_prg(self) -> int:
        return (self.mode_register & 3) << 5

    def _high_chr(self) -> int:
        r = self.mode_register
        a18 = (r >> 2) & 1 if self.submapper else r & 1
        return (a18 | (r & 2)) << 8

    def prg_bank(self, asic: Any, window: int, bank: int) -> int:
        if asic is self.jy:
            return bank & 0x1F | self._high_prg()
        a17 = bank & 0x10 if self.outer & 0x10 else (self.outer & 8) << 1
        return bank & 0x0F | a17 | self._high_prg()

    def chr_bank(self, asic: Any, bank: int) -> int:
        if asic is self.jy:
            return bank & 0xFF | self._high_chr()
        a17 = bank & 0x80 if self.outer & 0x80 else (self.outer & 0x40) << 1
        return bank & 0x7F | a17 | self._high_chr()

    def _select(self) -> None:
        mode = (self.mode_register >> 3) & 3
        self.asic = None if mode == 0 else self.mmc3 if mode == 1 else self.jy
        if self.asic:
            self.asic.refresh()
            return
        a17 = 0 if self.outer & 0x10 else (self.outer >> 3) & 1
        self.map_prg(0, 32, (self.outer >> 1) & 3 | a17 << 2 | self._high_prg() >> 2)
        self.map_chr(0, 8, self._high_chr() >> 3)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF00F == 0x5009:
            self.mode_register = value
            self._select()
        elif address & 0xF00F == 0x500B:
            self.outer = value
            self._select()
        else:
            self.forward_write(address, value, t)


class Techline351(Composite):
    """Mapper 351: Techline's XB multicarts: an MMC3, an MMC1 or a VRC4 on one die.

    NES_2.0_Mapper_351.wiki (mask $F003, all 0 at reset): $5000 ``BBBBBBMM``: the 8 KiB
    CHR base and M, the ASIC (0/1 MMC3, 2 MMC1, 3 VRC4); $5001 ``BBBBBB..``:
    the 16 KiB PRG base; $5002 ``CCCpPP.R``: the inner PRG size (PP: p clear
    256, 128 KiB; p set NROM of 32, 16, 8 KiB), the inner CHR size (1xx 8 KiB,
    01x 128, 001 32, 000 256 KiB), and R: CHR-RAM, with the CHR-ROM becoming
    the second half of the PRG. In NROM mode $4025 D3 is the mirroring (1
    horizontal). The page's marks for CCC fall on D6-D4, which holds p;
    D7-D5 is the reading that leaves p alone, and the menu's $5002 = $D4 suits
    it. The B fields are bank numbers (value >> 2): the menu's stub writes
    $5001 = $3C from the bank that must stay put, the 16 KiB bank 15.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.rom = image.chr
        self.chr_ram = bytearray(0x2000)
        self.registers = [0, 0, 0]
        self.asics = {
            0: HostMMC3(self, image, cpu_cycle_ticks),
            2: HostMMC1(self, image, cpu_cycle_ticks),
            3: HostVRC4(self, image, cpu_cycle_ticks),
        }
        self.asics[1] = self.asics[0]
        self._select()

    def prg_bank(self, asic: Any, window: int, bank: int) -> int:
        base8, mode = (self.registers[1] >> 2) * 2, self.registers[2]
        size = (mode >> 2) & 3
        if mode & 0x10:
            if size == 0:
                return (base8 & ~3) | window
            return (base8 & ~1) | window & 1 if size == 1 else base8
        mask = 0x1F if size == 0 else 0x0F
        return (base8 & ~mask) | bank & mask

    def chr_bank(self, asic: Any, bank: int) -> int:
        size = self.registers[2] >> 5
        mask = 0x07 if size & 4 else 0x7F if size & 2 else 0x1F if size & 1 else 0xFF
        return (((self.registers[0] >> 2) * 8) & ~mask) | bank & mask

    def _select(self) -> None:
        self.asic = self.asics[self.registers[0] & 3]
        ram = self.registers[2] & 1
        for asic in self.asics.values():
            asic.prg = self.prg + self.rom if ram else self.prg
            asic.chr = self.chr_ram if ram else self.rom
            asic.chr_writable = bool(ram)
        self.asic.refresh()

    def m2_gap(self, t: int) -> None:
        self.registers = [0, 0, 0]
        self._select()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF003 in (0x5000, 0x5001, 0x5002):
            self.registers[address & 3] = value
            self._select()
        elif address == 0x4025 and self.registers[2] & 0x10:
            self.asic.set_mirroring(HORIZONTAL if value & 8 else VERTICAL)
        else:
            self.forward_write(address, value, t)


#: Mapper 446's (submapper, $5000) that are MMC1 and MMC3 boards.
FPGA_MMC1 = {(0, 1), (1, 5), (1, 6), (1, 7), (2, 5), (2, 6), (2, 7)}
FPGA_MMC3 = {(1, 1), (2, 1), (2, 9), (2, 0x0D)}


class Mindkids446(Composite):
    """Mapper 446: Mindkids' SMD172B_FPGA: an FPGA that becomes the mapper the game asks for.

    NES_2.0_Mapper_446.wiki. $5000 ``L..MMMMM``: the mapper, by submapper's table, and L
    locks the supervisor until reset. $5001/$5002 the outer 8 KiB bank; $5003
    its mask, 1 the outer bit, but the inner one on submapper 2; $5004
    D5-D4 CHR-RAM's inner mask (0x 256, 10 128, 11 32 KiB), D0 the mirroring
    (1 vertical); $5005 D2 protects CHR-RAM; $5006 D4-D0 its outer 8 KiB bank.

    Only the MMC1 and MMC3 boards and H3001 are here, the ones the dumps ask for.
    Until the mapper is chosen the board acts as an UNROM (mapper 0 on the
    table; the page gives no reset state, the games decide): the outer bank at
    $8000, from which they copy their CHR to CHR-RAM, and the last 16 KiB fixed.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.image = image
        self.ticks = cpu_cycle_ticks
        self.submapper = image.board.submapper
        self.outer = self.mask = 0
        self.flags = self.protect = self.chr_outer = 0
        self.locked = False
        self.chr_ram = bytearray(0x40000)
        self.chr = self.chr_ram
        self.chr_writable = True
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self._map_outer()

    def _map_outer(self) -> None:
        self.map_prg(0, 8, self.outer)
        self.map_prg(1, 8, self.outer + 1)

    def prg_bank(self, asic: Any, window: int, bank: int) -> int:
        mask = ~self.mask & 0xFFFF if self.submapper == 2 else self.mask
        return (bank & ~mask & 0xFFFF) | (self.outer & mask)

    def chr_bank(self, asic: Any, bank: int) -> int:
        inner = {2: 0x7F, 3: 0x1F}.get(self.flags >> 4 & 3, 0xFF)
        return (bank & inner) | (self.chr_outer << 3 & ~inner)

    def _choose(self, value: int) -> None:
        key = (self.submapper, value & 0x1F)
        small = replace(self.image, prg=self.image.prg[:0x40000])
        if key in FPGA_MMC1:
            self.asic = HostMMC1(self, small, self.ticks)
        elif self.submapper == 3 and key[1] == 1:
            self.asic = HostH3001(self, self.image, self.ticks)
        elif key in FPGA_MMC3:
            self.asic = HostMMC3(self, self.image, self.ticks)
        else:
            return
        asic = self.asic
        asic.prg, asic.chr, asic.chr_writable = self.prg, self.chr_ram, not self.protect
        asic.prg_ram = self.prg_ram or asic.prg_ram
        asic.set_mirroring(VERTICAL if self.flags & 1 else HORIZONTAL)
        asic.refresh()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x5007 and not self.locked:
            register = address & 7
            if register == 0:
                self.locked = bool(value & 0x80)
                self._choose(value)
            elif register == 1:
                self.outer = (self.outer & 0xFF00) | value
                if not self.asic:
                    self._map_outer()
            elif register == 2:
                self.outer = (self.outer & 0x00FF) | value << 8
                if not self.asic:
                    self._map_outer()
            elif register == 3:
                self.mask = value
            elif register == 4:
                self.flags = value
            elif register == 5:
                self.protect = value & 4
                self.chr_writable = not self.protect
            else:
                self.chr_outer = value & 0x1F
                self.map_chr(0, 8, self.chr_outer)
            if self.asic:
                self.asic.chr_writable = not self.protect
                self.asic.refresh()
        elif self.asic:
            self.forward_write(address, value, t)
        else:
            super().cpu_write(address, value, t)
