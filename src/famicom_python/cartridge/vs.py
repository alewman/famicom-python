"""The Vs. System's own ROM sockets: iNES mapper 99.

A Vs. mainboard has no cartridge connector. Each side has six EPROM sockets,
four of program (1A-1D or 6A-6D, 8 KiB each, at $E000, $C000, $A000 and $8000)
and two of graphics, and the 2A03's OUT2 ($4016 D2) chooses the graphics socket
through "a simple 1-to-2 demultiplexer" (INES_Mapper_099.wiki; Vs._System.wiki
"Controller and CHR ROM bank"; specification tier). Games on a daughterboard
are the mappers they would be on a Famicom (1, 2, 67, 75, 206), on a board
with four-screen nametable RAM.

The mainboard's 2 KiB of RAM at $6000-$7FFF and its coin counter are the
board's (``famicom_python/vs.py``): nothing of them is here.
"""

from __future__ import annotations

from .banked import Banked
from .ines import RomImage

BANK = 0x2000


class VsSockets(Banked):
    """Mapper 99: unbanked PRG, and OUT2 selecting one of two 8 KiB CHR ROMs.

    How an image's PRG lies (NES_2.0.wiki "PRG-ROM Area"): up to 32 KiB end at
    $FFFF, "24 KiB (half-)blocks are mapped to $A000-$FFFF"; *Vs. Gumshoe*'s 40
    KiB are the 32 KiB seen with OUT2 low and then the 8 KiB that OUT2 high
    puts at $8000-$9FFF (its 16 KiB EPROM in socket 1D has OUT2 on A13).

    "Unlike all other mappers, an undersize mapper 99 image implies open bus
    instead of mirroring ... for games with only 8 KiB of CHR, when the bank
    select bit is high the PPU will have no tile data to render"
    (INES_Mapper_099.wiki): an empty socket drives nothing.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False  # $6000-$7FFF is the mainboard's
        size = min(len(image.prg), 4 * BANK)
        self._prg_base = 0x10000 - size  # the lowest address a socket answers
        self._prg_start = -self._prg_base  # prg[address + _prg_start]
        # Gumshoe's second $8000 bank, if the image has one.
        self._alternate = 4 * BANK if len(image.prg) >= 5 * BANK else None
        self.out2 = 0
        self.map_chr(0, 8, 0)
        self._chr_present = True

    def out(self, value: int) -> None:
        self.out2 = (value >> 2) & 1
        if not self.chr_writable:
            self._chr_present = self.out2 * BANK < len(self.chr)
            if self._chr_present:
                self.map_chr(0, 8, self.out2)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0xA000 or (address >= self._prg_base and not self.out2):
            return self.prg[address + self._prg_start]
        if address >= 0x8000:
            if self._alternate is not None and self.out2:
                return self.prg[self._alternate + (address & 0x1FFF)]
            if address >= self._prg_base:
                return self.prg[address + self._prg_start]
        return None

    def cpu_write(self, address: int, value: int, t: int) -> None:
        pass  # ROM sockets only

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000 and not self._chr_present:
            return None
        return super().ppu_read(address, t)
