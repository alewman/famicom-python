"""Waixing's MMC3 boards: the 8025 "enhanced MMC3" (176), the CHR-ROM/CHR-RAM mixes (74, 191,
192, 194, 195) and FS309 (199).

INES_Mapper_176.wiki, MMC3_with_CHR_ROM_and_CHR_RAM.wiki and each mapper's
page. No judge ROM exists; the claims rest on sweeps against Mesen2, a
detector whose 176 blends the submappers where this one follows the wiki's
per-submapper registers (docs/claims.md).
"""

from __future__ import annotations

from dataclasses import replace

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL
from .ines import RomImage
from .konami import VRC4E, VRC24
from .mmc3 import MMC3

#: The power-on bank registers: MMC3 R0-R7, then the extended mode's R8-RB.
POWER_ON_REGISTERS = (0x00, 0x02, 0x04, 0x05, 0x06, 0x07, 0x00, 0x01, 0xFE, 0xFF, 0xFF, 0xFF)


class FK23C(MMC3):
    """Mapper 176: the 8025 chipset, an MMC3 with outer banks, NROM/UNROM/CNROM modes and more.

    Outer registers at $5000-$5FFF where A4 is set (the solder pad at 0, which
    the wiki says suits every image), A1-A0 (A2-A0 on 176.3) selecting:

    - $5xx0 ``PCTmPMMM``: PRG mode (0-2 MMC3 in a 512 KiB / 256 / 128 KiB
      outer bank, 3 NROM-128, 4 NROM-256, 5 UNROM), the outer CHR size (D4:
      256 or 128 KiB), CHR-RAM (D5, boards with both) or 176.1's CNROM latch
      off, CHR A12-A10 from the PPU (D6: 8 KiB CHR banks), and on 176.2 PRG
      A21 (D3) and A22 (D7).
    - $5xx1: PRG A20-A14, the outer PRG base; $5xx2: CHR A20-A13, and on 176.2
      PRG A25 (D5) and A24-A23 (D7-D6), on 176.4 PRG A21 (D7).
    - $5xx3 D1 (176.1/2): the extended MMC3 mode, RAMBO-1-like: R8/R9 make the
      fixed PRG banks selectable, RA/RB split the 2 KiB CHR banks.
    - 176.3: $5xx5 PRG A24-A21, $5xx6 CHR A24-A21. 176.5: $4800 PRG A24-A19.

    176.1 and 176.3 give the MMC3 eight PRG bits (a 2 MiB outer bank, fixed
    banks $FE/$FF). The MMC3's registers decode with mask $E003 (writes to
    $8002/$8003 do nothing: verified on hardware, the wiki). On 176.2 (FS005)
    $A001 D5 turns $A001 into the RAM configuration register: 32 KiB of WRAM in
    four banks (D1-D0 at $6000), the first 8 KiB of CHR from RAM (D2), the
    $5000 registers enabled (D6; disabled, $5000-$5FFF is the second 4 KiB of
    WRAM bank 2, which Waixing's copy protection uses), one-screen mirroring
    allowed, and D7 enables the RAM. Power-on registers per the wiki.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        board = image.board
        self.submapper = board.submapper
        self.wide_mmc3 = self.submapper in (1, 3)
        self.mode = 0
        self.prg_base = 0
        self.chr_base = 0
        self.extended = False
        self.prg_high = 0  # 176.3 $5xx5 / 176.5 $4800
        self.chr_high = 0  # 176.3 $5xx6
        self.latch = 0  # UNROM / CNROM latch
        self.ram_config = 0  # 176.2 $A001 while D5 is set
        super().__init__(image, cpu_cycle_ticks)
        self.rom = image.chr
        self.chr_ram = bytearray(max(board.chr_ram + board.chr_nvram, 0x2000))
        self.chr_ram_window = [False] * 8
        self.registers = list(POWER_ON_REGISTERS)
        self.prg_ram = bytearray(max(len(self.prg_ram), 0x2000))
        self.prg_ram_enabled = False  # $A001 powers on $00 (the wiki)
        self._update()

    # -- the CPU side ----------------------------------------------------

    def _outer_enabled(self) -> bool:
        return not self.ram_config & 0x20 or bool(self.ram_config & 0x40)

    def _wram_offset(self, address: int) -> int | None:
        """The WRAM byte a CPU address reaches, or None."""
        config = self.ram_config
        if self.submapper == 2 and config & 0x20:
            if 0x6000 <= address < 0x8000:
                return ((config & 3) * 0x2000 + (address & 0x1FFF)) % len(self.prg_ram)
            if 0x5000 <= address < 0x6000 and not config & 0x40:
                return (2 * 0x2000 + 0x1000 + (address & 0x0FFF)) % len(self.prg_ram)
            return None
        if 0x6000 <= address < 0x8000 and self.prg_ram_enabled:
            return (address & 0x1FFF) % len(self.prg_ram)
        return None

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return super().cpu_read(address, t)
        offset = self._wram_offset(address)
        return None if offset is None else self.prg_ram[offset]

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            offset = self._wram_offset(address)
            if offset is not None and (self.ram_config & 0x20 or self.prg_ram_writable):
                self.prg_ram[offset] = value
            elif 0x5000 <= address < 0x6000 and self._outer_enabled():
                self._outer_write(address, value)
            elif self.submapper == 5 and address & 0xF800 == 0x4800:
                self.prg_high = value & 0x3F
                self._update()
            return
        self.latch = value
        register = address & 0xE003
        if register == 0x8000:
            self.bank_select = value
        elif register == 0x8001:
            index = self.bank_select & (0x0F if self.extended else 0x07)
            if index < len(self.registers):
                self.registers[index] = value
        elif register == 0xA000:
            modes = (VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)
            mask = 3 if self.submapper == 2 and self.ram_config & 0x20 else 1
            self.set_mirroring(modes[value & mask])
        elif register == 0xA001:
            if self.submapper == 2 and (value & 0x20 or self.ram_config & 0x20):
                self.ram_config = value
            else:
                self.ram_protect(value)
        elif register in (0xC000, 0xC001, 0xE000, 0xE001):
            super().cpu_write(register, value, t)
            return
        self._update()

    def ram_protect(self, value: int) -> None:
        self.prg_ram_enabled = bool(value & 0x80)
        self.prg_ram_writable = not value & 0x40

    def _outer_write(self, address: int, value: int) -> None:
        if not address & 0x10:  # the solder pad's address line
            return
        register = address & (7 if self.submapper == 3 else 3)
        if register == 0:
            self.mode = value
        elif register == 1:
            self.prg_base = value & 0x7F
        elif register == 2:
            self.chr_base = value
            self.latch = 0
        elif register == 3:
            self.extended = bool(value & 0x02) and self.submapper in (1, 2)
        elif register == 5:
            self.prg_high = value & 0x0F
        elif register == 6:
            self.chr_high = value & 0x0F
        self._update()

    # -- banking ---------------------------------------------------------

    def _prg_high_bits(self) -> int:
        """PRG A21 and up, as a 16 KiB bank offset."""
        mode, chr_base, sub = self.mode, self.chr_base, self.submapper
        if sub == 2:
            a21 = (
                (mode >> 3) & 1 | (mode >> 6) & 2 | (chr_base >> 4) & 0x0C | (chr_base >> 1) & 0x10
            )
            return a21 << 7
        if sub == 3:
            return self.prg_high << 7
        if sub == 4:
            return (chr_base >> 7) << 7
        if sub == 5:
            return self.prg_high << 5
        return 0

    def _update(self) -> None:
        if len(self.registers) < 12:  # MMC3.__init__'s first call, before ours
            return
        r, select, mode = self.registers, self.bank_select, self.mode & 7
        base16 = self.prg_base & (0x1F if self.submapper == 5 else 0x7F)
        high16 = self._prg_high_bits()
        if mode >= 3 and not self.extended:
            if mode == 3:  # NROM-128
                self.map_prg(0, 16, high16 | base16)
                self.map_prg(2, 16, high16 | base16)
            elif mode == 4:  # NROM-256
                self.map_prg(0, 32, (high16 | base16) >> 1)
            else:  # UNROM: inner bank from the latch, 7 fixed
                self.map_prg(0, 16, high16 | base16 & ~7 | self.latch & 7)
                self.map_prg(2, 16, high16 | base16 & ~7 | 7)
        else:
            inner = 0xFF if self.extended or self.wide_mmc3 else 0x3F >> min(mode, 2)
            outer8 = ((high16 | base16) << 1) & ~inner
            if self.extended:
                banks = (r[8], r[7], r[6], r[9]) if select & 0x40 else (r[6], r[7], r[8], r[9])
            else:
                fixed = (0xFE, r[7], r[6], 0xFF) if select & 0x40 else (r[6], r[7], 0xFE, 0xFF)
                banks = fixed
            for window, bank in enumerate(banks):
                self.map_prg(window, 8, outer8 | bank & inner)
        self._update_chr()

    def _update_chr(self) -> None:
        r, select, mode = self.registers, self.bank_select, self.mode
        base8 = self.chr_base | self.chr_high << 8
        if mode & 0x40:  # CHR A12-A10 from the PPU: 8 KiB banks
            if self.submapper == 1 and not mode & 0x20:  # CNROM latch
                mask = 1 if mode & 0x10 else 3
                bank8 = base8 & ~mask | self.latch & mask
            else:
                bank8 = base8
            for i in range(8):
                self._map_chr_1k(i, bank8 * 8 + i)
            return
        a12 = 4 if select & 0x80 else 0
        if self.extended:
            ones = (r[0], r[10], r[1], r[11])
            inner = 0xFF
        else:
            ones = (r[0] & 0xFE, r[0] | 1, r[1] & 0xFE, r[1] | 1)
            inner = 0x7F if mode & 0x10 else 0xFF
        outer1 = (base8 << 3) & ~inner
        for i, bank in enumerate(ones):
            self._map_chr_1k(a12 + i, outer1 | bank & inner)
        for i in range(4):
            self._map_chr_1k((a12 ^ 4) + i, outer1 | r[2 + i] & inner)

    def _map_chr_1k(self, window: int, bank: int) -> None:
        ram = (
            not self.rom
            or (self.submapper in (0, 1) and bool(self.mode & 0x20) and not self.mode & 0x40)
            or (self.submapper == 2 and self.ram_config & 0x24 == 0x24 and bank < 8)
        )
        self.chr_ram_window[window] = ram
        if ram:
            self.chr_offsets[window] = bank * 0x400 % len(self.chr_ram)
        else:
            self.chr_offsets[window] = bank * 0x400 % len(self.rom)

    # -- the PPU side ----------------------------------------------------

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            window = address >> 10
            memory = self.chr_ram if self.chr_ram_window[window] else self.rom
            return memory[self.chr_offsets[window] + (address & 0x3FF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            window = address >> 10
            if self.chr_ram_window[window]:
                self.chr_ram[self.chr_offsets[window] + (address & 0x3FF)] = value
            return
        super().ppu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg_ram) if self.battery else None


#: Mapper -> (first CHR bank that is RAM, how many 1 KiB banks): the wiki's table.
MIXED_CHR = {74: (8, 2), 192: (8, 4), 194: (0, 2)}

#: Mapper 195's CHR-RAM window by the value written to CHR-ROM (D7, D6, D3, D1):
#: (first bank, banks); None for CHR-ROM only (INES_Mapper_195.wiki).
FS303_WINDOWS = {
    0x80: (0x28, 4),
    0x82: (0x00, 4),
    0x88: (0x4C, 4),
    0x8A: (0x64, 4),
    0xC0: (0x46, 2),
    0xC2: (0x7C, 2),
    0xC8: (0x0A, 2),
    0xCA: None,
}


class MixedCHR(MMC3):
    """Mappers 74, 191, 192, 194 and 195: MMC3 clones whose CHR bank numbers pick CHR-RAM too.

    74 (43-393), 192 (FS308), 194: banks 8-9, 8-B and 0-1 are RAM, the rest
    ROM (MMC3_with_CHR_ROM_and_CHR_RAM.wiki). 195 (FS303): a write to a CHR-ROM
    bank moves the RAM window, by that bank's number and not the data (the page's
    ``CHRB~``): D7-D6, D3 and D1 pick 2 or 4 banks from its table (D4: ROM only),
    $80 at power-on; the RAM sees CHR A12-A10
    only, so windows that differ only above A12 share it. 191 (Xianfeng's
    Dǔshén): CHR A17 (bank bit 7) picks 2 KiB of RAM; 191.1 adds the outer
    register at $90AA (mask $F0FF): D1-D0 move the fixed PRG banks
    ($18/$19 + 2 x value) and, below 3, force CHR A17 high with the RAM off.
    195's variant with 4 KiB of volatile PRG-RAM (NES 2.0 PRG-RAM 4 KiB)
    maps it at $5000-$5FFF.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        board = image.board
        self.kind = board.mapper
        self.window: tuple[int, int] | None = MIXED_CHR.get(self.kind, (0x28, 4))
        self.outer = 0
        self.dushen_outer = self.kind == 191 and (board.submapper == 1 or len(image.chr) >= 0x40000)
        self.rom = image.chr
        self.chr_ram = bytearray(max(board.chr_ram + board.chr_nvram, 0x2000))
        self.chr_ram_window = [False] * 8
        self.window_banks = [0] * 8
        super().__init__(image, cpu_cycle_ticks)
        self.low_ram = bytearray(0x1000) if self.kind == 195 and board.prg_ram == 0x1000 else None

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        if self.dushen_outer and window >= 2 and bank >= len(self.prg) // 0x2000 - 2:
            bank = 0x18 + 2 * self.outer + (window & 1)
        super().map_prg(window, size_kib, bank)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            self._map_1k(window + i, bank * size_kib + i)

    def _map_1k(self, window: int, bank: int) -> None:
        self.window_banks[window] = bank
        if self.kind == 191:
            if self.dushen_outer and self.outer < 3:
                ram, bank = False, bank | 0x80
            else:
                ram = bool(bank & 0x80)
            offset = (bank & 1) * 0x400 if ram else bank * 0x400
        elif self.kind == 195:
            ram = self.window is not None and self.window[0] <= bank < sum(self.window)
            offset = (bank & 7 if ram else bank) * 0x400
        else:
            first, count = self.window or (0, 0)
            ram = first <= bank < first + count
            offset = (bank - first if ram else bank) * 0x400
        self.chr_ram_window[window] = ram
        memory = self.chr_ram if ram else self.rom
        self.chr_offsets[window] = offset % len(memory) if ram else offset % max(len(memory), 1)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.low_ram is not None and 0x5000 <= address < 0x6000:
            return self.low_ram[address & 0x0FFF]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if self.low_ram is not None and 0x5000 <= address < 0x6000:
            self.low_ram[address & 0x0FFF] = value
            return
        if self.dushen_outer and address & 0xF0FF == 0x90AA:
            self.outer = value & 3
            self._update()
        super().cpu_write(address, value, t)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            window = address >> 10
            memory = self.chr_ram if self.chr_ram_window[window] else self.rom
            return memory[self.chr_offsets[window] + (address & 0x3FF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x2000:
            super().ppu_write(address, value, t)
            return
        window = address >> 10
        if self.chr_ram_window[window]:
            self.chr_ram[self.chr_offsets[window] + (address & 0x3FF)] = value
        elif self.kind == 195 and self.window_banks[window] & 0x80:
            bank = self.window_banks[window]
            self.window = None if bank & 0x10 else FS303_WINDOWS[bank & 0xCA]
            self._update()


#: 252/253: a pattern-table write in this bank moves the RAM to (mask, match).
WAIXING_GAL = {0x88: (0xFC, 0x4C), 0xC2: (0xFE, 0x7C), 0xC8: (0xFE, 0x04)}


class WaixingVRC4(VRC24):
    """Mappers 252 and 253: Waixing's VRC4e clones with 2 KiB of CHR-RAM among the banks.

    INES_Mapper_252.wiki, INES_Mapper_253.wiki: chip A0/A1 on CPU A2/A3 (23.2); bank numbers
    6-7 (252) or 4-5 (253) are the RAM. Which numbers can change: a GAL watches
    the bank a pattern-table write lands in, and a bank of $88 moves the RAM to
    $4C-$4F, $C2 to $7C-$7D and $C8 to $04-$05, seen at the next bank write
    (MAME's vrc_clones.cpp, BSD-3; *Shenhua Jian Yun* needs it).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.ram_mask, self.ram_match = 0xFE, 6 if image.board.mapper == 252 else 4
        self.rom = image.chr
        self.chr_ram = bytearray(0x800)
        self.chr_ram_window = [False] * 8
        self.banks = [0] * 8
        super().__init__(image.with_board(replace(image.board, **VRC4E)), cpu_cycle_ticks)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        self.banks[window] = bank
        for w, one in enumerate(self.banks):
            ram = one & self.ram_mask == self.ram_match
            self.chr_ram_window[w] = ram
            self.chr_offsets[w] = (one & 1) * 0x400 if ram else one * 0x400 % len(self.rom)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            window = address >> 10
            memory = self.chr_ram if self.chr_ram_window[window] else self.rom
            return memory[self.chr_offsets[window] + (address & 0x3FF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x2000:
            super().ppu_write(address, value, t)
            return
        window = address >> 10
        if self.chr_ram_window[window]:
            self.chr_ram[self.chr_offsets[window] + (address & 0x3FF)] = value
        self.ram_mask, self.ram_match = WAIXING_GAL.get(
            self.banks[window], (self.ram_mask, self.ram_match)
        )


class FS309(MMC3):
    """Mapper 199: Waixing's FS309, a TNROM-like board with more PRG and 12 KiB of RAM low.

    INES_Mapper_199.wiki: the MMC3 clone's PRG bank registers reach past 512
    KiB (all eight bits taken); 8 KiB of CHR-RAM, unbanked (the games leave
    the CHR registers non-contiguous); 32 KiB of battery-backed PRG-RAM, of
    which 12 KiB are at $5000-$7FFF. Which 12 KiB the page does not say:
    here the first 4 KiB at $5000-$5FFF and the next 8 KiB at $6000.
    Mesen2 models a different board (extra bank registers); this is the
    wiki's.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram = bytearray(max(len(self.prg_ram), 0x8000))
        self.chr = bytearray(max(len(self.chr), 0x2000)) if self.chr_writable else self.chr

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            self.chr_offsets[window + i] = (window + i) * 0x400

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x5000 <= address < 0x8000:
            return self.prg_ram[address - 0x5000]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x8000:
            self.prg_ram[address - 0x5000] = value
            return
        super().cpu_write(address, value, t)


#: T9552's scrambling (T9552.wiki): for each pattern, the address lines in table order.
T9552_PRG = {0: (16, 17, 15, 14), 1: (17, 16, 14, 15), 2: (14, 15, 16, 17), 3: (15, 14, 17, 16)}
T9552_CHR = {
    0: (15, 12, 16, 17, 14, 13),
    1: (14, 15, 13, 12, 17, 16),
    2: (12, 13, 14, 15, 16, 17),
    3: (16, 14, 12, 13, 17, 15),
    4: (15, 13, 17, 16, 12, 14),
    5: (14, 12, 15, 16, 17, 13),
    6: (13, 16, 14, 15, 12, 17),
    7: (12, 15, 16, 17, 13, 14),
}


def unscramble(bank: int, unit_bit: int, order: tuple[int, ...], stored: tuple[int, ...]) -> int:
    """Move the address lines of a bank number (bit 0 = A``unit_bit``) from the
    MMC3's ``order`` to where the file stores them (``stored``)."""
    lines = {line: (bank >> (line - unit_bit)) & 1 for line in order}
    moved = bank & ~sum(1 << (line - unit_bit) for line in order)
    for row, line in enumerate(order):
        moved |= lines[line] << (stored[row] - unit_bit)
    return moved


class T9552(MMC3):
    """Mapper 249: early Waixing boards whose T9552 scrambles the MMC3's PRG and CHR lines.

    T9552.wiki: $5000 (mask $F000) D1-D0 pick the PRG pattern and D2-D0 the
    CHR pattern; an MMC3 output line found in the current pattern's column
    goes, for mapper 249 files, to the line in the same row of column 0
    (the file is stored as pattern 0 shows it). Every known game writes $02
    at once; power-on is pattern 0. (Mapper 4.5 files, stored as pattern 2,
    run as plain MMC3.)
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.pattern = 0
        super().__init__(image, cpu_cycle_ticks)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        order = T9552_PRG[self.pattern & 3]
        super().map_prg(window, size_kib, unscramble(bank, 13, order, T9552_PRG[0]))

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        order = T9552_CHR[self.pattern & 7]
        for i in range(size_kib):
            one = bank * size_kib + i
            super().map_chr(window + i, 1, unscramble(one, 10, order, T9552_CHR[0]))

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF000 == 0x5000:
            self.pattern = value & 7
            self._update()
            return
        super().cpu_write(address, value, t)


class Xiangfeng198(MMC3):
    """Mapper 198: Xiangfeng Cartoon's Destiny of an Emperor II translation, 640 KiB of PRG.

    INES_Mapper_198.wiki: an MMC3 whose 8 KiB banks $00-$3F are on a 512 KiB
    chip and $40-$4F on a 128 KiB one, the fixed banks being $4E and $4F;
    8 KiB of CHR-RAM; 8 KiB of battery-backed WRAM at $6000 and 4 KiB more,
    not backed, at $5000-$5FFF.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.low_ram = bytearray(0x1000)
        super().__init__(image, cpu_cycle_ticks)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        last = len(self.prg) // 0x2000 - 1
        if bank >= last - 1:  # the MMC3's fixed banks: $4E/$4F on the second chip
            bank = 0x4E + (bank - (last - 1))
        super().map_prg(window, size_kib, bank % 0x50)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x5000 <= address < 0x6000:
            return self.low_ram[address & 0x0FFF]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            self.low_ram[address & 0x0FFF] = value
            return
        super().cpu_write(address, value, t)


class Jncota523(FK23C):
    """Mapper 523: Jncota's re-release of Fengshenbang: FS005 with CHR rewired for 2 KiB banks.

    NES_2.0_Mapper_523.wiki: horizontal mirroring, hard-wired; CHR A10 is PPU A10, the
    clone's CHR outputs drive CHR A11-A18, its own PPU A10 input is grounded.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image.with_board(replace(image.board, submapper=2)), cpu_cycle_ticks)

    def set_mirroring(self, mode: str) -> None:
        super().set_mirroring(HORIZONTAL)

    def _map_chr_1k(self, window: int, bank: int) -> None:
        if not window & 1:
            super()._map_chr_1k(window, bank * 2)
            super()._map_chr_1k(window + 1, bank * 2 + 1)
