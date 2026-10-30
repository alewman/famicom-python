"""Cony's (Yoko's) chip-on-board ASIC on its boards: mapper 83 (submappers 0-3) and NES 2.0 264.

INES_Mapper_083.wiki. No judge ROM exists; the claims rest on sweeps against
Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage

#: 83.1 and 264 bank CHR in 2 KiB amounts: for each real 1 KiB window, the ASIC's register.
TWO_KIB_CHR = (0, 0, 1, 1, 6, 6, 7, 7)


class Cony(Banked):
    """Mappers 83.0 (256 KiB CHR), 83.1 (512 KiB, 2 KiB CHR banks), 83.2 (4-in-1 with 32 KiB of
    PRG-NVRAM), 83.3 (4-in-1) and 264 (2-in-1; the ASIC's A9-A8 are CPU A11-A10).

    Registers (83's addresses): $8000 (mask $8300) the PRG base (83.0/1, 264:
    PRG A21-A14; 83.2 ``RRQQPPPP``: A17-A14, PRG/CHR A19-A18, PRG-RAM
    A14-A13; 83.3 ``CCPPPPPP``: A19-A14 and CHR A19-A18); $8100 ``CD6PP.NN``:
    the arrangement (vertical, horizontal, one-screen 0, 1), the PRG mode (0
    UxROM: the inner bank's last at $C000; 1 NROM-128; 2/3 the four 8 KiB
    registers, $E000 the inner bank's last), $6000 from PRG-ROM (6), the
    counter's direction (D: 0 up) and C: counting enabled at the next MSB
    write; $8200/$8201 the counter's low byte (acknowledges) and high byte;
    $8300-$8303 (mask $8310) the 8 KiB banks at $8000/$A000/$C000/$6000;
    $8310-$8317 (mask $8318) the 1 KiB CHR banks; $8318 the counter's clock
    (0 M2, else unfiltered PPU A12 rises: which data bit decides is unknown,
    any here). The inner PRG bank is 256 KiB (83.0-83.2) or 128 KiB (83.3,
    264). Counting, the counter steps and on reaching 0 stops and asserts
    /IRQ. $5000 (mask $F100) reads the solder pads (D1-D0, 0 here);
    $5100-$5103 four bytes of scratch RAM. Power-on registers 0.
    """

    counts_m2 = True
    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.remapped = board.mapper == 264
        self.submapper = 0 if self.remapped else board.submapper
        self.two_kib_chr = self.remapped or self.submapper == 1
        self.inner = 0x07 if self.remapped or self.submapper == 3 else 0x0F  # 16 KiB banks
        self.nvram = self.submapper == 2
        if self.nvram:
            self.prg_ram = bytearray(max(len(self.prg_ram), 0x8000))
        self.prg_ram_enabled = False
        self.base = self.mode = 0
        self.prg_regs = [0] * 4
        self.chr_regs = [0] * 8
        self.counter = 0
        self.counting = False
        self.a12_clock = False
        self.a12 = 0
        self.scratch = [0] * 4
        self._update()

    # -- banking ---------------------------------------------------------

    def _base16(self) -> tuple[int, int]:
        """(the PRG base in 16 KiB banks, CHR A19-A18 as a 1 KiB bank offset)."""
        b, sub = self.base, self.submapper
        if sub == 2:
            return ((b >> 4) & 3) << 4 | b & 0x0F, ((b >> 4) & 3) << 8
        if sub == 3:
            return b & 0x3F, (b >> 6) << 8
        return b, 0

    def _update(self) -> None:
        base16, chr_outer = self._base16()
        inner16, prg_mode = self.inner, (self.mode >> 3) & 3
        outer16 = base16 & ~inner16
        if prg_mode == 0:
            self.map_prg(0, 16, base16)
            self.map_prg(2, 16, outer16 | inner16)
        elif prg_mode == 1:
            self.map_prg(0, 16, base16)
            self.map_prg(2, 16, base16)
        else:
            inner8, outer8 = inner16 << 1 | 1, outer16 << 1
            for window in range(3):
                self.map_prg(window, 8, outer8 | self.prg_regs[window] & inner8)
            self.map_prg(3, 8, outer8 | inner8)
        self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[self.mode & 3])
        for window in range(8):
            if self.two_kib_chr:
                bank = self.chr_regs[TWO_KIB_CHR[window]] * 2 + (window & 1)
            else:
                bank = self.chr_regs[window]
            self.map_chr(window, 1, chr_outer | bank)

    # -- the CPU side ----------------------------------------------------

    def _address(self, address: int) -> int:
        """264's address as 83's: its CPU A11-A10 are the ASIC's A9-A8."""
        if self.remapped:
            return (address & 0xF0FF) | ((address >> 10) & 3) << 8
        return address

    def cpu_read(self, address: int, t: int) -> int | None:
        a = self._address(address)
        if a & 0xF100 == 0x5000 and a < 0x6000:
            return 0x00 | 0xFC << 8
        if a & 0xF100 == 0x5100 and a < 0x6000:
            return self.scratch[a & 3]
        if 0x6000 <= address < 0x8000:
            if self.nvram:
                bank = (self.base >> 6) & 3
                return self.prg_ram[bank * 0x2000 + (address & 0x1FFF)]
            if self.mode & 0x20:
                base16, _ = self._base16()
                outer8 = (base16 & ~self.inner) << 1
                bank = outer8 | self.prg_regs[3] & (self.inner << 1 | 1)
                return self.prg[(bank * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
            return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        a = self._address(address)
        if address < 0x8000:
            if a & 0xF100 == 0x5100 and a < 0x6000:
                self.scratch[a & 3] = value
            elif self.nvram and address >= 0x6000:
                self.prg_ram[((self.base >> 6) & 3) * 0x2000 + (address & 0x1FFF)] = value
            return
        if a & 0x8300 == 0x8000:
            self.base = value
        elif a & 0x8300 == 0x8100:
            self.mode = value
        elif a & 0x8301 == 0x8200:
            self.counter = (self.counter & 0xFF00) | value
            self.irq = False
        elif a & 0x8301 == 0x8201:
            self.counter = (self.counter & 0x00FF) | value << 8
            self.counting = bool(self.mode & 0x80)
        elif a & 0x8318 == 0x8318:
            self.a12_clock = bool(value)
        elif a & 0x8318 == 0x8310:
            self.chr_regs[a & 7] = value
        elif a & 0x8310 == 0x8300:
            self.prg_regs[a & 3] = value
        else:
            return
        self._update()

    # -- the counter -----------------------------------------------------

    def _clock(self) -> None:
        if not self.counting:
            return
        step = -1 if self.mode & 0x40 else 1
        self.counter = (self.counter + step) & 0xFFFF
        if self.counter == 0:
            self.counting = False
            self.irq = True

    def m2(self, t: int) -> None:
        if not self.a12_clock:
            self._clock()

    def ppu_address(self, address: int, t: int) -> None:
        a12 = (address >> 12) & 1
        if self.a12_clock and a12 and not self.a12:
            self._clock()
        self.a12 = a12

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg_ram) if self.nvram else None
