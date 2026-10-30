"""Unlicensed North American discrete boards: Color Dreams (11), Camerica/Codemasters (71,
232) and AVE's NINA-03/06 (79) with HES's multicart extension (113).

Each from its NESdev wiki page (pinned in scripts/pinned_files.json). No judge
ROM exists for any of them; the claims rest on sweeps against Mesen2, a
detector (docs/claims.md). The lockout-defeat circuits (charge pumps, CIC
stun latches) have nothing to do on an emulated console and are left out.
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .ines import RomImage


class ColorDreams(Banked):
    """Mapper 11: a 74377 latch: ``CCCCLLPP``, the 32 KiB PRG and 8 KiB CHR banks.

    Color_Dreams.wiki: D3-D2 drive the lockout defeat. Submapper 2 has
    AND-type bus conflicts (every commercial game); 1 has none; 0 says
    nothing and gets none, as the wiki advises. Power-on banks unspecified:
    0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.bus_conflicts = image.board.submapper == 2
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if self.bus_conflicts:
            value = self.bus_conflict(address, value)
        self.map_prg(0, 32, value & 3)
        self.map_chr(0, 8, value >> 4)


class Camerica(Banked):
    """Mappers 71 (BF9093/BF9097) and 232 (BF9096, the Quattro multicarts): UNROM-like.

    INES_Mapper_071.wiki, _232.wiki; no bus conflicts, 8 KiB CHR-RAM. A write
    to $C000-$FFFF selects the 16 KiB bank at $8000, the last fixed.
    71.1 (Fire Hawk): $9000-$9FFF D4 selects the one-screen nametable. 71.0
    says nothing, and some dumps of Fire Hawk carry it, so the arrangement
    stays hard-wired until the first write to $9000-$9FFF (the wiki's FCEUX
    rule: other games write $8000, never $9000). 232: $8000-$BFFF D4-D3
    select a 64 KiB outer bank (swapped on 232.1, the Aladdin Deck Enhancer),
    the inner bank D1-D0, and $C000 is the outer bank's last 16 KiB. Power-on
    banks unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        self.quattro = board.mapper == 232
        self.aladdin = self.quattro and board.submapper == 1
        self.outer = 0
        self.inner = 0
        if board.mapper == 71 and board.submapper == 1:
            self.set_mirroring(SCREEN_A)
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        if self.quattro:
            self.map_prg(0, 16, self.outer << 2 | self.inner & 3)
            self.map_prg(2, 16, self.outer << 2 | 3)
        else:
            self.map_prg(0, 16, self.inner)
            self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        if address >= 0xC000:
            self.inner = value & 0x0F
        elif self.quattro:
            outer = (value >> 3) & 3
            self.outer = (outer >> 1) | (outer & 1) << 1 if self.aladdin else outer
        elif address & 0xF000 == 0x9000:
            self.set_mirroring(SCREEN_B if value & 0x10 else SCREEN_A)
        self._update()


class NINA03(Banked):
    """Mappers 79 (AVE NINA-03/06) and 113 (HES NTD-8), the register at $4100-$5FFF.

    NINA-003-006.wiki, INES_Mapper_113.wiki: the register answers when A14 is
    high, A15 and A13 low and A8 high ($4100-$41FF, $4300-$43FF, ... $5Fxx).
    79: ``....PCCC``, the 32 KiB PRG bank and the 8 KiB CHR bank. 113:
    ``MCPPPCCC``: PRG from D5-D3, CHR from D6 and D2-D0, and the arrangement
    (0 horizontal, 1 vertical). Power-on banks unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.multicart = image.board.mapper == 113
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE100 != 0x4100:
            super().cpu_write(address, value, t)
            return
        if self.multicart:
            self.map_prg(0, 32, (value >> 3) & 7)
            self.map_chr(0, 8, (value >> 3) & 8 | value & 7)
            self.set_mirroring(VERTICAL if value & 0x80 else HORIZONTAL)
        else:
            self.map_prg(0, 32, (value >> 3) & 1)
            self.map_chr(0, 8, value & 7)


class Racermate(Banked):
    """Mapper 168: Racermate Challenge II: UNROM with 64 KiB of CHR-RAM in 4 KiB banks.

    INES_Mapper_168.wiki: $8000-$BFFF ``PP..CCCC``: the 16 KiB PRG bank at
    $8000 (the last fixed) and the 4 KiB CHR-RAM bank at PPU $1000 ($0000 is
    bank 0); $C000-$FFFF D2 (the reworked boards): set, the counter holds at
    0 and /IRQ is acknowledged; clear, it counts M2 cycles, its 1024s bit
    driving /IRQ; its fall to 0 clears the RAM protection. The battery half
    (banks 8-15) is the save; the protection (set at power loss: reads open
    bus, writes ignored there) starts set. The exercise bike is not modelled.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr = bytearray(0x10000)
        self.chr_writable = True
        self.held = False
        self.protected = True
        self.counter = 0
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self.map_chr(0, 4, 0)
        self.map_chr(4, 4, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x8000 <= address < 0xC000:
            self.map_prg(0, 16, value >> 6)
            self.map_chr(4, 4, value & 0x0F)
        elif address >= 0xC000:
            held = bool(value & 4)
            if self.held and not held:
                self.protected = False
            self.held = held
            if held:
                self.counter = 0
                self.irq = False
        else:
            super().cpu_write(address, value, t)

    def m2(self, t: int) -> None:
        if not self.held:
            self.counter = (self.counter + 1) & 0x7FF
            self.irq = bool(self.counter & 0x400)

    def _battery_bank(self, address: int) -> bool:
        return self.chr_offsets[address >> 10] >= 0x8000

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000 and self.protected and self._battery_bank(address):
            return None
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000 and self.protected and self._battery_bank(address):
            return
        super().ppu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.chr[0x8000:])

    def _restore(self, data: bytes) -> None:
        self.chr[0x8000:] = data


class Action52(Banked):
    """Mapper 228: Active Enterprises' Action 52 and Cheetahmen II.

    INES_Mapper_228.wiki: the address of a write to $8000-$FFFF ``..MHHPPPPPS.CCCC``
    and its data's D1-D0: the 8 KiB CHR bank (CCCC then D1-D0), the 16 KiB PRG
    bank PPPPP of 512 KiB chip HH (S set: mirrored; clear: the even/odd pair),
    M the mirroring (0 vertical, 1 horizontal). Action 52's file holds chips
    0, 1 and 3; chip 2 does not exist and reads open bus. The rumoured 4x4
    bits of RAM at $4020 are on neither cartridge (the wiki) and left out.
    Power-on latch 0 (the games expect it).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.three_chips = len(self.prg) == 0x180000
        self.open_bus = False
        self._latch(0, 0)

    def _latch(self, address: int, value: int) -> None:
        chip, page = (address >> 11) & 3, (address >> 6) & 0x1F
        self.open_bus = self.three_chips and chip == 2
        if self.three_chips and chip == 3:
            chip = 2
        bank = chip << 5 | page
        if address & 0x20:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, bank)
        else:
            self.map_prg(0, 16, bank & ~1)
            self.map_prg(2, 16, bank | 1)
        self.map_chr(0, 8, (address & 0x0F) << 2 | value & 3)
        self.set_mirroring(HORIZONTAL if address & 0x2000 else VERTICAL)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000 and self.open_bus:
            return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self._latch(address, value)
        else:
            super().cpu_write(address, value, t)


class DeathRace(ColorDreams):
    """Mapper 144 (Death Race): a Color Dreams board where the ROM's D0 always wins the conflict.

    INES_Mapper_144.wiki: a 300 ohm resistor on CPU D0 makes the latched value
    ROM AND (written OR 1).
    """

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        rom = self.prg[self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)]
        value = rom & (value | 1)
        self.map_prg(0, 32, value & 3)
        self.map_chr(0, 8, value >> 4)


class Caltron41(Banked):
    """Mapper 41 (Caltron 6-in-1): an outer register in the address of $6000-$67FF writes.

    INES_Mapper_041.wiki: $6000-$67FF ``..MCCEPP``-style address bits: the 32
    KiB PRG bank (A2-A0), E (A2: banks 4-7) enabling the inner CHR register,
    the 32 KiB outer CHR bank (A4-A3), the mirroring (A5: 0 vertical);
    $8000-$FFFF (AND-type bus conflicts), while enabled: D1-D0 the inner 8
    KiB CHR bank. Power-on and reset clear both.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.outer = self.inner = 0
        self._update()

    def _update(self) -> None:
        self.map_prg(0, 32, self.outer & 7)
        self.map_chr(0, 8, ((self.outer >> 3) & 3) << 2 | self.inner & 3)
        self.set_mirroring(HORIZONTAL if self.outer & 0x20 else VERTICAL)

    def m2_gap(self, t: int) -> None:
        self.outer = self.inner = 0
        self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x6800:
            self.outer = address & 0x3F
            self._update()
        elif address >= 0x8000 and self.outer & 4:
            self.inner = self.bus_conflict(address, value)
            self._update()


class BitCorp38(Banked):
    """Mapper 38 (Bit Corp.'s Crime Busters): GNROM with the register at $7000-$7FFF.

    INES_Mapper_038.wiki ``....CCPP``: the 32 KiB PRG and 8 KiB CHR banks.
    Not modelled: the board's likely accidental copy at $F000-$FFFF (decoded
    while M2 is low), which well-behaved code does not touch.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x7000 <= address < 0x8000:
            self.map_prg(0, 32, value & 3)
            self.map_chr(0, 8, (value >> 2) & 3)


class NINA08(Banked):
    """NES 2.0 mapper 487: AVE's NINA-08 (the unreleased Maxivision 30-in-1).

    NES_2.0_Mapper_487.wiki: $4180 (A14 high, A13 low, A8 and A7 set)
    ``NMCBBBBb``: the outer bank (PRG/CHR A19-A15, b only with M clear), C
    the chips and inner register (0: the first 512 KiB, NINA-03's register at
    $4100; 1: the next 1 MiB, Color Dreams' at $8000), M 64 KiB inner banks,
    N the mirroring (0 vertical). NINA-03 register ``....PcCC`` and Color
    Dreams register ``.cCC...P``: CHR A14-A13, and with M, CHR A15 (c) and
    PRG A15 (P). Only the selected inner register answers. Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.outer = 0
        self.inner_prg = self.inner_chr = 0
        self._update()

    def _update(self) -> None:
        o = self.outer
        big = o & 0x40
        bits = o & (0x1F if o & 0x20 else 0x0F)  # A15-A19 (A19 only past the first chip)
        base32 = bits & ~1 if big else bits  # in 32 KiB units
        if o & 0x20:
            base32 += 16  # the second and third chips follow the first 512 KiB
        prg32 = base32 | (self.inner_prg & 1 if big else 0)
        chr8 = base32 << 2 | self.inner_chr & (7 if big else 3)
        self.map_prg(0, 32, prg32)
        self.map_chr(0, 8, chr8)
        self.set_mirroring(HORIZONTAL if o & 0x80 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE180 == 0x4180:
            self.outer = value
        elif address & 0xE180 == 0x4100 and not self.outer & 0x20:
            self.inner_prg, self.inner_chr = (value >> 3) & 1, value & 7
        elif address >= 0x8000 and self.outer & 0x20:
            self.inner_prg, self.inner_chr = value & 1, (value >> 4) & 7
        else:
            super().cpu_write(address, value, t)
            return
        self._update()


class Pegasus104(Banked):
    """Mapper 104 (Pegasus 5-in-1 / Golden Five: five Codemasters games).

    PEGASUS_5_IN_1.wiki: $8000-$BFFF ``....wPPP``: the 256 KiB game (w
    write-protects the register); $C000-$FFFF D3-D0 the inner 16 KiB bank
    at $8000, $C000 being the game's last. Cleared at power-up only (an RC
    circuit; a reset leaves them, and the copy protection relies on the
    slow RC: not modelled, the registers take writes at once).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.outer = self.inner = 0
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        game = self.outer & 7
        self.map_prg(0, 16, game << 4 | self.inner)
        self.map_prg(2, 16, game << 4 | 0x0F)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x8000 <= address < 0xC000:
            if not self.outer & 8:
                self.outer = value & 0x0F
        elif address >= 0xC000:
            self.inner = value & 0x0F
        else:
            super().cpu_write(address, value, t)
            return
        self._update()


class RumbleStation46(Banked):
    """Mapper 46 (Rumble Station 15-in-1): Color Dreams inside 64 KiB outer banks.

    INES_Mapper_046.wiki: $6000-$7FFF ``CCCCPPPP`` the high CHR and PRG bits;
    $8000-$FFFF ``.CCC...P`` the low ones (no bus conflicts known): the 32
    KiB PRG bank PPPPP and the 8 KiB CHR bank CCCCCCC. No PRG-RAM. Power-on
    and reset clear both (Nestopia's, FCEUX's).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.outer = self.inner = 0
        self._update()

    def _update(self) -> None:
        self.map_prg(0, 32, (self.outer & 0x0F) << 1 | self.inner & 1)
        self.map_chr(0, 8, (self.outer >> 4) << 3 | (self.inner >> 4) & 7)

    def m2_gap(self, t: int) -> None:
        self.outer = self.inner = 0
        self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.outer = value
        elif address >= 0x8000:
            self.inner = value
        else:
            return
        self._update()


class Subor167(Banked):
    """Mapper 167 (Subor's computer learning cartridges): four registers, banks XORed in pairs.

    INES_Mapper_167.wiki: $8000-$9FFF ``...F...N`` (N: 0 horizontal
    arrangement, i.e. vertical mirroring); $A000-$BFFF ``...fMM..``;
    $C000-$DFFF and $E000-$FFFF the 16 KiB bank's A18-A14, the final bank
    the XOR of both copies (F^f giving A19). Modes (the page's table): 0,
    the bank at $8000 and bank $20 at $C000; 1, bank $1F at $8000 and the
    bank at $C000; 2/3, 32 KiB with PRG A14 inverted from CPU A14.
    8 KiB of PRG-RAM and of CHR-RAM. Power-on 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.regs = [0, 0, 0, 0]
        self.map_chr(0, 8, 0)
        self._update()

    def _update(self) -> None:
        r = self.regs
        bank = ((r[0] ^ r[1]) >> 4 & 1) << 5 | (r[2] ^ r[3]) & 0x1F
        mode = (r[1] >> 2) & 3
        if mode == 0:
            self.map_prg(0, 16, bank)
            self.map_prg(2, 16, 0x20)
        elif mode == 1:
            self.map_prg(0, 16, 0x1F)
            self.map_prg(2, 16, bank)
        else:
            self.map_prg(0, 16, bank | 1)
            self.map_prg(2, 16, bank & ~1)
        self.set_mirroring(HORIZONTAL if r[0] & 1 else VERTICAL)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.regs[(address >> 13) & 3] = value
            self._update()
        else:
            super().cpu_write(address, value, t)
