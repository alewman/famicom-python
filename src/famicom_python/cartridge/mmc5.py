"""MMC5 (mapper 5), its banking, ExRAM, scanline detection and vertical split.

MMC5.wiki throughout. The forum's ``mmc5test`` ROMs are not pinned; the claim
rests on milestone 7's sweep against Mesen2, a detector (docs/claims.md). The
sound (milestone 8) is mmc5_sound.py; MMC5A's extras ($5207-$520A, $5800)
and reset detection are not modelled.

**Reading the PPU.** The MMC5 watches the PPU's reads (/RD), not its address
phases: every read reaches the cartridge, nametable-space reads through
:meth:`ciram_a10` (CIRAM's chip select) and pattern reads through
:meth:`ppu_read`. Three consecutive reads of one $2xxx address, then any read,
is the scanline (the wiki's pseudo-code); from the third of those reads the
MMC5 counts reads, four per tile: slots 0-31 are the line's background tiles
(columns 2-33), 32-39 the sprite fetches, 40 and 41 the next line's columns 0
and 1. That count is how it tells sprite fetches from background ones for
8x16 sprites, and where the vertical split is. Three M2 cycles without a read
clear the in-frame flag.
"""

from __future__ import annotations

from .banked import Banked
from .ines import RomImage
from .mmc5_sound import MMC5Sound

SPRITE_SLOTS = range(32, 40)


class MMC5(Banked):
    counts_m2 = True
    expansion_audio = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.prg_ram_enabled = False  # mapped by the PRG registers, not Banked's window
        self.exram = bytearray(0x400)
        self.prg_mode = 3
        self.prg_registers = [0, 0, 0, 0, 0xFF]  # $5113-$5117
        self.protect = [1, 2]
        self.exram_mode = 3
        self.nametables = [0, 0, 0, 0]
        self.fill_tile = self.fill_attribute = 0
        self.chr_mode = 3
        self.chr_high = 0  # $5130
        self.chr_registers = [0] * 12  # 10-bit, $5120-$512B
        self.last_chr_set_b = False
        self.sprites_8x16 = False
        self.substitutions = False
        self.split_control = 0
        self.split_scroll = self.split_bank = 0
        self.irq_target = 0
        self.irq_enabled = self.irq_pending = False
        self.in_frame = False
        self.scanline = 0
        self.multiplicand = self.multiplier = 0xFF
        # Scanline detection and the fetch count.
        self.last_read = -1
        self.matches = 0
        self.fetch = 0  # reads since the scanline's third matching read
        self.read_since_m2 = False
        self.idle = 0
        self.ext_tile = 0  # ExRAM byte of the tile being fetched (extended attributes)
        self.split_tile = 0  # ExRAM offset of the split region's tile
        self.in_split = False
        self.prg_windows: list[tuple[bool, int] | None] = [None] * 5
        self.chr_a = [0] * 8  # 1 KiB window offsets: $5120-$5127
        self.chr_b = [0] * 8  # $5128-$512B
        self.sound = MMC5Sound(self)
        self._update_prg()
        self._update_chr()

    # -- PRG -------------------------------------------------------------

    def _ram_offset(self, bank: int) -> int | None:
        """PRG-RAM by bank (MMC5.wiki "PRG-RAM configurations"): D2 picks one of
        two chips, D1-D0 an 8 KiB page within it. One chip of 8 or 32 KiB
        answers D2 = 0 only; 16 KiB is two 8 KiB chips; 64 KiB two of 32."""
        size = len(self.prg_ram)
        if not size:
            return None
        chip = (bank >> 2) & 1
        two_chips = size in (0x4000, 0x10000)
        chip_size = size // 2 if two_chips else size
        if chip and not two_chips:
            return None
        return chip * chip_size + ((bank & 3) * 0x2000) % chip_size

    def _update_prg(self) -> None:
        """The five 8 KiB windows, $6000-$FFFF, as (is ROM, offset) or None (open bus)."""
        r = self.prg_registers
        windows: list[tuple[bool, int] | None] = [None] * 5
        ram = self._ram_offset(r[0] & 0x0F)
        windows[0] = None if ram is None else (False, ram)
        mode = self.prg_mode
        prg_len = len(self.prg)
        # (register, size in 8 KiB units) for $8000, $A000, $C000, $E000
        layout = {
            0: [(4, 4)] * 4,
            1: [(2, 2), (2, 2), (4, 2), (4, 2)],
            2: [(2, 2), (2, 2), (3, 1), (4, 1)],
            3: [(1, 1), (2, 1), (3, 1), (4, 1)],
        }[mode]
        for window, (register, units) in enumerate(layout):
            value = r[register]
            bank = (value & 0x7F) & ~(units - 1) | (window & (units - 1))
            if register == 4 or value & 0x80:
                windows[window + 1] = (True, bank * 0x2000 % prg_len)
            else:
                ram = self._ram_offset(bank & 0x0F)
                windows[window + 1] = None if ram is None else (False, ram)
        self.prg_windows = windows

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x6000:
            if address >= 0xFFFA and address < 0xFFFC:  # the NMI vector: vblank
                self._leave_frame()
                self.irq_pending = False
                self._update_irq()
            window = self.prg_windows[(address - 0x6000) >> 13]
            if window is None:
                return None
            rom, offset = window
            value = (self.prg if rom else self.prg_ram)[offset + (address & 0x1FFF)]
            if self.sound.read_mode and 0x8000 <= address < 0xC000:
                self.sound.dac(value)  # PCM read mode: the byte goes to the DAC too
                self._update_irq()
            return value
        if address >= 0x5C00:
            return self.exram[address - 0x5C00] if self.exram_mode >= 2 else None
        if address == 0x5204:
            value = (0x80 if self.irq_pending else 0) | (0x40 if self.in_frame else 0)
            self.irq_pending = False
            self._update_irq()
            return value
        if address == 0x5010 or address == 0x5015:
            value = self.sound.read(address)
            self._update_irq()
            return value
        if address == 0x5205:
            return (self.multiplicand * self.multiplier) & 0xFF
        if address == 0x5206:
            return (self.multiplicand * self.multiplier) >> 8
        return None

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x6000:
            window = self.prg_windows[(address - 0x6000) >> 13]
            if window is not None and not window[0] and self.protect == [2, 1]:
                self.prg_ram[window[1] + (address & 0x1FFF)] = value
            return
        if address < 0x5000:
            self._snoop(address, value)
        elif address >= 0x5C00:
            if self.exram_mode != 3:
                # Modes 0 and 1 take writes only while rendering; at other
                # times "they may be ignored or cause a corruption": 0 here,
                # as Mesen2 writes (Mappers/Nintendo/MMC5.h).
                self.exram[address - 0x5C00] = value if self.exram_mode == 2 or self.in_frame else 0
        elif address <= 0x5015:
            self.sound.write(address, value)
            self._update_irq()
        elif 0x5100 <= address <= 0x5206:
            self._register(address, value)

    def _snoop(self, address: int, value: int) -> None:
        """Writes the MMC5 overhears: PPUCTRL, PPUMASK, OAMDMA (fully decoded)."""
        if address == 0x2000:
            self.sprites_8x16 = bool(value & 0x20)
        elif address == 0x2001:
            enabled = bool(value & 0x18)
            if not enabled:
                self._leave_frame()
            self.substitutions = enabled
        elif address == 0x4014:
            self._leave_frame()

    def _register(self, address: int, value: int) -> None:
        if address == 0x5100:
            self.prg_mode = value & 3
            self._update_prg()
        elif address == 0x5101:
            self.chr_mode = value & 3
            self._update_chr()
        elif address in (0x5102, 0x5103):
            self.protect[address - 0x5102] = value & 3
        elif address == 0x5104:
            self.exram_mode = value & 3
        elif address == 0x5105:
            self.nametables = [(value >> shift) & 3 for shift in (0, 2, 4, 6)]
        elif address == 0x5106:
            self.fill_tile = value
        elif address == 0x5107:
            self.fill_attribute = (value & 3) * 0x55
        elif 0x5113 <= address <= 0x5117:
            self.prg_registers[address - 0x5113] = value
            self._update_prg()
        elif 0x5120 <= address <= 0x512B:
            self.chr_registers[address - 0x5120] = self._chr_register(value)
            self.last_chr_set_b = address >= 0x5128
            self._update_chr()
        elif address == 0x5130:
            self.chr_high = value & 3
        elif address == 0x5200:
            self.split_control = value
        elif address == 0x5201:
            self.split_scroll = value
        elif address == 0x5202:
            self.split_bank = value
        elif address == 0x5203:
            self.irq_target = value
        elif address == 0x5204:
            self.irq_enabled = bool(value & 0x80)
            self._update_irq()
        elif address == 0x5205:
            self.multiplicand = value
        elif address == 0x5206:
            self.multiplier = value

    # -- CHR -------------------------------------------------------------

    def _chr_register(self, value: int) -> int:
        """The 10 bits a $512x write stores, by CHR mode (MMC5.wiki's table; its
        "?" bits taken as 0)."""
        mode = self.chr_mode
        if mode == 3:
            return self.chr_high << 8 | value
        if mode == 2:
            return (self.chr_high & 1) << 9 | value << 1 | (value & 1)
        if mode == 1:
            return value << 2 | (value & 1)
        return (value & 0x7F) << 3 | (value & 1)

    def _update_chr(self) -> None:
        """Each set's eight 1 KiB windows: in mode m a register covers 2**(3-m)
        KiB, its low 3-m bits replaced by the PPU address."""
        mode = self.chr_mode
        span = 8 >> mode  # 1 KiB windows per bank
        size = len(self.chr)
        regs = self.chr_registers
        for window in range(8):
            first = window - window % span
            a = regs[first + span - 1]
            b = regs[8 + ((first + span - 1) & 3)]
            low = window % span
            self.chr_a[window] = (((a & ~(span - 1)) | low) << 10) % size
            self.chr_b[window] = (((b & ~(span - 1)) | low) << 10) % size

    def ppu_read(self, address: int, t: int) -> int | None:
        if address >= 0x2000:
            return self._nametable_byte(address)
        self._read(address)
        slot = self.fetch >> 2
        if self.in_frame and self.substitutions:
            if self.in_split and slot not in SPRITE_SLOTS:
                # CHR A2-A0 from the PPU: Nintendo's boards are wired "CL",
                # so the split's fine scroll is the PPU's (MMC5_pinout.wiki).
                return self.chr[(self.split_bank * 0x1000 + (address & 0xFFF)) % len(self.chr)]
            if self.exram_mode == 1 and slot not in SPRITE_SLOTS:
                bank = self.chr_high << 6 | (self.ext_tile & 0x3F)
                return self.chr[(bank * 0x1000 + (address & 0xFFF)) % len(self.chr)]
            if self.sprites_8x16:
                offsets = self.chr_a if slot in SPRITE_SLOTS else self.chr_b
                return self.chr[offsets[address >> 10] + (address & 0x3FF)]
        elif self.sprites_8x16 and self.last_chr_set_b:
            return self.chr[self.chr_b[address >> 10] + (address & 0x3FF)]
        return self.chr[self.chr_a[address >> 10] + (address & 0x3FF)]

    # -- nametables ------------------------------------------------------

    def ciram_a10(self, address: int) -> int | None:
        self._read(address)
        if self.in_frame and self.substitutions:
            if self.in_split:
                return None
            if self.exram_mode == 1 and address & 0x3FF >= 0x3C0:
                return None  # extended attributes replace the attribute byte
        source = self.nametables[(address >> 10) & 3]
        return source if source < 2 else None

    def _nametable_byte(self, address: int) -> int:
        attribute = address & 0x3FF >= 0x3C0
        if self.in_frame and self.substitutions:
            if self.in_split:
                if attribute:
                    tile = self.split_tile
                    shift = ((tile >> 4) & 4) | (tile & 2)
                    at = 0x3C0 | ((tile & 0x380) >> 4) | ((tile & 0x1F) >> 2)
                    return ((self.exram[at] >> shift) & 3) * 0x55
                return self.exram[self.split_tile]
            if self.exram_mode == 1 and attribute:
                return (self.ext_tile >> 6) * 0x55
        source = self.nametables[(address >> 10) & 3]
        if source == 2:
            return self.exram[address & 0x3FF] if self.exram_mode < 2 else 0
        return self.fill_attribute if attribute else self.fill_tile

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            if self.chr_writable:
                self.chr[self.chr_a[address >> 10] + (address & 0x3FF)] = value
        elif self.nametables[(address >> 10) & 3] == 2 and self.exram_mode < 2:
            self.exram[address & 0x3FF] = value

    # -- scanline detection, the fetch count, the split ---------------------

    def _read(self, address: int) -> None:
        """One PPU /RD (the wiki's pseudo-code, with the fetch count)."""
        self.read_since_m2 = True
        self.fetch += 1
        if 0x2000 <= address < 0x3000 and address == self.last_read:
            self.matches += 1
            if self.matches == 2:  # the third matching read: column 2's tile
                self.fetch = 0
        elif self.matches >= 2:
            self.matches = 0
            self._scanline()
        else:
            self.matches = 0
        self.last_read = address
        if 0x2000 <= address < 0x3000 and not self.fetch & 3:
            self._tile(address)

    def _scanline(self) -> None:
        if not self.in_frame:
            self.in_frame = True
            self.scanline = 0
        else:
            self.scanline += 1
            if self.scanline == self.irq_target and self.irq_target:
                self.irq_pending = True
                self._update_irq()

    def _tile(self, address: int) -> None:
        """A tile's nametable read: its extended attribute, and whether it is in the split."""
        slot = self.fetch >> 2
        if self.exram_mode == 1:
            self.ext_tile = self.exram[address & 0x3FF]
        control = self.split_control
        if not control & 0x80 or self.exram_mode >= 2 or SPRITE_SLOTS.start <= slot < 40:
            self.in_split = False
            return
        column = slot + 2 if slot < 32 else slot - 40
        threshold = control & 0x1F
        right = bool(control & 0x40)
        self.in_split = column >= threshold if right else column < threshold
        if self.in_split:
            line = (self.scanline + (1 if slot >= 40 else 0) + self.split_scroll) % 240
            self.split_tile = (line & 0xF8) << 2 | column

    def m2(self, t: int) -> None:
        self.sound.m2()
        if self.read_since_m2:
            self.read_since_m2 = False
            self.idle = 0
        else:
            self.idle += 1
            if self.idle == 3:
                self._leave_frame()

    def _leave_frame(self) -> None:
        self.in_frame = False
        self.last_read = -1
        self.matches = 0

    def _update_irq(self) -> None:
        self.irq = (self.irq_pending and self.irq_enabled) or self.sound.irq

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg_ram) if self.battery else None
