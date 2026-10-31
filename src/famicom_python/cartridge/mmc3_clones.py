"""MMC3 clones on pirate and multicart boards: outer banks, rewired registers, 32 KiB PRG modes.

Each from its NESdev wiki page. No judge ROM exists for any of them; the
claims rest on sweeps against Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from dataclasses import replace

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL
from .flash import Flash29F040
from .ines import RomImage
from .mmc3 import MMC3


class GA23C(MMC3):
    """Mapper 45: the GA23C multicart ASIC, an MMC3 with four outer registers at $6000.

    INES_Mapper_045.wiki: successive writes to $6000 (mask $F001) fill
    registers 0-3 in turn: 0 the CHR OR (A10-A17); 1 the PRG OR (A13-A18, D7-D6
    A19-A20); 2 the CHR AND (D3-D0: $F keeps 8 MMC3 bits, $E 7, ... $7 and
    below none), CHR A18-A19 (D5-D4), CHR A20-A21 and PRG A21-A22 (D7-D6); 3
    the PRG AND, inverted (D5-D0), and D6 locks the registers. A write to
    $6001 unlocks them and restarts the sequence. The registers take writes
    whatever the MMC3's RAM enable says; locked, $6000 is the WRAM's. The CHR
    masking applies to CHR-ROM only: a CHR-RAM board's RAM takes the MMC3's
    lines (an assumption the wiki does not settle; Mesen2 makes it too). The
    CHR registers power on as 0, 2, 4, 5, 6, 7 (Mesen2's choice, which a game
    writing CHR-RAM before setting them needs; the MMC3's are unspecified)
    and the outer registers as Mesen2's soft reset leaves them, with
    register 2 = $0F.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = [0, 0, 0x0F, 0]
        self.next_register = 0
        self.chr_rom = bool(image.chr)
        super().__init__(image, cpu_cycle_ticks)
        self.registers[:6] = [0, 2, 4, 5, 6, 7]
        self._update()

    def m2_gap(self, t: int) -> None:
        """A reset clears the outer registers as $6001 does (the wiki)."""
        self.outer = [0, 0, 0x0F, 0]
        self.next_register = 0
        self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            if address & 0xF001 == 0x6001:
                self.outer[3] &= ~0x40
                self.next_register = 0
            elif address & 0xF001 == 0x6000 and not self.outer[3] & 0x40:
                self.outer[self.next_register] = value
                self.next_register = (self.next_register + 1) & 3
                self._update()
                return
            elif self.outer[3] & 0x40:
                super().cpu_write(address, value, t)
            return
        super().cpu_write(address, value, t)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        o1, o2, o3 = self.outer[1], self.outer[2], self.outer[3]
        mask = ~o3 & 0x3F
        prg_or = o1 | (o2 >> 6) << 8
        super().map_prg(window, size_kib, (bank & mask) | prg_or)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        o0, o2 = self.outer[0], self.outer[2]
        bits = o2 & 0x0F
        mask = 0xFF >> (15 - bits) if bits >= 7 else 0
        chr_or = o0 | (o2 & 0xF0) << 4
        for i in range(size_kib):
            one = bank * size_kib + i
            if self.chr_rom:
                one = (one & mask) | chr_or
            super().map_chr(window + i, 1, one)


class PRG32Override(MMC3):
    """Mapper 189: TXC's and Yoko Soft's MMC3 games with a 32 KiB PRG register.

    INES_Mapper_189.wiki, "Generalized definition for emulation": a write to
    $4020-$7FFF ORs the data's two nibbles into the 32 KiB PRG bank (which
    covers the original board's D5-D4 at $4100-$5FFF, the oversize board's
    D6-D4, and the pirates' A1-A0 written alongside D1-D0); the MMC3 keeps
    CHR, mirroring and the IRQ. No PRG-RAM. Power-on bank 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.bank32: int | None = 0
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        if self.bank32 is None:
            super().map_prg(window, size_kib, bank)
        else:
            super().map_prg(window, 8, self.bank32 * 4 + window)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x4020 <= address < 0x8000:
            self.bank32 = (value & 0x0F) | value >> 4
            self._update()
            return
        super().cpu_write(address, value, t)


class MRCM196(PRG32Override):
    """Mapper 196: MRCM's Mario hacks: the MMC3 clone's A0 wired to another address line.

    INES_Mapper_196.wiki by submapper: 1, the MMC3's A0 is CPU A1; 2, CPU A2;
    3, CPU A1 with mapper 189's PRG banking; 0 (unknown), the wiki's
    heuristic: A0 is 1 when A1, A2 or A3 is set and A0 is clear, and 189's
    PRG banking starts at the first write to $6000-$7FFF.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.submapper = image.board.submapper
        super().__init__(image, cpu_cycle_ticks)
        if self.submapper != 3:
            self.bank32 = None
            self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            if self.submapper in (0, 3) and address >= 0x6000:
                super().cpu_write(address, value, t)
            return
        sub = self.submapper
        if sub in (1, 3):
            a0 = (address >> 1) & 1
        elif sub == 2:
            a0 = (address >> 2) & 1
        else:
            a0 = int(bool(address & 0x0E) and not address & 1)
        super().cpu_write((address & ~1) | a0, value, t)


def nrom_bank(mode_bank: int, thirty_two: bool, window: int) -> int:
    """The 8 KiB bank an NROM override gives CPU window ``window``: 16 KiB bank
    ``mode_bank`` in both halves, or (32 KiB) its pair, CPU A14 choosing."""
    bank16 = (mode_bank & ~1) | (window >> 1) if thirty_two else mode_bank
    return bank16 * 2 + (window & 1)


#: Address scrambling: (address written & $E001) -> the MMC3 register meant.
SCRAMBLE_114 = {
    0: {0x8000: 0xA001, 0x8001: 0xA000, 0xA000: 0x8000, 0xA001: 0xC000, 0xC000: 0x8001},
    1: {0x8000: 0xA001, 0xA000: 0x8000, 0xA001: 0xC001, 0xC000: 0xA000, 0xC001: 0xC000},
}
SCRAMBLE_215 = {
    1: {0x8000: 0xA001, 0x8001: 0xA000, 0xA000: 0x8000, 0xA001: 0xC000, 0xC000: 0x8001},
    3: {
        0x8000: 0xC001,
        0x8001: 0x8000,
        0xA000: 0x8001,
        0xA001: 0xA000,
        0xC000: 0xA001,
        0xC001: 0xE001,
        0xE001: 0xC000,
    },
    4: {0x8000: 0xA001, 0xA000: 0x8000, 0xA001: 0xC000, 0xC000: 0xA000},
}
#: Index scrambling: the low three bits written to $8000 -> the register meant.
INDEX_114 = {0: (0, 3, 1, 5, 6, 7, 2, 4), 1: (0, 2, 5, 3, 6, 1, 7, 4)}
INDEX_215 = {
    1: (0, 2, 6, 1, 7, 3, 4, 5),
    2: (0, 5, 4, 1, 7, 2, 6, 3),
    3: (0, 6, 3, 7, 5, 2, 4, 1),
    4: (0, 2, 5, 3, 6, 1, 7, 4),
}
IDENTITY = (0, 1, 2, 3, 4, 5, 6, 7)


class SuperGame(MMC3):
    """Kǎshèng's and SuperGame's MMC3 clones with an NROM override register and scrambling.

    - 114 (and its duplicate 182): $6000 (mask $E001) ``M.S.BBBb``: M
      replaces the MMC3's PRG with 16 KiB bank BBBb (S: 32 KiB, b from CPU
      A14); $6001 D0 CHR A18; the MMC3's register addresses and $8000 indices
      scrambled by submapper (INES_Mapper_114.wiki's tables); the IRQ is the
      MMC3A's (NEC: a latch of 0 disables it).
    - 123 (H2288): $5800 (mask $F800) ``.M31.2S0``, the same override with
      its bank bits in that order; indices scrambled as 114.0's.
    - 187 (A98402): $5000 (mask $F001) ``M.NBBBb.``; reads of $5000-$5FFF
      give D7 set (all King of Fighters '96 checks); with 512 KiB of CHR,
      PPU A12 is CHR A18.
    - 215 (8237): $5000 ``MCS.BBBb`` (C: a 128 KiB outer bank, PRG/CHR A17
      from $5001 D4/D5), $5001 the outer banks (215.0 ``..cpCCPP``, 215.1
      ``..cpPCCP``-style: PRG A18-A20 from D0, D1, D3 and CHR A18-A20 from
      D1-D3), $5007 the scrambling pattern (INES_Mapper_215.wiki's tables);
      $5001 powers on as $0F.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        board = image.board
        self.kind = 114 if board.mapper == 182 else board.mapper
        self.submapper = board.submapper
        self.mode = 0
        self.chr_outer = 0
        self.outer = 0x0F if self.kind == 215 else 0
        self.pattern = 0
        self.big_chr = self.kind == 187 and len(image.chr) > 0x40000
        super().__init__(image, cpu_cycle_ticks)
        self.nec_irq = self.kind == 114
        self.prg_ram_enabled = False

    def m2_gap(self, t: int) -> None:
        if self.kind == 215:  # the outer register returns to $0F (INES_Mapper_215.wiki)
            self.outer = 0x0F
            self._update()

    def _override(self) -> tuple[bool, int, bool]:
        """(active, 16 KiB bank, 32 KiB) from the override register."""
        v = self.mode
        if self.kind == 123:
            one = (v >> 4 | v >> 3) & 1  # D3 too: Earthworm Jim 2 boots with $5800 = $CD
            bank = (v & 1) | one << 1 | ((v >> 2) & 1) << 2 | ((v >> 5) & 1) << 3
            return bool(v & 0x40), bank, bool(v & 2)
        if self.kind == 187:
            return bool(v & 0x80), (v >> 1) & 0x0F, bool(v & 0x20)
        return bool(v & 0x80), v & 0x0F, bool(v & 0x20)

    def _outer_215(self) -> tuple[int, int, int]:
        """215: (PRG outer in 128 KiB units, CHR outer in 128 KiB units, A17-replacing)."""
        o, replace = self.outer, self.mode & 0x40
        if self.submapper == 1:
            prg, chr_ = (o & 3) | (o >> 1) & 4, (o >> 1) & 7
        else:
            prg, chr_ = o & 3, (o >> 2) & 3
        prg, chr_ = prg << 1, chr_ << 1
        if replace:
            prg |= (o >> 4) & 1
            chr_ |= (o >> 5) & 1
        return prg, chr_, replace

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        active, bank16, thirty_two = self._override()
        if self.kind == 215:
            prg, _, replace = self._outer_215()
            inner = 0x0F if replace else 0x1F
            if active:
                bank = nrom_bank(bank16 & (inner >> 1), thirty_two, window)
            super().map_prg(window, size_kib, (bank & inner) | prg << 4)
            return
        if active:
            bank = nrom_bank(bank16, thirty_two, window)
        super().map_prg(window, size_kib, bank)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            one, w = bank * size_kib + i, window + i
            if self.kind == 215:
                _, chr_, replace = self._outer_215()
                one = (one & (0x7F if replace else 0xFF)) | chr_ << 7
            elif self.kind == 114:
                one = (one & 0xFF) | self.chr_outer << 8
            elif self.big_chr:
                one = (one & 0xFF) | (w >> 2) << 8
            super().map_chr(w, 1, one)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.kind == 187 and 0x5000 <= address < 0x6000:
            return 0x80 | 0x7F << 8  # D7 set; the rest unknown, left open
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        kind = self.kind
        if address < 0x8000:
            if (kind == 114 and address & 0xE001 == 0x6000) or (
                kind == 187 and address & 0xF001 == 0x5000
            ):
                self.mode = value
            elif kind == 114 and address & 0xE001 == 0x6001:
                self.chr_outer = value & 1
            elif (kind == 123 and address & 0xF800 == 0x5800) or (
                kind == 215 and address & 0xF007 == 0x5000
            ):
                self.mode = value
            elif kind == 215 and address & 0xF007 == 0x5001:
                self.outer = value
            elif kind == 215 and address & 0xF007 == 0x5007:
                self.pattern = value & 7
            else:
                super().cpu_write(address, value, t)
                return
            self._update()
            return
        if kind == 114:
            table, index = (
                SCRAMBLE_114.get(self.submapper, {}),
                INDEX_114.get(self.submapper, IDENTITY),
            )
        elif kind == 215:
            table, index = SCRAMBLE_215.get(self.pattern, {}), INDEX_215.get(self.pattern, IDENTITY)
        elif kind == 123:
            table, index = {}, INDEX_114[0]
        else:
            table, index = {}, IDENTITY
        register = table.get(address & 0xE001, address & 0xE001)
        if register == 0x8000:
            value = (value & 0xC0) | index[value & 7]
        super().cpu_write(register, value, t)


#: Mapper 121's protection array, indexed by the last write to $5000-$5FFF.
A9711_ARRAY = (0x83, 0x83, 0x42, 0x00)


def reverse6(value: int) -> int:
    return (value & 0xC0) | sum(((value >> bit) & 1) << (5 - bit) for bit in range(6))


class A9711(MMC3):
    """Mapper 121: Kǎshèng's A9711/A9713 protected boards.

    INES_Mapper_121.wiki: a write to $5000-$5FFF picks an entry of the
    protection array ($83, $83, $42, $00) that reads of $5000-$5FFF return
    (FCEUX's second array on A8 the wiki only reports, so left out). A write
    to $8003 (mask $E003) is also the MMC3's $8000 and selects a protection
    index; the last $8001 value, its low six bits reversed, then replaces
    PRG banks: index $26/$28/$2A $E000/$C000/$A000, applied again on later
    $8001 writes; $2C $E000 if not 0; $20, $29, $2B, $3C, $3F $E000 once;
    $2F keeps what is there; any other index restores the MMC3's banking.
    With 512 KiB of CHR, PPU A12 is CHR A18; A9713 (512 KiB PRG): $5180 (mask
    $F180) D7 the outer 256 KiB PRG and CHR bank.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.overrides: dict[int, int] = {}
        self.protection_index = 0
        self.protection_value = 0
        self.array_index = 0
        self.outer = 0
        self.big_chr = len(image.chr) > 0x40000
        self.big_prg = len(image.prg) > 0x40000
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        bank = self.overrides.get(window, bank)
        if self.big_prg:
            bank = (bank & 0x1F) | self.outer << 5
        super().map_prg(window, size_kib, bank)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            one, w = bank * size_kib + i, window + i
            if self.big_chr:
                one = (one & 0xFF) | (w >> 2) << 8
            elif self.big_prg:
                one = (one & 0xFF) | self.outer << 8
            super().map_chr(w, 1, one)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x5000 <= address < 0x6000:
            return A9711_ARRAY[self.array_index]
        return super().cpu_read(address, t)

    def _apply(self, index: int, persistent: bool) -> None:
        value = self.protection_value
        windows = {0x26: 3, 0x28: 2, 0x2A: 1}
        if index in windows:
            self.overrides[windows[index]] = value
        elif index == 0x2C:
            if value:
                self.overrides[3] = value
        elif index in (0x20, 0x29, 0x2B, 0x3C, 0x3F):
            if not persistent:
                self.overrides[3] = value
        elif index != 0x2F and not persistent:
            self.overrides.clear()
        self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            if self.big_prg and address & 0xF180 == 0x5180:
                self.outer = value >> 7
                self._update()
            self.array_index = value & 3
            return
        register = address & 0xE003
        if register == 0x8001:
            self.protection_value = reverse6(value)
            super().cpu_write(0x8001, value, t)
            if self.protection_index in (0x26, 0x28, 0x2A):
                self._apply(self.protection_index, True)
            return
        if register == 0x8003:
            self.protection_index = value & 0x3F
            super().cpu_write(0x8000, value, t)
            self._apply(self.protection_index, False)
            return
        super().cpu_write(address, value, t)


#: Mapper 197: for each real 1 KiB PPU window, the MMC3 window it sees, by submapper.
REWIRED_197 = {
    0: (0, 0, 1, 1, 4, 4, 5, 5),
    1: (2, 2, 3, 3, 6, 6, 7, 7),
    2: (0, 0, 3, 3, 4, 4, 7, 7),
    3: (0, 0, 1, 1, 4, 4, 5, 5),
}


class Rewired197(MMC3):
    """Mapper 197: Kǎshèng's mapper hacks, an MMC3 rewired for 512 KiB of CHR in 2/4 KiB banks.

    INES_Mapper_197.wiki: PPU A10 goes straight to CHR-ROM A10 and the MMC3's
    CHR A10-A17 to CHR-ROM A11-A18; which MMC3 window each real window looks
    up depends on the submapper's wiring of PA10/PA11 (the page's tables).
    197.3 adds a register through the MMC3's WRAM interface ($6000-$7FFF,
    mask $E000, only while $A001 enables and allows writing): D3 set makes
    D0 PRG A17.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.wiring = REWIRED_197.get(image.board.submapper, REWIRED_197[0])
        self.outer = 0
        self.ram_control = 0x80
        self.mmc3_banks = [0] * 8
        super().__init__(image, cpu_cycle_ticks)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            self.mmc3_banks[window + i] = bank * size_kib + i
        for real in range(8):
            super().map_chr(real, 1, self.mmc3_banks[self.wiring[real]] * 2 + (real & 1))

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        if self.outer & 8:
            bank = (bank & 0x0F) | (self.outer & 1) << 4
        super().map_prg(window, size_kib, bank)

    def ram_protect(self, value: int) -> None:
        self.ram_control = value
        super().ram_protect(value)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000 and self.wiring == REWIRED_197[3]:
            if self.ram_control & 0xC0 == 0x80:
                self.outer = value
                self._update()
            return
        super().cpu_write(address, value, t)


class F003(MMC3):
    """Mapper 245: Waixing's F003, TNROM-like with the MMC3's CHR A11 as PRG A19.

    INES_Mapper_245.wiki: CHR-RAM sees PPU A10-A12 directly (the CHR bank
    registers do nothing to it); the MMC3's PPU A12 input is grounded, so
    the active CHR register is R0 ($8000 D7 clear) or R2 (set), and its D1
    selects the 512 KiB PRG half for all of $8000-$FFFF.
    """

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        r = self.registers
        half = (r[2] if self.bank_select & 0x80 else r[0]) >> 1 & 1
        super().map_prg(window, size_kib, (bank & 0x3F) | half << 6)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            self.chr_offsets[window + i] = (window + i) * 0x400 % len(self.chr)


class Latched165(MMC3):
    """Mapper 165: an MMC3 with MMC2-style CHR latches and 4 KiB of CHR-RAM as page 0.

    INES_Mapper_165.wiki (Disch's notes): the MMC3's PRG, mirroring and IRQ;
    CHR in two 4 KiB halves, $0000 from R0 or R1 and $1000 from R2 or R4 by
    the halves' latches; 4 KiB page 0 (register value 0-3) is the RAM. The
    latches flip on PPU addresses $xFD0-$xFD7 (0) and $xFE8-$xFEF (1), taking
    effect after the access: Disch's notes say the game reads $xFD0/$xFE0,
    which MMC2's ranges would miss; these are Mesen2's ranges.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.latches = [0, 0]
        self.ram_half = [False, False]
        self.rom = image.chr
        self.chr_ram = bytearray(0x1000)
        super().__init__(image, cpu_cycle_ticks)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        r = self.registers
        for half in range(2):
            page = (
                r[(1 if self.latches[0] else 0) if half == 0 else (4 if self.latches[1] else 2)]
                >> 2
            )
            self.ram_half[half] = page == 0
            for i in range(4):
                if page == 0:
                    self.chr_offsets[half * 4 + i] = i * 0x400
                else:
                    self.chr_offsets[half * 4 + i] = (page * 0x1000 + i * 0x400) % len(self.rom)

    def ppu_address(self, address: int, t: int) -> None:
        super().ppu_address(address, t)
        low = address & 0x2FF8
        if low in (0x0FD0, 0x0FE8):
            self.latches[(address >> 12) & 1] = 1 if low == 0x0FE8 else 0
            self.map_chr(0, 8, 0)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            window = address >> 10
            memory = self.chr_ram if self.ram_half[window >> 2] else self.rom
            return memory[self.chr_offsets[window] + (address & 0x3FF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            window = address >> 10
            if self.ram_half[window >> 2]:
                self.chr_ram[self.chr_offsets[window] + (address & 0x3FF)] = value
            return
        super().ppu_write(address, value, t)


class T4A54A(MMC3):
    """Mapper 134: the T4A54A / WX-KB4K / BS-5652 MMC3 multicart.

    INES_Mapper_134.wiki (mask $E003): $6000 ``LDcpC...``: CHR from the CNROM
    register (C), PRG A19 (p), CHR A19 (c), reads of $8000-$FFFF give the
    solder pads (D; 0 here), L locks the $6xxx registers until reset (but
    $6002 D1-D0); $6001 ``NcCCnpPP``: PRG A18-A17 (PP, A17 only with p), a
    128 KiB outer PRG bank (p), NROM-128 (n) in NROM mode, CHR A18-A17 (CC,
    A17 only with c), a 128 KiB outer CHR bank (c), NROM mode (N: MMC3
    register 6 for all of $8000-$FFFF, CPU A13 and, unless n, A14 passed);
    $6002 the 8 KiB CNROM bank. Power-on and reset clear them.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = [0, 0, 0]
        super().__init__(image, cpu_cycle_ticks)

    def m2_gap(self, t: int) -> None:
        self.outer = [0, 0, 0]
        self._update()

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        mode, outer = self.outer[0], self.outer[1]
        if outer & 0x80:  # NROM: register 6 for everything
            bank = self.registers[6] & ~3 | (window & 1)
            if not outer & 8:
                bank |= window & 2
            else:
                bank |= self.registers[6] & 2
        small = outer & 4
        inner = 0x0F if small else 0x1F
        high = ((outer & 3) if small else (outer & 2)) | (mode >> 2 & 1) << 2
        super().map_prg(window, size_kib, (bank & inner) | high << 4)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        mode, outer = self.outer[0], self.outer[1]
        small = outer & 0x40
        inner = 0x7F if small else 0xFF
        high = ((outer >> 4) & 3 if small else (outer >> 4) & 2) | (mode >> 5 & 1) << 2
        for i in range(size_kib):
            cnrom = mode & 8
            one = self.outer[2] * 8 + window + i if cnrom else bank * size_kib + i
            super().map_chr(window + i, 1, (one & inner) | high << 7)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.outer[0] & 0x40:
            return 0
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            register = address & 3
            if register < 3:
                if self.outer[0] & 0x80:
                    if register == 2:
                        self.outer[2] = (self.outer[2] & ~3) | value & 3
                else:
                    self.outer[register] = value
                self._update()
            return
        super().cpu_write(address, value, t)


#: Mapper 313: (first game's 128 KiB PRG blocks, other games', CHR 128 KiB blocks) by submapper.
RESET_TXROM = {0: (1, 1, 1), 1: (2, 2, 1), 2: (1, 1, 2), 3: (2, 2, 2), 4: (2, 1, 1)}


class ResetTxROM(MMC3):
    """NES 2.0 mapper 313 (BMC-RESET-TXROM): MMC3 multicarts whose game advances on each reset.

    NES_2.0_Mapper_313.wiki: an interruption of M2 (:meth:`m2_gap`)
    increments the outer bank; the submapper gives the games' sizes (0: 128
    KiB PRG and CHR, 1: 256 KiB PRG, 2: 256 KiB CHR, 3: both, 4: the first
    game 256 KiB PRG, the others 128 KiB). Power-on: the first game.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.sizes = RESET_TXROM.get(image.board.submapper, RESET_TXROM[0])
        self.game = 0
        super().__init__(image, cpu_cycle_ticks)

    def _prg_base(self) -> tuple[int, int]:
        """(first 8 KiB bank of the current game, its banks - 1)."""
        first, others, _ = self.sizes
        if self.game == 0:
            return 0, first * 16 - 1
        return (first + (self.game - 1) * others) * 16, others * 16 - 1

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        base, mask = self._prg_base()
        if bank >= len(self.prg) // 0x2000 - 2:  # the MMC3's fixed banks: the game's last two
            bank = mask - (len(self.prg) // 0x2000 - 1 - bank)
        super().map_prg(window, size_kib, base + (bank & mask))

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        blocks = self.sizes[2]
        base, mask = self.game * blocks * 128, blocks * 128 - 1
        for i in range(size_kib):
            super().map_chr(window + i, 1, base + ((bank * size_kib + i) & mask))

    def m2_gap(self, t: int) -> None:
        self.game = (self.game + 1) & 3
        self._update()


class Rex263(MMC3):
    """NES 2.0 mapper 263 (UNL-KOF97: Boogerman II, The King of Fighters '97).

    NES_2.0_Mapper_263.wiki: the MMC3 clone's A0 is CPU A12 (mask $F000), and
    the data lines are shuffled: the written bits 76543210 are the actual
    bits 76243051.
    """

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = (address & 0xE000) | (address >> 12) & 1
        value = (
            (value & 0xD8)
            | (value & 0x20) >> 4
            | (value & 4) << 3
            | (value & 2) >> 1
            | (value & 1) << 2
        )
        super().cpu_write(register, value, t)


#: Mapper 208's protection XOR table (INES_Mapper_208.wiki, from FCEUX).
PROTECTION_208 = bytes.fromhex(
    "59595959595959595949190959491909"
    "59595959595959595141110151411101"
    "59595959595959595949190959491909"
    "59595959595959595141110151411101"
    "00104050001040500000000000000000"
    "08184858081848580000000000000000"
    "00104050001040500000000000000000"
    "08184858081848580000000000000000"
    "59595959595959595848180858481808"
    "59595959595959595040100050401000"
    "59595959595959595848180858481808"
    "59595959595959595040100050401000"
    "01114151011141510000000000000000"
    "09194959091949590000000000000000"
    "01114151011141510000000000000000"
    "09194959091949590000000000000000"
)


class Gouder208(MMC3):
    """Mapper 208 (Street Fighter IV, Gouder): MMC3 CHR and IRQ, a 32 KiB PRG register, protection.

    INES_Mapper_208.wiki (FCEUX's implementation): $4800-$4FFF and
    $6800-$6FFF ``..MP...P``: the 32 KiB PRG bank (D4, D0) and the mirroring
    (0 vertical), $11 at power-on; $5000-$57FF the protection table index;
    writes to $5800-$5FFF store data XOR table[index] in one of four
    registers (A1-A0), which reads there return. 208.1 (the version without
    Gouder's notice): no extra registers; the 32 KiB bank is MMC3 register
    6 shifted right by 2.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.plain = image.board.submapper == 1
        self.prg_mode = 0x11
        self.index = 0
        self.protection = [0] * 4
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        if not self.plain:
            self.set_mirroring(HORIZONTAL if self.prg_mode & 0x20 else VERTICAL)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        if self.plain:
            bank32 = self.registers[6] >> 2
        else:
            bank32 = (self.prg_mode >> 3) & 2 | self.prg_mode & 1
        super().map_prg(window, 8, bank32 * 4 + window)

    def cpu_read(self, address: int, t: int) -> int | None:
        if not self.plain and 0x5800 <= address < 0x6000:
            return self.protection[address & 3]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not self.plain and address < 0x8000:
            if 0x4800 <= address < 0x5000 or 0x6800 <= address < 0x7000:
                self.prg_mode = value
                self.set_mirroring(HORIZONTAL if value & 0x20 else VERTICAL)
                self._update()
            elif 0x5000 <= address < 0x5800:
                self.index = value
            elif 0x5800 <= address < 0x6000:
                self.protection[address & 3] = value ^ PROTECTION_208[self.index]
            return
        if not self.plain and address & 0xE000 == 0xA000 and not address & 1:
            return  # the mirroring is the PRG register's
        super().cpu_write(address, value, t)


class Nitra250(MMC3):
    """Mapper 250 (Nitra: Time Diver Avenger, Queen Bee V): an MMC3 wired to the address bus.

    INES_Mapper_250.wiki: the MMC3's A0 is CPU A10 and its data the address's
    low byte (the written value is discarded). Not modelled: Queen Bee V's
    extra 74153 controlling PRG A13, which the page tabulates too sparsely.
    """

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = (address & 0xE000) | (address >> 10) & 1
        super().cpu_write(register, address & 0xFF, t)


#: Mapper 205's blocks: (PRG AND, PRG OR, CHR AND, CHR OR) (INES_Mapper_205.wiki).
JC016_BLOCKS = (
    (0x1F, 0x00, 0xFF, 0x000),
    (0x1F, 0x10, 0xFF, 0x080),
    (0x0F, 0x20, 0x7F, 0x100),
    (0x0F, 0x30, 0x7F, 0x180),
)


class JC016(MMC3):
    """Mapper 205 (BMC-JC-016-2: 3-in-1, 15-in-1): an MMC3 inside four blocks.

    INES_Mapper_205.wiki: $6000-$7FFF D1-D0 select the block, whose AND/OR
    pairs (the page's table) confine the MMC3's PRG and CHR banks; no
    PRG-RAM. The solder pad forcing block 1 to 3 is open here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.block = 0
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        prg_and, prg_or, _, _ = JC016_BLOCKS[self.block]
        super().map_prg(window, size_kib, (bank & prg_and) | prg_or)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        _, _, chr_and, chr_or = JC016_BLOCKS[self.block]
        for i in range(size_kib):
            super().map_chr(window + i, 1, ((bank * size_kib + i) & chr_and) | chr_or)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.block = value & 3
            self._update()
            return
        super().cpu_write(address, value, t)


class SL5020B(MMC3):
    """Mapper 12 (Gouder's SL-5020B: Dragon Ball Z 5): the Huang-1 as an MMC3A with CHR A18.

    INES_Mapper_012.wiki: the MMC3A's IRQ (NEC); a GAL at $4132 (mask $E100)
    gives CHR A18 for PPU A12 low (D0) and high (D4), taking effect at once
    (FCEUX's latching until the next CHR register write is what a homebrew
    hack relies on, not the board); reads there return the language bit
    (D0: 0, the Chinese text all known copies show). 12.1 (Magic Card 4M
    extracts) is not modelled.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.chr_high = 0
        super().__init__(image, cpu_cycle_ticks)
        self.nec_irq = True

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            w = window + i
            a18 = (self.chr_high >> (4 if w >= 4 else 0)) & 1
            super().map_chr(w, 1, ((bank * size_kib + i) & 0xFF) | a18 << 8)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xE100 == 0x4100 and address < 0x6000:
            return 0x00 | 0xFE << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE100 == 0x4100 and address < 0x6000:
            self.chr_high = value
            self._update()
            return
        super().cpu_write(address, value, t)


class BMW8544(MMC3):
    """NES 2.0 mapper 292 (Flying Star's Dragon Fighter): MMC3 PRG/IRQ, custom CHR banking.

    NES_2.0_Mapper_292.wiki: every CPU write's data is latched; with the
    MMC3's RAM enabled, a write to $6000-$7FFF sets the index (D5 picks
    extra register 0 or 1) and a *read* there copies the latch into the
    selected extra register. CHR: $0000-$07FF the 2 KiB bank extra0 XOR
    (the MMC3's register 0 >> 1); $0800-$0FFF (the MMC3's register 1 >> 1)
    with CHR A18 from extra1 D6; $1000-$1FFF the 4 KiB bank extra1 D5-D0.
    (With CHR A12 inversion the MMC3's registers 2/3 and 4/5 apply instead.)
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.extra = [0, 0]
        self.latch = 0
        self.index = 0
        self.ram_control = 0x80
        super().__init__(image, cpu_cycle_ticks)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        r = self.registers
        inverted = self.bank_select & 0x80
        first, second = (r[2] >> 1, r[4] >> 1) if inverted else (r[0] >> 1, r[1] >> 1)
        low = self.extra[0] ^ first
        high = ((self.extra[1] << 1) & 0x80) ^ second
        for i in range(2):
            super().map_chr(i, 1, low * 2 + i)
            super().map_chr(2 + i, 1, high * 2 + i)
        for i in range(4):
            super().map_chr(4 + i, 1, (self.extra[1] & 0x3F) * 4 + i)

    def ram_protect(self, value: int) -> None:
        self.ram_control = value
        super().ram_protect(value)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000 and self.ram_control & 0x80:
            self.extra[(self.index >> 5) & 1] = self.latch
            self._update()
            return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        self.latch = value
        if 0x6000 <= address < 0x8000:
            if self.ram_control & 0x80:
                self.index = value
            return
        super().cpu_write(address, value, t)


class Board513(MMC3):
    """NES 2.0 mapper 513 (Mei Shaonu Meng Gongchang): MMC3, 32 KiB of CHR-RAM, an outer bank.

    NES_2.0_Mapper_513.wiki: the CHR bank registers' D4-D0 pick 1 KiB of
    CHR-RAM and D7-D6 the 512 KiB outer PRG bank of the switchable PRG banks
    (the fixed ones stay in bank 0); taken from the register for PPU $0000
    (R0, or R2 with A12 inversion), as the registers are meant to agree.
    Outer bank 3 of the 1536 KiB dump mirrors 2 (as FCEUX; on hardware it
    would enable two chips at once). The page's CHR-RAM has a battery: that is
    what is saved.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr = bytearray(0x8000)
        self.chr_writable = True
        self._update()

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        last = len(self.prg) // 0x2000 - 1
        if bank < last - 1:  # switchable: the outer bank applies
            r = self.registers
            outer = min((r[2] if self.bank_select & 0x80 else r[0]) >> 6, 2)
            bank = outer << 6 | bank & 0x3F
        else:
            bank = 0x3E | bank & 1
        super().map_prg(window, size_kib, bank)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            super().map_chr(window + i, 1, (bank * size_kib + i) & 0x1F)

    def battery_ram(self) -> bytes | None:
        return bytes(self.chr) if self.battery else None

    def _restore(self, data: bytes) -> None:
        self.chr[:] = data


class XorRAM254(MMC3):
    """Mapper 254 (Pikachu Y2K): MMC3 whose PRG-RAM reads are XORed until $8000 is written.

    INES_Mapper_254.wiki (from MesenCE's source; the wiki asks what the
    hardware is): PRG-RAM reads return the value XOR the last $A001 write
    until the first write to $8000. A reset clears that state again
    (:meth:`m2_gap`), which the game needs (the wiki).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.xor_mask = 0
        self.scrambling = True
        super().__init__(image, cpu_cycle_ticks)

    def m2_gap(self, t: int) -> None:
        self.scrambling = True

    def cpu_read(self, address: int, t: int) -> int | None:
        value = super().cpu_read(address, t)
        if 0x6000 <= address < 0x8000 and value is not None and self.scrambling:
            return value ^ self.xor_mask
        return value

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            if address & 0xE001 == 0x8000:
                self.scrambling = False
            elif address & 0xE001 == 0xA001:
                self.xor_mask = value
        super().cpu_write(address, value, t)


class SachenShero(MMC3):
    """NES 2.0 mapper 262 (UNL-SHERO: Sachen's Street Heroes): MMC3, CHR-ROM or -RAM, four screens.

    NES_2.0_Mapper_262.wiki: $4100 (mask taken as $C100) write: CHR A18 for
    PPU $1000-$17FF (D0), $1800-$1FFF (D1), $0800-$0FFF (D2), $0000-$07FF
    (D3), and D6 swaps the whole pattern space to 8 KiB of CHR-RAM; read: D7
    the title jumper (0: Street Heroes). 4 KiB of VRAM give four screens.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.high = 0
        super().__init__(image, cpu_cycle_ticks)
        self.rom = self.chr
        self.chr_ram = bytearray(0x2000)
        self.four_screen = True
        self.vram = bytearray(0x1000)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            w = window + i
            a18 = (self.high >> (3, 3, 2, 2, 0, 0, 1, 1)[w]) & 1
            super().map_chr(w, 1, ((bank * size_kib + i) & 0xFF) | a18 << 8)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xC100 == 0x4100 and address < 0x6000:
            return 0x00 | 0x7F << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xC100 == 0x4100 and address < 0x6000:
            self.high = value
            self._update()
            return
        super().cpu_write(address, value, t)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000 and self.high & 0x40:
            return self.chr_ram[address]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            if self.high & 0x40:
                self.chr_ram[address] = value
            return
        super().ppu_write(address, value, t)


class Outer52(MMC3):
    """Mapper 52 ("Mario Party" 7-in-1 and kin): MMC3 with an outer register at $6000.

    INES_Mapper_052.wiki: with the MMC3's RAM enabled and writable, $6000-$7FFF
    ``LTCcSBPp``: PRG A18-A17 (Pp; S: A17 from p, a 128 KiB bank, else from
    the MMC3), PRG/CHR A19 (B), CHR A18-A17 (Cc; T: A17 from c), L locks the
    register until reset. Submappers 13/14 (mixed CHR-RAM) are not modelled.
    Power-on and reset clear it.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = 0
        self.ram_control = 0x80
        super().__init__(image, cpu_cycle_ticks)

    def m2_gap(self, t: int) -> None:
        self.outer = 0
        self._update()

    def ram_protect(self, value: int) -> None:
        self.ram_control = value
        super().ram_protect(value)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        o = self.outer
        high = (o & 3) | (o >> 2 & 1) << 2  # PRG A19-A17 in 128 KiB units
        small = o & 8  # a 128 KiB bank: A17 from p, not the MMC3
        inner, outer = (0x0F, high) if small else (0x1F, high & 6)
        super().map_prg(window, size_kib, (bank & inner) | outer << 4)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        o = self.outer
        high = (o >> 4) & 3 | (o >> 2 & 1) << 2  # CHR A19-A17 in 128 KiB units
        for i in range(size_kib):
            small = o & 0x40  # a 128 KiB bank: A17 from c, not the MMC3
            inner, outer = (0x7F, high) if small else (0xFF, high & 6)
            super().map_chr(window + i, 1, ((bank * size_kib + i) & inner) | outer << 7)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            if self.ram_control & 0xC0 == 0x80 and not self.outer & 0x80:
                self.outer = value
                self._update()
            return
        super().cpu_write(address, value, t)


class HPxx260(MMC3):
    """NES 2.0 mapper 260 (BMC-HPxx, BMC-HP2018-A multicarts).

    NES_2.0_Mapper_260.wiki, whose CNROM mode is from FCEUX's source and which no
    ROM uses (mask $F003): $5000 ``L....MMM``: the mode (0-3
    MMC3 with 256 or 128 KiB PRG and CHR, 4 NROM-128, 5 NROM-256, 6/7 CNROM),
    L locks the $5xxx registers; $5001 the 16 KiB PRG base; $5002 the 8 KiB
    CHR base; reads of $5000 give the DIP switches (D1-D0, 0 here). The MMC3
    banks are masked to the mode's size and ORed with the base; in modes
    4-7 the latch at $8000-$FFFF gives the CNROM bank and the mirroring (M:
    0 vertical). WRAM at $6000.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = [0, 0, 0]
        self.latch = 0
        super().__init__(image, cpu_cycle_ticks)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        mode, base = self.outer[0] & 7, self.outer[1]
        if mode == 4:
            bank = base * 2 + (window & 1)
        elif mode >= 5:
            bank = (base & ~1) * 2 + window
        else:
            inner = 0x0F if mode & 2 else 0x1F
            bank = (bank & inner) | (base * 2 & ~inner)
        super().map_prg(window, size_kib, bank)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        mode, base = self.outer[0] & 7, self.outer[2]
        for i in range(size_kib):
            w = window + i
            if mode < 4:
                inner = 0x7F if mode & 1 else 0xFF
                one = ((bank * size_kib + i) & inner) | (base * 8 & ~inner)
            elif mode < 6:
                one = base * 8 + w
            else:
                mask = 1 if mode == 6 else 3
                one = ((base & ~mask) | self.latch & mask) * 8 + w
            super().map_chr(w, 1, one)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address == 0x5000:
            return 0x00 | 0xFC << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            if not self.outer[0] & 0x80 and address & 3 < 3:
                self.outer[address & 3] = value
                self._update()
            return
        if address >= 0x8000:
            self.latch = value
            if self.outer[0] & 4:
                self.set_mirroring(HORIZONTAL if value & 4 else VERTICAL)
                self._update()
        super().cpu_write(address, value, t)


class A9461(MMC3):
    """Mapper 219 (Kǎshèng's A9461: Toy Story, Super 1997 4-in-1): an MMC3 with an extended mode.

    INES_Mapper_219.wiki (FCEUX's and Nestopia's implementations): $8002
    (mask $E003) as $8000 but D5 selects extended mode; $5002 D0 and $5003 D5
    the outer 128 KiB PRG and CHR bank (initialised to 3 for the menu). In
    extended mode, $8001 writes depend on the index: $23-$26 the PRG banks at
    $E000/$C000/$A000/$8000 (D5-D2, reversed); even $08-$1E latch CHR bits
    4-6 (D2-D0); odd $09-$0F the 1 KiB banks at $0000-$0C00 (D7-D1, ORed with
    index D1 and the latch); odd $11-$1F those at $1000-$1C00. Otherwise a
    plain MMC3, its banks masked to 128 KiB.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.extended = False
        self.outer = 3
        self.prg_banks: dict[int, int] = {}
        self.chr_banks: dict[int, int] = {}
        self.chr_latch = 0
        super().__init__(image, cpu_cycle_ticks)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        if self.extended and window in self.prg_banks:
            bank = self.prg_banks[window]
        super().map_prg(window, size_kib, (bank & 0x0F) | self.outer << 4)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            w = window + i
            one = (
                self.chr_banks.get(w, bank * size_kib + i) if self.extended else bank * size_kib + i
            )
            super().map_chr(w, 1, (one & 0x7F) | self.outer << 7)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            if address & 0x5003 == 0x5002:
                self.outer = (self.outer & 2) | value & 1
            elif address & 0x5003 == 0x5003:
                self.outer = (self.outer & 1) | (value >> 4) & 2
            self._update()
            return
        register = address & 0xE003
        if register == 0x8002:
            self.extended = bool(value & 0x20)
            super().cpu_write(0x8000, value, t)
            return
        if register & 0xE001 == 0x8001 and self.extended:
            self._extended(value)
            return
        super().cpu_write(address, value, t)

    def _extended(self, value: int) -> None:
        index = self.bank_select & 0x3F
        if 0x23 <= index <= 0x26:
            bits = (value >> 2) & 0x0F
            bank = sum(((bits >> b) & 1) << (3 - b) for b in range(4))
            self.prg_banks[{0x26: 0, 0x25: 1, 0x24: 2, 0x23: 3}[index]] = bank
        elif index & 1 == 0:
            self.chr_latch = value & 7
        elif index <= 0x0F:
            window = (index >> 1) & 3
            self.chr_banks[window] = (value >> 1) | (index >> 1) & 1 | self.chr_latch << 4
        else:
            window = 4 + ((index >> 2) & 3)
            self.chr_banks[window] = (value >> 1) | self.chr_latch << 4
        self._update()


class ING003C(MMC3):
    """Mappers 126 (TEC9719), 422 (ING003C) and 534 (ING-022): MMC3 multicarts with four registers.

    NES_2.0_Mapper_534.wiki, written only while $A001 enables the RAM, WRAM
    staying enabled either way: $6000 (mask $E003) ``XYbBCPPp``: PRG A17 from
    p instead of the MMC3 (Y), PRG A19-A18 (PP), PRG A21-A20 (b inverted,
    B), CHR A17 from C instead of the MMC3 (X), CHR A20 (PP's high bit), CHR
    A19-A18 (bB, swapped on 126); $6001 ``.....PEM``: one-screen mirroring
    allowed through $A000 D1 (E), the menu pads on PRG A0 (M; 0 here), the
    PRG chip on 534.2 (P); $6002 ``LGFEDCBA``: the 8 KiB CHR bank (D3-D0),
    its bits locked one by one (E, F, G: B, C, D) and L the locks; $6003
    ``L.M8DCBA``: L locks $6000/$6001/$6003, M ANROM mirroring (R6 D4), 8
    the 8 KiB CHR mode, and the PRG mode DCBA: 0 MMC3, 1-2 NROM-128, 3
    NROM-256, 4-7 the same, D or 9 UNROM, F or B ANROM. In modes 8-F writes
    to $8000-$FFFF act as odd addresses; in D and F (latch) they all reach
    $8001. 534's scanline counter takes $C000 inverted. Reset clears them.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = [0, 0, 0, 0]
        self.ram_control = 0x80
        self.kind = image.board.mapper
        super().__init__(image, cpu_cycle_ticks)

    def m2_gap(self, t: int) -> None:
        self.outer = [0, 0, 0, 0]
        self._update()

    def ram_protect(self, value: int) -> None:
        self.ram_control = value
        super().ram_protect(value)

    def _prg_high(self) -> int:
        o = self.outer[0]
        return ((o >> 1) & 3) << 5 | ((o >> 4) & 1) << 7 | (~o >> 5 & 1) << 8

    def _mmc3_bank(self, window: int) -> int:
        """The MMC3's own 5-bit bank for a CPU window."""
        r = self.registers
        if window == 1:
            return r[7] & 0x1F
        if window == 3:
            return 0x1F
        swapped = bool(self.bank_select & 0x40)
        return 0x1E if (window == 0) == swapped else r[6] & 0x1F

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        o, mode, r6 = self.outer[0], self.outer[3] & 0x0F, self.registers[6]
        if mode < 8:
            kind = mode & 3
            if kind == 0:
                inner = self._mmc3_bank(window)
            elif kind == 3:  # NROM-256
                inner = r6 & 0x1C | window
            else:  # NROM-128
                inner = r6 & 0x1E | window & 1
        elif mode in (9, 0x0D):  # UNROM
            inner = (r6 & 0x0F) << 1 | window & 1 if window < 2 else 0x1E | window & 1
        elif mode in (0x0B, 0x0F):  # ANROM
            inner = (r6 & 7) << 2 | window
        else:  # the page's "nonsense" modes: taken as MMC3
            inner = self._mmc3_bank(window)
        if o & 0x40:
            inner = inner & 0x0F | (o & 1) << 4
        super().map_prg(window, size_kib, inner | self._prg_high())

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        o, mode = self.outer[0], self.outer[3]
        bb = (o >> 4) & 3
        if self.kind == 126:
            bb = (bb >> 1) | (bb & 1) << 1
        high = bb << 8 | ((o >> 2) & 1) << 10
        for i in range(size_kib):
            w = window + i
            eight_kib = mode & 0x10
            one = (self.outer[2] & 0x0F) * 8 + w if eight_kib else bank * size_kib + i
            if o & 0x80:
                one = one & 0x7F | ((o >> 3) & 1) << 7
            super().map_chr(w, 1, (one & 0xFF) | high)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            if self.ram_control & 0x80:
                self._outer_write(address & 3, value)
            super().cpu_write(address, value, t)
            return
        if address >= 0x8000:
            mode = self.outer[3] & 0x0F
            if mode >= 8:
                address |= 1
            if mode in (0x0D, 0x0F):
                address = 0x8001
        register = address & 0xE001
        if self.kind == 534 and register == 0xC000:
            value ^= 0xFF
        if register == 0xA000 and self.outer[1] & 2:
            from_modes = (VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)
            self.set_mirroring(from_modes[value & 3])
            return
        super().cpu_write(address, value, t)
        if self.outer[3] & 0x20 and address >= 0x8000:
            self.set_mirroring(SCREEN_B if self.registers[6] & 0x10 else SCREEN_A)

    def _outer_write(self, register: int, value: int) -> None:
        locked = self.outer[3] & 0x80
        if register == 2:
            old = self.outer[2]
            keep = (old >> 4 & 1) << 1 | (old >> 5 & 1) << 2 | (old >> 6 & 1) << 3
            value = (value & ~keep) | (old & keep)
            if old & 0x80:
                value = (value & ~0x70) | (old & 0x70)
            self.outer[2] = value
        elif not locked:
            self.outer[register] = value
        self._update()


class Henggedianzi412(MMC3):
    """NES 2.0 mapper 412 (Intellivision 10-in-1, Henggedianzi multicarts): MMC3 plus NROM.

    NES_2.0_Mapper_412.wiki, through the MMC3's WRAM interface (mask $E003):
    $6000 D7-D2 the 8 KiB CHR bank in NROM mode; $6001 ``CARQDBPL``: L locks
    this register, P PRG A18 from B, D CHR A18, Q PRG A17 from A, R CHR A17
    from C; $6002 ``BBBBbQP.``: P NROM mode, Q NROM-256, b PRG A14, BBBB PRG
    A18-A15. Reset clears them.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = [0, 0, 0]
        self.ram_control = 0x80
        super().__init__(image, cpu_cycle_ticks)

    def m2_gap(self, t: int) -> None:
        self.outer = [0, 0, 0]
        self._update()

    def ram_protect(self, value: int) -> None:
        self.ram_control = value
        super().ram_protect(value)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        mode, prg = self.outer[1], self.outer[2]
        if prg & 2:  # NROM
            bank16 = prg >> 3
            if prg & 4:
                bank16 = (bank16 & ~1) | (window >> 1)
            bank = bank16 << 1 | window & 1
        else:
            if mode & 2:
                bank = (bank & 0x1F) | (mode & 4) << 3
            if mode & 0x10:
                bank = (bank & 0x2F) | (mode >> 2) & 0x10
        super().map_prg(window, size_kib, bank)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        mode, chr_reg, prg = self.outer[1], self.outer[0], self.outer[2]
        for i in range(size_kib):
            w = window + i
            if prg & 2:
                one = (chr_reg >> 2) * 8 + w
            else:
                one = (bank * size_kib + i) & 0xFF | (mode & 8) << 5
                if mode & 0x20:
                    one = one & ~0x80 | (mode >> 7) << 7
            super().map_chr(w, 1, one)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            register = address & 3
            if self.ram_control & 0x80 and register < 3:
                if register != 1 or not self.outer[1] & 1:
                    self.outer[register] = value
                self._update()
            return
        super().cpu_write(address, value, t)


class Multicart334(MMC3):
    """Mapper 334: the 5/20-in-1 1993: the MMC3 does mirroring and CHR, a register does PRG.

    NES_2.0_Mapper_334.wiki (masks "probably" $6003): with the MMC3's RAM enabled and
    writable, $6000 D2-D1 the 32 KiB bank; a read of $6002 gives the jumper on
    D0 (0: the 20-in-1 menu), the rest open bus.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.bank32 = 0
        self.registers_open = False
        super().__init__(image, cpu_cycle_ticks)

    def ram_protect(self, value: int) -> None:
        self.registers_open = value & 0xC0 == 0x80

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        super().map_prg(window, size_kib, self.bank32 * 4 + window)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.registers_open and address & 0xE003 == 0x6002:
            return 0x00 | 0xFE << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE003 == 0x6000:
            if self.registers_open:
                self.bank32 = (value >> 1) & 3
                self._update()
        else:
            super().cpu_write(address, value, t)


class Cocoma516(MMC3):
    """Mapper 516: EduBank's Cocoma Pack: an MMC3 clone in a 128 KiB window with a PAL's outer bank.

    NES_2.0_Mapper_516.wiki: writes with A4 clear are the MMC3's (mask $E011);
    with A4 set (mask $8010) A1-A0 are PRG A18-A17 and A3-A2 CHR A18-A17.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = 0
        super().__init__(image, cpu_cycle_ticks)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        super().map_prg(window, size_kib, (bank & 0x0F) | (self.outer & 3) << 4)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        for i in range(size_kib):
            one = ((bank * size_kib + i) & 0x7F) | ((self.outer >> 2) & 3) << 7
            super().map_chr(window + i, 1, one)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0x8010 == 0x8010:
            self.outer = address & 0x0F
            self._update()
        else:
            super().cpu_write(address, value, t)


class Zhongguo512(MMC3):
    """Mapper 512: Sachen's Zhongguo Daheng: an MMC3 clone, CHR-ROM and RAM, and four more pages.

    NES_2.0_Mapper_512.wiki: $4100 (mask "probably" $C100) D1-D0: 0 CHR-ROM and
    CIRAM; 1 CHR-ROM and the board's 4 KiB of VRAM as four screens; 2, 3
    CHR-RAM and CIRAM. The RAM and the VRAM are separate, and 8 KiB of WRAM
    stays enabled whatever $A001 says (the game never enables it).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.mode = 0
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.rom = image.chr
        self.chr_ram = bytearray(max(board.chr_ram + board.chr_nvram, 0x2000))
        self.vram = bytearray(0x1000)
        self.prg_ram = bytearray(max(len(self.prg_ram), 0x2000))
        self.prg_ram_mask = 0x1FFF
        self.prg_ram_enabled = True

    def ram_protect(self, value: int) -> None:
        pass

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xC100 == 0x4100:
            self.mode = value & 3
            self.four_screen = self.mode == 1
        elif address & 0xE001 == 0xA000:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        else:
            super().cpu_write(address, value, t)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000 and self.mode >= 2:
            offset = self.chr_offsets[address >> 10] + (address & 0x3FF)
            return self.chr_ram[offset % len(self.chr_ram)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            if self.mode >= 2:
                offset = self.chr_offsets[address >> 10] + (address & 0x3FF)
                self.chr_ram[offset % len(self.chr_ram)] = value
        else:
            super().ppu_write(address, value, t)


class BATMAP399(MMC3):
    """Mapper 399: BATMAP-000 (Star Versus): an MMC3's IRQ and mirroring with simpler banking.

    NES_2.0_Mapper_399.wiki (masks "probably" $E001): $8000: D2-D0 a 4 KiB CHR bank
    at PPU $0000 (D7 clear) or $1000; $8001: D6-D0 an 8 KiB bank at $A000 (D7
    clear) or $C000; banks 0 and last fixed at $8000 and $E000.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.chr4 = [0, 0]
        self.prg8 = [0, 0]
        super().__init__(image, cpu_cycle_ticks)

    def _update(self) -> None:
        self.map_prg(0, 8, 0)
        self.map_prg(1, 8, self.prg8[0])
        self.map_prg(2, 8, self.prg8[1])
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        self.map_chr(0, 4, self.chr4[0])
        self.map_chr(4, 4, self.chr4[1])

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE000 != 0x8000:
            super().cpu_write(address, value, t)
            return
        if address & 1:
            self.prg8[value >> 7] = value & 0x7F
        else:
            self.chr4[value >> 7] = value & 7
        self._update()


class FlashMMC3(MMC3):
    """An MMC3 board whose PRG is flash, written through the same CPU bus as its registers."""

    def attach_flash(self, flash: type, *ids: int) -> None:
        self.prg = bytearray(self.prg)
        self.flash = flash(self.prg, *ids)

    def _flash_offset(self, address: int) -> int:
        return self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.flash.id_mode and address >= 0x8000:
            return self.flash.read(self._flash_offset(address))
        return super().cpu_read(address, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg)

    def _restore(self, data: bytes) -> None:
        self.prg[:] = data


class Haradius406(FlashMMC3):
    """Mapper 406: Haradius Zero: a homebrew TLROM saving high scores to flash.

    NES_2.0_Mapper_406.wiki: submapper 0 (60-pin, a Macronix MX29F040, $C2/$A4) has the
    MMC3's A0 on CPU A1; submapper 1 (72-pin, an AMD AM29F040, $01/$A4) swaps
    the MMC3's $8xxx and $Exxx registers. The game checks the flash's ID.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.rewired = image.board.submapper
        self.attach_flash(Flash29F040, 0x01 if self.rewired else 0xC2, 0xA4)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.flash.write(self._flash_offset(address), value)
            if self.rewired:
                if address & 0xE000 in (0x8000, 0xE000):
                    address ^= 0x6000
            else:
                address = (address & ~1) | (address >> 1) & 1
        super().cpu_write(address, value, t)


class Haratyler451(FlashMMC3):
    """Mapper 451: Haratyler HG/MP: an MMC3's IRQ behind address-decoded registers, and flash.

    NES_2.0_Mapper_451.wiki: banks 0, $10+x, $20+x, $30 and an 8 KiB CHR-RAM bank; a
    write to $A000-$BFFF: A0 horizontal; to $C000-$DFFF: A7-A0 = V acts as
    MMC3 writes of $C000 = V - 1, $C001, and $E000 if V is $FF else $E001; to
    $E000-$FFFF: A0 is CHR A13 and adds 1 to x, A1 adds 8. Flash: an AMIC
    A29040B ($37, $86). The MP3 controller of Haratyler MP is not modelled.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.bank = 0
        super().__init__(image, cpu_cycle_ticks)
        self.attach_flash(Flash29F040, 0x37, 0x86)

    def _update(self) -> None:
        x = (self.bank & 1) | (self.bank & 2) << 2
        for window, bank in enumerate((0, 0x10 + x, 0x20 + x, 0x30)):
            self.map_prg(window, 8, bank)
        self.map_chr(0, 8, self.bank & 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        self.flash.write(self._flash_offset(address), value)
        region = address & 0xE000
        if region == 0xA000:
            self.set_mirroring(HORIZONTAL if address & 1 else VERTICAL)
        elif region == 0xC000:
            v = address & 0xFF
            super().cpu_write(0xC000, (v - 1) & 0xFF, t)
            super().cpu_write(0xC001, 0, t)
            super().cpu_write(0xE000 if v == 0xFF else 0xE001, 0, t)
        elif region == 0xE000:
            self.bank = address & 3
            self._update()


#: Mapper 594's $B000 D7-D6: (the bank at $6000's mask and base, the MMC3's PRG base in 8 KiB
#: banks, its CHR base in 1 KiB banks, per PPU A12).
RINCO_MODES = {
    0: (0xFF, 0x000, 0x000, (0x000, 0x100)),
    1: (0x3F, 0x0C0, 0x0C0, (0x200, 0x200)),
    2: (0x7F, 0x100, 0x100, (0x300, 0x300)),
}


class Rinco594(MMC3):
    """Mapper 594: Rinco's Talkman 3-in-1, for the RS-7600 famiclone's speech hardware.

    NES_2.0_Mapper_594.wiki: $9000 (mask $F001): an 8 KiB bank at $6000; $B000 D7-D6 the
    PRG and CHR windows of the bank at $6000 and the MMC3 (:data:`RINCO_MODES`).
    The FIFO and MSM6585 ADPCM behind $5000/$5001 are not modelled: a read of
    $5001 reports the FIFO at least half full on D6, a choice of ours so that the
    games' fill loops end (an idle FIFO would be empty), and the speech is silent.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.mode = 0
        self.extra = 0
        super().__init__(image, cpu_cycle_ticks)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        super().map_prg(window, size_kib, (bank & 0x3F) | RINCO_MODES[self.mode][2])

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        bases = RINCO_MODES[self.mode][3]
        for i in range(size_kib):
            one = bases[(window + i) >> 2] | ((bank * size_kib + i) & 0xFF)
            super().map_chr(window + i, 1, one)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xF001 == 0x5001:
            return 0x00 | 0xBF << 8
        if 0x6000 <= address < 0x8000:
            mask, base = RINCO_MODES[self.mode][:2]
            bank = base | self.extra & mask
            return self.prg[(bank * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF001 == 0x9000:
            self.extra = value
        elif address & 0xF001 == 0x9001:
            pass
        elif address & 0xF000 == 0xB000:
            self.mode = min(value >> 6, 2)
            self._update()
        else:
            super().cpu_write(address, value, t)


class ContraFighter238(MMC3):
    """Mapper 238 (Contra Fighter): an MMC3 and a protection register.

    The page names only the game. Its code decides (C68): anywhere in $4020-$7FFF a write
    selects an entry and a read gives it, and it checks D1-D0 against 0, 2, 2
    and 3 for writes of 0, 1, 2 and 3 ($0300 and $DB9D in its last banks).
    """

    PROTECTION = (0, 2, 2, 3)

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.protection = 0

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x4020 <= address < 0x8000:
            return self.PROTECTION[self.protection] | 0xFC << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x4020 <= address < 0x8000:
            self.protection = value & 3
        else:
            super().cpu_write(address, value, t)


class Board158B(SuperGame):
    """Mapper 258 (UNL-158B: Blood of Jurassic, Super Hang-On): 215's 8237 with protection.

    The page has only the name; MAME's mmc3_clones.cpp (BSD-3) has the rest: $5002 (mask $F003)
    picks a row, and reads of $5000-$5FFF give that row's entry for A2-A0 on
    D3-D0, the high lines open bus. The games decrypt their start from these.
    """

    PROTECTION = (
        (0, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 3, 0),
        (0, 0, 0, 0, 3, 4, 0, 0),
        (0, 0, 0, 1, 0, 4, 5, 0),
        (0, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 1, 2, 4, 15, 0),
    )

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.row = 7
        super().__init__(image.with_board(replace(image.board, mapper=215)), cpu_cycle_ticks)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x5000 <= address < 0x6000:
            return self.PROTECTION[self.row][address & 7] | 0xF0 << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF003 == 0x5002:
            self.row = value & 7
        else:
            super().cpu_write(address, value, t)
