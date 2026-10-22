"""What most mappers share: PRG and CHR in windows, PRG-RAM, the CIRAM wiring.

A discrete-logic or ASIC mapper is, on the connector, a few registers that
choose which slice of ROM each CPU and PPU address window sees. This base keeps
the windows as offsets (8 KiB on the CPU side, 1 KiB on the PPU side, the finest
grain the licensed mappers need), so a mapper's register writes only recompute
offsets and every access is one index.
"""

from __future__ import annotations

from .connector import Cartridge
from .ines import RomImage

# CIRAM A10 per nametable arrangement (docs/cartridge.md "Nametables"):
# horizontal mirroring takes PPU A11, vertical takes A10, single-screen a constant.
HORIZONTAL, VERTICAL, SCREEN_A, SCREEN_B = "H", "V", "A", "B"


class Banked(Cartridge):
    """PRG in four 8 KiB windows at $8000, CHR in eight 1 KiB windows, PRG-RAM at $6000."""

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__()
        board = image.board
        self.image = image
        self.cpu_cycle_ticks = cpu_cycle_ticks
        self.prg = image.prg
        chr_ram = board.chr_ram + board.chr_nvram
        self.chr_writable = not image.chr
        self.chr: bytes | bytearray = bytearray(chr_ram or 0x2000) if not image.chr else image.chr
        ram_size = board.prg_ram + board.prg_nvram
        self.prg_ram = bytearray(ram_size)
        self.prg_ram_enabled = ram_size > 0
        self.prg_ram_writable = True  # a write-protect bit (MMC3 $A001 D6) clears it
        # The 8 KiB window at $6000: a bank offset for boards with more RAM
        # (SOROM, SXROM), a mask that mirrors smaller chips (2 KiB) through it.
        self.prg_ram_offset = 0
        self.prg_ram_mask = min(ram_size, 0x2000) - 1
        self.battery = board.battery or board.prg_nvram > 0
        self.prg_offsets = [0, 0, 0, 0]
        self.chr_offsets = [0] * 8
        self.four_screen = board.mirroring == "4"
        self.vram = bytearray(0x1000 if self.four_screen else 0)
        self.set_mirroring(VERTICAL if board.mirroring == "V" else HORIZONTAL)

    # -- banking helpers -------------------------------------------------

    def map_prg(self, window: int, size_kib: int, bank: int) -> None:
        """Point ``size_kib`` KiB of CPU space from 8 KiB window ``window`` at ``bank``."""
        base = bank * size_kib * 1024
        for i in range(size_kib // 8):
            self.prg_offsets[window + i] = (base + i * 0x2000) % len(self.prg)

    def map_chr(self, window: int, size_kib: int, bank: int) -> None:
        """Point ``size_kib`` KiB of PPU space from 1 KiB window ``window`` at ``bank``."""
        base = bank * size_kib * 1024
        for i in range(size_kib):
            self.chr_offsets[window + i] = (base + i * 0x400) % len(self.chr)

    def set_mirroring(self, mode: str) -> None:
        self.mirroring = mode

    # -- the connector ---------------------------------------------------

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0x8000:
            return self.prg[self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)]
        if address >= 0x6000 and self.prg_ram_enabled:
            return self.prg_ram[self.prg_ram_offset + (address & self.prg_ram_mask)]
        return None

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if 0x6000 <= address < 0x8000 and self.prg_ram_enabled and self.prg_ram_writable:
            self.prg_ram[self.prg_ram_offset + (address & self.prg_ram_mask)] = value

    def bus_conflict(self, address: int, value: int) -> int:
        """An AND-type bus conflict: the ROM drives the byte at ``address`` as the CPU writes."""
        return value & self.prg[self.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)]

    def ciram_a10(self, address: int) -> int | None:
        mode = self.mirroring
        if self.four_screen:
            return None
        if mode == VERTICAL:
            return (address >> 10) & 1
        if mode == HORIZONTAL:
            return (address >> 11) & 1
        return 0 if mode == SCREEN_A else 1

    def ppu_read(self, address: int, t: int) -> int | None:
        if address < 0x2000:
            return self.chr[self.chr_offsets[address >> 10] + (address & 0x3FF)]
        if self.four_screen:
            return self.vram[address & 0x0FFF]
        return None

    def ppu_write(self, address: int, value: int, t: int) -> None:
        if address < 0x2000:
            if self.chr_writable:
                self.chr[self.chr_offsets[address >> 10] + (address & 0x3FF)] = value
        elif self.four_screen:
            self.vram[address & 0x0FFF] = value

    def battery_ram(self) -> bytes | None:
        return bytes(self.prg_ram) if self.battery else None
