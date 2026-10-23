"""MMC3 and its relatives (mapper 4): MMC6, MC-ACC, and the NEC and Sharp IRQs.

MMC3.wiki and MMC6.wiki (specification tier); judged by blargg's
``mmc3_test_2``, ``mmc3_test`` and ``mmc3_irq_tests`` and by Holy Mapperel
(docs/claims.md). Submappers (NES_2.0_submappers.wiki "004"):

- **4.0** Sharp MMC3, the "new" IRQ: an IRQ whenever a clock leaves the
  counter at 0, so a latch of 0 interrupts on every scanline.
- **4.1** MMC6: Sharp's IRQ, 1 KiB of RAM at $7000-$7FFF in two 512-byte
  halves with their own enables (contradiction C18: blargg's ``6-MMC6``
  expects NEC's IRQ).
- **4.2** MMC3C with the nametable arrangement hard-wired: $A000 does nothing.
- **4.3** MC-ACC: the counter is clocked by every eighth *fall* of A12, with
  no M2 filter, and interrupts like Sharp.
- **4.4** NEC MMC3, the "old" IRQ: only when a decrement or a reload takes a
  counter that was not 0, or a $C001 reload, to 0.

Names are behaviours, never chip letters (contradiction C17).

**The A12 filter** (MMC3.wiki "IRQ Specifics", from Furrtek's MMC3C
schematic): the counter is clocked by a rise of PPU A12 "after the line has
remained low for three falling edges of M2". The connector gives every
address phase with its master-clock time, and the CPU cycles end (M2 falls)
at the multiples of ``cpu_cycle_ticks``, so the rise counts when the third
multiple after A12 fell is no later than the rise. The pathological
consecutive-$C001 behaviour (blargg's readme) is not modelled; no game is
known to need it and the wiki says no emulator does.
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage


class MMC3(Banked):
    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        submapper = image.board.submapper
        self.nec_irq = submapper == 4
        self.fixed_mirroring = submapper == 2
        # Power-on values are unspecified (MMC3.wiki: the reset vector must be
        # in $E000-$FFFF); zero here, with PRG-RAM enabled and writable, as
        # games that never write $A001 expect.
        self.bank_select = 0
        self.registers = [0] * 8
        self.latch = 0
        self.counter = 0
        self.reload = False
        self.irq_enabled = False
        self.a12 = 0
        self.a12_ready = 0  # the time of A12's third M2 fall while low
        self._update()

    # -- the CPU side ----------------------------------------------------

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        odd = address & 1
        region = address & 0xE000
        if region == 0x8000:
            if odd:
                self.registers[self.bank_select & 7] = value
            else:
                self.bank_select = value
            self._update()
        elif region == 0xA000:
            if odd:
                self.ram_protect(value)
            elif not self.fixed_mirroring and not self.four_screen:
                self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        elif region == 0xC000:
            if odd:
                self.counter = 0
                self.reload = True
            else:
                self.latch = value
        elif odd:
            self.irq_enabled = True
        else:
            self.irq_enabled = False
            self.irq = False

    def ram_protect(self, value: int) -> None:
        """$A001: D7 enables PRG-RAM (open bus when clear), D6 denies writes."""
        self.prg_ram_enabled = bool(self.prg_ram) and bool(value & 0x80)
        self.prg_ram_writable = not value & 0x40

    def _update(self) -> None:
        r = self.registers
        second_last = len(self.prg) // 0x2000 - 2
        if self.bank_select & 0x40:
            self.map_prg(0, 8, second_last)
            self.map_prg(2, 8, r[6])
        else:
            self.map_prg(0, 8, r[6])
            self.map_prg(2, 8, second_last)
        self.map_prg(1, 8, r[7])
        self.map_prg(3, 8, second_last + 1)
        low = 4 if self.bank_select & 0x80 else 0  # CHR A12 inversion
        self.map_chr(low, 2, r[0] >> 1)
        self.map_chr(low + 2, 2, r[1] >> 1)
        high = low ^ 4
        for i in range(4):
            self.map_chr(high + i, 1, r[2 + i])

    # -- the PPU side: the scanline counter ------------------------------

    def ppu_address(self, address: int, t: int) -> None:
        if address & 0x1000:
            if not self.a12:
                self.a12 = 1
                if t >= self.a12_ready:
                    self.clock_counter()
        elif self.a12:
            self.a12 = 0
            ticks = self.cpu_cycle_ticks
            self.a12_ready = (t // ticks + 3) * ticks

    def clock_counter(self) -> None:
        was = self.counter
        reload = self.reload
        if was == 0 or reload:
            self.counter = self.latch
        else:
            self.counter = was - 1
        self.reload = False
        if self.counter == 0 and self.irq_enabled and (not self.nec_irq or was or reload):
            self.irq = True


class MCACC(MMC3):
    """Submapper 4.3: the counter is clocked on every eighth fall of A12, unfiltered.

    The prescaler's phase at power-on and whether a register write resets it
    are unknown (the forum's MC-ACC test results); it starts at 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.prescaler = 0
        super().__init__(image, cpu_cycle_ticks)

    def ppu_address(self, address: int, t: int) -> None:
        if address & 0x1000:
            self.a12 = 1
        elif self.a12:
            self.a12 = 0
            self.prescaler = (self.prescaler + 1) & 7
            if not self.prescaler:
                self.clock_counter()


class MMC6(MMC3):
    """Submapper 4.1: 1 KiB of PRG-RAM at $7000-$7FFF, two halves with their own enables.

    MMC6.wiki: $8000 D5 enables the RAM (and while it is clear, $A001 is held
    at 0); $A001 D5/D4 enable reading/writing $7000-$71FF (mirrored through
    the half), D7/D6 the same for $7200-$73FF. Writes need the half readable
    too. With neither half readable the window is open bus; with one, the
    other reads 0. $6000-$6FFF is open bus.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram = bytearray(0x400)
        self.protect = 0

    def ram_protect(self, value: int) -> None:
        if self.bank_select & 0x20:
            self.protect = value

    def _update(self) -> None:
        super()._update()
        if not self.bank_select & 0x20:
            self.protect = 0

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return self.prg[self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)]
        if address < 0x7000:
            return None
        protect = self.protect
        if not protect & 0xA0:
            return None
        high = address & 0x200
        if not protect & (0x80 if high else 0x20):
            return 0
        return self.prg_ram[address & 0x3FF]

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            super().cpu_write(address, value, t)
            return
        if address < 0x7000:
            return
        enables = (self.protect >> (6 if address & 0x200 else 4)) & 3
        if enables == 3:  # readable and writable
            self.prg_ram[address & 0x3FF] = value

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg_ram) if self.battery else None


class TxSROM(MMC3):
    """Mapper 118 (TKSROM, TLSROM): CHR A17 drives CIRAM A10, so CHR banking picks the nametables.

    INES_Mapper_118.wiki: the MMC3's CHR bank circuit ignores PPU A13, so a
    nametable fetch at $2000-$2FFF selects the bank register of the matching
    1 KiB slot of $0000-$0FFF, and that register's D7 is CIRAM A10. With CHR
    A12 inversion off, $0000-$0FFF is the two 2 KiB registers R0 and R1; with
    it on, the four 1 KiB registers R2-R5. $A000 does nothing.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.nametable_a10 = [0, 0, 0, 0]
        super().__init__(image, cpu_cycle_ticks)
        self.fixed_mirroring = True

    def _update(self) -> None:
        super()._update()
        r = self.registers
        banks = r[2:6] if self.bank_select & 0x80 else [r[0], r[0], r[1], r[1]]
        self.nametable_a10 = [bank >> 7 for bank in banks]

    def ciram_a10(self, address: int) -> int | None:
        return self.nametable_a10[(address >> 10) & 3]


class AA6023(MMC3):
    """Mapper 268, submappers 0/1 and 8/9: the AA6023 (SMD132/133) MMC3 clone's outer banks.

    NES_2.0_Mapper_268.wiki; the licensed dumps are modern reissues
    (Retro-Bit, Limited Run Games, Pixel Heart). Six registers at $6000 (even
    submapper) or $5000 (odd), mask $F007, alongside any PRG-RAM. The
    0 register's D6 and the 1 register's D7-D5 choose, for PRG A17-A20, the
    MMC3's bit or a fixed offset; the offsets come from D2-D0 of 0 and D4 of
    1, with A21-A24 from 1's D3-D2 and 0's D5-D4 (submappers 0/1 only). 0's
    D7 and D3 do the same for CHR A17. 3's D4 is GNROM mode: PRG A16-A14
    from its D3-D1 (A14 from CPU A14 when 1's D1 asks for 32 KiB) and CHR
    A16-A13 from 2's D3-D0. 3's D7 locks every register but 2 while in MMC3
    mode. The IRQ is NEC's (the wiki's notes). Not modelled: the "weird"
    modes (3's D6), mixed CHR-ROM/RAM (register 4), mega-UNROM (5), and the
    other submappers' PCBs, which no licensed dump uses.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        submapper = image.board.submapper
        self.outer_base = 0x5000 if submapper & 1 else 0x6000
        self.wide = submapper < 8  # 0/1: PRG A21-A24 offsets
        self.outer = [0] * 6
        super().__init__(image, cpu_cycle_ticks)
        self.nec_irq = True

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if self.outer_base <= address < self.outer_base + 0x1000:
            register = address & 7
            locked = self.outer[3] & 0x80 and not self.outer[3] & 0x10
            if register < 6 and (not locked or register == 2):
                if register == 2 and self.outer[2] & 0x80:
                    value = (self.outer[2] & 0xF0) | (value & 0x0F)
                self.outer[register] = value
                self._update()
        super().cpu_write(address, value, t)

    def _prg_bank(self, bank: int) -> int:
        o0, o1 = self.outer[0], self.outer[1]
        mmc3 = 0x0F
        mmc3 |= 0 if o0 & 0x40 else 0x10  # A17
        mmc3 |= 0 if o1 & 0x80 else 0x20  # A18
        mmc3 |= 0x40 if o1 & 0x40 else 0  # A19
        mmc3 |= 0x80 if o1 & 0x20 else 0  # A20
        offset = (o0 & 7) << 4 | (o1 & 0x10) << 3
        if self.wide:
            offset |= ((o1 >> 2) & 1) << 8 | ((o1 >> 3) & 1) << 9 | ((o0 >> 4) & 3) << 10
        return (bank & mmc3) | (offset & ~mmc3)

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        o1, o3 = self.outer[1], self.outer[3]
        bank = self._prg_bank(bank)
        if o3 & 0x10:  # GNROM mode: A16-A14 from register 3, A13 from the CPU
            bank &= ~0x0F
            if o1 & 0x02:  # 32 KiB
                bank |= ((o3 >> 2) & 3) << 2 | (window & 3)
            else:
                bank |= ((o3 >> 1) & 7) << 1 | (window & 1)
        super().map_prg(window, size_kib, bank)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        o0, o3 = self.outer[0], self.outer[3]
        for i in range(size_kib):
            one = bank * size_kib + i
            if o0 & 0x80:
                one = (one & ~0x80) | (o0 & 8) << 4
            if o3 & 0x10:
                one = (one & ~0x7F) | (self.outer[2] & 0x0F) << 3 | ((window + i) & 7)
            super().map_chr(window + i, 1, one)


def mmc3_for(image: RomImage, cpu_cycle_ticks: int) -> MMC3:
    """Mapper 4's board by submapper."""
    submapper = image.board.submapper
    if submapper == 1:
        return MMC6(image, cpu_cycle_ticks)
    if submapper == 3:
        return MCACC(image, cpu_cycle_ticks)
    return MMC3(image, cpu_cycle_ticks)
