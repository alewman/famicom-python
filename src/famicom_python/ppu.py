"""The RP2C02 picture processor, dot by dot, every fetch on its bus.

A frame is 262 lines of 341 dots (docs/timing.md "The PPU"). :meth:`PPU.run_to`
executes dots in order; each dot does what the 2C02 does on it, from the
schedule of PPU_rendering.wiki and its frame-timing diagram (Ntsc_timing.png,
die-derived from Visual 2C02):

- **Background** (lines 0-239 and the pre-render line, dots 1-256 and 321-336):
  each tile is four fetches of two dots, address (ALE) on the first and /RD on
  the second: nametable, attribute, pattern low, pattern high. Shifts on dots
  2-257 and 322-337, reloads on 9, 17, ..., 257 and 329, 337; coarse X++ on every
  8th dot, Y++ on 256, hori(v) = hori(t) on 257, vert(v) = vert(t) on 280-304 of
  the pre-render line (PPU_scrolling.wiki). Dots 337-340 fetch the next
  nametable byte twice.
- **Sprites**: secondary OAM cleared on dots 1-64, evaluated on 65-256 (odd dots
  read OAM, even dots write secondary OAM, with the overflow check's diagonal
  scan), fetched on 257-320: two garbage nametable fetches and the pattern pair
  per slot, tile $FF for empty slots (PPU_sprite_evaluation.wiki). OAMADDR is 0
  on each of 257-320.
- **Pixels**: pixel x is chosen on dot x + 2 from the shifters before they shift
  ("sprite 0 hit acts as if the image starts at cycle 2", PPU_rendering.wiki),
  through the priority multiplexer; the output is the 9-bit ``eeellcccc``
  (emphasis, palette value) of docs/start-here.md "Output format". With
  rendering off a visible dot shows the backdrop, or the palette entry v points
  at (backdrop override, PPU_palettes.wiki).
- **Frame events**: VBL set on (241, 1) unless a $2002 read on (241, 0)
  suppressed it, cleared with sprite 0 and overflow on (261, 1); /NMI low while
  VBL and PPUCTRL.7; odd frames with rendering on skip (339, 261) -> (0, 0)
  (PPU_frame_timing.wiki, NMI.wiki).

**What a read or write "at a dot" means here.** The board runs the PPU to the
point inside each CPU cycle where the PPU sees a register access, two dots in
(board.py), so an access sees every dot up to and including :attr:`line` and
:attr:`dot`, and its effect lands before the next dot; the CPU samples /NMI at
the cycle's end. That gives the races of docs/timing.md in blargg's preferred
synchronization, settled against ``ppu_vbl_nmi`` and ``vbl_nmi_timing``
(docs/validation.md, milestone 2).

The bus: pattern tables ($0000-$1FFF) are the cartridge's; nametables
($2000-$3EFF) are CIRAM, 2 KiB on the console, whose A10 and /CE the cartridge
drives (``Cartridge.ciram_a10``); palette RAM ($3F00-$3FFF) is inside the PPU.
An undriven read returns the address's low byte (docs/cartridge.md). A
cartridge that sets ``watches_ppu_address`` also sees every ALE dot's address.
"""

from __future__ import annotations

from array import array
from collections.abc import Callable

from .cartridge.connector import Cartridge
from .machine import Timing

# Dots after the access before a register write's effect: 0 is the first dot
# after the CPU cycle's access point (board.PPU_ACCESS_TICKS). Measured on
# Breaknes PPUSim co-simulated at the skew where it passes ppu_vbl_nmi
# (scripts/ppusim_compare.py, docs/validation.md milestone 2); no test ROM pins
# them (undocumented-behavior.md C21, C22).
DELAYS = {
    "2006_copy": 2,  # the second $2006 write's t -> v copy
    "2007_write": 3,  # a $2007 write reaches palette RAM or the bus
    "2007_increment": 4,  # ... and v increments (after a $2007 read too)
}
# A $2007 read's buffer refill lands with its increment, and a second read
# before then is ignored: it returns the buffer and starts nothing. PPUSim at
# the board's skew prints blargg's hardware results for both reads one CPU
# cycle apart (dmc_dma_during_read4: double_2007_read F018C287, dma_2007_read
# 159A7A8F; docs/validation.md milestone 3).

DOTS = 341
WIDTH, HEIGHT = 256, 240
VBL, SPRITE0, OVERFLOW = 0x80, 0x40, 0x20
# Sprite line-buffer entries: palette index (0x10-0x1F), then these flags.
BEHIND, IS_SPRITE0 = 0x20, 0x40


class PPU:
    def __init__(
        self,
        timing: Timing,
        cartridge: Cartridge,
        latch_decay_seconds: float = 0.6,
    ) -> None:
        self.timing = timing
        self.cartridge = cartridge
        self.lines = timing.lines
        self.vblank_line = timing.vblank_line
        self.prerender_line = timing.lines - 1
        self.dot_ticks = timing.dot_divider
        self.odd_frame_skip = timing.odd_frame_skip
        self.ciram = bytearray(0x800)
        self.palette = bytearray(0x20)
        self.oam = bytearray(0x100)
        self.oam2 = bytearray(b"\xff" * 32)  # secondary OAM
        # The picture: 240 rows of 256 9-bit values, written as the dots run.
        self.picture = array("H", bytes(2 * WIDTH * HEIGHT))
        # The next dot runs at master tick ``time``.
        self.time = 0
        self.line = 0
        self.dot = 0
        self.frame = 0
        self._watch = cartridge.watches_ppu_address
        # The I/O latch's bits decay to 0 when not driven for this long
        # (Machine.ppu_latch_decay_seconds; contradiction C1).
        self.latch_decay_ticks = int(latch_decay_seconds * timing.master_hz)
        self._latch_times = [0] * 8  # when each latch bit was last driven
        # Register effects that land some dots after the access: (time, action),
        # applied as the first dot at or after ``time`` begins (DELAYS).
        self._events: list[tuple[int, Callable[[], None]]] = []
        self._read_in_flight_until = -1  # a $2007 read's refill and increment pending
        self._oam_corrupt: int | None = None  # the OAM row a frozen OAM2 address will corrupt
        self._refill_from_fetch = False  # a $2007 read's refill, waiting on a fetch
        self._last_pixel = -1  # picture index of the last pixel computed
        self._last_value = 0  # its palette value, before greyscale and emphasis
        self._last_pixel_time = -1  # the dot (its time) that computed it
        self.power()

    # -- power and reset -------------------------------------------------

    def power(self) -> None:
        self.status = 0
        self.oam_addr = 0
        self.v = 0
        # Background pipeline: the fetch latches and the 16-bit shifters (the
        # attribute shifters hold 8 copies of each bit; PPU_rendering.wiki's
        # 1-bit latch feeding an 8-bit shifter gives the same pixels).
        self.nt_latch = 0
        self.at_latch = 0
        self.lo_latch = 0
        self.hi_latch = 0
        self.bg_lo = 0
        self.bg_hi = 0
        self.at_lo = 0
        self.at_hi = 0
        # Sprite evaluation state (PPU_sprite_evaluation.wiki).
        self.oam_bus = 0xFF  # what a $2004 read returns while rendering
        self._oam2_index = 0
        self._copying = 0  # bytes of an in-range sprite still to copy
        self._eval_done = False
        self._overflow_found = False
        self._sprite_count = 0
        self._sprite0_next = False
        self._sprite0_line = False
        self._fetch_tile = 0xFF
        self._fetch_attr = 0xFF
        self._garbage = 0x2000  # the first garbage fetch's address (dot 257)
        self._fetch_x = 0xFF
        self._fetch_lo = 0
        # The sprite pixels of the line being drawn and of the next one.
        self.sprite_line = [0] * WIDTH
        self._sprite_next = [0] * WIDTH
        self._vbl_suppress = False
        self._skip_sample = 0
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
        ticks = self.dot_ticks
        while self.time < time:
            dot = self.dot
            line = self.line
            if 1 <= dot < DOTS - 4 and (
                not self.mask & 0x18 or self.vblank_line - 1 <= line < self.prerender_line
            ):
                # Idle until the line's end: no fetches and no events on dots
                # 2-337; visible lines show the backdrop.
                dots = min((time - self.time + ticks - 1) // ticks, DOTS - 4 - dot)
                if self._events:  # stop short of a pending register effect
                    dots = min(dots, (self._events[0][0] - self.time) // ticks - 1)
                    if dots <= 0:
                        self._step()
                        continue
                if line < HEIGHT:
                    self._fill_backdrop(line, dot + 1, dot + dots)
                self.dot = dot + dots
                self.time += dots * ticks
                continue
            self._step()

    def _fill_backdrop(self, line: int, first: int, last: int) -> None:
        """The pixels of dots ``first``-``last`` with rendering off."""
        first = max(first, 2)
        last = min(last, WIDTH + 1)
        if first > last:
            return
        v = self.v & 0x3FFF
        value = self.palette[self.palette_index(v) if v >= 0x3F00 else 0]
        if self.mask & 0x01:
            value &= 0x30
        value |= (self.mask & 0xE0) << 1
        base = line * WIDTH - 2
        picture = self.picture
        for index in range(base + first, base + last + 1):
            picture[index] = value
        self._last_pixel = base + last
        self._last_value = self.palette[self.palette_index(v) if v >= 0x3F00 else 0]
        self._last_pixel_time = self.time + (last - self.dot) * self.dot_ticks  # dot ``last``

    def _schedule(self, dots: int, action: Callable[[], None]) -> None:
        """Run ``action`` before the work of the ``dots``-th dot after the next."""
        due = self.time + (dots + 1) * self.dot_ticks
        events = self._events
        events.append((due, action))
        events.sort(key=lambda event: event[0])

    def _step(self) -> None:
        """Advance one dot and do its work."""
        self.time += self.dot_ticks
        if self._events:
            events = self._events
            while events and events[0][0] <= self.time:
                events.pop(0)[1]()
        dot = self.dot + 1
        line = self.line
        rendering = self.mask & 0x18
        if dot == DOTS:
            dot = 0
            line = self._next_line(line)
        elif (
            dot == DOTS - 1
            and line == self.prerender_line
            and self.frame & 1
            and self._skip_sample
            and self.odd_frame_skip
        ):
            # Odd frames with rendering on jump from (339, 261) to (0, 0),
            # doing dot 340's fetch there (PPU_frame_timing.wiki). Rendering
            # is sampled on dot 338: ppu_vbl_nmi/10-even_odd_timing shows a
            # $2001 write that lands after it, enabling or disabling, is too
            # late for this frame (docs/validation.md, milestone 2).
            self._render(line, dot)
            dot = 0
            line = self._next_line(line)
            self.dot = 0
            return
        self.dot = dot
        if dot == DOTS - 3:
            self._skip_sample = rendering
        if dot == 1:
            if line == self.vblank_line:
                if not self._vbl_suppress:
                    self.status |= VBL
                    self.nmi = bool(self.ctrl & 0x80)
                self._vbl_suppress = False
            elif line == self.prerender_line:
                self.status &= ~(VBL | SPRITE0 | OVERFLOW)
                self.nmi = False
                self.resetting = False
        if line < HEIGHT or line == self.prerender_line:
            if rendering:
                if self._oam_corrupt is not None:
                    self._corrupt_oam()
                self._render(line, dot)
            elif line < HEIGHT and 2 <= dot <= WIDTH + 1:
                self._fill_backdrop(line, dot, dot)

    def _next_line(self, line: int) -> int:
        line += 1
        if line == self.lines:
            line = 0
            self.frame += 1
        self.line = line
        # The sprites fetched on the last line are this line's.
        self.sprite_line, self._sprite_next = self._sprite_next, self.sprite_line
        return line

    # -- rendering -------------------------------------------------------

    def _render(self, line: int, dot: int) -> None:
        """One dot of a rendering line (visible or pre-render) with rendering on."""
        visible = line < HEIGHT
        if dot <= WIDTH + 1:
            if dot == 0:
                return
            if dot >= 2:
                if visible:
                    self._pixel(line, dot - 2)
                self._shift()
            if visible:
                self._evaluate(line, dot)
            if dot <= WIDTH:
                self._background_fetch(dot)
                if dot == WIDTH:
                    self._increment_y()
            else:  # 257
                self._reload()
                self.oam_addr = 0
                self._sprite0_line = self._sprite0_next if visible else False
                for i in range(WIDTH):
                    self._sprite_next[i] = 0
                # The first garbage fetch's address goes out before hori(v)
                # is copied, and the octal latch holds it for the read on 258
                # (PPUSim, docs/validation.md milestone 2).
                self._sprite_fetch(line, dot, visible)
                self.v = (self.v & ~0x041F) | (self.t & 0x041F)
        elif dot <= 320:
            self.oam_addr = 0
            if line == self.prerender_line and 280 <= dot <= 304:
                self.v = (self.v & ~0x7BE0) | (self.t & 0x7BE0)
            self._sprite_fetch(line, dot, visible)
        elif dot <= 336:
            if dot >= 322:
                self._shift()
            self._background_fetch(dot)
            self.oam_bus = self.oam2[0]
        else:  # 337-340: the next line's first nametable byte, twice
            if dot == 337:
                self._shift()
                self._reload()
            address = 0x2000 | (self.v & 0x0FFF)
            if not dot & 1:
                self.nt_latch = self._fetch(address)
            elif self._watch:
                self._ale(address)

    def _shift(self) -> None:
        self.bg_lo = (self.bg_lo << 1) & 0xFFFF
        self.bg_hi = ((self.bg_hi << 1) & 0xFFFF) | 1  # PPU_rendering.wiki: shifts in 1
        self.at_lo = (self.at_lo << 1) & 0xFFFF
        self.at_hi = (self.at_hi << 1) & 0xFFFF

    def _reload(self) -> None:
        self.bg_lo = (self.bg_lo & 0xFF00) | self.lo_latch
        self.bg_hi = (self.bg_hi & 0xFF00) | self.hi_latch
        at = self.at_latch
        self.at_lo = (self.at_lo & 0xFF00) | (0xFF if at & 1 else 0)
        self.at_hi = (self.at_hi & 0xFF00) | (0xFF if at & 2 else 0)

    def _background_fetch(self, dot: int) -> None:
        phase = (dot - 1) & 7
        v = self.v
        if phase == 0:
            if dot >= 9:
                self._reload()
            if self._watch:
                self._ale(0x2000 | (v & 0x0FFF))
        elif phase == 1:
            self.nt_latch = self._fetch(0x2000 | (v & 0x0FFF))
        elif phase == 2:
            if self._watch:
                self._ale(0x23C0 | (v & 0x0C00) | ((v >> 4) & 0x38) | ((v >> 2) & 0x07))
        elif phase == 3:
            at = self._fetch(0x23C0 | (v & 0x0C00) | ((v >> 4) & 0x38) | ((v >> 2) & 0x07))
            self.at_latch = (at >> (((v >> 4) & 4) | (v & 2))) & 3
        elif phase == 4:
            if self._watch:
                self._ale(self._bg_pattern(v))
        elif phase == 5:
            self.lo_latch = self._fetch(self._bg_pattern(v))
        elif phase == 6:
            if self._watch:
                self._ale(self._bg_pattern(v) | 8)
        else:
            self.hi_latch = self._fetch(self._bg_pattern(v) | 8)
            # Coarse X++ (PPU_scrolling.wiki "Wrapping around").
            if v & 0x1F == 31:
                self.v = (v & ~0x1F) ^ 0x0400
            else:
                self.v = v + 1

    def _bg_pattern(self, v: int) -> int:
        return ((self.ctrl & 0x10) << 8) | (self.nt_latch << 4) | (v >> 12)

    def _increment_y(self) -> None:
        v = self.v
        if v & 0x7000 != 0x7000:
            self.v = v + 0x1000
            return
        v &= ~0x7000
        y = (v >> 5) & 31
        if y == 29:
            y = 0
            v ^= 0x0800
        elif y == 31:
            y = 0  # no nametable switch (PPU_scrolling.wiki)
        else:
            y += 1
        self.v = (v & ~0x03E0) | (y << 5)

    def _pixel(self, line: int, x: int) -> None:
        mask = self.mask
        bg = 0
        if mask & 0x08 and (x >= 8 or mask & 0x02):
            shift = 15 - self.x
            bg = ((self.bg_hi >> shift) & 1) << 1 | ((self.bg_lo >> shift) & 1)
            if bg:
                bg |= (((self.at_hi >> shift) & 1) << 3) | (((self.at_lo >> shift) & 1) << 2)
        sprite = self.sprite_line[x]
        if sprite and mask & 0x10 and (x >= 8 or mask & 0x04):
            if bg and sprite & IS_SPRITE0 and x != 255:
                self.status |= SPRITE0
            index = bg if bg and sprite & BEHIND else sprite & 0x1F
        else:
            index = bg
        value = self.palette[index]
        self._last_pixel = line * WIDTH + x
        self._last_value = value
        self._last_pixel_time = self.time
        if mask & 0x01:
            value &= 0x30
        self.picture[line * WIDTH + x] = value | ((mask & 0xE0) << 1)

    # -- sprites ---------------------------------------------------------

    def _evaluate(self, line: int, dot: int) -> None:
        """Dots 1-256 of a visible line: clear, then evaluate, secondary OAM."""
        if dot <= 64:
            self.oam_bus = 0xFF
            if not dot & 1:
                self.oam2[(dot >> 1) - 1] = 0xFF
            return
        if dot & 1:  # odd: read OAM
            if dot == 65:
                self._oam2_index = 0
                self._copying = 0
                self._eval_done = False
                self._overflow_found = False
                self._sprite0_next = False
            self.oam_bus = self.oam[self.oam_addr]
            return
        # Even: write secondary OAM, or read it once it is full.
        value = self.oam_bus
        address = self.oam_addr
        index = self._oam2_index
        height = 16 if self.ctrl & 0x20 else 8
        if self._eval_done:
            # Once n has wrapped nothing more lands in secondary OAM: the next
            # free slot keeps the last failed copy, OAM[63]'s Y, and empty
            # slots fetch their row from it (PPUSim, docs/validation.md
            # milestone 2).
            # Even dots read secondary OAM at its address, wrapped to 0 once full
            # (AccuracyCoin "$2004 Stress Test" 2).
            self.oam_bus = self.oam2[index & 31]
            self.oam_addr = (address + 4) & 0xFC
            return
        if index < 32:
            self.oam2[index] = value
            if self._copying:
                self._copying -= 1
                self._oam2_index = index + 1
                address = (address + 1) & 0xFF
                if not self._copying and not 0 <= line - value < height:
                    # The X byte gets Y's range check too: out of range, the
                    # address is masked back into alignment (AccuracyCoin
                    # "Misaligned OAM behavior" 4-7; aligned OAM cannot tell).
                    address &= 0xFC
                if address < 4 and not self._copying:
                    self._eval_done = True  # n wrapped: all 64 seen
            elif 0 <= line - value < height:
                if dot == 66:
                    self._sprite0_next = True
                self._copying = 3
                self._oam2_index = index + 1
                address = (address + 1) & 0xFF
            else:
                # Out of range: +4, realigned (AccuracyCoin "Misaligned OAM
                # behavior" 2).
                address = (address + 4) & 0xFC
                if address < 4:
                    self._eval_done = True
            self.oam_addr = address
            return
        # Eight found: secondary OAM is read, and the check scans diagonally.
        self.oam_bus = self.oam2[0]
        if self._copying:
            self._copying -= 1
            address = (address + 1) & 0xFF
            if not self._copying:
                self._eval_done = True
        elif 0 <= line - value < height:
            self.status |= OVERFLOW
            self._copying = 3
            address = (address + 1) & 0xFF
        else:
            # n++ and m++ without carry: the hardware bug.
            n = ((address >> 2) + 1) & 0x3F
            address = (n << 2) | ((address + 1) & 3)
            if n == 0:
                self._eval_done = True
        self.oam_addr = address

    def _sprite_fetch(self, line: int, dot: int, visible: bool) -> None:
        """Dots 257-320: per slot, Y, tile, attribute, X, then the pattern pair."""
        slot = (dot - 257) >> 3
        phase = (dot - 257) & 7
        oam2 = self.oam2
        base = slot << 2
        if phase == 0:
            if slot == 0:
                self._sprite_count = min(self._oam2_index, 32) >> 2 if visible else 0
            self.oam_bus = oam2[base]
            self._garbage = 0x2000 | (self.v & 0x0FFF)
            if self._watch:
                self._ale(self._garbage)
        elif phase == 1:
            self._fetch_tile = self.oam_bus = oam2[base + 1]
            self._fetch(self._garbage)
        elif phase == 2:
            self._fetch_attr = self.oam_bus = oam2[base + 2]
            if self._watch:
                self._ale(0x2000 | (self.v & 0x0FFF))
        elif phase == 3:
            self._fetch_x = self.oam_bus = oam2[base + 3]
            self._fetch(0x2000 | (self.v & 0x0FFF))
        elif phase == 4:
            if self._watch:
                self._ale(self._sprite_pattern(line, oam2[base]))
        elif phase == 5:
            self._fetch_lo = self._fetch(self._sprite_pattern(line, oam2[base]))
        elif phase == 6:
            if self._watch:
                self._ale(self._sprite_pattern(line, oam2[base]) | 8)
        else:
            hi = self._fetch(self._sprite_pattern(line, oam2[base]) | 8)
            if slot < self._sprite_count:
                self._draw_sprite(slot, self._fetch_lo, hi)
        if phase >= 3:
            self.oam_bus = oam2[base + 3]

    def _sprite_pattern(self, line: int, y: int) -> int:
        tile = self._fetch_tile
        row = (line - y) & 0xFF
        if self.ctrl & 0x20:  # 8x16: the tile's bit 0 picks the table
            if self._fetch_attr & 0x80:
                row = 15 - (row & 15)
            return ((tile & 1) << 12) | ((tile & 0xFE) << 4) | ((row & 8) << 1) | (row & 7)
        if self._fetch_attr & 0x80:
            row = 7 - (row & 7)
        return ((self.ctrl & 0x08) << 9) | (tile << 4) | (row & 7)

    def _draw_sprite(self, slot: int, lo: int, hi: int) -> None:
        """Put a fetched sprite into the next line's buffer; lower slots win."""
        attr = self._fetch_attr
        x = self._fetch_x
        flags = 0x10 | ((attr & 3) << 2) | (BEHIND if attr & 0x20 else 0)
        if slot == 0 and self._sprite0_line:
            flags |= IS_SPRITE0
        buffer = self._sprite_next
        flip = attr & 0x40
        for i in range(8):
            px = x + i
            if px >= WIDTH:
                break
            bit = i if flip else 7 - i
            pixel = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)
            if pixel and not buffer[px]:
                buffer[px] = flags | pixel

    # -- the PPU bus -----------------------------------------------------

    def _ale(self, address: int) -> None:
        self.cartridge.ppu_address(address, self.time)

    def _fetch(self, address: int) -> int:
        """A rendering fetch (/RD), at this dot's time."""
        if address >= 0x2000:
            a10 = self.cartridge.ciram_a10(address)
            if a10 is not None:
                value = self.ciram[(a10 << 10) | (address & 0x3FF)]
                if self._refill_from_fetch:
                    self._refill_from_fetch = False
                    self.buffer = value
                return value
        value = self.cartridge.ppu_read(address, self.time)
        value = address & 0xFF if value is None else value
        if self._refill_from_fetch:
            self._refill_from_fetch = False
            self.buffer = value
        return value

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

    def _oam2_row(self) -> int:
        """The secondary OAM address (0-31) at this dot, as AccuracyCoin's "OAM
        Corruption" notes give it (hardware-corrected): every other dot on
        1-64; the evaluation's write index on 65-256, raised to a multiple of 4
        (0 once full); on 257-320 it restarts and counts slot fetches (+1 on
        phases 0-2 and 7 of each 8); 0 on 321-340."""
        dot = self.dot
        if 1 <= dot <= 64:
            return (dot - 1) >> 1
        if 65 <= dot <= 256:
            index = self._oam2_index
            return 0 if index >= 32 else ((index + 3) & ~3) & 31
        if 257 <= dot <= 320:
            phase = (dot - 257) & 7
            return (((dot - 257) >> 3) << 2) + min(phase, 3)
        return 0

    def _corrupt_oam(self) -> None:
        """Rendering begins at the pre-render line with the secondary OAM
        address still frozen at row n: the OAMADDR row (row 0 after a DMA) is
        copied over row n of OAM, and secondary OAM's byte 0 over its byte n
        (Errata.wiki "OAM and Sprites", 2C02C-H; AccuracyCoin "OAM
        Corruption"). A mid-frame re-enable leaves no corruption, as blargg's
        sprite_overflow_tests/5.Emulator needs on hardware."""
        row = self._oam_corrupt
        assert row is not None
        self._oam_corrupt = None
        source = self.oam_addr & 0xF8
        self.oam[row * 8 : row * 8 + 8] = self.oam[source : source + 8]
        self.oam2[row] = self.oam2[0]

    @property
    def rendering_now(self) -> bool:
        """Rendering is on and this is a line on which the PPU fetches."""
        return bool(self.mask & 0x18) and (self.line < HEIGHT or self.line == self.prerender_line)

    # -- the CPU's registers ---------------------------------------------

    def read_register(self, register: int) -> int:
        if register == 2:
            value = (self.status & 0xE0) | (self._decayed_latch() & 0x1F)
            if self.line == self.vblank_line and self.dot == 0:
                # One dot before the set: reads clear and the flag never sets
                # this frame (NMI.wiki "Race condition").
                self._vbl_suppress = True
            self.status &= ~VBL
            self.nmi = False
            self.w = 0
            self._drive(value, 0xE0)
            return value
        if register == 4:
            value = self.oam_bus if self.rendering_now else self.oam[self.oam_addr]
            self._drive(value)
            return value
        if register == 7:
            v = self.v & 0x3FFF
            if v >= 0x3F00:
                value = self.palette[self.palette_index(v)]
                if self.mask & 0x01:
                    value &= 0x30
                value |= self._decayed_latch() & 0xC0
                self._drive(value, 0x3F)
            else:
                value = self.buffer
                self._drive(value)
            if self.time >= self._read_in_flight_until:
                dots = DELAYS["2007_increment"]
                self._read_in_flight_until = self.time + (dots + 1) * self.dot_ticks  # as _schedule
                self._schedule(dots, self._complete_2007_read)
            return value
        return self._decayed_latch()  # write-only registers read the I/O latch

    # -- the I/O latch ("PPU open bus", ppu_open_bus's readme) -----------

    def _drive(self, value: int, bits: int = 0xFF) -> None:
        """The CPU's data bus drove ``bits`` of the latch: they take ``value``, refreshed."""
        self.latch = (self.latch & ~bits) | (value & bits)
        now = self.time
        times = self._latch_times
        for bit in range(8):
            if bits >> bit & 1:
                times[bit] = now

    def _decayed_latch(self) -> int:
        """The latch, each 1 bit not driven for ``latch_decay_ticks`` having decayed to 0."""
        latch = self.latch
        if latch:
            limit = self.time - self.latch_decay_ticks
            times = self._latch_times
            for bit in range(8):
                if latch >> bit & 1 and times[bit] < limit:
                    latch &= ~(1 << bit)
            self.latch = latch
        return latch

    def _complete_2007_read(self) -> None:
        """The read's bus cycle: refill the buffer from v (the nametable under a
        palette address), then increment. While rendering, the PPU's bus is
        busy with fetches, and the buffer takes what the fetch reads (on a
        fetch's read dot; on its address dot the outcome is analogue): the
        next rendering fetch's byte (AccuracyCoin "$2007 Stress Test")."""
        if self.rendering_now:
            self._refill_from_fetch = True
        else:
            v = self.v & 0x3FFF
            self.buffer = self.bus_read(v - 0x1000 if v >= 0x3F00 else v)
        self._increment_after_2007()

    def _increment_after_2007(self) -> None:
        if self.rendering_now:
            # During rendering an access increments coarse X and Y together
            # (PPU_scrolling.wiki "$2007 reads and writes").
            v = self.v
            self.v = (v & ~0x1F) ^ 0x0400 if v & 0x1F == 31 else v + 1
            self._increment_y()
        else:
            self.v = (self.v + (32 if self.ctrl & 0x04 else 1)) & 0x7FFF
            if self._watch:
                self._ale(self.v & 0x3FFF)

    def write_register(self, register: int, value: int) -> None:
        self._drive(value)
        if register == 0:
            if self.resetting:
                return
            self.ctrl = value
            self.t = (self.t & ~0x0C00) | ((value & 0x03) << 10)
            self.nmi = bool(value & 0x80 and self.status & VBL)
        elif register == 1:
            if not self.resetting:
                if self.rendering_now and not value & 0x18:
                    # Rendering turned off mid-line freezes the secondary OAM
                    # address; if it is still frozen when rendering begins at
                    # the pre-render line, OAM's row there is overwritten.
                    self._oam_corrupt = self._oam2_row()
                elif value & 0x18 and self.line < HEIGHT:
                    # Back on during a visible line, the address counts again
                    # and is 0 by the line's end: nothing to corrupt.
                    self._oam_corrupt = None
                self.mask = value
                # Greyscale and emphasis act a stage after the palette lookup,
                # so they reach the pixel already looked up (PPUSim, DELAYS).
                if self._last_pixel_time == self.time:  # still in the pipeline
                    colour = self._last_value & (0x30 if value & 0x01 else 0x3F)
                    self.picture[self._last_pixel] = colour | ((value & 0xE0) << 1)
        elif register == 3:
            self.oam_addr = value
        elif register == 4:
            if self.rendering_now:
                # Not written; OAMADDR's high six bits bump (PPU_registers.wiki)
                # and the low two clear (AccuracyCoin "Address $2004 behavior" A).
                self.oam_addr = (self.oam_addr + 4) & 0xFC
            else:
                # Attribute bytes have no bits 4-2 in the array itself, so every
                # reader sees them missing, sprite evaluation's included
                # (AccuracyCoin "$2004 Stress Test" 2).
                address = self.oam_addr
                self.oam[address] = value & 0xE3 if address & 3 == 2 else value
                self.oam_addr = (address + 1) & 0xFF
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
                self._schedule(DELAYS["2006_copy"], self._copy_t)
            self.w ^= 1
        elif register == 7:
            # The address is v as the write lands, not as it was at the access:
            # a read one CPU cycle earlier has incremented v by then (blargg
            # dmc_dma_during_read4/read_write_2007, STA $2007,X).
            self._schedule(DELAYS["2007_write"], lambda: self._write_2007(self.v & 0x3FFF, value))
            self._schedule(DELAYS["2007_increment"], self._increment_after_2007)

    def _copy_t(self) -> None:
        """The second $2006 write's t -> v copy."""
        self.v = self.t
        if self._watch and not self.rendering_now:
            self._ale(self.v & 0x3FFF)

    def _write_2007(self, v: int, value: int) -> None:
        if v >= 0x3F00:
            self.palette[self.palette_index(v)] = value & 0x3F
        else:
            self.bus_write(v, value)

    def oam_dma_write(self, value: int) -> None:
        """A DMA write to $2004."""
        self.write_register(4, value)
