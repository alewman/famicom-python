"""Namco's mappers: the 108 family (206), the 129/163 (19) and the 175/340 (210).

No judge ROM exists for any of them (docs/cartridge.md); their claims rest on
milestone 7's sweep against Mesen2, a detector (docs/claims.md). The 163's
sound level is the board's submapper (its mixing resistor), from the
measurements on the wiki (milestone 8).
"""

from __future__ import annotations

from .banked import HORIZONTAL, SCREEN_A, SCREEN_B, VERTICAL, Banked
from .connector import expansion_gain
from .ines import RomImage

#: A full-volume N163 square, one channel, against a full-volume APU square
#: (dB), by NES 2.0 submapper: the mixing resistor, set from the games'
#: measurements (INES_Mapper_019/Submapper_table: 11.0-13.0, 16.0-17.0 and
#: 18.0-19.5 dB; the middle of each). Submapper 0 leaves it unspecified: the
#: median of the nine games measured (Namco_163_audio.wiki "Mixing"), 18.0.
#: Submappers 1 and 2: no sound.
N163_DB = {0: 18.0, 3: 12.0, 4: 16.5, 5: 18.75}
N163_UPDATE = 15  # CPU cycles per channel update (Namco_163_audio.wiki)


class Namco108(Banked):
    """Mapper 206: Namco 108/109/118/119 and Tengen MIMIC-1, the MMC3's predecessor.

    INES_Mapper_206.wiki: registers at $8000-$9FFF only (mask $E001): an even
    address selects one of eight bank registers, an odd one writes it, as the
    MMC3's R0-R7 without its mode bits. PRG: 8 KiB at $8000 and $A000, the
    last 16 KiB fixed; CHR: 2 KiB x 2 at $0000, 1 KiB x 4 at $1000. Register
    bits beyond the chips' pins are dropped (128 KiB PRG, 64 KiB CHR). No
    IRQ, no PRG-RAM, nametables hard-wired (four-screen on Gauntlet).
    Submapper 1 (PCBs 3407, 3417, 3451) leaves 32 KiB of PRG unbanked.
    Not modelled: the Namco 108's spurious bank switch on a RAM write while
    executing from $8000-$9FFF (the wiki's errata), which games avoid. Power-on
    registers unspecified: 0 here, and the games initialise them.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.unbanked = image.board.submapper == 1
        self.prg_ram_enabled = False
        self.bank_select = 0
        self.registers = [0] * 8
        self._update()

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x8000 <= address < 0xA000:
            if address & 1:
                self.registers[self.bank_select] = value
                self._update()
            else:
                self.bank_select = value & 7

    def _update(self) -> None:
        r = self.registers
        if self.unbanked:
            self.map_prg(0, 32, 0)
        else:
            last = len(self.prg) // 0x2000 - 1
            self.map_prg(0, 8, r[6] & 0x0F)
            self.map_prg(1, 8, r[7] & 0x0F)
            self.map_prg(2, 8, last - 1)
            self.map_prg(3, 8, last)
        self.map_chr(0, 2, (r[0] & 0x3E) >> 1)
        self.map_chr(2, 2, (r[1] & 0x3E) >> 1)
        for i in range(4):
            self.map_chr(4 + i, 1, r[2 + i] & 0x3F)


class Namco163(Banked):
    """Mapper 19: Namco 129/163: 1 KiB CHR banks, nametables from CIRAM or CHR-ROM, a cycle IRQ.

    INES_Mapper_019.wiki; each register decodes $800 bytes:

    - $8000-$BFFF: the eight CHR banks. $C000-$DFFF: the four nametables, a
      value of $E0 or more being CIRAM (even A, odd B), anything else a 1 KiB
      page of CHR-ROM.
    - $E000 D5-D0, $E800 D5-D0, $F000 D5-D0: PRG at $8000, $A000, $C000; the
      last 8 KiB fixed.
    - $F800: PRG-RAM write protection (writes need the high nibble 4 and the
      2 KiB window's bit clear) and the address port of the 128-byte chip RAM
      (D6-D0, D7 auto-increment), read and written through $4800.
    - $5000/$5800: the 15-bit IRQ counter itself, and $5800 D7 its enable,
      both readable; writing either acknowledges. The counter counts up each
      CPU cycle and stops at $7FFF, asserting /IRQ. The wiki has it count
      always; that it counts only while enabled is Mesen2's reading
      (Mappers/Namco/Namco163.h), the only one there is.

    The sound (Namco_163_audio.wiki): the chip RAM's top 8 bytes per channel
    are its registers (channel 8 at $78-$7F; $7F D6-D4 the channels enabled
    less one). Every 15 CPU cycles one channel, from 8 downwards, adds its
    18-bit frequency to its 24-bit phase and outputs (sample - 8) x volume,
    held until the next update: the channels are not mixed but take turns,
    as on the chip (the wiki's "high-pitched whining" with 8). $E000 D6
    silences it.

    Not modelled: pattern-table banks of $E0 and up selecting CIRAM (with
    $E800 D6/D7 clear), which would need CIRAM enabled below $2000 on the
    connector and which no licensed game is known to use. Power-on registers
    unspecified: 0 here.
    """

    counts_m2 = True
    expansion_audio = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.chip_ram = bytearray(0x80)
        self.chip_address = 0
        self.protect = 0
        self.counter = 0
        self.irq_enabled = False
        self.nametables = [0xE0, 0xE1, 0xE0, 0xE1]
        self.nametable_offsets = [0, 0, 0, 0]
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)
        submapper = image.board.submapper
        self.expansion_audio = submapper in N163_DB
        # A full-volume square: samples 0 and 15 at volume 15, -120 to +105.
        self.gain = expansion_gain(N163_DB.get(submapper, 0.0), 225)
        self.sound_enabled = True  # $E000 D6 clear
        self.update = N163_UPDATE
        self.channel = 7  # the next to update, 7 (channel 8) downwards

    def m2(self, t: int) -> None:
        if self.irq_enabled and self.counter < 0x7FFF:
            self.counter += 1
            if self.counter == 0x7FFF:
                self.irq = True
        self.update -= 1
        if not self.update:
            self.update = N163_UPDATE
            if self.sound_enabled:
                self._update_channel()

    def _update_channel(self) -> None:
        ram = self.chip_ram
        channel = self.channel
        base = 0x40 + 8 * channel
        frequency = (ram[base + 4] & 3) << 16 | ram[base + 2] << 8 | ram[base]
        phase = ram[base + 5] << 16 | ram[base + 3] << 8 | ram[base + 1]
        length = 256 - (ram[base + 4] & 0xFC)
        phase = (phase + frequency) % (length << 16)
        ram[base + 5], ram[base + 3], ram[base + 1] = phase >> 16, (phase >> 8) & 0xFF, phase & 0xFF
        index = ((phase >> 16) + ram[base + 6]) & 0xFF
        sample = (ram[index >> 1] >> ((index & 1) << 2)) & 0x0F
        self.audio_out.expansion = (sample - 8) * (ram[base + 7] & 0x0F) * self.gain
        lowest = 7 - ((ram[0x7F] >> 4) & 7)
        self.channel = channel - 1 if channel > lowest else 7

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x6000:
            return super().cpu_read(address, t)
        region = address & 0xF800
        if region == 0x4800:
            value = self.chip_ram[self.chip_address & 0x7F]
            self._step_chip_address()
            return value
        if region == 0x5000:
            return self.counter & 0xFF
        if region == 0x5800:
            return (self.counter >> 8) | (0x80 if self.irq_enabled else 0)
        return None

    def _step_chip_address(self) -> None:
        if self.chip_address & 0x80:
            self.chip_address = 0x80 | ((self.chip_address + 1) & 0x7F)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            if address >= 0x6000:
                window = (address >> 11) & 3
                if self.protect & 0xF0 == 0x40 and not self.protect & (1 << window):
                    super().cpu_write(address, value, t)
                return
            region = address & 0xF800
            if region == 0x4800:
                self.chip_ram[self.chip_address & 0x7F] = value
                self._step_chip_address()
            elif region == 0x5000:
                self.counter = (self.counter & 0x7F00) | value
                self.irq = False
            elif region == 0x5800:
                self.counter = (self.counter & 0xFF) | (value & 0x7F) << 8
                self.irq_enabled = bool(value & 0x80)
                self.irq = False
            return
        region = address & 0xF800
        if region < 0xC000:
            self.map_chr((region - 0x8000) >> 11, 1, value)
        elif region < 0xE000:
            slot = (region - 0xC000) >> 11
            self.nametables[slot] = value
            self.nametable_offsets[slot] = (value * 0x400) % len(self.chr)
        elif region == 0xF800:
            self.protect = value
            self.chip_address = value
        else:
            if region == 0xE000:
                self.sound_enabled = not value & 0x40
                if not self.sound_enabled:
                    self.audio_out.expansion = 0.0
            self.map_prg((region - 0xE000) >> 11, 8, value & 0x3F)

    def ciram_a10(self, address: int) -> int | None:
        value = self.nametables[(address >> 10) & 3]
        return value & 1 if value >= 0xE0 else None

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            return self.chr[self.chr_offsets[address >> 10] + (address & 0x3FF)]
        return self.chr[self.nametable_offsets[(address >> 10) & 3] + (address & 0x3FF)]

    def ppu_write(self, address: int, value: int, t: int) -> None:
        """CHR-ROM ignores writes; the commercial boards have no CHR-RAM."""

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg_ram) + bytes(self.chip_ram) if self.battery else None


class Namco175(Banked):
    """Mapper 210: Namco 175 (210.1) and 340 (210.2), the 163's banking without its extras.

    INES_Mapper_210.wiki: $8000-$BFFF the eight 1 KiB CHR banks (decoding $800
    bytes each), $E000/$E800/$F000 D5-D0 PRG at $8000/$A000/$C000, the last
    8 KiB fixed. The 175 has PRG-RAM enabled by $C000 D0 and hard-wired
    nametables; the 340 has no RAM and takes $E000 D7-D6 as the arrangement
    (0 one-screen A, 1 vertical, 2 one-screen B, 3 horizontal). Without a
    submapper the wiki's rule applies: a battery means the 175. Power-on
    registers unspecified: 0 here, with the 175's RAM disabled.
    """

    ARRANGEMENTS = (SCREEN_A, VERTICAL, SCREEN_B, HORIZONTAL)

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        submapper = image.board.submapper
        self.is_340 = submapper == 2 or (submapper != 1 and not image.board.battery)
        self.prg_ram_enabled = False
        self.map_prg(3, 8, len(self.prg) // 0x2000 - 1)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x8000:
            super().cpu_write(address, value, t)
            return
        region = address & 0xF800
        if region < 0xC000:
            self.map_chr((region - 0x8000) >> 11, 1, value)
        elif region == 0xC000:
            if not self.is_340:
                self.prg_ram_enabled = bool(self.prg_ram) and bool(value & 1)
        elif 0xE000 <= region < 0xF800:
            self.map_prg((region - 0xE000) >> 11, 8, value & 0x3F)
            if region == 0xE000 and self.is_340:
                self.set_mirroring(self.ARRANGEMENTS[value >> 6])
