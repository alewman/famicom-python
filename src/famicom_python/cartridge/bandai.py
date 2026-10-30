"""Bandai's FCG family: FCG-1/2 and LZ93D50 (16), the Datach Joint ROM System (157), and the
LZ93D50 with an X24C01 (159) or 8 KiB of RAM (153); the discrete 74161/7432 boards (70, 152);
the Oeka Kids board (96); and Karaoke Studio's M60001 (188).

INES_Mapper_016.wiki, _157.wiki, _159.wiki, _153.wiki, _070.wiki, _152.wiki,
_096.wiki and _188.wiki. No judge
ROM exists (docs/cartridge.md); the claims rest on sweeps against Mesen2, a
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

    def _restore(self, data: bytes) -> None:
        for eeprom in self.eeproms:
            size = len(eeprom.memory)
            eeprom.memory[:], data = data[:size], data[size:]


class BandaiFCGRAM(BandaiFCG):
    """Mapper 153: the LZ93D50 with 8 KiB of battery-backed RAM (Famicom Jump II).

    INES_Mapper_153.wiki: $8000-$8003 D0 selects the 256 KiB outer PRG bank
    (the ASIC's PA12/PA13 inputs are grounded, so the same value goes to all
    four; $8004-$8007 do nothing); $8008 the inner 16 KiB bank, the outer
    bank's last at $C000; $8009-$800C as 16.5; $800D D5 enables the RAM. CHR
    is 8 KiB of RAM, unbanked. Power-on registers unspecified: 0 here (the
    wiki: the game hangs on a power-on with the RAM all zeroes).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.outer = self.inner = 0
        super().__init__(image, cpu_cycle_ticks)
        self.map_chr(0, 8, 0)
        self._map_prg()

    def _eeproms(self, nvram: int) -> list[Eeprom]:
        return []

    def _map_prg(self) -> None:
        self.map_prg(0, 16, self.outer << 4 | self.inner)
        self.map_prg(2, 16, self.outer << 4 | 0x0F)

    def chr_register(self, number: int, value: int) -> None:
        if number < 4:
            self.outer = value & 1
            self._map_prg()

    def register(self, number: int, value: int) -> None:
        if number == 8:
            self.inner = value & 0x0F
            self._map_prg()
        elif number == 0x0D:
            self.prg_ram_enabled = bool(value & 0x20) and bool(self.prg_ram)
        else:
            super().register(number, value)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000 and self.prg_ram_enabled:
            return self.prg_ram[address & self.prg_ram_mask]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            if self.prg_ram_enabled:
                self.prg_ram[address & self.prg_ram_mask] = value
            return
        super().cpu_write(address, value, t)

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg_ram) if self.battery else None

    def _restore(self, data: bytes) -> None:
        self.prg_ram[:] = data


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


class Bandai74161(Banked):
    """Mappers 70 and 152: a 74161 and a 7432, UNROM's PRG with a CHR bank on top.

    INES_Mapper_070.wiki, _152.wiki: a write to $8000-$FFFF (AND-type bus
    conflicts) selects the 16 KiB PRG bank at $8000 (the last fixed) from
    the high nibble and the 8 KiB CHR bank from the low; on 152, D7 is the
    one-screen select (A or B) and the PRG bank three bits. 70's arrangement
    is hard-wired. Power-on banks unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.one_screen = image.board.mapper == 152
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)
        self._latch(0)

    def _latch(self, value: int) -> None:
        self.map_chr(0, 8, value & 0x0F)
        if self.one_screen:
            self.map_prg(0, 16, (value >> 4) & 7)
            self.set_mirroring(SCREEN_B if value & 0x80 else SCREEN_A)
        else:
            self.map_prg(0, 16, value >> 4)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        self._latch(self.bus_conflict(address, value))


class OekaKids(Banked):
    """Mapper 96: the Oeka Kids board: CHR-RAM banked by the nametable the PPU last moved to.

    INES_Mapper_096.wiki: a write to $8000-$FFFF (AND-type bus conflicts)
    selects the 32 KiB PRG bank (D1-D0) and the 16 KiB outer CHR-RAM bank
    (D2). A 7474 latches PPU A9-A8 whenever the PPU's address moves into
    $2000-$2FFF from elsewhere (A13 high, A12 low, rising; the read and
    write strobes play no part, so a $2006 write does it too): the 4 KiB
    bank at PPU $0000; $1000 is the outer bank's last. 32 KiB of CHR-RAM,
    vertical arrangement. The wiki's NOR-logic note (banks appear on the RAM
    as 3, 2, 1, 0) is invisible to software and not modelled. Power-on
    latches unspecified: 0 here.
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr = bytearray(0x8000)
        self.chr_writable = True
        self.outer = 0
        self.inner = 0
        self.in_nametables = False
        self.map_prg(0, 32, 0)
        self._map_chr()

    def _map_chr(self) -> None:
        self.map_chr(0, 4, self.outer << 2 | self.inner)
        self.map_chr(4, 4, self.outer << 2 | 3)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        value = self.bus_conflict(address, value)
        self.map_prg(0, 32, value & 3)
        self.outer = (value >> 2) & 1
        self._map_chr()

    def ppu_address(self, address: int, t: int) -> None:
        now = address & 0x3000 == 0x2000
        if now and not self.in_nametables:
            self.inner = (address >> 8) & 3
            self._map_chr()
        self.in_nametables = now


class Karaoke(Banked):
    """Mapper 188: Bandai's Karaoke Studio (M60001): 16 KiB PRG banks, internal or expansion ROM.

    INES_Mapper_188.wiki: a write to $8000-$FFFF (AND-type bus conflicts)
    sets ``.LXRBBBB``: the 16 KiB bank at $8000 from the internal ROM (R = 1)
    or the expansion cartridge's (R = 0), and CIRAM A10 from PPU A10 (X = 0)
    or A11; $C000 is the internal ROM's last bank. A 256 KiB image is the
    128 KiB internal ROM and then an expansion; with none, the expansion
    reads are open bus (the wiki's advice, not other emulators' last-bank
    stand-in). $6000-$7FFF reads the microphone: D0 and D1 its A and B
    buttons (0 pressed; here neither), D2 its 1-bit ADC (here silent, 0),
    D7-D3 open bus. 8 KiB of CHR-RAM. Power-on bank unspecified: 0 here.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.internal_banks = min(len(self.prg), 0x20000) // 0x4000
        self.expansion = len(self.prg) > 0x20000
        self.from_expansion = False
        self.map_prg(2, 16, self.internal_banks - 1)
        self.map_prg(0, 16, 0)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return 0x03 | 0xF8 << 8  # the buttons released, the ADC low; D7-D3 undriven
        if 0x8000 <= address < 0xC000 and self.from_expansion and not self.expansion:
            return None
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            return
        value = self.bus_conflict(address, value)
        bank = value & 0x0F
        self.from_expansion = not value & 0x10
        if self.from_expansion:
            bank = self.internal_banks + bank % self.internal_banks
        else:
            bank %= self.internal_banks
        self.map_prg(0, 16, bank)
        self.set_mirroring(HORIZONTAL if value & 0x20 else VERTICAL)
