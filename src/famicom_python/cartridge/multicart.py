"""Discrete-logic multicarts: outer and inner banks latched from the data or the address bus.

Each from its NESdev wiki page. No judge ROM exists for any of them; the
claims rest on sweeps against Mesen2, a detector (docs/claims.md). A board's
DIP switches or solder pads, which pick a menu, read as 0.
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage
from .mmc1 import MMC1
from .mmc3 import MMC3


class AddressLatch58(Banked):
    """Mapper 58 (and its duplicate 213): the address of a write to $8000-$FFFF is the latch.

    INES_Mapper_058.wiki ``1... .... MSCC CPPP``: PRG A16-A14 (S set: 16 KiB
    mirrored, else 32 KiB with A14 from the CPU), CHR A15-A13, and the
    mirroring (0 vertical, 1 horizontal). Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self._latch(0)

    def _latch(self, address: int) -> None:
        prg = address & 7
        if address & 0x40:
            self.map_prg(0, 16, prg)
            self.map_prg(2, 16, prg)
        else:
            self.map_prg(0, 32, prg >> 1)
        self.map_chr(0, 8, (address >> 3) & 7)
        self.set_mirroring(HORIZONTAL if address & 0x80 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class BS5(Banked):
    """NES 2.0 mapper 286: the BS-5 multicart: four 8 KiB PRG and four 2 KiB CHR windows.

    NES_2.0_Mapper_286.wiki, all from the address: $8000-$9FFF A11-A10 pick
    the 2 KiB CHR window and A4-A0 its 2 KiB bank (the page says "8 KiB" in
    one place and 2 KiB in the bank list; 2 KiB draws the menus, 8 KiB not);
    $A000-$BFFF A11-A10 pick the 8 KiB PRG window and A3-A0 its bank, taken
    only when the address bit the DIP switch selects among A7-A4 is set
    (setting 1, A4, here). Every bank powers on as $F; vertical mirroring.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        for window in range(4):
            self.map_prg(window, 8, 0x0F)
            self.map_chr(window * 2, 2, 0x1F)
        self.set_mirroring(VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        window = (address >> 10) & 3
        if address & 0xE000 == 0x8000:
            self.map_chr(window * 2, 2, address & 0x1F)
        elif address & 0xE000 == 0xA000 and address & 0x10:
            self.map_prg(window, 8, address & 0x0F)
        else:
            super().cpu_write(address, value, t)


class HP898F(Banked):
    """NES 2.0 mapper 319: the HP-898F and KD-7/9-E boards.

    NES_2.0_Mapper_319.wiki, two registers decoded by A14, A13 and A2 (mask
    $6004, so $6000-$7FFF and $E000-$FFFF): A2 clear, D7-D4 the 8 KiB CHR
    bank; A2 set, ``MDaBC...``: PRG A16 (B), A15 (C), A14 (a, with D clear:
    16 KiB mirrored; D set: 32 KiB, A14 from the CPU), and the mirroring
    (0 horizontal, 1 vertical). $5FF0 reads the solder pad (D6, 0 here).
    Mesen2 orders the PRG bits as the public UNIF image's mixed-up banks;
    this is the wiki's NES 2.0 order. Power-on registers 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self._prg(0)
        self.map_chr(0, 8, 0)

    def _prg(self, value: int) -> None:
        bank32 = (value >> 3) & 3  # PRG A16-A15
        if value & 0x40:
            self.map_prg(0, 32, bank32)
        else:
            bank16 = bank32 << 1 | (value >> 5) & 1
            self.map_prg(0, 16, bank16)
            self.map_prg(2, 16, bank16)
        self.set_mirroring(VERTICAL if value & 0x80 else HORIZONTAL)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address == 0x5FF0:
            return 0x00 | 0xBF << 8  # the solder pad on D6: 0
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0x6000 != 0x6000:
            super().cpu_write(address, value, t)
        elif address & 4:
            self._prg(value)
        else:
            self.map_chr(0, 8, value >> 4)


class AddressLatch242(Banked):
    """Mappers 242 and 227: address-latch multicarts with UNROM-like and NROM modes.

    INES_Mapper_242.wiki, _227.wiki: the address of a write to $8000-$FFFF
    is latched, ``...m LQ OQQPPpMS`` on 227 (``...C Lm OQQPPpMS`` on 242):
    the inner 16 KiB bank PPp (S: p from CPU A14, 32 KiB), the outer bank QQ
    (227: and Q, A19); O set: NROM-128 or NROM-256 (S); O clear: the inner
    bank at $8000 and $C000 fixed to inner bank 7 (L) or 0 (227.2: and outer
    A18-A17 0 too). M: the mirroring (0 vertical, 1 horizontal). m: PRG
    A4-A0 (227: A3-A0) read the solder pads (0 here; 227 only on 227.1).
    CHR-RAM is write-protected in the NROM modes on the multicarts (no
    battery; 227.1/227.2), not on the Chinese RPG boards, which also have no
    UNROM modes (O taken as set). 242's C bit: on the 640 KiB ET-113 board,
    clear selects the 128 KiB replacement chip (second in the file), as it
    is at power-on. Power-on and reset (:meth:`m2_gap`) clear the latch.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.wide = board.mapper == 227
        self.submapper = board.submapper
        self.rpg = self.battery and not (self.wide and self.submapper in (1, 2))
        self.two_chips = len(self.prg) == 0xA0000
        self.chr_ram = not image.chr
        self.latch = 0
        self.pads_shown = False
        self.map_chr(0, 8, 0)
        self._latch(0)

    def _latch(self, address: int) -> None:
        self.latch = address
        inner, outer = (address >> 2) & 7, (address >> 5) & 3
        if self.wide:
            outer |= ((address >> 8) & 1) << 2
            self.pads_shown = bool(address & 0x400) and self.submapper == 1
        else:
            self.pads_shown = bool(address & 0x100)
        thirty_two = address & 1
        nrom = address & 0x80 or self.rpg
        base = outer << 3
        if nrom:
            if thirty_two:
                low, high = base | inner & 6, base | inner | 1
            else:
                low = high = base | inner
        else:
            low = base | (inner & 6 if thirty_two else inner)
            if address & 0x200:
                high = base | 7
            else:
                high = base & ~0x18 if self.wide and self.submapper == 2 else base
        if self.two_chips and not self.wide and not address & 0x400:
            low, high = 32 + (low & 7), 32 + (high & 7)
        self.map_prg(0, 16, low)
        self.map_prg(2, 16, high)
        self.set_mirroring(HORIZONTAL if address & 2 else VERTICAL)
        multicart = not self.rpg
        self.chr_writable = self.chr_ram and not (multicart and nrom)

    def m2_gap(self, t: int) -> None:
        self._latch(0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.pads_shown:
            address &= ~(0x0F if self.wide else 0x1F)
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class AddressLatch59(Banked):
    """Mapper 59 (BMC-T3H53, BMC-D1038): an address latch with a lock and a jumper read.

    INES_Mapper_059.wiki ``1......LDSPPpMCCC``: the 8 KiB CHR bank, the
    mirroring (0 vertical, 1 horizontal), the 16 KiB PRG bank (S clear: 32
    KiB, p from CPU A14), D: reads of $8000-$FFFF return the jumper (D1-D0,
    0 here; the rest open bus) instead of PRG, L: further writes ignored
    until reset (:meth:`m2_gap`). Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.locked = False
        self.jumper_read = False
        self._latch(0)

    def _latch(self, address: int) -> None:
        bank = (address >> 4) & 7
        if address & 0x80:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        else:
            self.map_prg(0, 32, bank >> 1)
        self.map_chr(0, 8, address & 7)
        self.set_mirroring(HORIZONTAL if address & 8 else VERTICAL)
        self.jumper_read = bool(address & 0x100)
        self.locked = bool(address & 0x200)

    def m2_gap(self, t: int) -> None:
        self.locked = False

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.jumper_read:
            return 0x00 | 0xFC << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            if not self.locked:
                self._latch(address)
        else:
            super().cpu_write(address, value, t)


class AddressLatch212(Banked):
    """Mapper 212 (BMC Super HiK 300-in-1): an address latch with a read-back quirk.

    INES_Mapper_212.wiki ``1o.. .... .... MBBb``: A2-A0 are PRG A16-A14 (o
    set: 32 KiB, BB) and CHR A15-A13; M the mirroring (0 vertical, 1
    horizontal). Reads of $6000-$7FFF (mask $E010) return A4 inverted in D7
    and the solder pads (D3-D0, 0 here); D6-D4 open bus. Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self._latch(0)

    def _latch(self, address: int) -> None:
        bank = address & 7
        if address & 0x4000:
            self.map_prg(0, 32, bank >> 1)
        else:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        self.map_chr(0, 8, bank)
        self.set_mirroring(HORIZONTAL if address & 8 else VERTICAL)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return (0 if address & 0x10 else 0x80) | 0x70 << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class AddressLatch225(Banked):
    """Mappers 225 and 255: an address latch with sixteen bits of RAM at $5800.

    INES_Mapper_225.wiki ``.HMOPPPPPPCCCCCC``: H is bit 6 of both the 16 KiB
    PRG bank (P) and the 8 KiB CHR bank (C); O set: 16 KiB mirrored, else 32
    KiB; M the mirroring (0 vertical, 1 horizontal). $5800-$5803, mirrored
    to $5FFF: four 4-bit RAM cells (the 74'670, D3-D0; D7-D4 open bus).
    Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.nibbles = [0] * 4
        self._latch(0)

    def _latch(self, address: int) -> None:
        high = (address >> 14) & 1
        prg = high << 6 | (address >> 6) & 0x3F
        if address & 0x1000:
            self.map_prg(0, 16, prg)
            self.map_prg(2, 16, prg)
        else:
            self.map_prg(0, 32, prg >> 1)
        self.map_chr(0, 8, high << 6 | address & 0x3F)
        self.set_mirroring(HORIZONTAL if address & 0x2000 else VERTICAL)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x5800 <= address < 0x6000:
            return self.nibbles[address & 3] | 0xF0 << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        elif 0x5800 <= address < 0x6000:
            self.nibbles[address & 3] = value & 0x0F
        else:
            super().cpu_write(address, value, t)


class Latch226(Banked):
    """Mapper 226 (76-in-1, Super 42-in-1): two latches at $8000/$8001 (mask $8001).

    INES_Mapper_226.wiki: $8000 ``PMOPPPPP``: PRG bank bits 0-5 (D7 is bit 5),
    O set: 16 KiB mirrored, else 32 KiB; M the mirroring (0 horizontal, 1
    vertical); $8001 D0 PRG bank bit 6, D1 write-protects the CHR-RAM (the
    original document; no game relies on it). 8 KiB of CHR-RAM. Power-on and
    reset clear both registers.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.regs = [0, 0]
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        low, high = self.regs
        bank = (low & 0x1F) | (low >> 2) & 0x20 | (high & 1) << 6
        if low & 0x20:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        else:
            self.map_prg(0, 32, bank >> 1)
        self.set_mirroring(VERTICAL if low & 0x40 else HORIZONTAL)
        self.chr_writable = not self.image.chr and not high & 2

    def m2_gap(self, t: int) -> None:
        self.regs = [0, 0]
        self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.regs[address & 1] = value
            self._update()
        else:
            super().cpu_write(address, value, t)


class WS332(Banked):
    """NES 2.0 mapper 332 (BMC-WS: Super 40-in-1, Super 500-in-1).

    NES_2.0_Mapper_332.wiki: $6000 (mask $E001) ``.H.MBPPp``: the 16 KiB PRG
    bank PPp (B set: mirrored; clear: 32 KiB), H as PRG A17 and CHR A16, M
    the mirroring (0 vertical, 1 horizontal); $6001 ``DDMM.Cdc``: CHR A15 (C)
    and CHR A14-A13: from the CNROM latch at $8000-$FFFF (MM 00), A13 from it
    and A14 from d (10), or dc (11); DD probe the solder pads (none bridged
    here, so no effect). Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.regs = [0, 0]
        self.latch = 0
        self._update()

    def _update(self) -> None:
        r0, r1 = self.regs
        high = (r0 >> 6) & 1
        bank = high << 3 | r0 & 7
        if r0 & 8:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        else:
            self.map_prg(0, 32, bank >> 1)
        self.set_mirroring(HORIZONTAL if r0 & 0x10 else VERTICAL)
        mode = (r1 >> 4) & 3
        if mode == 3:
            low = r1 & 3
        elif mode == 2:
            low = (r1 & 2) | self.latch & 1
        else:
            low = self.latch & 3
        self.map_chr(0, 8, high << 3 | ((r1 >> 2) & 1) << 2 | low)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.latch = value
        elif address & 0xE001 in (0x6000, 0x6001):
            self.regs[address & 1] = value
        else:
            super().cpu_write(address, value, t)
            return
        self._update()


class ResetMulticart60(Banked):
    """Mapper 60: the reset-based NROM-128 4-in-1.

    INES_Mapper_060.wiki (Disch's notes): four NROM games of 16 KiB PRG (at
    $8000 and $C000) and 8 KiB CHR; an internal 2-bit register, counted up
    by each reset (:meth:`m2_gap`), selects one. Power-on game 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.game = 0
        self._select()

    def _select(self) -> None:
        self.map_prg(0, 16, self.game)
        self.map_prg(2, 16, self.game)
        self.map_chr(0, 8, self.game)

    def m2_gap(self, t: int) -> None:
        self.game = (self.game + 1) & 3
        self._select()


class GK57(Banked):
    """Mapper 57 (GK 47-in-1, 6-in-1 SuperGK): two registers at $8000 and $8800 (mask $8800).

    INES_Mapper_057.wiki: $8000 ``CH....AA``, $8800 ``PPPOMBbb``: the 8 KiB
    CHR bank H B AA (C clear, CNROM) or H B bb (C set, NROM); the 16 KiB PRG
    bank PPP (O set: 32 KiB); M the mirroring (0 vertical, 1 horizontal).
    Power-on registers 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.regs = [0, 0]
        self._update()

    def _update(self) -> None:
        low, high = self.regs
        inner = high & 3 if low & 0x80 else low & 3
        self.map_chr(0, 8, ((low >> 6) & 1) << 3 | ((high >> 2) & 1) << 2 | inner)
        bank = high >> 5
        if high & 0x10:
            self.map_prg(0, 32, bank >> 1)
        else:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        self.set_mirroring(HORIZONTAL if high & 8 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.regs[(address >> 11) & 1] = value
            self._update()
        else:
            super().cpu_write(address, value, t)


class Latch519(Banked):
    """NES 2.0 mapper 519: an address-and-data latch with a lock and a DIP switch read.

    NES_2.0_Mapper_519.wiki: a write to $8000-$FFFF latches A ``L pDPP PPPP``
    and D ``MCCC CCCC``: the 8 KiB CHR bank (D6-D0), the mirroring (D7: 0
    vertical), the 16 KiB PRG bank (A5-A0; p set: mirrored, clear: 32 KiB),
    D: reads of $8000-$FFFF see the address AND $FFF0 OR the DIP switches (0
    here), L: lock every field but the inner CHR bank (D1-D0). Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.address = self.value = 0
        self.locked = False
        self._update()

    def _update(self) -> None:
        a, d = self.address, self.value
        bank = a & 0x3F
        if a & 0x80:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        else:
            self.map_prg(0, 32, bank >> 1)
        self.map_chr(0, 8, d & 0x7F)
        self.set_mirroring(HORIZONTAL if d & 0x80 else VERTICAL)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.address & 0x40:
            address &= 0xFFF0
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.locked:
            self.value = (self.value & ~3) | value & 3
        else:
            self.address, self.value = address, value
            self.locked = bool(address & 0x100)
        self._update()


class GoldenGame235(Banked):
    """Mapper 235 ("Golden Game" 150-in-1 and kin): an address latch over up to four 1 MiB ROMs.

    INES_Mapper_235.wiki (The Mad Dumper's notes): ``1xMPRNBB xxxAAAAA``: the
    32 KiB page A within ROM chip BB (chips the file lacks read open bus), R
    16 KiB pages (P the half), M the mirroring (0 horizontal, 1 vertical) or N
    one-screen. 8 KiB of CHR-RAM. Power-on and reset clear the latch.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_chr(0, 8, 0)
        self.open_bus = False
        self._latch(0)

    def _latch(self, address: int) -> None:
        chip, page = (address >> 8) & 3, address & 0x1F
        bank32 = chip << 5 | page
        self.open_bus = bank32 * 0x8000 >= len(self.prg)
        if address & 0x800:
            bank16 = bank32 << 1 | (address >> 12) & 1
            self.map_prg(0, 16, bank16)
            self.map_prg(2, 16, bank16)
        else:
            self.map_prg(0, 32, bank32)
        if address & 0x400:
            self.set_mirroring(SCREEN_A)
        else:
            self.set_mirroring(VERTICAL if address & 0x2000 else HORIZONTAL)

    def m2_gap(self, t: int) -> None:
        self._latch(0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.open_bus:
            return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class Maxi15(Banked):
    """Mapper 234: the Maxi 15 multicart, banking on the value the CPU *reads* at $FF80-$FFF7.

    INES_Mapper_234.wiki: reads (and writes, with AND-type bus conflicts)
    latch: $FF80-$FF9F the outer register ``MOQqBBBb``: the block, ROMs 3+4
    (Q) unless disabled (q), NINA-03 mode (O), the mirroring (M: 0 vertical);
    once any of Q, q, BBB or b is set it, and the lockout register, are
    frozen. $FFE8-$FFF7 the inner register ``.cCC...P``. CNROM mode: PRG
    BBBb, CHR BBBbCC; NINA-03 mode: PRG BBBP, CHR BBBcCC. The lockout
    defeat at $FFC0-$FFDF is left out. Power-on and reset clear them.
    """

    latches_reads = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.outer = self.inner = 0
        self.disabled = False
        self._update()

    def _update(self) -> None:
        o, i = self.outer, self.inner
        block = o & 0x0F
        chip = 0x10 if o & 0x20 else 0  # ROMs 3+4: the second half
        self.disabled = bool(o & 0x20 and o & 0x10)
        if o & 0x40:  # NINA-03
            prg, chr8 = (block & 0x0E) | i & 1, (block & 0x0E) << 2 | (i >> 4) & 7
        else:
            prg, chr8 = block, block << 2 | (i >> 4) & 3
        self.map_prg(0, 32, chip | prg)
        self.map_chr(0, 8, chip << 2 | chr8)
        self.set_mirroring(HORIZONTAL if o & 0x80 else VERTICAL)

    def m2_gap(self, t: int) -> None:
        self.outer = self.inner = 0
        self._update()

    def _latch(self, address: int, value: int) -> None:
        if 0xFF80 <= address <= 0xFF9F:
            if not self.outer & 0x3F:
                self.outer = value
                self._update()
        elif 0xFFE8 <= address <= 0xFFF7:
            self.inner = value
            self._update()

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.disabled:
            return None
        return super().cpu_read(address, t)

    def read_data(self, address: int, value: int, t: int) -> None:
        self._latch(address, value)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address, self.bus_conflict(address, value))
        else:
            super().cpu_write(address, value, t)


class K1029(Banked):
    """Mapper 15: the K-1029/K-1030P boards (100-in-1 and 168-in-1 Contra Function 16).

    INES_Mapper_015.wiki: a write to $8000-$FFFF latches A1-A0 (the PRG mode:
    0 NROM-256, 1 UNROM with 111 at $C000, 2 NROM-64 with p as A13, 3
    NROM-128) and the data ``pMPPPPPP`` (PRG A19-A14, the mirroring: 0
    vertical). CHR-RAM is write-protected in modes 0 and 3, as the board
    does (mapper hacks of 164/227 set to 15 need it unprotected and RAM at
    $6000; those are not these boards). Power-on and reset clear it.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_chr(0, 8, 0)
        self._latch(0, 0)

    def _latch(self, address: int, value: int) -> None:
        mode, bank = address & 3, value & 0x3F
        if mode == 0:
            self.map_prg(0, 32, bank >> 1)
        elif mode == 1:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank | 7)
        elif mode == 2:
            bank8 = bank << 1 | value >> 7
            for window in range(4):
                self.map_prg(window, 8, bank8)
        else:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        self.set_mirroring(HORIZONTAL if value & 0x40 else VERTICAL)
        self.chr_writable = not self.image.chr and mode in (1, 2)

    def m2_gap(self, t: int) -> None:
        self._latch(0, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address, value)
        else:
            super().cpu_write(address, value, t)


class NoRepeat314(Banked):
    """NES 2.0 mapper 314 (BMC-64in1NoRepeat: the Y2K multicarts).

    NES_2.0_Mapper_314.wiki (mask taken as $F003): $5000 ``U.M..CCP``: NROM
    (U) or UNROM, the mirroring (M: 0 vertical), CHR bank bits 0-1, PRG A21;
    $5001 ``MpPPPPPP``: the 32 KiB PRG bank (A20-A15), p the 16 KiB half and
    M 32 KiB (NROM modes); $5002 CHR bank bits 2-5; $8000-$FFFF the UNROM
    latch (D2-D0: the inner 16 KiB bank at $8000, 7 at $C000). Power-on
    $80, $43, $00.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.regs = [0x80, 0x43, 0x00]
        self.latch = 0
        self._update()

    def _update(self) -> None:
        r0, r1, r2 = self.regs
        bank32 = (r0 & 1) << 6 | r1 & 0x3F
        if r0 & 0x80:  # NROM
            if r1 & 0x80:
                self.map_prg(0, 32, bank32)
            else:
                half = bank32 << 1 | (r1 >> 6) & 1
                self.map_prg(0, 16, half)
                self.map_prg(2, 16, half)
        else:  # UNROM inside a 128 KiB block
            base = (bank32 << 1) & ~7
            self.map_prg(0, 16, base | self.latch & 7)
            self.map_prg(2, 16, base | 7)
        self.map_chr(0, 8, (r2 & 0x0F) << 2 | (r0 >> 1) & 3)
        self.set_mirroring(HORIZONTAL if r0 & 0x20 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.latch = value
        elif address & 0xF003 in (0x5000, 0x5001, 0x5002):
            self.regs[address & 3] = value
        else:
            super().cpu_write(address, value, t)
            return
        self._update()


class Champion289(Banked):
    """NES 2.0 mapper 289 (Super HiK 17-in-1, Champion Cassette 1200-in-1, Super 76-in-1).

    NES_2.0_Mapper_289.wiki: $6000 (mask $E001) ``....MLPP``: the PRG mode (0
    NROM-128, 1 NROM-256, 2 UNROM from the latch with 111 at $C000, 3 all
    111), CHR-RAM write protection (L), the mirroring (M: 0 vertical); $6001
    ``.QQQQPPp``: PRG A20-A17 and, in the NROM modes, A16-A15 (A14); reads
    of $6000 (mask $E000) give the solder pads (D1-D0, 0 here); $8000-$FFFF
    the UNROM latch. 8 KiB of CHR-RAM. Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.mode = self.outer = self.latch = 0
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        mode, outer = self.mode, self.outer
        base = (outer >> 3) << 3  # 16 KiB banks of 128 KiB
        kind = mode & 3
        if kind == 0:
            self.map_prg(0, 16, base | outer & 7)
            self.map_prg(2, 16, base | outer & 7)
        elif kind == 1:
            self.map_prg(0, 32, (base | outer & 6) >> 1)
        else:
            low = base | (self.latch & 7 if kind == 2 else 7)
            self.map_prg(0, 16, low)
            self.map_prg(2, 16, base | 7)
        self.set_mirroring(HORIZONTAL if mode & 8 else VERTICAL)
        self.chr_writable = not self.image.chr and not mode & 4

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xE000 == 0x6000:
            return 0x00 | 0xFC << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.latch = value
        elif address & 0xE001 == 0x6000:
            self.mode = value
        elif address & 0xE001 == 0x6001:
            self.outer = value
        else:
            super().cpu_write(address, value, t)
            return
        self._update()


class Asder290(Banked):
    """NES 2.0 mapper 290 (Asder 20-in-1): an address latch.

    NES_2.0_Mapper_290.wiki ``1PPPPMCC Sp...CCC``: the 8 KiB CHR bank (A9-A8,
    A2-A0), the 32 KiB PRG bank PPPP (S set: 16 KiB bank PPPPp), the
    mirroring (M: 0 vertical). Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self._latch(0)

    def _latch(self, address: int) -> None:
        bank32 = (address >> 11) & 0x0F
        if address & 0x80:
            half = bank32 << 1 | (address >> 6) & 1
            self.map_prg(0, 16, half)
            self.map_prg(2, 16, half)
        else:
            self.map_prg(0, 32, bank32)
        self.map_chr(0, 8, (address >> 5) & 0x18 | address & 7)
        self.set_mirroring(HORIZONTAL if address & 0x400 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class Latch299(Banked):
    """NES 2.0 mapper 299: a data latch at $8000-$FFFF (mask $8000).

    NES_2.0_Mapper_299.wiki ``M.PP..CC``: the 32 KiB PRG bank PP, which is
    also the 32 KiB outer CHR bank, the inner 8 KiB CHR bank CC, the
    mirroring (M: 0 horizontal, 1 vertical). Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self._latch(0)

    def _latch(self, value: int) -> None:
        outer = (value >> 4) & 3
        self.map_prg(0, 32, outer)
        self.map_chr(0, 8, outer << 2 | value & 3)
        self.set_mirroring(VERTICAL if value & 0x80 else HORIZONTAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(value)
        else:
            super().cpu_write(address, value, t)


class Latch229(Banked):
    """Mapper 229 (BMC 31-in-1): the address of a write to $8000-$FFFF (mask $803F).

    INES_Mapper_229.wiki: A4-A0 the 16 KiB PRG bank at both halves and the 8
    KiB CHR bank, except that with A4-A0 all 0 the second half is bank 1
    (the menu's 32 KiB); A5 the mirroring (0 vertical). Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self._latch(0)

    def _latch(self, address: int) -> None:
        bank = address & 0x1F
        self.map_prg(0, 16, bank)
        self.map_prg(2, 16, bank if bank else 1)
        self.map_chr(0, 8, bank)
        self.set_mirroring(HORIZONTAL if address & 0x20 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class N625092(Banked):
    """Mapper 221 (NTDEC N625092 multicarts): two address latches.

    INES_Mapper_221.wiki: $8000-$BFFF ``10....Bp...OOOPM``: the mirroring (M: 0
    vertical), NROM-128 (P clear) or, P set, NROM-256 (p clear) or UNROM (p
    set), the 128 KiB outer bank OOO and A20 (B); $C000-$FFFF ``....CIII``:
    the inner 16/32 KiB bank and the CHR-RAM write protection (C). Power-on 0.
    A6 also drives PRG A18, which the page does not show: the 400-in-1's stub
    writes $8040 before copying its tiles from $C000, garbage without it.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.mode = self.inner = 0
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        mode, inner = self.mode, self.inner & 7
        base = ((mode >> 2) & 7 | (mode >> 5) & 2 | (mode >> 6) & 8) << 3  # 16 KiB banks
        if not mode & 2:
            self.map_prg(0, 16, base | inner)
            self.map_prg(2, 16, base | inner)
        elif mode & 0x100:
            self.map_prg(0, 16, base | inner)
            self.map_prg(2, 16, base | 7)
        else:
            self.map_prg(0, 32, (base | inner) >> 1)
        self.set_mirroring(HORIZONTAL if mode & 1 else VERTICAL)
        self.chr_writable = not self.image.chr and not self.inner & 8

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x8000 <= address < 0xC000:
            self.mode = address
        elif address >= 0xC000:
            self.inner = address
        else:
            super().cpu_write(address, value, t)
            return
        self._update()


class A65AS(Banked):
    """NES 2.0 mapper 285: the A65AS (285.0) and JY-066 (285.1) multicarts, a data latch.

    NES_2.0_Mapper_285.wiki: P (D6) chooses 32 KiB banks (D2-D1) or 16 KiB
    ones (the inner bank D2-D0 at $8000, 7 at $C000) in a 128 KiB outer bank
    (285.0: D4-D3; 285.1: D5-D4); S (D7) one-screen mirroring (page from D5),
    else horizontal/vertical (285.0: D5; 285.1: D3; 0 vertical). The 32 KiB
    mode takes the outer bank too (the page shows no other source). 8 KiB
    CHR-RAM. Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.jy066 = image.board.submapper == 1
        self.map_chr(0, 8, 0)
        self._latch(0)

    def _latch(self, value: int) -> None:
        outer = (value >> 4) & 3 if self.jy066 else (value >> 3) & 3
        if value & 0x40:
            self.map_prg(0, 32, outer << 2 | (value >> 1) & 3)
        else:
            self.map_prg(0, 16, outer << 3 | value & 7)
            self.map_prg(2, 16, outer << 3 | 7)
        if value & 0x80:
            self.set_mirroring(SCREEN_B if value & 0x20 else SCREEN_A)
        else:
            horizontal = value & 8 if self.jy066 else value & 0x20
            self.set_mirroring(HORIZONTAL if horizontal else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(value)
        else:
            super().cpu_write(address, value, t)


class Powerful63(Banked):
    """Mapper 63 (Powerful 255-in-1 and kin): an address latch, unpopulated banks open bus.

    INES_Mapper_063.wiki: ``1....CBB BBBBBbPM`` on 63.0 (63.1: ``1.....CB
    BBBBBbPM``, one PRG bit fewer): the 16 KiB PRG bank (P clear: mirrored,
    b kept; set: 32 KiB), the mirroring (M: 0 vertical), CHR-RAM write
    protection (C). Banks past the ROM read open bus, which the menu uses to
    count the games. Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.narrow = image.board.submapper == 1
        self.map_chr(0, 8, 0)
        self.banks = (0, 0)
        self._latch(0)

    def _latch(self, address: int) -> None:
        bank = (address >> 2) & (0x7F if self.narrow else 0xFF)
        if address & 2:
            low, high = bank & ~1, bank | 1
        else:
            low = high = bank
        self.banks = (low, high)
        self.map_prg(0, 16, low)
        self.map_prg(2, 16, high)
        self.set_mirroring(HORIZONTAL if address & 1 else VERTICAL)
        protect = address & (0x200 if self.narrow else 0x400)
        self.chr_writable = not self.image.chr and not protect

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.banks[(address >> 14) & 1] * 0x4000 >= len(self.prg):
            return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class Super700(Banked):
    """Mapper 62 (Super 700-in-1): the address and the data of a write to $8000-$FFFF.

    INES_Mapper_062.wiki (Disch's notes): A ``..ppppppMPOCCCCC`` and D
    ``......cc``: the 8 KiB CHR bank CCCCCcc, the PRG bank (P high, pppppp
    low: 16 KiB mirrored with O set, else 32 KiB), the mirroring (M: 0
    vertical). Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self._latch(0, 0)

    def _latch(self, address: int, value: int) -> None:
        bank = (address >> 6) & 0x40 | (address >> 8) & 0x3F
        if address & 0x20:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        else:
            self.map_prg(0, 32, bank >> 1)
        self.map_chr(0, 8, (address & 0x1F) << 2 | value & 3)
        self.set_mirroring(HORIZONTAL if address & 0x80 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address, value)
        else:
            super().cpu_write(address, value, t)


class Latch61(Banked):
    """Mapper 61 (Tetris Family 9-in-1, HQ 15-in-1, 32-in-1): an address latch.

    INES_Mapper_061.wiki ``1...CCCCMcpNPPPP``: PRG A18-A15 (N set: 16 KiB, p
    as A14; clear: 32 KiB), the mirroring (M: 0 vertical), the 8 KiB CHR
    bank CCCC (61.1: CCCC as A17-A14 and c as A13). CHR-RAM on GS-2017,
    unbanked. Power-on latch 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.wide_chr = image.board.submapper == 1
        self.rom_chr = bool(image.chr)
        self.map_chr(0, 8, 0)
        self._latch(0)

    def _latch(self, address: int) -> None:
        prg = address & 0x0F
        if address & 0x10:
            half = prg << 1 | (address >> 5) & 1
            self.map_prg(0, 16, half)
            self.map_prg(2, 16, half)
        else:
            self.map_prg(0, 32, prg)
        if self.rom_chr:
            bank = (address >> 8) & 0x0F
            if self.wide_chr:
                bank = bank << 1 | (address >> 6) & 1
            self.map_chr(0, 8, bank)
        self.set_mirroring(HORIZONTAL if address & 0x80 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)
        else:
            super().cpu_write(address, value, t)


class Latch380(Banked):
    """Mapper 380: the 970630C (0) and KN-35A (1) multicarts' address latch.

    NES_2.0_Mapper_380.wiki: a write to $8000-$FFFF latches ``..Om CRQP PpMS``.
    S: 1 PRG A14 from p; M: 1 horizontal; RQPPp: PRG A18-A14; C: 1 protects
    the CHR-RAM. m: on submapper 0 PRG A3-A0 read solder pads (0 here), on 1
    PRG A17 = 1 at $C000 (UOROM). O: 0 fixes PRG A16-A14 to 111 at $C000
    (UNROM), 1 keeps PPp there.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.submapper = image.board.submapper
        self.pads_replace = False
        self.map_chr(0, 8, 0)
        self._latch(0)

    def _latch(self, a: int) -> None:
        bank, nrom128, unrom_off, m = (a >> 2) & 0x1F, a & 1, a & 0x200, a & 0x100
        low, high = bank, bank
        if unrom_off:
            if not nrom128:
                low, high = bank & ~1, bank | 1
        else:
            high = bank | (0x0F if m and self.submapper == 1 else 7)
        self.map_prg(0, 16, low)
        self.map_prg(2, 16, high)
        self.set_mirroring(HORIZONTAL if a & 2 else VERTICAL)
        self.chr_writable = not a & 0x80
        self.pads_replace = bool(m) and self.submapper == 0

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.pads_replace and address >= 0x8000:
            address &= ~0x0F
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address)


class Caltron389(Banked):
    """Mapper 389: the Caltron 9-in-1.

    NES_2.0_Mapper_389.wiki, all by address: $8000-$8FFF A6-A3 PRG A18-A15,
    A0 horizontal; $9000-$9FFF A5-A3 CHR A17-A15, A1 UNROM-064 (else
    NROM-256); $A000-$FFFF A3-A2 PRG A15-A14 at $8000 in UNROM-064 (inner
    bank 3 at $C000), A1-A0 CHR A14-A13. The page's bit orders are read
    with the low bit the low line.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.outer = self.mode = self.inner = 0
        self._update()

    def _update(self) -> None:
        outer_prg = (self.outer >> 3) & 0x0F
        if self.mode & 2:
            base = (outer_prg & ~1) << 1
            self.map_prg(0, 16, base | (self.inner >> 2) & 3)
            self.map_prg(2, 16, base | 3)
        else:
            self.map_prg(0, 32, outer_prg)
        self.map_chr(0, 8, ((self.mode >> 3) & 7) << 2 | self.inner & 3)
        self.set_mirroring(HORIZONTAL if self.outer & 1 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            return
        if address < 0x9000:
            self.outer = address
        elif address < 0xA000:
            self.mode = address
        else:
            self.inner = address
        self._update()


class YY850437C(Banked):
    """Mapper 396: J.Y.'s YY850437C and Realtec's GN-51: UNROM with an outer bank.

    NES_2.0_Mapper_396.wiki: the outer register at $A000-$BFFF ($8000-$BFFF on
    submapper 3): D2-D0 PRG A19-A17, D6 (1), D5 (2, 3) or either (0) 1 for
    vertical mirroring. The inner register, every other address, D2-D0 the
    bank at $8000; the inner bank 7 is at $C000.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.submapper = image.board.submapper
        self.outer = self.inner = 0
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        self.map_prg(0, 16, self.outer << 3 | self.inner)
        self.map_prg(2, 16, self.outer << 3 | 7)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            return
        outer = address & 0xC000 == 0x8000 if self.submapper == 3 else address & 0xE000 == 0xA000
        if outer:
            self.outer = value & 7
            bits = {0: 0x60, 1: 0x40}.get(self.submapper, 0x20)
            self.set_mirroring(VERTICAL if value & bits else HORIZONTAL)
        else:
            self.inner = value & 7
        self._update()


class RetroUSB400(Banked):
    """Mapper 400: retroUSB's 8-BIT XMAS 2017, UNROM 512's Christmas lights as a multicart.

    NES_2.0_Mapper_400.wiki: $C000-$FFFF: D6-D5 the CHR-RAM bank, D2-D0 the
    inner bank at $8000 (7 at $C000). $7000 (mask $F83F): D7-D3 the outer
    bank at $8000; $7800 (mask $F800): the same at $C000 and D5 horizontal
    (the page's mark falls on D5). The LEDs at $8000-$BFFF and the LCD are
    not modelled. The page gives no power-on value; the outer at $C000
    powers on 31, the last, where a UNROM 512's reset code is.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.low_outer = 0
        self.high_outer = 0x1F
        self.inner = 0
        self._update()

    def _update(self) -> None:
        self.map_prg(0, 16, self.low_outer << 3 | self.inner & 7)
        self.map_prg(2, 16, self.high_outer << 3 | 7)
        self.map_chr(0, 8, (self.inner >> 5) & 3)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0xC000:
            self.inner = value
        elif address & 0xF83F == 0x7000:
            self.low_outer = value >> 3
        elif address & 0xF800 == 0x7800:
            self.high_outer = value >> 3
            self.set_mirroring(HORIZONTAL if value & 0x20 else VERTICAL)
        else:
            return
        self._update()


class DPCMCart409(Banked):
    """Mapper 409: retroUSB's DPCMcart: UNROM addressing 64 MiB by a 12-bit address latch.

    NES_2.0_Mapper_409.wiki: a write to $C000-$CFFF selects the bank at $8000
    from its A11-A0 (the game uses no other range, so no other is known);
    the last bank is fixed at $C000.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_chr(0, 8, 0)
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF000 == 0xC000:
            self.map_prg(0, 16, address & 0x0FFF)


class ImpactSoft471(Banked):
    """Mapper 471: Impact Soft's IM1 (Haratyler, Haraforce): mapper 201 with a scanline IRQ.

    NES_2.0_Mapper_471.wiki: a write to $8000-$FFFF selects, by A0, the 32 KiB
    PRG and 8 KiB CHR banks and acknowledges. Every fall of PPU A12 asserts
    /IRQ, unfiltered.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.a12 = 0
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.map_prg(0, 32, address & 1)
            self.map_chr(0, 8, address & 1)
            self.irq = False

    def ppu_address(self, address: int, t: int) -> None:
        a12 = (address >> 12) & 1
        if self.a12 and not a12:
            self.irq = True
        self.a12 = a12


class Maxivision493(Banked):
    """Mapper 493: the Maxivision 30-in-1 prototype: mapper 11 with an outer bank.

    NES_2.0_Mapper_493.wiki: $6000-$7FFF D3-D0 PRG and CHR A19-A16; $8000-$FFFF
    (bus conflicts) D0 PRG A15, D6-D4 CHR A15-A13. Vertical mirroring.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.outer = self.inner = 0
        self.set_mirroring(VERTICAL)
        self._update()

    def _update(self) -> None:
        self.map_prg(0, 32, self.outer << 1 | self.inner & 1)
        self.map_chr(0, 8, self.outer << 3 | (self.inner >> 4) & 7)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.inner = self.bus_conflict(address, value)
        elif address >= 0x6000:
            self.outer = value & 0x0F
        else:
            return
        self._update()


class LittleCom541(Banked):
    """Mapper 541: the LittleCom 160-in-1's address latch.

    NES_2.0_Mapper_541.wiki: a write to $C000-$FFFF latches A7-A2 as the 16 KiB
    bank, A1 1 for NROM-128 (0: NROM-256), A0 1 for vertical mirroring.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_chr(0, 8, 0)
        self._latch(0)

    def _latch(self, a: int) -> None:
        bank = (a >> 2) & 0x3F
        self.map_prg(0, 16, bank if a & 2 else bank & ~1)
        self.map_prg(2, 16, bank if a & 2 else bank | 1)
        self.set_mirroring(VERTICAL if a & 1 else HORIZONTAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0xC000:
            self._latch(address)


class NTDEC81(Banked):
    """Mapper 81: NTDEC's N715021 (Super Gun).

    INES_Mapper_081.wiki: a write to $8000-$FFFF latches A3-A2 as the 16 KiB
    bank at $8000 and A1-A0 as the 8 KiB CHR bank; the last bank is fixed.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.map_prg(0, 16, (address >> 2) & 3)
            self.map_chr(0, 8, address & 3)


class JY043(Banked):
    """Mapper 122: the JY043: 32 KiB of PRG and two 4 KiB CHR banks.

    INES_Mapper_122.wiki: writes to $8000-$FFFF, D2-D0 the 4 KiB bank at PPU
    $0000 (A0 clear) or $1000 (A0 set).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.map_chr(4 if address & 1 else 0, 4, value & 7)


class ResetMMC1(MMC1):
    """Mapper 374: reset-based MMC1 multicarts: each game an MMC1 in 128 KiB of PRG and of CHR.

    NES_2.0_Mapper_374.wiki: an interruption of M2 (:meth:`m2_gap`) steps the higher
    address lines. The page gives only that; the games sit in order.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = 0
        super().__init__(image, cpu_cycle_ticks)

    def m2_gap(self, t: int) -> None:
        self.outer = (self.outer + 1) % max(len(self.prg) // 0x20000, 1)
        self._update()

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        banks = 128 // size_kib
        super().map_prg(window, size_kib, bank % banks + self.outer * banks)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        banks = 128 // size_kib
        super().map_chr(window, size_kib, bank % banks + self.outer * banks)


class SB5013(MMC3):
    """Mappers 359 (SB-5013, GCL8050, 841242C: Super Boy multicarts) and 540 (UNL-82112C).

    NES_2.0_Mapper_359.wiki (mask $F003): $8000-$8003 8 KiB banks at $8000, $A000, $C000,
    $6000, the last of the outer bank at $E000; $9000 D5-D3 the 128 KiB outer
    PRG bank; $9001 D1-D0 its size (512, 256, ?, 128 KiB: masks $3F, $1F,
    $2F, $0F), D6 the CHR's (128, 256 KiB); $9002 the arrangement; $9003 D1-D0
    the 128 KiB outer CHR bank; $A000-$A003, $B000-$B003 the 1 KiB CHR banks.
    The IRQ: $C002 ``AME`` (auto, source, enable), $C003 D0 the enable unless
    A. M2 source: $C000/$C001 set the 16-bit counter's low and high bytes, which
    while enabled counts down and on reaching 0 asserts /IRQ. PA12 source:
    $C000 reloads and $C001 sets the latch, an MMC3's counter. With A, $C000
    disables and $C001 enables.

    540 (NES_2.0_Mapper_540.wiki) rewires the CHR lines for 2 KiB banks: $A000, $A001,
    $B002, $B003 at PPU $0000, $0800, $1000, $1800.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.two_kib = image.board.mapper == 540
        self.prg8 = [0, 0, 0, 0]
        self.chr1 = [0] * 8
        self.prg_outer = self.prg_size = self.chr_outer = self.chr_wide = 0
        self.a12_source = self.auto = False
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False

    def _bank(self, bank: int) -> int:
        mask = (0x3F, 0x1F, 0x2F, 0x0F)[self.prg_size]
        return ((self.prg_outer * 16) & ~mask) | bank & mask

    def _update(self) -> None:
        for window in range(3):
            self.map_prg(window, 8, self._bank(self.prg8[window]))
        self.map_prg(3, 8, self._bank(0xFF))
        if self.chr_writable:
            self.map_chr(0, 8, 0)
        elif self.two_kib:
            for window, register in enumerate((0, 1, 6, 7)):
                self.map_chr(window * 2, 2, self.chr1[register])
        else:
            mask = 0xFF if self.chr_wide else 0x7F
            for window in range(8):
                self.map_chr(window, 1, (self.chr_outer << 7) & ~mask | self.chr1[window] & mask)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            bank = self._bank(self.prg8[3])
            return self.prg[(bank * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def _enable(self, on: bool) -> None:
        self.irq_enabled = on
        if not on:
            self.irq = False

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0xF003
        if address < 0x8000:
            return
        if register < 0x8004:
            self.prg8[register & 3] = value
        elif register == 0x9000:
            self.prg_outer = (value >> 3) & 7
        elif register == 0x9001:
            self.prg_size, self.chr_wide = value & 3, value & 0x40
        elif register == 0x9002:
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
        elif register == 0x9003:
            self.chr_outer = value & 3
        elif 0xA000 <= register < 0xC000:
            self.chr1[((register >> 10) & 4) | register & 3] = value
        elif register == 0xC000:
            if self.a12_source:
                self.reload = True
            else:
                self.counter = (self.counter & 0xFF00) | value
            if self.auto:
                self._enable(False)
        elif register == 0xC001:
            if self.a12_source:
                self.latch = value
            else:
                self.counter = (self.counter & 0x00FF) | value << 8
            if self.auto:
                self._enable(True)
        elif register == 0xC002:
            self.auto, self.a12_source = bool(value & 4), bool(value & 2)
            self._enable(bool(value & 1))
        elif register == 0xC003 and not self.auto:
            self._enable(bool(value & 1))
        self._update()

    def m2(self, t: int) -> None:
        if not self.a12_source and self.irq_enabled and self.counter:
            self.counter -= 1
            if self.counter == 0:
                self.irq = True

    def ppu_address(self, address: int, t: int) -> None:
        if self.a12_source:
            super().ppu_address(address, t)
