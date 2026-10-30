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
