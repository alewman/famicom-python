"""Konami's VRC5 in the Q-Ta adapter (mapper 547): NHK Gakuen's Space School and Space College.

From NES_2.0_Mapper_547.wiki. The adapter holds 128 KiB of its own PRG, a 128 KiB
kanji ROM, 8 KiB of RAM and 8 KiB of CHR-RAM; the 40-pin cartridge in it adds
512 KiB of PRG and 8 KiB of battery RAM. No judge ROM exists, and Mesen2 2.1.1
has no such mapper; the claims rest on looking (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage

#: JIS X 0208 rows' 256-code pages to Kanji ROM pages (the page's pageTable, which it
#: says FCEUX replicates from the hardware).
PAGES = (
    0x0, 0x0, 0x2, 0x2, 0x1, 0x1, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF,
    0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF, 0xD, 0xD,
)  # fmt: skip

INTERNAL_PRG_BANKS = 16  # 128 KiB of 8 KiB banks, before the cartridge's 512 KiB


def kanji_tile(column: int, row: int, position: int) -> int:
    """The kanji ROM tile of a glyph's 8x8 corner, from its JIS X 0208 code."""
    row, column = (row - 0x21) & 0x7F, (column - 0x21) & 0x7F
    code = (
        column % 32 + (row % 16) * 32 + (column // 32) * 32 * 16 + (row // 16) * 32 * 16 * 3
    ) % 0x2400
    return ((code & 0xFF) | PAGES[code >> 8] << 8) * 4 | position


class QTa(Banked):
    """Mapper 547: PRG, RAM and an IRQ like any Konami, and two banks for every tile.

    $D000/$D100 the 4 KiB RAM banks at $6000/$7000 (D3 the adapter's chip,
    D0 A12); $D200-$D400 the 8 KiB banks at $8000-$C000 (D6 the cartridge's
    chip, D5-D0 A18-A13); $E000 is always the cartridge's last bank. $D500 D0
    CHR-RAM's A12 at PPU $0000. $D600/$D700 the IRQ latch, $D800 acknowledges
    and moves A to E, $D900 acknowledges, sets E and A, and with E reloads;
    the 16-bit counter counts M2, and its wrap asserts /IRQ and reloads. $DA00
    D1 the mirroring, D0 sends PPU writes at $2000-$2FFF to QTRAM.

    QTRAM is a second 2 KiB nametable: each background tile's fetch also
    takes a byte there which picks where its pattern comes from, D6 the kanji
    ROM or CHR-RAM, then D5-D0 or D0 the 4 KiB bank; PPU A12 means nothing
    then. The PPU's fetches tell themselves apart: background patterns follow
    an attribute fetch, sprites' follow two nametable fetches (our inference
    from the PPU's fetch order; the page says only "the next CHR pattern data").
    Pattern writes come from the CPU, never from rendering, so they end it.
    Power-on registers are not given: 0 here.

    A limit: while $DA00 D0 is set, reads of $2000-$2FFF also come from QTRAM,
    though the page redirects writes only. The connector has one ``ciram_a10``
    for both directions, and the games set it with rendering off.

    $DB00 (corner, attribute), $DC00, $DD00 (JIS column and row) go in, and
    $DC00 and $DD00 read back the tile for CIRAM and the byte for QTRAM. The
    kanji ROM is 1 bpp: PPU A3 takes it off the bus, the other plane all
    zeros or ones by QTRAM D7. Bank 1 of CHR-RAM for sprites at $1000: the
    page's note of a kanji mode there is unused by every game.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.kanji = image.chr
        self.chr_ram = bytearray(0x2000)
        self.qtram = bytearray(0x800)
        self.prg_ram = bytearray(0x4000)
        self.prg_ram_mask = 0x0FFF
        self.ram_banks = [0, 0]
        self.sprite_bank = 0
        self.latch = self.counter = 0
        self.irq_enable = self.irq_after = False
        self.to_qtram = False
        self.attribute = self.jis_column = self.jis_row = 0
        self.qt_byte = 0
        self.background = False
        self.map_prg(0, 8, 0)
        self.map_prg(1, 8, 0)
        self.map_prg(2, 8, 0)
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        self.set_mirroring(VERTICAL)

    def _ram_offset(self, address: int) -> int:
        bank = self.ram_banks[(address >> 12) & 1]
        return ((bank & 8) << 10 | (bank & 1) << 12) + (address & 0x0FFF)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg_ram[self._ram_offset(address)]
        if address & 0xFF00 == 0xDC00:
            tile = kanji_tile(self.jis_column, self.jis_row, self.attribute & 3)
            return tile & 0xFF
        if address & 0xFF00 == 0xDD00:
            tile = kanji_tile(self.jis_column, self.jis_row, self.attribute & 3)
            return tile >> 8 | 0x40 | (self.attribute & 4) << 5
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.prg_ram[self._ram_offset(address)] = value
        elif address & 0xF000 == 0xD000:
            self._register((address >> 8) & 0x0F, value)
        else:
            super().cpu_write(address, value, t)

    def _register(self, register: int, value: int) -> None:
        if register < 2:
            self.ram_banks[register] = value
        elif register < 5:
            bank = value & 0x3F
            bank = INTERNAL_PRG_BANKS + bank if value & 0x40 else bank % INTERNAL_PRG_BANKS
            self.map_prg(register - 2, 8, bank)
        elif register == 5:
            self.sprite_bank = value & 1
        elif register == 6:
            self.latch = (self.latch & 0xFF00) | value
        elif register == 7:
            self.latch = (self.latch & 0x00FF) | value << 8
        elif register == 8:
            self.irq = False
            self.irq_enable = self.irq_after
        elif register == 9:
            self.irq = False
            self.irq_enable, self.irq_after = bool(value & 2), bool(value & 1)
            if self.irq_enable:
                self.counter = self.latch
        elif register == 0x0A:
            self.to_qtram = bool(value & 1)
            self.set_mirroring(HORIZONTAL if value & 2 else VERTICAL)
        elif register == 0x0B:
            self.attribute = value & 7
        elif register == 0x0C:
            self.jis_column = value & 0x7F
        elif register == 0x0D:
            self.jis_row = value & 0x7F

    def m2(self, t: int) -> None:
        if self.irq_enable:
            self.counter = (self.counter + 1) & 0xFFFF
            if not self.counter:
                self.counter = self.latch
                self.irq = True

    def ciram_a10(self, address: int) -> int | None:
        a10 = super().ciram_a10(address)
        if a10 is not None:
            self.background = address & 0x3FF >= 0x3C0
            if not self.background:
                self.qt_byte = self.qtram[a10 << 10 | (address & 0x3FF)]
        return None if self.to_qtram else a10

    def _chr_ram_offset(self, address: int) -> int:
        if self.background:
            return (self.qt_byte & 1) << 12 | (address & 0x0FFF)
        bank = 1 if address & 0x1000 else self.sprite_bank
        return bank << 12 | (address & 0x0FFF)

    def ppu_read(self, address: int, t: int) -> int | None:
        if address >= 0x2000:
            a10 = Banked.ciram_a10(self, address)
            return self.qtram[(a10 or 0) << 10 | (address & 0x3FF)]
        if self.background and self.qt_byte & 0x40:
            if address & 8:
                return 0xFF if self.qt_byte & 0x80 else 0
            line = (address & 7) << 1 | (address >> 4) & 1 | (address & 0x0FE0) >> 1
            return self.kanji[(line | (self.qt_byte & 0x3F) << 11) % len(self.kanji)]
        return self.chr_ram[self._chr_ram_offset(address)]

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x2000:
            a10 = Banked.ciram_a10(self, address)
            self.qtram[(a10 or 0) << 10 | (address & 0x3FF)] = value
        else:
            self.background = False
            self.chr_ram[self._chr_ram_offset(address)] = value
