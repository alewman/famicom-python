"""Bandai's FCG family: FCG-1/2 and LZ93D50 (16), the Datach Joint ROM System (157), and the
LZ93D50 with an X24C01 (159).

INES_Mapper_016.wiki, _157.wiki and _159.wiki. No judge ROM exists
(docs/cartridge.md); the claims rest on milestone 7's sweep against Mesen2, a
detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .eeprom import X24C01, Eeprom
from .ines import RomImage


class BandaiFCG(Banked):
    """Mapper 16: 16 KiB PRG and the last fixed, eight 1 KiB CHR banks, a 16-bit M2 counter.

    Registers by the address's low nibble, at $6000-$7FFF on the FCG-1/2
    (16.4) and $8000-$FFFF on the LZ93D50 (16.5, 157, 159); without a
    submapper both decode, as an iNES file cannot say which chip it had:

    - 0-7 the CHR banks; 8 D3-D0 the PRG bank; 9 D1-D0 the arrangement
      (vertical, horizontal, one-screen A, one-screen B).
    - A: D0 enables counting and the write acknowledges /IRQ; on the LZ93D50
      it also copies the latch into the counter. B/C: the counter's low and
      high bytes, written straight into it on the FCG, into the latch on the
      LZ93D50. While counting, each M2 cycle the counter is tested and then
      decremented, a zero asserting /IRQ: the order Mesen2 found makes two
      games work (Mappers/Bandai/BandaiFcg.h), not otherwise documented.
    - D (LZ93D50): D5 the EEPROM's SCL, D6 SDA, D7 the direction (1: the
      master releases SDA to read). A read of $6000-$7FFF drives D4 alone,
      the SDA line (open drain: the master's level AND the part's).

    The header's PRG-NVRAM is the EEPROM, not RAM at $6000: 256 bytes on
    16.5 mean a 24C02. Power-on registers unspecified: 0 here.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        board = image.board
        submapper = board.submapper
        self.lz93d50 = submapper == 5 or board.mapper != 16
        self.ports_low = board.mapper == 16 and submapper != 5  # $6000-$7FFF
        self.ports_high = board.mapper != 16 or submapper != 4  # $8000-$FFFF
        self.prg_ram_enabled = False
        self.eeproms: list[Eeprom] = self._eeproms(board.prg_nvram)
        self.scl = self.sda = 1
        self.releasing = False
        self.counter = self.latch = 0
        self.counting = False
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)

    def _eeproms(self, nvram: int) -> list[Eeprom]:
        return [Eeprom()] if nvram == 256 or self.image.board.submapper == 0 else []

    def m2(self, t: int) -> None:
        if self.counting:
            if not self.counter:
                self.irq = True
            self.counter = (self.counter - 1) & 0xFFFF

    def sda_line(self) -> int:
        line = 1 if self.releasing else self.sda
        for eeprom in self.eeproms:
            line &= eeprom.output
        return line

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return super().cpu_read(address, t)
        if address >= 0x6000 and self.eeproms:
            return self.sda_line() << 4 | 0xEF << 8
        return None

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if self.ports_high if address >= 0x8000 else address >= 0x6000 and self.ports_low:
            self.register(address & 0x0F, value)

    def register(self, number: int, value: int) -> None:
        if number < 8:
            self.chr_register(number, value)
        elif number == 8:
            self.map_prg(0, 16, value & 0x0F)
        elif number == 9:
            self.set_mirroring((VERTICAL, HORIZONTAL, SCREEN_A, SCREEN_B)[value & 3])
        elif number == 0x0A:
            self.counting = bool(value & 1)
            self.irq = False
            if self.lz93d50:
                self.counter = self.latch
        elif number in (0x0B, 0x0C):
            shift = 8 if number == 0x0C else 0
            if self.lz93d50:
                self.latch = (self.latch & (0xFF00 >> shift)) | value << shift
            else:
                self.counter = (self.counter & (0xFF00 >> shift)) | value << shift
        elif number == 0x0D and self.lz93d50:
            self.releasing = bool(value & 0x80)
            self.sda = (value >> 6) & 1
            self.scl = (value >> 5) & 1
            self.clock_eeproms()

    def chr_register(self, number: int, value: int) -> None:
        self.map_chr(number, 1, value)

    def clock_eeproms(self) -> None:
        # SDA is open drain: a part pulling it low (an acknowledge, a 0 bit)
        # holds it there when the master releases it, so releasing with SCL
        # high is no STOP.
        sda = self.sda_line()
        for eeprom in self.eeproms:
            eeprom.lines(self.scl, sda)

    def battery_ram(self) -> bytes | None:
        return b"".join(bytes(e.memory) for e in self.eeproms) or None


class BandaiX24C01(BandaiFCG):
    """Mapper 159: the LZ93D50 with Xicor's 128-byte X24C01 (INES_Mapper_159.wiki)."""

    def _eeproms(self, nvram: int) -> list[Eeprom]:
        return [X24C01()]


class Datach(BandaiFCG):
    """Mapper 157: the Datach Joint ROM System: unbanked CHR-RAM, a barcode reader, two EEPROMs.

    INES_Mapper_157.wiki: the base unit's 24C02 on SCL = $800D D5; Battle
    Rush's external X24C01 (PRG-NVRAM 128 in the header) on SCL = D3 of the
    $8000-$8003 writes, both on the one SDA. A read of $6000 drives D4 (the
    SDA line) and D3, the barcode reader's output, idle here (0: no barcode
    is being swiped; input is milestone 8's).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_chr(0, 8, 0)  # unbanked: the 8 KiB straight through

    def _eeproms(self, nvram: int) -> list[Eeprom]:
        return [Eeprom(), X24C01()] if nvram == 128 else [Eeprom()]

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return super().cpu_read(address, t)
        if address >= 0x6000:
            return self.sda_line() << 4 | 0xE7 << 8
        return None

    def chr_register(self, number: int, value: int) -> None:
        if number < 4 and len(self.eeproms) == 2:
            self.eeproms[1].lines((value >> 3) & 1, self.sda_line())

    def clock_eeproms(self) -> None:
        sda = self.sda_line()
        self.eeproms[0].lines(self.scl, sda)
        if len(self.eeproms) == 2:
            external = self.eeproms[1]
            external.lines(external.scl, sda)
