"""J.Y. Company's ASIC (209, and the boards 35, 90 and 211), from J.Y._Company_ASIC.wiki.

No judge ROM exists; the claims rest on sweeps against Mesen2, a detector
(docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage

ARRANGEMENTS = (VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)  # $D001 D1-D0, by CIRAM A10's source
SOURCE_M2, SOURCE_A12, SOURCE_PPU_READS, SOURCE_CPU_WRITES = range(4)


def reverse7(bank: int) -> int:
    """PRG mode 3: bank bits 0-6 reversed."""
    return (bank & 0x80) | sum(((bank >> bit) & 1) << (6 - bit) for bit in range(7))


class JYCompany(Banked):
    """Mappers 209 (the standard board), 35 (the same, WRAM in the header), 211 (a duplicate
    of 209) and 90 (a jumper inhibits ROM nametables and the extended mirroring).

    Registers (writes):

    - $8000-$8003 (mask $F803): PRG banks; $9000-$9007/$A000-$A007 (mask
      $F807): CHR banks, low and high bytes; $B000-$B007: the four nametables'
      ROM banks (low/high) and, in D0, their CIRAM page; D7 against $D002 D7
      picks ROM or CIRAM per nametable.
    - $D000 (mask $F803) ``6GRCCLPP``: PRG mode (32/16/8 KiB, 8 KiB with the
      bank's bits 0-6 reversed), the last bank switchable by $8003 (L), CHR
      mode (8/4/2/1 KiB), ROM nametables (R; G: for all four), and $6000 from
      PRG-ROM ($8003's bank, shifted and right-filled with 1s) instead of RAM.
    - $D001 D3 extended mirroring ($B00x D0 per nametable), else D1-D0 the
      arrangement: CIRAM A10 from PPU A10, A11, 0 or 1. $D002 D6 CHR-RAM
      write enable, D7 the ROM nametable polarity. $D003 ``M.LccPPC``: PRG
      A20-A19, CHR A20-A19, the CHR outer size (L: 512 KiB, else 256 KiB with
      C as CHR A18), and M: MMC4-like CHR latches in 4 KiB mode (reads of
      $xFD8-$xFDF set a half's latch to 0, $xFE8-$xFEF to 1, after the read).
    - $C000-$C007 (mask $F007): the IRQ. $C001 ``DD..EPSS``: the clock (M2,
      PPU A12 rises unfiltered, PPU reads, CPU writes), the prescaler mask
      ($FF or $07), the direction (1 up, 2 down; 0 and 3 stop). A clock steps
      the prescaler; when its masked value wraps the counter steps, and the
      counter's wrap ($00 up, $FF down) asserts /IRQ. $C000 D0 / $C002 / $C003
      disable or enable (disabling acknowledges and clears the prescaler);
      $C004/$C005 load the prescaler/counter XOR $C006. $C007's mode is
      unknown (no game) and ignored.
    - $5000/$5400/$5C00 read the solder pads (D7-D6, 0 here); $5800-$5803
      (mask $F803) the multiplier (product ready at once: the 8 M2 cycles of
      intermediate results are not modelled) and the accumulator and test
      register.

    PRG and CHR bank numbers are masked to the 512 KiB outer bank. Power-on
    registers unspecified: 0 here.
    """

    counts_m2 = True
    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.nametables_allowed = image.board.mapper != 90
        self.prg_regs = [0] * 4
        self.chr_regs = [0] * 8  # low | high << 8
        self.nt_regs = [0] * 4
        self.mode = self.arrangement = self.ppu_config = self.outer = 0
        self.latches = [0, 0]
        self.irq_enabled = False
        self.irq_mode = self.prescaler = self.counter = self.xor = 0
        self.multiplicand = self.multiplier = 0
        self.accumulator = self.test = 0
        self.a12 = 0
        self.rom_bank_6000: int | None = None
        self._update()

    # -- banking ---------------------------------------------------------

    def _update(self) -> None:
        self._update_prg()
        self._update_chr()
        self.set_mirroring(ARRANGEMENTS[self.arrangement & 3])

    def _update_prg(self) -> None:
        mode, r, last = self.mode & 3, self.prg_regs, self.mode & 4
        outer8 = ((self.outer >> 1) & 3) << 6
        if mode == 0:
            bank32 = r[3] & 0x0F if last else 0x0F
            banks = [bank32 * 4 + i for i in range(4)]
            bank6000 = (r[3] << 2 | 3) & 0x3F
        elif mode == 1:
            low = r[1] & 0x1F
            high = r[3] & 0x1F if last else 0x1F
            banks = [low * 2, low * 2 + 1, high * 2, high * 2 + 1]
            bank6000 = (r[3] << 1 | 1) & 0x3F
        else:
            fix = reverse7 if mode == 3 else int
            banks = [fix(r[0]), fix(r[1]), fix(r[2]), fix(r[3]) if last else 0x3F]
            banks = [b & 0x3F for b in banks]
            bank6000 = fix(r[3]) & 0x3F
        for window, bank in enumerate(banks):
            self.map_prg(window, 8, outer8 | bank)
        self.rom_bank_6000 = (outer8 | bank6000) if self.mode & 0x80 else None

    def _chr_outer(self) -> tuple[int, int]:
        """The outer CHR bank's size and base, in bytes."""
        o = self.outer
        if o & 0x20:
            return 0x80000, ((o >> 3) & 3) * 0x80000
        return 0x40000, ((o >> 3) & 3) * 0x80000 + (o & 1) * 0x40000

    def _update_chr(self) -> None:
        r, mode = self.chr_regs, (self.mode >> 3) & 3
        if mode == 0:
            self._map_chr(0, 8, r[0])
        elif mode == 1:
            mmc4 = self.outer & 0x80
            self._map_chr(0, 4, r[2] if mmc4 and self.latches[0] else r[0])
            self._map_chr(4, 4, r[6] if mmc4 and self.latches[1] else r[4])
        elif mode == 2:
            for i in range(4):
                self._map_chr(i * 2, 2, r[i * 2])
        else:
            for i in range(8):
                self._map_chr(i, 1, r[i])

    def _map_chr(self, window: int, size_kib: int, bank: int) -> None:
        size, base = self._chr_outer()
        start = base + (bank * size_kib * 0x400) % size
        for i in range(size_kib):
            self.chr_offsets[window + i] = (start + i * 0x400) % len(self.chr)

    # -- the CPU side ----------------------------------------------------

    def cpu_read(self, address: int, t: int) -> int | None:
        if address in (0x5000, 0x5400, 0x5C00):
            return 0x00 | 0x3F << 8  # the solder pads (D7-D6): 0
        if address & 0xF803 == 0x5800:
            return (self.multiplicand * self.multiplier) & 0xFF
        if address & 0xF803 == 0x5801:
            return (self.multiplicand * self.multiplier) >> 8
        if address & 0xF803 == 0x5802:
            return self.accumulator
        if address & 0xF803 == 0x5803:
            return self.test
        if 0x6000 <= address < 0x8000 and self.rom_bank_6000 is not None:
            return self.prg[(self.rom_bank_6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if self.irq_mode & 3 == SOURCE_CPU_WRITES:
            self._clock_irq()
        if address < 0x8000:
            register = address & 0xF803
            if register == 0x5800:
                self.multiplicand = value
            elif register == 0x5801:
                self.multiplier = value
            elif register == 0x5802:
                self.accumulator = (self.accumulator + value) & 0xFF
            elif register == 0x5803:
                self.accumulator, self.test = 0, value
            elif self.rom_bank_6000 is None:
                super().cpu_write(address, value, t)
            return
        region = address & 0xF000
        if region == 0xC000:
            self._irq_register(address & 7, value)
            return
        if address & 0x0800:  # A11 set: the other registers ignore the write
            return
        if region == 0x8000:
            self.prg_regs[address & 3] = value
        elif region in (0x9000, 0xA000):
            i, shift = address & 7, 8 if region == 0xA000 else 0
            self.chr_regs[i] = (self.chr_regs[i] & (0xFF00 >> shift)) | value << shift
        elif region == 0xB000:
            i, shift = address & 3, 8 if address & 4 else 0
            self.nt_regs[i] = (self.nt_regs[i] & (0xFF00 >> shift)) | value << shift
        elif region == 0xD000:
            register = address & 3
            if register == 0:
                self.mode = value
            elif register == 1:
                self.arrangement = value
            elif register == 2:
                self.ppu_config = value
            else:
                self.outer = value
        self._update()

    def _irq_register(self, register: int, value: int) -> None:
        if register in (0, 2, 3):
            enable = bool(value & 1) if register == 0 else register == 3
            if not enable:
                self.irq = False
                self.prescaler = 0
            self.irq_enabled = enable
        elif register == 1:
            self.irq_mode = value
        elif register == 4:
            self.prescaler = value ^ self.xor
        elif register == 5:
            self.counter = value ^ self.xor
        elif register == 6:
            self.xor = value

    def _clock_irq(self) -> None:
        direction = self.irq_mode >> 6
        if not self.irq_enabled or direction in (0, 3):
            return
        mask = 0x07 if self.irq_mode & 4 else 0xFF
        step = 1 if direction == 1 else -1
        self.prescaler = (self.prescaler + step) & 0xFF
        if self.prescaler & mask != (0 if step == 1 else mask):
            return
        self.counter = (self.counter + step) & 0xFF
        if self.counter == (0 if step == 1 else 0xFF):
            self.irq = True

    def m2(self, t: int) -> None:
        if self.irq_mode & 3 == SOURCE_M2:
            self._clock_irq()

    # -- the PPU side ----------------------------------------------------

    def ppu_address(self, address: int, t: int) -> None:
        source = self.irq_mode & 3
        a12 = (address >> 12) & 1
        if (source == SOURCE_A12 and a12 and not self.a12) or source == SOURCE_PPU_READS:
            self._clock_irq()
        self.a12 = a12

    def _rom_nametable(self, address: int) -> int | None:
        """The ROM bank of a nametable address, or None if CIRAM answers."""
        if not (self.nametables_allowed and self.mode & 0x20):
            return None
        reg = self.nt_regs[(address >> 10) & 3]
        if self.mode & 0x40 or (reg >> 7) & 1 != (self.ppu_config >> 7) & 1:
            return reg
        return None

    def ciram_a10(self, address: int) -> int | None:
        if self._rom_nametable(address) is not None:
            return None
        extended = self.nametables_allowed and (self.arrangement & 8 or self.mode & 0x20)
        if extended:
            return self.nt_regs[(address >> 10) & 3] & 1
        return super().ciram_a10(address)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address >= 0x2000:
            bank = self._rom_nametable(address)
            if bank is None:
                return None
            return self.chr[(bank * 0x400 + (address & 0x3FF)) % len(self.chr)]
        value = super().ppu_read(address, t)
        if self.outer & 0x80:
            low = address & 0xFF8
            if low in (0xFD8, 0xFE8):
                self.latches[address >> 12] = 1 if low == 0xFE8 else 0
                self._update_chr()
        return value

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000 and not (self.chr_writable and self.ppu_config & 0x40):
            return
        super().ppu_write(address, value, t)


class JY830623C(Banked):
    """Mapper 91: J.Y. Company's JY830623C/YY840238C (91.0) and EJ-006-1 (91.1).

    INES_Mapper_091.wiki: $6000-$6003 the four 2 KiB CHR banks; $7000/$7001
    the 8 KiB PRG banks at $8000/$A000, the last 16 KiB fixed; $7006 stops
    the counter and acknowledges, $7007 starts it from 0 (mask $F003 on
    91.0, $F007 on 91.1). 91.0: the counter counts PPU A12 rises, unfiltered,
    and asserts /IRQ at the 64th (eight scanlines); writes to $8000-$9FFF set
    the outer banks from the address: A0 CHR A19, A2-A1 PRG A18-A17.
    91.1: $6004/$6005 select horizontal/vertical mirroring, $6006/$6007 the
    counter's low/high byte; it counts down by five every fourth M2 cycle,
    and its wrap below 0 asserts /IRQ and stops it (the wiki gives the rate,
    not the edge: an assumption). Power-on registers 0.
    """

    watches_ppu_address = True
    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.cycle_counter = image.board.submapper == 1
        self.mask = 0xF007 if self.cycle_counter else 0xF003
        self.chr_regs = [0] * 4
        self.prg_regs = [0, 0]
        self.outer = 0
        self.counter = 0
        self.counting = False
        self.prescaler = 0
        self.a12 = 0
        self._update()

    def _update(self) -> None:
        prg_outer = ((self.outer >> 1) & 3) << 4  # 8 KiB units of 128 KiB
        last = len(self.prg) // 0x2000 - 1
        self.map_prg(0, 8, prg_outer | self.prg_regs[0] & 0x0F)
        self.map_prg(1, 8, prg_outer | self.prg_regs[1] & 0x0F)
        self.map_prg(2, 8, (prg_outer | 0x0E) & last)
        self.map_prg(3, 8, (prg_outer | 0x0F) & last)
        chr_outer = (self.outer & 1) << 8  # 2 KiB units of 512 KiB
        for i, bank in enumerate(self.chr_regs):
            self.map_chr(i * 2, 2, chr_outer | bank)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not self.cycle_counter and 0x8000 <= address < 0xA000:
            self.outer = address & 7
            self._update()
            return
        register = address & self.mask
        if 0x6000 <= register <= 0x6003:
            self.chr_regs[register & 3] = value
        elif register in (0x7000, 0x7001):
            self.prg_regs[register & 1] = value
        elif register in (0x7002, 0x7006):
            self.counting = False
            self.irq = False
        elif register in (0x7003, 0x7007):
            self.counting = True
            if not self.cycle_counter:
                self.counter = 0
        elif self.cycle_counter and register in (0x6004, 0x6005):
            self.set_mirroring(HORIZONTAL if register == 0x6004 else VERTICAL)
        elif self.cycle_counter and register == 0x6006:
            self.counter = (self.counter & 0xFF00) | value
        elif self.cycle_counter and register == 0x6007:
            self.counter = (self.counter & 0x00FF) | value << 8
        else:
            super().cpu_write(address, value, t)
            return
        self._update()

    def ppu_address(self, address: int, t: int) -> None:
        a12 = (address >> 12) & 1
        if a12 and not self.a12 and self.counting and not self.cycle_counter:
            self.counter += 1
            if self.counter == 64:
                self.irq = True
        self.a12 = a12

    def m2(self, t: int) -> None:
        if not (self.cycle_counter and self.counting):
            return
        self.prescaler = (self.prescaler + 1) & 3
        if self.prescaler == 0:
            self.counter -= 5
            if self.counter < 0:
                self.counter &= 0xFFFF
                self.counting = False
                self.irq = True
