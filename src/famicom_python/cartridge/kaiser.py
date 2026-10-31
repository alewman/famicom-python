"""Kaiser's and others' FDS-to-cartridge conversions: 8 KiB PRG banks at $6000 and simple
cycle counters standing in for the disk system's timer.

Each from its NESdev wiki page. No judge ROM exists; the claims rest on sweeps
against Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage


class Kaiser42(Banked):
    """Mapper 42 (Ai Senshi Nicol, Bio Miracle Bokutte Upa): $6000 banked, the last 32 KiB fixed.

    INES_Mapper_042.wiki (mask $E003): $8000 D3-D0 the 8 KiB CHR-ROM bank
    (ignored with CHR-RAM); $E000 D3-D0 the 8 KiB PRG bank at $6000; $E001
    D3 the mirroring (0 vertical, 1 horizontal); $E002 D1 enables the 15-bit
    M2 counter (clear: acknowledges and resets it); /IRQ is asserted while
    its two high bits are set (24,576 cycles in, for 8,192), as the page says
    FCEUX's source implies.

    42.2 (Green Beret, Kaiser and Whirlwind Manu): the page has nothing, and
    the game decides (C65): both dumps write $8000 = 5 then a bank to $8001,
    D4-D1 the 8 KiB bank at $6000 (Whirlwind's D5 is always set). Neither
    writes anything else.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.green_beret = image.board.submapper == 2
        self.bank6000 = 0
        self.counter = 0
        self.counting = False
        self.map_prg(0, 32, len(self.prg) // 0x8000 - 1)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0xE003
        if self.green_beret:
            if register == 0x8001:
                self.bank6000 = (value >> 1) & 0x0F
        elif register == 0x8000 and not self.chr_writable:
            self.map_chr(0, 8, value & 0x0F)
        elif register == 0xE000:
            self.bank6000 = value & 0x0F
        elif register == 0xE001:
            self.set_mirroring(HORIZONTAL if value & 8 else VERTICAL)
        elif register == 0xE002:
            self.counting = bool(value & 2)
            if not self.counting:
                self.counter = 0
                self.irq = False

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter = (self.counter + 1) & 0x7FFF
            self.irq = self.counter & 0x6000 == 0x6000


class Contra326(Banked):
    """Mapper 326 (a bootleg Contra): 8 KiB PRG, 1 KiB CHR, a CIRAM bit per nametable.

    From krzysiobal's dump notes (forum t=17352; the wiki has none): $8000, $A000 and
    $C000 (mask $E010) the 8 KiB banks, the last fixed at $E000; $8010-$8017
    (mask $801F) the 1 KiB CHR banks; $8018-$801B D0 CIRAM A10 for each
    nametable. No bus conflicts. The mask matters: the game writes $F018.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.nametables = [0, 0, 1, 1]
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
        elif address & 0x10:
            register = address & 0x0F
            if register < 8:
                self.map_chr(register, 1, value)
            elif register < 12:
                self.nametables[register & 3] = value & 1
        elif address < 0xE000:
            self.map_prg((address >> 13) & 3, 8, value)

    def ciram_a10(self, address: int) -> int | None:
        return self.nametables[(address >> 10) & 3]


class KS7032(Banked):
    """Mapper 142: Kaiser KS-7032 (SMB2J and other FDS conversions).

    INES_Mapper_142.wiki: $8000-$BFFF the reload value's nibbles, low first,
    as the VRC3's; $C000 enables (D1, which the game sets with $02 or $05);
    $D000 acknowledges. $E000 D2-D0 selects a bank register (1-3: the 8 KiB
    PRG banks at $8000/$A000/$C000, 4: at $6000) and $F000 D3-D0 writes it;
    $E000 the last 8 KiB. 8 KiB of CHR-RAM. The counter counts M2 cycles up
    from the reload value and asserts /IRQ on overflowing from $FFFF, then
    reloads (the VRC3's 16-bit mode; the 8-bit mode is not documented here).
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.select = 0
        self.bank6000 = 0
        self.reload = self.counter = 0
        self.counting = False
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        region = address & 0xF000
        if 0x8000 <= region < 0xC000:
            shift = (region - 0x8000) >> 10
            self.reload = (self.reload & ~(0xF << shift)) | (value & 0x0F) << shift
        elif region == 0xC000:
            self.counting = bool(value & 2)
            if self.counting:
                self.counter = self.reload
            self.irq = False
        elif region == 0xD000:
            self.irq = False
        elif region == 0xE000:
            self.select = value & 7
        elif region == 0xF000:
            if 1 <= self.select <= 3:
                self.map_prg(self.select - 1, 8, value & 0x0F)
            elif self.select == 4:
                self.bank6000 = value & 0x0F

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter += 1
            if self.counter > 0xFFFF:
                self.counter = self.reload
                self.irq = True


class Kaiser303(Banked):
    """NES 2.0 mapper 303: Kaiser's conversion keeping the disk system's timer and mirroring.

    NES_2.0_Mapper_303.wiki: a write to $4A00-$4AFF latches the 16 KiB PRG
    bank at $8000 from A6 and A3-A2, applied by a write to $5100; $C000 is
    bank 2. $4020/$4021/$4022, $4025 D3 and $4030 D0 act as the FDS's (its
    timer IRQ: reload, repeat, the flag read and acknowledged at $4030; the
    mirroring, 0 vertical). 8 KiB of PRG-RAM and of CHR-RAM. The FDS sound
    writes the conversion keeps are ignored, as on the cartridge.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.latched = 0
        self.reload = self.counter = 0
        self.timer_enabled = self.timer_repeat = False
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, 2)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address == 0x4030:
            value = int(self.irq)
            self.irq = False
            return value | 0xFE << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xFF00 == 0x4A00:
            self.latched = (address >> 2) & 3 | (address >> 4) & 4
        elif address & 0xFF00 == 0x5100:
            self.map_prg(0, 16, self.latched)
        elif address == 0x4020:
            self.reload = (self.reload & 0xFF00) | value
        elif address == 0x4021:
            self.reload = (self.reload & 0x00FF) | value << 8
        elif address == 0x4022:
            self.timer_repeat = bool(value & 1)
            self.timer_enabled = bool(value & 2)
            if self.timer_enabled:
                self.counter = self.reload
            else:
                self.irq = False
        elif address == 0x4025:
            self.set_mirroring(HORIZONTAL if value & 8 else VERTICAL)
        else:
            super().cpu_write(address, value, t)

    def m2(self, t: int) -> None:
        if self.timer_enabled:
            if self.counter == 0:
                self.irq = True
                self.counter = self.reload
                self.timer_enabled = self.timer_repeat
            else:
                self.counter -= 1


class Board09034A(Banked):
    """NES 2.0 mapper 304: the 09-034A conversions (Whirlwind Manu's SMB2J, Volleyball, Zanac).

    NES_2.0_Mapper_304.wiki: $8000-$FFFF is 32 KiB bank 0; $4027 D0 puts 8 KiB
    bank 4 or 5 at $6000; reads of $4042-$4055 return $FF (SMB2J freezes
    otherwise). $4068 is FCEUX's IRQ counter (5,750 M2 cycles), but a
    recording of the cartridge on hardware shows SMB2J hanging after 4-4
    as it does without one: no counter here, as on the cartridge.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.bank6000 = 4
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x4042 <= address <= 0x4055:
            return 0xFF
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address == 0x4027:
            self.bank6000 = 4 | value & 1


class NTDEC2722(Banked):
    """Mapper 40: NTDEC 2722 (SMB2J conversions) and 40.1, the 2752 multicart.

    INES_Mapper_040.wiki, from FCEUX's and Nestopia's source as the page says (mask $E000):
    $8000 disables and acknowledges the
    counter, $A000 enables it, $E000 the 8 KiB bank at $C000; $6000 is bank 6,
    $8000 4, $A000 5, $E000 7. The counter (a CD4020) asserts /IRQ 4096 M2
    cycles after enabling and releases it 4096 later. 40.1: $C000 latches its
    address ``.ppNPCCM``: the mirroring, CHR A14-A13, P regular NROM mode
    (PRG A16, A15-A14 from pp, N NROM-256) instead of the SMB2J layout.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.multicart = image.board.submapper == 1
        self.prg_ram_enabled = False
        self.outer = 0
        self.inner = 0
        self.counting = False
        self.counter = 0
        self._update()

    def _update(self) -> None:
        o = self.outer
        if self.multicart and o & 8:
            bank16 = ((o >> 3) & 1) << 2 | (o >> 5) & 3
            if o & 0x10:
                self.map_prg(0, 32, bank16 >> 1)
            else:
                self.map_prg(0, 16, bank16)
                self.map_prg(2, 16, bank16)
        else:
            for window, bank in enumerate((4, 5, self.inner, 7)):
                self.map_prg(window, 8, bank)
        self.map_chr(0, 8, (o >> 1) & 3)
        if self.multicart:
            self.set_mirroring(HORIZONTAL if o & 1 else VERTICAL)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(6 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        region = address & 0xE000
        if region == 0x8000:
            self.counting = False
            self.counter = 0
            self.irq = False
        elif region == 0xA000:
            self.counting = True
        elif region == 0xC000 and self.multicart:
            self.outer = address & 0x7F
            self._update()
        elif region == 0xE000:
            self.inner = value & 7
            self._update()

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter = (self.counter + 1) & 0x1FFF
            self.irq = bool(self.counter & 0x1000)


#: Mapper 43's $4022 values and the 8 KiB banks they select (INES_Mapper_043.wiki).
TONY_I_BANKS = (4, 3, 4, 4, 4, 7, 5, 6)


class TonyI43(Banked):
    """Mapper 43 (SMB2J conversions on the TONY-I and YS-612 boards): three PRG chips.

    INES_Mapper_043.wiki: $5000-$5FFF a 2 KiB chip twice; $6000 bank 2, $8000
    bank 1, $A000 bank 0 and $C000 the bank $4022 (mask $71FF) selects
    through the page's table, from the two 32 KiB chips; $E000 an 8 KiB chip.
    $4122 (TONY-I) / $8122 (YS-612) D0 enables a 12-bit M2 counter (clear:
    acknowledges and resets it) that asserts /IRQ on overflowing. The file
    holds the 64 KiB, then an 8 KiB block whose start is the 2 KiB chip,
    then the 8 KiB chip (Mesen2's layout; the page gives none).
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.counter = 0
        self.counting = False
        for window, bank in enumerate((1, 0, 4, 9)):
            self.map_prg(window, 8, bank)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x5000 <= address < 0x6000:
            return self.prg[(0x10000 + (address & 0x7FF)) % len(self.prg)]
        if 0x6000 <= address < 0x8000:
            return self.prg[(2 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0x71FF
        if register == 0x4022:
            self.map_prg(2, 8, TONY_I_BANKS[value & 7])
        elif register == 0x4122 or address & 0xF1FF == 0x8122:
            self.counting = bool(value & 1)
            self.counter = 0
            self.irq = False

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter += 1
            if self.counter >= 0x1000:
                self.counting = False
                self.irq = True


class Whirlwind309(Banked):
    """NES 2.0 mapper 309: Whirlwind Manu's Ai Senshi Nicol conversion.

    NES_2.0_Mapper_309.wiki (masks taken as $E000): $8000 D3-D0 the 8 KiB PRG
    bank at $8000, banks 13-15 fixed after it; $E000 D3 the mirroring (0
    vertical). 8 KiB of PRG-RAM and CHR-RAM. The FDS sound writes it keeps
    are ignored, as on the cartridge.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        for window, bank in enumerate((0, 13, 14, 15)):
            self.map_prg(window, 8, bank)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        region = address & 0xE000
        if region == 0x8000:
            self.map_prg(0, 8, value & 0x0F)
        elif region == 0xE000:
            self.set_mirroring(HORIZONTAL if value & 8 else VERTICAL)
        else:
            super().cpu_write(address, value, t)


class Kaiser305(Banked):
    """NES 2.0 mapper 305: a Kaiser conversion in 2 KiB PRG banks.

    NES_2.0_Mapper_305.wiki: writes to $8000/$8800/$9000/$9800 (A12-A11) set
    the 2 KiB banks at $6000/$6800/$7000/$7800; $8000-$FFFF holds 2 KiB banks
    15 down to 0 in that order. 8 KiB of CHR-RAM, vertical mirroring.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.low_banks = [0, 0, 0, 0]
        self.map_chr(0, 8, 0)
        self.set_mirroring(VERTICAL)

    def _bank(self, bank: int, address: int) -> int:
        return self.prg[(bank * 0x800 + (address & 0x7FF)) % len(self.prg)]

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return self._bank(15 - ((address - 0x8000) >> 11), address)
        if address >= 0x6000:
            return self._bank(self.low_banks[(address >> 11) & 3], address)
        return None

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000 and address < 0xA000:
            self.low_banks[(address >> 11) & 3] = value


class Kaiser306(Banked):
    """NES 2.0 mapper 306: a Kaiser conversion banking $6000 by address.

    NES_2.0_Mapper_306.wiki (mask $D903, FCEUX's): A3-A2 bits 0-1 of the 8
    KiB bank at $6000; A6 set: A5-A4 bits 2-3, clear: bits 2-3 are 10.
    Banks $0C-$0F mirror $0B. $8000-$FFFF is 32 KiB bank 3; 8 KiB CHR-RAM;
    mirroring hard-wired vertical.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.bank6000 = 8  # not given: A6-A2 clear
        self.set_mirroring(VERTICAL)
        self.map_prg(0, 32, 3)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xD903 == 0xD903:
            high = (address >> 4) & 3 if address & 0x40 else 2
            self.bank6000 = min(high << 2 | (address >> 2) & 3, 0x0B)


class Kaiser522(Banked):
    """NES 2.0 mapper 522 (Fūun Shōrinken): an MMC3 clone wired for two PRG banks and RAM at $C000.

    NES_2.0_Mapper_522.wiki: $8000 (even) selects a register, $8001 (odd)
    writes it: 6 and 7 the 8 KiB banks at $8000/$A000 (the others do
    nothing). $6000 is the second-last bank, $C000-$DFFF 8 KiB of RAM, $E000
    the last bank; 8 KiB CHR-RAM; mirroring hard-wired.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.ram = bytearray(0x2000)
        self.select = 0
        last = len(self.prg) // 0x2000 - 1
        self.map_prg(3, 8, last)
        self.second_last = last - 1
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[self.second_last * 0x2000 + (address & 0x1FFF)]
        if 0xC000 <= address < 0xE000:
            return self.ram[address & 0x1FFF]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0xC000 <= address < 0xE000:
            self.ram[address & 0x1FFF] = value
        elif 0x8000 <= address < 0xA000:
            if address & 1:
                if self.select in (6, 7):
                    self.map_prg(self.select - 6, 8, value)
            else:
                self.select = value & 7


class KS7021A(Banked):
    """NES 2.0 mapper 525 (UNL-KS7021A: Kaiser's VRC2 mapper hacks of Contra, Getsu Fūma Den).

    NES_2.0_Mapper_525.wiki: $8000 (mask $F000) D3-D1 the 16 KiB PRG bank at
    $8000 (the last fixed); $9000 D0 the mirroring (0 vertical); $B000-$B007
    (mask $F007) the eight 1 KiB CHR banks.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(2, 16, len(self.prg) // 0x4000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        region = address & 0xF000
        if region == 0x8000:
            self.map_prg(0, 16, (value >> 1) & 7)
        elif region == 0x9000:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        elif address & 0xF000 == 0xB000 and address & 0x0FF8 == 0:
            self.map_chr(address & 7, 1, value)
        else:
            super().cpu_write(address, value, t)


class KS7057(Banked):
    """NES 2.0 mapper 302 (Kaiser KS7057): eight 2 KiB PRG banks set by nibbles.

    NES_2.0_Mapper_302.wiki: $8000-$9FFF D0 the mirroring (0 horizontal, 1
    vertical); $B000-$E003 (mask $F003) the 2 KiB banks' nibbles (A0: low or
    high): $B000-$C003 the banks at $8000-$9FFF, $D000-$E003 those at
    $6000-$7FFF. $A000 is 8 KiB bank $0D, $C000 16 KiB bank 7. 8 KiB CHR-RAM.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.small = [0] * 8  # 2 KiB banks: $8000-$9FFF (0-3), $6000-$7FFF (4-7)
        self.map_prg(1, 8, 0x0D)
        self.map_prg(2, 16, 7)
        self.map_chr(0, 8, 0)

    def _small(self, index: int, address: int) -> int:
        return self.prg[(self.small[index] * 0x800 + (address & 0x7FF)) % len(self.prg)]

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self._small(4 + ((address >> 11) & 3), address)
        if 0x8000 <= address < 0xA000:
            return self._small((address >> 11) & 3, address)
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x8000 <= address < 0xA000:
            self.set_mirroring(VERTICAL if value & 1 else HORIZONTAL)
            return
        register = address & 0xF003
        if 0xB000 <= register <= 0xE003:
            index = ((register >> 12) - 0x0B) * 2 + ((register >> 1) & 1)
            shift = 4 if register & 1 else 0
            self.small[index] = (self.small[index] & (0xF0 >> shift)) | (value & 0x0F) << shift


class KS7013B(Banked):
    """NES 2.0 mapper 312 (UNL-KS7013B: Kaiser's Highway Star).

    NES_2.0_Mapper_312.wiki: $6000-$7FFF (mask $E000) D2-D0 the 16 KiB PRG
    bank at $8000 ($C000 bank 7); $8000-$FFFF D0 the mirroring (0
    vertical). 8 KiB CHR-RAM.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.map_prg(0, 16, 0)
        self.map_prg(2, 16, 7)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        elif address >= 0x6000:
            self.map_prg(0, 16, value & 7)


class Kaiser307(Banked):
    """NES 2.0 mapper 307: a Kaiser conversion with RAM and ROM in 4 KiB pieces.

    NES_2.0_Mapper_307.wiki: $6000-$6FFF RAM bank 0, $7000-$7FFF 4 KiB ROM
    bank 15, $8000 and $C000 8 KiB banks from registers 6 and 7, $A000-$AFFF
    4 KiB ROM bank 28, $B000-$BFFF RAM bank 1, $E000 8 KiB bank 15; $8000
    (even) selects a register, $8001 (odd) writes it; registers 2-5 D0 pick
    the CIRAM page of $2000, $2800, $2400 and $2C00. 8 KiB CHR-RAM.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.ram = bytearray(0x2000)
        self.select = 0
        self.pages = [0, 0, 0, 0]  # by nametable: $2000, $2400, $2800, $2C00
        self.map_prg(3, 8, 15)
        self.map_chr(0, 8, 0)

    def _rom4k(self, bank: int, address: int) -> int:
        return self.prg[(bank * 0x1000 + (address & 0xFFF)) % len(self.prg)]

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x7000:
            return self.ram[address & 0xFFF]
        if 0x7000 <= address < 0x8000:
            return self._rom4k(15, address)
        if 0xA000 <= address < 0xB000:
            return self._rom4k(28, address)
        if 0xB000 <= address < 0xC000:
            return self.ram[0x1000 | (address & 0xFFF)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x7000:
            self.ram[address & 0xFFF] = value
        elif 0xB000 <= address < 0xC000:
            self.ram[0x1000 | (address & 0xFFF)] = value
        elif 0x8000 <= address < 0xA000:
            if not address & 1:
                self.select = value & 7
            elif self.select == 6:
                self.map_prg(0, 8, value)
            elif self.select == 7:
                self.map_prg(2, 8, value)
            elif 2 <= self.select <= 5:
                quadrant = (0, 2, 1, 3)[self.select - 2]
                self.pages[quadrant] = value & 1

    def ciram_a10(self, address: int) -> int | None:
        return self.pages[(address >> 10) & 3]


class Board521(Banked):
    """NES 2.0 mapper 521 (Korean Igo): a 16 KiB bank register at $5020 (mask $F030).

    NES_2.0_Mapper_521.wiki: D3-D0 the 16 KiB bank at $8000; $C000 is the
    file's last 16 KiB (a separate chip, so the size need not be a power of
    two). Writes to $5030 are ignored. 8 KiB CHR-RAM; mirroring hard-wired.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 16, 0)
        self.last = len(self.prg) - 0x4000
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0xC000:
            return self.prg[self.last + (address & 0x3FFF)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xF030 == 0x5020:
            self.map_prg(0, 16, value & 0x0F)
        else:
            super().cpu_write(address, value, t)


class Whirlwind125(Banked):
    """Mapper 125 (Whirlwind Manu's Monty no Doki Doki Daisassou): $6000 banked, RAM at $C000.

    INES_Mapper_125.wiki (mask taken as $E000): writes to $6000-$7FFF select
    the 8 KiB bank at $6000 (D3-D0); $8000 is bank 12, $A000 13, $C000-$DFFF
    8 KiB of RAM, $E000 bank 15. 8 KiB CHR-RAM, vertical mirroring.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.ram = bytearray(0x2000)
        self.bank6000 = 0
        for window, bank in ((0, 12), (1, 13), (3, 15)):
            self.map_prg(window, 8, bank)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        if 0xC000 <= address < 0xE000:
            return self.ram[address & 0x1FFF]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.bank6000 = value & 0x0F
        elif 0xC000 <= address < 0xE000:
            self.ram[address & 0x1FFF] = value


class Board526(Banked):
    """NES 2.0 mapper 526 (Sangoku III, BJ-56): direct 1 KiB CHR and 8 KiB PRG registers.

    NES_2.0_Mapper_526.wiki (mask taken as $800F): $8000-$8007 the eight 1
    KiB CHR banks, $8008-$800B the four 8 KiB PRG banks; $800D and $800F
    acknowledge and reset the counter (which does which is unknown; both
    here). The counter counts M2 cycles; its bit 12 drives /IRQ (4096 cycles
    in, 4096 out).
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.counter = 0
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = address & 0x0F
        if register < 8:
            self.map_chr(register, 1, value)
        elif register < 0x0C:
            self.map_prg(register - 8, 8, value)
        elif register in (0x0D, 0x0F):
            self.counter = 0
            self.irq = False

    def m2(self, t: int) -> None:
        self.counter = (self.counter + 1) & 0x1FFF
        self.irq = bool(self.counter & 0x1000)


class SMB3Bootleg106(Banked):
    """Mapper 106: a discrete Super Mario Bros. 3 bootleg (two 128 KiB PRG chips, combined here).

    INES_Mapper_106.wiki (mask $800F): $8000-$8007 the 1 KiB CHR banks
    ($8000/$8002 force D0 low, $8001/$8003 high: 2 KiB pairs); $8008 and
    $800B the 8 KiB banks at $8000/$E000 from the second chip (+16 in the
    combined image), $8009/$800A those at $A000/$C000 (D4 picks the chip);
    $800C D0 the mirroring (0 vertical); a 16-bit counter counts every M2
    cycle until $FFFF, where it stays and asserts /IRQ while enabled; $800D
    clears it and disables, $800E/$800F set its low/high byte ($800F
    enables). 8 KiB of PRG-RAM. Power-on registers 0 (the page has its 74LS670s
    powering up all $F; the game does not care).
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.counter = 0
        self.enabled = False

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        register = address & 0x0F
        if register < 4:
            self.map_chr(register, 1, (value & 0x7E) | register & 1)
        elif register < 8:
            self.map_chr(register, 1, value & 0x7F)
        elif register in (8, 0x0B):
            self.map_prg(register - 8, 8, 16 + (value & 0x0F))
        elif register in (9, 0x0A):
            self.map_prg(register - 8, 8, value & 0x1F)
        elif register == 0x0C:
            self.set_mirroring(HORIZONTAL if value & 1 else VERTICAL)
        elif register == 0x0D:
            self.counter = 0
            self.enabled = False
            self.irq = False
        elif register == 0x0E:
            self.counter = (self.counter & 0xFF00) | value
        else:
            self.counter = (self.counter & 0x00FF) | value << 8
            self.enabled = True

    def m2(self, t: int) -> None:
        if self.counter != 0xFFFF:
            self.counter += 1
        self.irq = self.enabled and self.counter == 0xFFFF


class N32Mapper50(Banked):
    """Mapper 50 (the N-32 SMB2J conversion, "Romeo"): a scrambled bank register and a counter.

    INES_Mapper_050.wiki (mask $4120): $4020 ``....HLLM`` the 8 KiB bank at
    $C000, its bits in the order H, M, L, L; $6000 is bank $0F, $8000 8, $A000
    9, $E000 $0B; $4120 D0 enables the
    counter (clear: acknowledges and resets it). The wiki doubts Disch's
    16-bit counter and expects a 13-bit one with its MSB driving /IRQ: so
    here, /IRQ 4096 M2 cycles after enabling, released 4096 later.
    """

    counts_m2 = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.counter = 0
        self.counting = False
        for window, bank in enumerate((8, 9, 0, 0x0B)):
            self.map_prg(window, 8, bank)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(0x0F * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        register = address & 0x4120
        if address < 0x6000 and register == 0x4020:
            self.map_prg(2, 8, (value & 8) | (value & 1) << 2 | (value >> 1) & 3)
        elif address < 0x6000 and register == 0x4120:
            self.counting = bool(value & 1)
            if not self.counting:
                self.counter = 0
                self.irq = False

    def m2(self, t: int) -> None:
        if self.counting:
            self.counter = (self.counter + 1) & 0x1FFF
            self.irq = bool(self.counter & 0x1000)


class KaiserSMB3(KS7032):
    """Mapper 56 (Kaiser's Super Mario Bros. 3): the KS202 of mapper 142 plus CHR and mirroring.

    INES_Mapper_056.wiki: the KS202's counter and $E000/$F000 bank select and
    data as mapper 142's (banks 1-3 at $8000/$A000/$C000); superimposed on
    $F000-$FFFF: $F000-$F003 (mask $FC03) D4 is PRG A17 of the four windows
    (all 1 at power-on, which the game relies on), $F800 (mask $FC00) D0 the
    mirroring (0 horizontal, 1 vertical), $FC00-$FC07 the eight 1 KiB CHR
    banks. $E000 is bank 15 of the A17 half. 8 KiB of PRG-RAM, not backed.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        self.low = [0, 0, 0, 0x0F]
        self.upper = [1, 1, 1, 1]
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram = bytearray(0x2000)
        self.prg_ram_mask = 0x1FFF
        self.prg_ram_enabled = True
        self._map()

    def _map(self) -> None:
        for window in range(4):
            self.map_prg(window, 8, self.upper[window] << 4 | self.low[window])

    def cpu_read(self, address: int, t: int) -> int | None:
        return Banked.cpu_read(self, address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            Banked.cpu_write(self, address, value, t)
            return
        if address < 0xF000:
            super().cpu_write(address, value, t)  # the counter and the bank select
            return
        if 1 <= self.select <= 3:
            self.low[self.select - 1] = value & 0x0F
        region = address & 0xFC00
        if region == 0xF000:
            self.upper[address & 3] = (value >> 4) & 1
        elif region == 0xF800:
            self.set_mirroring(VERTICAL if value & 1 else HORIZONTAL)
        elif region == 0xFC00:
            self.map_chr(address & 7, 1, value & 0x7F)
        self._map()


class LH15(Banked):
    """Mapper 120 (Whirlwind Manu's Tobidase Daisakusen): $6000 banked by a $41FF register.

    INES_Mapper_120.wiki: $41FF (mask $E100) D2-D0 the 8 KiB bank at $6000;
    $8000-$FFFF 32 KiB bank 2. 8 KiB CHR-RAM, vertical mirroring.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.bank6000 = 0
        self.map_prg(0, 32, 2)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address & 0xE100 == 0x4100:
            self.bank6000 = value & 7


class DokiDoki103(Banked):
    """Mapper 103: a port of the FDS Doki Doki Panic, RAM over parts of the ROM.

    INES_Mapper_103.wiki (mask $F000): $8000 D3-D0 the 8 KiB ROM bank at
    $6000; $E000 D3 the mirroring (0 vertical); $F000 D4 set: ROM instead of
    RAM at $6000-$7FFF and $B800-$D7FF (writes always reach the RAM). Fixed
    ROM otherwise: $8000-$FFFF is the 32 KiB from offset $18000. 8 KiB of RAM
    at $6000 and 8 KiB more at $B800; CHR-RAM. Power-on: RAM visible, bank 0.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False
        self.low_ram = bytearray(0x2000)
        self.high_ram = bytearray(0x2000)
        self.rom_only = False
        self.bank6000 = 0
        self.map_prg(0, 32, 3)
        self.map_chr(0, 8, 0)

    def cpu_read(self, address: int, t: int) -> int | None:
        if 0x6000 <= address < 0x8000:
            if self.rom_only:
                return self.prg[(self.bank6000 * 0x2000 + (address & 0x1FFF)) % len(self.prg)]
            return self.low_ram[address & 0x1FFF]
        if 0xB800 <= address < 0xD800 and not self.rom_only:
            return self.high_ram[address - 0xB800]
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000:
            self.low_ram[address & 0x1FFF] = value
            return
        if 0xB800 <= address < 0xD800:
            self.high_ram[address - 0xB800] = value
        region = address & 0xF000
        if region == 0x8000:
            self.bank6000 = value & 0x0F
        elif region == 0xE000:
            self.set_mirroring(HORIZONTAL if value & 8 else VERTICAL)
        elif region == 0xF000:
            self.rom_only = bool(value & 0x10)


class KS7012(Banked):
    """NES 2.0 mapper 346 (UNL-KS7012: Kaiser's Zanac): 32 KiB banks by magic addresses.

    NES_2.0_Mapper_346.wiki: a write to $E0A0 selects bank 0, to $EE36 bank
    1 (the masks are unknown; exact here), 1 at power-on. 8 KiB of PRG-RAM
    and CHR-RAM.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.map_prg(0, 32, 1)
        self.map_chr(0, 8, 0)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address == 0xE0A0:
            self.map_prg(0, 32, 0)
        elif address == 0xEE36:
            self.map_prg(0, 32, 1)
        else:
            super().cpu_write(address, value, t)
