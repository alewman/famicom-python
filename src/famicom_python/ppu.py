"""The RP2C02 picture processor: registers, its 14-bit bus, and frame timing.

**Milestone 1 scope.** This is the PPU as the CPU sees it: the eight registers
with loopy's v/t/x/w (PPU_registers.wiki, PPU_scrolling.wiki), the read buffer,
palette RAM, OAM through $2003/$2004, the I/O latch (without decay), the power-up
write ignore, and the frame clock: 341 dots by 262 lines, VBL set on (241, 1)
and cleared on (261, 1), /NMI, and the odd-frame dot skip (docs/timing.md "The
PPU"). It does not render: no fetches, no sprite evaluation, no sprite-0 hit, no
pixels, and none of the read and enable races. Milestone 2 replaces the dot body
with the full schedule, every fetch on the connector.

The bus: pattern tables ($0000-$1FFF) are the cartridge's; nametables
($2000-$3EFF) are CIRAM, 2 KiB on the console, whose A10 and /CE the cartridge
drives (``Cartridge.ciram_a10``); palette RAM ($3F00-$3FFF) is inside the PPU.
An undriven read returns the address's low byte (docs/cartridge.md).
"""

from __future__ import annotations

from .cartridge.connector import Cartridge
from .machine import Timing

DOTS = 341
VBL, SPRITE0, OVERFLOW = 0x80, 0x40, 0x20


class PPU:
    def __init__(self, timing: Timing, cartridge: Cartridge, alignment: int = 0) -> None:
        self.timing = timing
        self.cartridge = cartridge
        self.lines = timing.lines
        self.vblank_line = timing.vblank_line
        self.prerender_line = timing.lines - 1
        self.dot_ticks = timing.dot_divider
        self.ciram = bytearray(0x800)
        self.palette = bytearray(0x20)
        self.oam = bytearray(0x100)
        # The next dot runs at master tick ``time``; alignment shifts the dot
        # clock against the CPU's (machine.PowerOn).
        self.time = alignment
        self.line = 0
        self.dot = 0
        self.frame = 0
        self.power()

    # -- power and reset -------------------------------------------------

    def power(self) -> None:
        self.status = 0
        self.oam_addr = 0
        self.v = 0
        self.reset()

    def reset(self) -> None:
        """The reset line: PPUCTRL, PPUMASK, t, x, w and the buffer clear; v does not.

        Writes to $2000, $2001, $2005 and $2006 are ignored until the reset flag
        clears at the next pre-render line (PPU_power_up_state.wiki; blargg 2008).
        """
        self.ctrl = 0
        self.mask = 0
        self.t = 0
        self.x = 0
        self.w = 0
        self.buffer = 0
        self.latch = 0
        self.resetting = True
        self.nmi = False

    # -- the clock -------------------------------------------------------

    def run_to(self, time: int) -> None:
        """Run every dot that begins before master tick ``time``."""
        while self.time < time:
            self.time += self.dot_ticks
            dot = self.dot + 1
            if dot == DOTS:
                dot = 0
                line = self.line + 1
                if line == self.lines:
                    line = 0
                    self.frame += 1
                self.line = line
            elif (
                dot == DOTS - 1
                and self.line == self.prerender_line
                and self.frame & 1
                and self.mask & 0x18
                and self.timing.odd_frame_skip
            ):
                # Odd frames with rendering on skip the last pre-render dot
                # (PPU_frame_timing.wiki).
                dot = 0
                self.line = 0
                self.frame += 1
            self.dot = dot
            if dot == 1:
                line = self.line
                if line == self.vblank_line:
                    self.status |= VBL
                    self.nmi = bool(self.ctrl & 0x80)
                elif line == self.prerender_line:
                    self.status &= ~(VBL | SPRITE0 | OVERFLOW)
                    self.nmi = False
                    self.resetting = False

    # -- the PPU bus -----------------------------------------------------

    def bus_read(self, address: int) -> int:
        address &= 0x3FFF
        cartridge = self.cartridge
        if address >= 0x2000:
            a10 = cartridge.ciram_a10(address)
            if a10 is not None:
                return self.ciram[(a10 << 10) | (address & 0x3FF)]
        value = cartridge.ppu_read(address, self.time)
        return address & 0xFF if value is None else value

    def bus_write(self, address: int, value: int) -> None:
        address &= 0x3FFF
        cartridge = self.cartridge
        if address >= 0x2000:
            a10 = cartridge.ciram_a10(address)
            if a10 is not None:
                self.ciram[(a10 << 10) | (address & 0x3FF)] = value
                return
        cartridge.ppu_write(address, value, self.time)

    @staticmethod
    def palette_index(address: int) -> int:
        # $3F10/$14/$18/$1C are the cells of $3F00/$04/$08/$0C (PPU_palettes.wiki).
        index = address & 0x1F
        return index & 0x0F if index & 0x13 == 0x10 else index

    # -- the CPU's registers ---------------------------------------------

    def read_register(self, register: int) -> int:
        if register == 2:
            value = (self.status & 0xE0) | (self.latch & 0x1F)
            self.status &= ~VBL
            self.nmi = False
            self.w = 0
            self.latch = value
            return value
        if register == 4:
            value = self.oam[self.oam_addr]
            if self.oam_addr & 3 == 2:
                value &= 0xE3  # attribute bits 4-2 do not exist
            self.latch = value
            return value
        if register == 7:
            v = self.v & 0x3FFF
            if v >= 0x3F00:
                value = self.palette[self.palette_index(v)]
                if self.mask & 0x01:
                    value &= 0x30
                value |= self.latch & 0xC0
                self.buffer = self.bus_read(v - 0x1000)  # the nametable underneath
            else:
                value = self.buffer
                self.buffer = self.bus_read(v)
            self.v = (self.v + (32 if self.ctrl & 0x04 else 1)) & 0x7FFF
            self.latch = value
            return value
        return self.latch  # write-only registers read the I/O latch

    def write_register(self, register: int, value: int) -> None:
        self.latch = value
        if register == 0:
            if self.resetting:
                return
            self.ctrl = value
            self.t = (self.t & ~0x0C00) | ((value & 0x03) << 10)
            self.nmi = bool(value & 0x80 and self.status & VBL)
        elif register == 1:
            if not self.resetting:
                self.mask = value
        elif register == 3:
            self.oam_addr = value
        elif register == 4:
            self.oam[self.oam_addr] = value
            self.oam_addr = (self.oam_addr + 1) & 0xFF
        elif register == 5:
            if self.resetting:
                return
            if self.w == 0:
                self.t = (self.t & ~0x001F) | (value >> 3)
                self.x = value & 0x07
            else:
                self.t = (self.t & ~0x73E0) | ((value & 0x07) << 12) | ((value & 0xF8) << 2)
            self.w ^= 1
        elif register == 6:
            if self.resetting:
                return
            if self.w == 0:
                self.t = (self.t & 0x00FF) | ((value & 0x3F) << 8)
            else:
                self.t = (self.t & 0x7F00) | value
                self.v = self.t
            self.w ^= 1
        elif register == 7:
            v = self.v & 0x3FFF
            if v >= 0x3F00:
                self.palette[self.palette_index(v)] = value & 0x3F
            else:
                self.bus_write(v, value)
            self.v = (self.v + (32 if self.ctrl & 0x04 else 1)) & 0x7FFF

    def oam_dma_write(self, value: int) -> None:
        """A DMA write to $2004."""
        self.write_register(4, value)
