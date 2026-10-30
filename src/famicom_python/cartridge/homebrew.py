"""Homebrew boards: Action 53 (28), the NSF subset (31), GTROM (111), Magic Floor (218) and
Drip (284).

Each from its NESdev wiki page (pinned in scripts/pinned_files.json) and judged by
its own community test ROMs (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .flash import SST39SF040
from .ines import RomImage


class NSF31(Banked):
    """Mapper 31: PRG-ROM in eight 4 KiB slots at $8000-$FFFF, as an NSF banks it.

    INES_Mapper_031.wiki: a write to $5000-$5FFF selects the 4 KiB bank of slot
    A2-A0 ($5FF8-$5FFF canonically); the register for $F000-$FFFF powers on as
    $FF, the last bank, and reset leaves it. No CHR banking (8 KiB CHR-RAM, or
    ROM), no mirroring control. The other slots' power-on banks are not given:
    0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.slots = [0] * 8  # byte offsets into PRG of each 4 KiB slot
        self._select(7, 0xFF)
        self.map_chr(0, 8, 0)

    def _select(self, slot: int, bank: int) -> None:
        self.slots[slot] = (bank << 12) % len(self.prg)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return self.prg[self.slots[(address >> 12) & 7] + (address & 0x0FFF)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            self._select(address & 7, value)
            return
        super().cpu_write(address, value, t)


class Action53(Banked):
    """Mapper 28: Damian Yerrick's multicart mapper, which simulates NROM, CNROM,
    UxROM, BNROM and AxROM (Action_53_mapper.wiki).

    $5000-$5FFF selects a register (D7 supervisor, D0 which), $8000-$FFFF writes
    it; no bus conflicts. $00: CHR-RAM bank (D1-D0) and, in a 1-screen mode,
    the screen (D4); $01: the inner PRG bank (and D4 as $00's); $80: the outer
    bank size (D5-D4), PRG mode (D3-D2) and mirroring (D1-D0: 1-screen lower,
    upper, vertical, horizontal); $81: the outer PRG bank. 32 KiB of CHR-RAM,
    as the Action 53 boards have (an iNES 1 header says 8). Power-on state
    unspecified but for the last 16 KiB at $C000: the wiki's suggested boot
    state, $81 = $FF and $80 = $02 (32 KiB mode, the last bank). Reset leaves it.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        if self.chr_writable and len(self.chr) < 0x8000:
            self.chr = bytearray(0x8000)
        self.select = 0
        self.regs = {0x00: 0, 0x01: 0, 0x80: 0x02, 0x81: 0xFF}
        self._update()

    def _update(self) -> None:
        regs = self.regs
        mode = regs[0x80]
        size, prg_mode, mirroring = (mode >> 4) & 3, (mode >> 2) & 3, mode & 3
        outer, inner = regs[0x81], regs[0x01]
        if prg_mode < 2:  # 32 KiB: the low outer bits give way to inner ones
            mask = (1 << size) - 1
            bank32 = (outer & ~mask) | (inner & mask)
            low, high = bank32 << 1, (bank32 << 1) | 1
        else:  # UxROM: one 16 KiB half switchable, the other fixed to the outer bank
            mask = (2 << size) - 1
            switched = ((outer << 1) & ~mask) | (inner & mask)
            if prg_mode == 2:  # fixed $8000 (mapper 180)
                low, high = outer << 1, switched
            else:  # fixed $C000 (mapper 2)
                low, high = switched, (outer << 1) | 1
        self.map_prg(0, 16, low)
        self.map_prg(2, 16, high)
        self.map_chr(0, 8, regs[0x00] & 3)
        self.set_mirroring((SCREEN_A, SCREEN_B, VERTICAL, HORIZONTAL)[mirroring])

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x5000 <= address < 0x6000:
            self.select = value & 0x81
            return
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = self.select
        self.regs[register] = value
        if register in (0x00, 0x01) and self.regs[0x80] & 2 == 0:
            # A 1-screen mode: D4 is the screen, as AxROM's (the wiki's "M").
            self.regs[0x80] = (self.regs[0x80] & ~1) | ((value >> 4) & 1)
        self._update()


class GTROM(Banked):
    """Mapper 111: Membler Industries' Cheapocabra (GTROM.wiki).

    One 74377 register at $5000-$5FFF and $7000-$7FFF (latched as M2 falls
    when /ROMSEL, A14 and A12 are high), ``GRNCPPPP``: the 32 KiB PRG bank,
    the 8 KiB CHR-RAM bank, the 8 KiB nametable bank, and the red and green
    LEDs (taken, not shown). The latch clocks on reads too, so a read stores
    whatever is on the data bus (:meth:`read_data`). No bus conflicts: every
    write to $8000-$FFFF goes to the SST39SF040, at the selected bank and
    A14-A0 (its $5555 is $D555 in any bank).

    The board's 32 KiB of RAM: $0000-$1FFF of the PPU sees its first or second
    8 KiB, $2000-$3EFF its third or fourth, unmirrored (four screens, and
    $3000-$3EFF is RAM of its own: the wiki's "bonus RAM"); CIRAM is never
    enabled. The register's power-on state is not given: 0 here. The PRG is
    flash, so it is the save (:meth:`battery_ram`) whatever the header's
    battery bit says.
    """

    latches_reads = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg = bytearray(image.prg)
        self.flash = SST39SF040(self.prg)
        self.chr = bytearray(0x8000)
        self.chr_writable = True
        self.register = 0
        self.nametables = 0x4000  # where the selected nametable page begins
        self._latch(0)

    def _latch(self, value: int) -> None:
        self.register = value
        self.map_prg(0, 32, value & 0x0F)
        self.map_chr(0, 8, (value >> 4) & 1)
        self.nametables = 0x4000 + ((value >> 5) & 1) * 0x2000

    def _flash_offset(self, address: int) -> int:
        return ((self.register & 0x0F) << 15 | (address & 0x7FFF)) % len(self.prg)

    def cpu_read(self, address: int, t: int) -> int | None:
        if self.flash.id_mode and address >= 0x8000:
            return self.flash.read(self._flash_offset(address))
        return super().cpu_read(address, t)

    def read_data(self, address: int, value: int, t: int) -> None:
        if address & 0x5000 == 0x5000 and address < 0x8000:
            self._latch(value)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.flash.write(self._flash_offset(address), value)
        elif address & 0x5000 == 0x5000:
            self._latch(value)

    def ciram_a10(self, address: int) -> int | None:
        return None

    def ppu_read(self, address: int, t: int) -> int | None:
        if address >= 0x2000:
            return self.chr[self.nametables + (address & 0x1FFF)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x2000:
            self.chr[self.nametables + (address & 0x1FFF)] = value
            return
        super().ppu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg)

    def _restore(self, data: bytes) -> None:
        self.prg[:] = data


class MagicFloor(Banked):
    """Mapper 218 (Magic Floor, Starfight): no CHR memory: the console's CIRAM is the CHR-RAM.

    INES_Mapper_218.wiki: CIRAM is always selected and its A10 wired to PPU
    A10, A11, A12 or A13 (the header: vertical, horizontal, and with the
    four-screen bit A12 or A13 for its two one-screen layouts), so pattern
    tables and nametables share the 2 KiB. The connector does not reach
    CIRAM for pattern addresses, so this board disables it and answers with
    a 2 KiB RAM of its own, which behaves identically (nothing else can
    reach CIRAM). PRG: up to 32 KiB, unbanked.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        flags6 = image.header[6] if len(image.header) > 6 else 0
        if flags6 & 8:
            self.a10_line = 13 if flags6 & 1 else 12
        else:
            self.a10_line = 10 if board.mirroring == "V" else 11
        self.four_screen = False
        self.ciram = bytearray(0x800)
        self.prg = self.prg * (0x8000 // len(self.prg))  # Magic Floor is 4 KiB
        for window in range(4):
            self.map_prg(window, 8, window)

    def _index(self, address: int) -> int:
        return ((address >> self.a10_line) & 1) << 10 | (address & 0x3FF)

    def ciram_a10(self, address: int) -> int | None:
        return None

    def ppu_read(self, address: int, t: int) -> int | None:
        return self.ciram[self._index(address)]

    def ppu_write(self, address: int, value: int, t: int) -> None:
        self.ciram[self._index(address)] = value


class DripGame(Banked):
    """NES 2.0 mapper 284: Quietust's FPGA for the port of Drip (UNIF_UNL-DripGame.wiki).

    $4800-$4FFF reads the status ($64: ready; D7 the DIP switch, 0 here);
    $5000/$5800 the sound channels' buffer status (empty here). Writes to
    $8000-$BFFF (low nibble): 0-7 the two sound channels (taken; the sample
    playback is not modelled, so they stay silent and empty), 8/9 the IRQ
    reload's low and high bits (9's D7 enables; 9 acknowledges and reloads),
    A ``....SAMM``: the mirroring (vertical, horizontal, one-screen A, B),
    the extended attributes (A), PRG-RAM writes (S); B the 16 KiB PRG bank at
    $8000 (the last fixed); C-F the 2 KiB CHR banks. $C000-$FFFF writes the
    extended attribute table (two 1 KiB halves, by the nametable page): with
    A set, a tile's attribute is its entry's D1-D0. The counter counts M2
    cycles down and, at expiry, asserts /IRQ and stops.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.control = 0
        self.reload = self.counter = 0
        self.counting = False
        self.ext = bytearray(0x800)
        self.last_tile = 0  # CIRAM index of the last nametable fetch
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.prg_ram_writable = False

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x4800 <= address < 0x5000:
            return 0x64
        if 0x5000 <= address < 0x6000:
            return 0x40 | 0x3F << 8  # buffer empty, not full
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0xC000:
            self.ext[address & 0x7FF] = value & 3
            return
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = address & 0x0F
        if register == 8:
            self.reload = (self.reload & 0x7F00) | value
        elif register == 9:
            self.reload = (self.reload & 0xFF) | (value & 0x7F) << 8
            self.counter = self.reload
            self.counting = bool(value & 0x80)
            self.irq = False
        elif register == 0x0A:
            self.control = value
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
            self.prg_ram_writable = bool(value & 8)
        elif register == 0x0B:
            self.map_prg(0, 16, value & 0x0F)
        elif register >= 0x0C:
            self.map_chr((register - 0x0C) * 2, 2, value & 0x0F)

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter -= 1
            if self.counter < 0:
                self.counter = 0
                self.counting = False
                self.irq = True

    def ciram_a10(self, address: int) -> int | None:
        a10 = super().ciram_a10(address)
        if address & 0x3FF >= 0x3C0:
            if self.control & 4:
                return None
        elif a10 is not None:
            self.last_tile = a10 << 10 | (address & 0x3FF)
        return a10

    def ppu_read(self, address: int, t: int) -> int | None:
        if address >= 0x2000 and self.control & 4:
            return self.ext[self.last_tile] * 0x55
        return super().ppu_read(address, t)


class SealieRET(Banked):
    """Mapper 29: Sealie Computing's RET-CUFROM (Glider): UNROM-like with 32 KiB of CHR-RAM.

    INES_Mapper_029.wiki: a write to $8000-$FFFF ``...PPPCC``: the 16 KiB PRG
    bank at $8000 (the last fixed) and the 8 KiB CHR-RAM bank; no bus
    conflicts; 8 KiB of WRAM; vertical mirroring. (The CopyNES reflashing
    path through EXP0 is not on the connector.) Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr = bytearray(0x8000)
        self.chr_writable = True
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self._latch(0)

    def _latch(self, value: int) -> None:
        self.map_prg(0, 16, (value >> 2) & 7)
        self.map_chr(0, 8, value & 3)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(value)
        else:
            super().cpu_write(address, value, t)


class BATMAPSRR(Banked):
    """Mapper 413 (Super Russian Roulette): BATMAP-SRR-X, a CPLD and a speech ROM.

    MAME's batlab.cpp (BSD-3); the wiki names only the game. $5000-$5FFF ROM at $1000; $6000,
    $8000 and $A000 8 KiB banks; $D000-$FFFF ROM at $7000; CHR 4 KiB banked at
    $0000, bank $3D at $1000. $E000-$FFFF: D7-D6 pick the $6000, $8000, $A000 or
    CHR bank, D5-D0 the bank. $8000 the counter's latch, $9000 clears the
    counter, $A000 disables and acknowledges, $B000 enables: an MMC3-like IRQ,
    on PPU A12 here as MAME's hblank approximates. $C000: D7 shifts into the
    pointer into the Misc ROM of DPCM; reads of $4800-$4FFF and $C000-$CFFF
    give its next byte and step it. $D000 is unexplained, stored nowhere.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.speech = image.misc
        self.pointer = 0
        self.bank6000 = 0
        self.counter = self.latch = 0
        self.irq_enabled = False
        self.a12 = self.a12_ready = 0
        self.prg_ram_enabled = False
        self.map_prg(2, 8, 3)
        self.map_prg(3, 8, 4)
        self.map_chr(0, 4, 0)
        self.map_chr(4, 4, 0x3D)

    def _speech_byte(self) -> int:
        self.pointer &= len(self.speech) - 1
        value = self.speech[self.pointer]
        self.pointer += 1
        return value

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x4800 <= address < 0x5000 or 0xC000 <= address < 0xD000:
            return self._speech_byte()
        if 0x5000 <= address < 0x6000:
            return self.prg[address - 0x4000]
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        region = address & 0xF000
        if region == 0x8000:
            self.latch = value
        elif region == 0x9000:
            self.counter = 0
        elif region == 0xA000:
            self.irq_enabled = self.irq = False
        elif region == 0xB000:
            self.irq_enabled = True
        elif region == 0xC000:
            self.pointer = self.pointer << 1 | value >> 7
        elif region >= 0xE000:
            kind, bank = value >> 6, value & 0x3F
            if kind == 0:
                self.bank6000 = bank
            elif kind == 3:
                self.map_chr(0, 4, bank)
            else:
                self.map_prg(kind - 1, 8, bank)

    def ppu_address(self, address: int, t: int) -> None:
        if address & 0x1000:
            if not self.a12:
                self.a12 = 1
                if t >= self.a12_ready:
                    self.counter = self.counter - 1 if self.counter else self.latch
                    if not self.counter and self.irq_enabled:
                        self.irq = True
        elif self.a12:
            self.a12 = 0
            self.a12_ready = (t // self.cpu_cycle_ticks + 3) * self.cpu_cycle_ticks
