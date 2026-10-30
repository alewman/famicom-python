"""One Chinese ASIC family on four boards: Nánjīng's FC-001 (163), Wàixīng's FS304 (162),
Dōngdá/Yànchéng's cy2000-3 (164) and Yànchéng's YC-03-09 (558).

Each from its wiki page (INES_Mapper_162/163/164.wiki, NES_2.0_Mapper_558.wiki):
32 KiB PRG banks (164 also UxROM), 8 KiB of CHR-RAM, registers at $5000-$5FFF
by A11-A8, all cleared on reset. No judge ROM exists; 162-164 rest on sweeps
against Mesen2, 558 (which Mesen2 2.1.1 lacks) on its pictures by eye.
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .eeprom import Microwire93C66
from .ines import RomImage


def swap_d0_d1(value: int) -> int:
    return (value & ~3) | (value & 1) << 1 | (value >> 1) & 1


class NanjingASIC(Banked):
    """What the four boards share: a 32 KiB PRG bank and unbanked 8 KiB CHR-RAM.

    The FC-001 and FS304 can make PPU A9, latched on PPU A13's last rise (a
    nametable fetch), CHR A12 for pattern fetches ($5000 D7): the top half of
    any nametable then takes its tiles from the left pattern table and the
    bottom half from the right, whatever the scroll (as mapper 96).
    """

    watches_ppu_address = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chr = bytearray(max(len(self.chr), 0x2000))
        self.chr_writable = True
        self.map_chr(0, 8, 0)
        self.regs = {0x5000: 0, 0x5100: 0, 0x5200: 0, 0x5300: 0}
        self.a13 = 0
        self.latched_a9 = 0  # PPU A9 at A13's last rise
        self.latched_a0 = 0  # PPU A0 likewise (164's 1 bpp mode)
        self._update()

    def _update(self) -> None:
        raise NotImplementedError

    def auto_switch(self) -> bool:
        return bool(self.regs[0x5000] & 0x80)

    def ppu_address(self, address: int, t: int) -> None:
        a13 = (address >> 13) & 1
        if a13 and not self.a13:
            self.latched_a9 = (address >> 9) & 1
            self.latched_a0 = address & 1
        self.a13 = a13

    def _chr_address(self, address: int) -> int:
        if self.auto_switch():
            return (address & 0x0FFF) | self.latched_a9 << 12
        return address

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            return self.chr[self._chr_address(address)]
        return super().ppu_read(address, t)

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            self.chr[self._chr_address(address)] = value
            return
        super().ppu_write(address, value, t)


class FC001(NanjingASIC):
    """Mapper 163: Nánjīng's FC-001.

    $5000 ``C...PPPP``: PRG A18-A15 and the CHR switch; $5200 D1-D0: PRG
    A20-A19; with $5300 D0 set, D0 and D1 of writes to $5000-$5200 are
    swapped; $5300 D2 clear holds PRG A15/A16 high (so the game boots in
    bank 3). $5100/$5101 is a protection latch: a $5100 write stores D2 (F)
    and D0 (E); a $5101 write with D0 set flips F; reads of $5100 (mask
    $F300) give F inverted on D2. 8 KiB of battery-backed PRG-RAM.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.feedback = 0
        super().__init__(image, cpu_cycle_ticks)

    def _update(self) -> None:
        bank = (self.regs[0x5200] & 3) << 4 | self.regs[0x5000] & 0x0F
        if not self.regs[0x5300] & 4:
            bank |= 3
        self.map_prg(0, 32, bank)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xF300 == 0x5100:
            return (~self.feedback & 1) << 2 | 0xFB << 8  # D2 driven, the rest open bus
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not 0x5000 <= address < 0x6000:
            super().cpu_write(address, value, t)
            return
        register = address & 0xFF00
        if register != 0x5300 and self.regs[0x5300] & 1:
            value = swap_d0_d1(value)
        if register == 0x5100:
            if address & 1:
                if value & 1:
                    self.feedback ^= 1
            else:
                self.feedback = (value >> 2) & 1
            return
        if register in self.regs:
            self.regs[register] = value
            self._update()


class FS304(NanjingASIC):
    """Mapper 162: Wàixīng's FS304.

    $5000 ``C...PPpq``: PRG A18-A17, and q/p for A15/A16 when $5300 says;
    $5100 D1: PRG A15 when $5300 D0 is clear; $5200 D1-D0: PRG A20-A19. $5300
    D0 and D2 choose where A15 and A16 come from (the wiki's table): A16 is 1
    unless D2, then $5000 D1; A15 is $5100 D1 unless D0, then 1 (D2 clear) or
    $5000 D0 (D2 set). The game boots in bank 2. 8 KiB of battery-backed
    PRG-RAM.
    """

    def _update(self) -> None:
        r5000, r5300 = self.regs[0x5000], self.regs[0x5300]
        a16 = (r5000 >> 1) & 1 if r5300 & 4 else 1
        a15 = (self.regs[0x5100] >> 1) & 1
        if r5300 & 1:
            a15 = r5000 & 1 if r5300 & 4 else 1
        bank = (self.regs[0x5200] & 3) << 4 | ((r5000 >> 2) & 3) << 2 | a16 << 1 | a15
        self.map_prg(0, 32, bank)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not 0x5000 <= address < 0x6000:
            super().cpu_write(address, value, t)
            return
        register = address & 0xFF00
        if register in self.regs:
            self.regs[register] = value
            self._update()


class Dongda164(NanjingASIC):
    """Mapper 164: the PEC-9588 / cy2000-3 board, with a 93C66 EEPROM for saves.

    $5000 ``CSQMPPPp``: with M clear, UxROM: $8000 the 16 KiB bank QPPPp,
    $C000 bank $1F (S clear) or 111p0 (S set), and vertical mirroring; with M
    set, a 32 KiB bank PPPp and the mirroring from $5300 D7 (0 horizontal, 1
    vertical). C: the 1 bpp mode: for pattern fetches CHR A12 and CHR A3 are
    PPU A9 and A0 latched at A13's last rise. $5100 D1-D0: PRG A20-A19.
    $5200: the EEPROM's DI (D0), CLK (D2) and CS (D4); $5500 D2 reads its DO,
    inverted. PRG-RAM (0-2 KiB on known carts) is not battery-backed: the
    EEPROM is the save. The second EEPROM (CS on D6) is unpopulated.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.eeprom = Microwire93C66()
        super().__init__(image, cpu_cycle_ticks)
        self.battery = True

    def auto_switch(self) -> bool:
        return False

    def _chr_address(self, address: int) -> int:
        if self.regs[0x5000] & 0x80:
            return (address & 0x0FF7) | self.latched_a9 << 12 | self.latched_a0 << 3
        return address

    def _update(self) -> None:
        r, high = self.regs[0x5000], (self.regs[0x5100] & 3) << 5
        if r & 0x10:  # BxROM
            self.map_prg(0, 32, (high >> 1) | r & 0x0F)
            self.set_mirroring(VERTICAL if self.regs[0x5300] & 0x80 else HORIZONTAL)
        else:  # UxROM
            self.map_prg(0, 16, high | (r >> 1) & 0x10 | r & 0x0F)
            fixed = 0x1C | (r & 1) << 1 if r & 0x40 else 0x1F
            self.map_prg(2, 16, high | fixed)
            self.set_mirroring(VERTICAL)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xFF00 == 0x5500:
            return (~self.eeprom.output & 1) << 2 | 0xFB << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not 0x5000 <= address < 0x6000:
            super().cpu_write(address, value, t)
            return
        register = address & 0xFF00
        if register == 0x5200:
            self.eeprom.lines((value >> 4) & 1, (value >> 2) & 1, value & 1)
        elif register in self.regs:
            self.regs[register] = value
            self._update()

    def battery_ram(self) -> bytes | None:
        return bytes(self.eeprom.memory)

    def _restore(self, data: bytes) -> None:
        self.eeprom.memory[:] = data


class YC0309(NanjingASIC):
    """NES 2.0 mapper 558: Yànchéng's YC-03-09 (and Wàixīng's compatible board).

    $5000 D3-D0: PRG A18-A15; $5100 (mask $FB00) D1-D0: PRG A20-A19; $5300 D2
    clear holds A15/A16 high (boot in bank 3), D1 clear swaps D0 and D1 of
    writes to $5000-$5200 (the board wires them reversed). $5200: the 93C66's
    CS (D2), and CLK/DI on D0/D1 (swapped by the same rule); $5500 D2 reads
    its DO, not inverted. With PRG-NVRAM in the header the save is 8 KiB of
    battery RAM (Wàixīng's games), else the EEPROM (Yànchéng's).
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.eeprom = None if image.board.prg_nvram else Microwire93C66()
        super().__init__(image, cpu_cycle_ticks)
        if self.eeprom:
            self.battery = True

    def auto_switch(self) -> bool:
        return False

    def _update(self) -> None:
        bank = (self.regs[0x5100] & 3) << 4 | self.regs[0x5000] & 0x0F
        if not self.regs[0x5300] & 4:
            bank |= 3
        self.map_prg(0, 32, bank)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address & 0xFF00 == 0x5500 and self.eeprom:
            return (self.eeprom.output & 1) << 2 | 0xFB << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if not 0x5000 <= address < 0x6000:
            super().cpu_write(address, value, t)
            return
        register = 0x5100 if address & 0xFB00 == 0x5100 else address & 0xFF00
        swapping = not self.regs[0x5300] & 2
        if register == 0x5200:
            if self.eeprom:  # the wiki's table, CPU bits: CLK on D0 while swapping, else DI
                d0, d1 = value & 1, (value >> 1) & 1
                clk, di = (d0, d1) if swapping else (d1, d0)
                self.eeprom.lines((value >> 2) & 1, clk, di)
            return
        if register != 0x5300 and swapping:
            value = swap_d0_d1(value)
        if register in self.regs:
            self.regs[register] = value
            self._update()

    def battery_ram(self) -> bytes | None:
        if self.eeprom:
            return bytes(self.eeprom.memory)
        return super().battery_ram()

    def _restore(self, data: bytes) -> None:
        if self.eeprom:
            self.eeprom.memory[:] = data
        else:
            super()._restore(data)
