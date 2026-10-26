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
    "2007_read_ale": 2,  # a $2007 read's ALE (PPUSim tmp_2), 2 dots before its /RD
}
# A $2007 read's buffer refill lands with its increment, and a second read
# before then is ignored: it returns the buffer and starts nothing. PPUSim at
# the board's skew prints blargg's hardware results for both reads one CPU
# cycle apart (dmc_dma_during_read4: double_2007_read F018C287, dma_2007_read
# 159A7A8F; docs/validation.md milestone 3).

DOTS = 341
WIDTH, HEIGHT = 256, 240
REVERSE = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))  # a byte's bits mirrored
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
        self._nt_340_time = -1  # when the last dot-340 nametable fetch happened
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
        # The octal latch (PPU A0-7 between ALE and /RD) when it does not hold
        # the next rendering fetch's own low byte: a $2006 copy or a $2007
        # read landed between that fetch's ALE and its /RD (C31). None: it does.
        self._octal: int | None = None
        self._bus_data = 0  # the last byte a /RD put on AD0-7
        self._last_pixel = -1  # picture index of the last pixel computed
        self._last_value = 0  # its palette value, before greyscale and emphasis
        self._last_pixel_time = -1  # the dot (its time) that computed it
        self._prev_pixel = -1  # and the one before it
        self._prev_value = 0
        self._prev_pixel_time = -1
        self.power()

    # -- power and reset -------------------------------------------------

    def power(self) -> None:
        # PPUSTATUS at power is "+0+x xxxx", + often set (PPU_power_up_state.wiki);
        # PPUSim powers on with the overflow bit set and VBL clear, and so does
        # the board by default (PowerOn.ppustatus, which the board applies).
        self.status = OVERFLOW
        self.oam_addr = 0
        self.v = 0
        # Background pipeline: the fetch latches and the 16-bit shifters (the
        # attribute shifters hold 8 copies of each bit; PPU_rendering.wiki's
        # 1-bit latch feeding an 8-bit shifter gives the same pixels).
        self.nt_latch = 0
        self.at_byte = 0  # the attribute table byte last fetched
        self.at_latch = 0  # its two bits for the tile, taken on the tile's last fetch dot
        self.lo_latch = 0
        self.hi_latch = 0
        self.bg_lo = 0
        self.bg_hi = 0
        self.at_lo = 0
        self.at_hi = 0
        # Sprite evaluation state (PPU_sprite_evaluation.wiki).
        self.oam_bus = 0xFF  # what a $2004 read returns while rendering
        self._oam2_index = 0
        # The secondary OAM address during the sprite fetch: a counter that steps
        # only while rendering (Visual 2C02 spr_ptr), so a toggle mid-fetch leaves
        # it behind (AccuracyCoin "Misaligned OAM2 Address" 4).
        self._oam2_fetch = 0
        self._fetch_y = 0
        self._copying = 0  # bytes of an in-range sprite still to copy
        self._eval_done = False
        self._sprite_count = 0
        self._sprite0_next = False
        self._sprite0_line = False
        self._fetch_tile = 0xFF
        self._fetch_attr = 0xFF
        self._garbage = 0x2000  # the first garbage fetch's address (dot 257)
        # Secondary OAM's address overflowed: the sprite fetch reads index 0
        # throughout (AccuracyCoin "Frozen OAM2 Increment").
        self._oam2_frozen = False
        # The object FIFO: eight lanes of [pattern low, pattern high (the
        # pixels not yet shifted out, the next in bit 7), attribute, X
        # counter, the time the lane starts drawing] (PPUSim fifo.cpp;
        # :meth:`_plan_sprites`).
        self._lanes = [[0, 0, 0, 0, 0] for _ in range(8)]
        self._plan = [WIDTH] * 8  # each lane's first pixel on the line
        self._zh = False  # dot 339 rendered: lanes still counting start counting
        # The sprite pixels of the line being drawn.
        self.sprite_line = [0] * WIDTH
        self._vbl_suppress = False
        self._skip_sample = 0
        self.reset()

    def reset(self) -> None:
        """The reset line: PPUCTRL, PPUMASK, t, x, w and the buffer clear; v does not.

        Writes to $2000, $2001, $2005 and $2006 are ignored, and the $2007 read
        buffer held clear, until the reset flag clears at the next pre-render
        line (PPU_power_up_state.wiki; blargg 2008).
        """
        self.ctrl = 0
        self.mask = 0
        self._mux = 0  # PPUMASK's enable and clip bits as the pixel multiplexer has them
        # Rendering as the fetch, shift and sprite logic see it, a dot or two
        # behind PPUMASK (write_register); ``_target`` is where it is going.
        self._on = False
        self._target = False
        self._waking = False  # the next rendering dot is the wake dot
        self._dark = False  # ... the first full one, whose pixel is still the backdrop
        # Dots left of rendering's stop: 2, the fade dot next; 1, the dot after it.
        self._fading = 0
        self._reload_pending = False  # a fade's shifter load, due at the next shift
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
                not (self._on or self.mask & 0x18 or self._fading)
                or self.vblank_line - 1 <= line < self.prerender_line
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
        raw = self.palette[self.palette_index(v) if v >= 0x3F00 else 0]
        last_time = self.time + (last - self.dot) * self.dot_ticks  # dot ``last``'s
        if last > first:
            self._prev_pixel, self._prev_value = base + last - 1, raw
            self._prev_pixel_time = last_time - self.dot_ticks
        else:
            self._prev_pixel = self._last_pixel
            self._prev_value = self._last_value
            self._prev_pixel_time = self._last_pixel_time
        self._last_pixel = base + last
        self._last_value = raw
        self._last_pixel_time = last_time

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
        rendering = self._on
        if dot == DOTS:
            dot = 0
            line = self._next_line(line)
            self.dot = 0
            self._line_start(line)
        elif (
            dot == DOTS - 1
            and line == self.prerender_line
            and self.frame & 1
            and self._skip_sample
            and self.timing.odd_frame_skip
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
            self._line_start(line)
            return
        self.dot = dot
        if dot == DOTS - 3:
            self._skip_sample = self.mask & 0x18
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
            # Sprite evaluation follows PPUMASK itself, without the fetches'
            # delay (PPUSim, scripts/ppusim_compare.py c12).
            if line < HEIGHT and 1 <= dot <= WIDTH and self.mask & 0x18:
                self._evaluate(line, dot)
            if self._waking:
                self._waking = False
                self._wake(line, dot)
            elif self._fading:
                self._fading -= 1
                if self._fading:
                    self._fade(line, dot)
                else:
                    self._after_fade(line, dot)
            elif rendering:
                if self._oam_corrupt is not None and self.mask & 0x18:
                    self._corrupt_oam()  # not on the dot that follows the stop
                self._render(line, dot)
                if self._dark:
                    self._dark = False
            elif line < HEIGHT and 2 <= dot <= WIDTH + 1:
                self._fill_backdrop(line, dot, dot)
        else:
            self._waking = False
            self._fading = 0

    def _next_line(self, line: int) -> int:
        line += 1
        if line == self.lines:
            line = 0
            self.frame += 1
        self.line = line
        return line

    def _line_start(self, line: int) -> None:
        """Dot 0: lanes the last line's dot 339 started counting begin, and a
        rendered visible line plans its sprite pixels."""
        if self._zh:
            self._zh = False
            now = self.time
            ticks = self.dot_ticks
            for lane in self._lanes:
                if lane[4] <= now and lane[3]:
                    lane[4] = now + lane[3] * ticks
                    lane[3] = 0
        if line < HEIGHT and self._on:
            self._plan_sprites(0)

    # -- rendering -------------------------------------------------------

    def _render(self, line: int, dot: int) -> None:
        """One dot of a rendering line (visible or pre-render) with rendering on."""
        visible = line < HEIGHT
        if dot <= WIDTH + 1:
            if dot == 0:
                # Idle, but after the dot-340 fetch the bus already carries the
                # CHR address of dot 5's pattern fetch (PPU_rendering.wiki
                # "Cycle 0"). Settled on PPUSim: not after a vblank line, nor
                # when the odd-frame skip took dot 340, so with BG at $1000 an
                # MMC3 sees A12 low for 8 dots there and may count twice.
                if self._watch and self.time - self._nt_340_time == self.dot_ticks:
                    self._ale(self._bg_pattern(self.v))
                return
            if dot >= 2:
                if visible:
                    if self._dark:
                        self._fill_backdrop(line, dot, dot)
                    else:
                        self._pixel(line, dot - 2)
                if not self._dark:
                    self._shift()
                elif self._reload_pending:
                    self._reload_pending = False
                    self._reload()
            if dot == 63 or dot == 255:
                self._oam2_frozen = False
            if dot <= WIDTH:
                self._background_fetch(dot)
                if dot == WIDTH:
                    self._increment_y()
            else:  # 257
                if not self._dark:
                    self._reload()
                self.oam_addr = 0
                if visible:
                    self._lanes_shifted(WIDTH)
                # Stale on the pre-render line: line 239's, or from before
                # a forced blank (AccuracyCoin "Sprites On Scanline 0").
                self._sprite0_line = self._sprite0_next
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
                if not self._dark:
                    self._shift()
                elif self._reload_pending:
                    self._reload_pending = False
                    self._reload()
            self._background_fetch(dot)
            if dot == 321 and not self._oam2_frozen:
                # The last slot's fourth step: 31 wraps to 0 and raises the freeze
                # (Visual 2C02 spr_ptr_overflow; AccuracyCoin "Frozen OAM2 Increment" 3).
                self._oam2_fetch += 1
                if self._oam2_fetch >= 32:
                    self._oam2_fetch = 0
                    self._oam2_frozen = True
            self.oam_bus = self.oam2[self._oam2_fetch & 31]
        else:  # 337-340: the next line's first nametable byte, twice
            if dot == 337 and not self._dark:
                self._shift()
                self._reload()
            elif dot == 339:
                # ZHPOS: lanes holding a nonzero X start counting at the next
                # line's dot 0, and the overflow freeze clears.
                self._zh = True
                self._oam2_frozen = False
            address = 0x2000 | (self.v & 0x0FFF)
            if not dot & 1:
                self.nt_latch = self._fetch(address)
                if dot == 340:
                    self._nt_340_time = self.time
            elif self._watch:
                self._ale(address)

    def _shift(self) -> None:
        self.bg_lo = (self.bg_lo << 1) & 0xFFFF
        self.bg_hi = ((self.bg_hi << 1) & 0xFFFF) | 1  # PPU_rendering.wiki: shifts in 1
        # The attribute shifters take the latch's bits in serially (PPUSim
        # bgcol.cpp), which shows only when a reload is missed (C12).
        at = self.at_latch
        self.at_lo = ((self.at_lo << 1) & 0xFFFF) | (at & 1)
        self.at_hi = ((self.at_hi << 1) & 0xFFFF) | (at >> 1)

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
            # The reload stands for the shifters' load on the dot before
            # (PPUSim SRLOAD), which a wake dot did not do.
            if dot >= 9 and not self._dark:
                self._reload()
            if self._watch:
                self._ale(0x2000 | (v & 0x0FFF))
        elif phase == 1:
            self.nt_latch = self._fetch(0x2000 | (v & 0x0FFF))
        elif phase == 2:
            if self._watch:
                self._ale(0x23C0 | (v & 0x0C00) | ((v >> 4) & 0x38) | ((v >> 2) & 0x07))
        elif phase == 3:
            self.at_byte = self._fetch(
                0x23C0 | (v & 0x0C00) | ((v >> 4) & 0x38) | ((v >> 2) & 0x07)
            )
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
            # The latch takes the byte's quadrant for v as it is now, before
            # the increment: after rendering restarts, the quadrant of the
            # tile in hand applied to whatever byte the latch last took
            # (PPUSim bgcol.cpp; scripts/ppusim_compare.py c12).
            self.at_latch = (self.at_byte >> (((v >> 4) & 4) | (v & 2))) & 3
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
        mux = self._mux
        bg = 0
        if mux & 0x08 and (x >= 8 or mux & 0x02):
            shift = 15 - self.x
            bg = ((self.bg_hi >> shift) & 1) << 1 | ((self.bg_lo >> shift) & 1)
            if bg:
                bg |= (((self.at_hi >> shift) & 1) << 3) | (((self.at_lo >> shift) & 1) << 2)
        sprite = self.sprite_line[x]
        if sprite and mux & 0x10 and (x >= 8 or mux & 0x04):
            if bg and sprite & IS_SPRITE0 and x != 255:
                self.status |= SPRITE0
            index = bg if bg and sprite & BEHIND else sprite & 0x1F
        else:
            index = bg
        value = self.palette[index]
        self._prev_pixel = self._last_pixel
        self._prev_value = self._last_value
        self._prev_pixel_time = self._last_pixel_time
        self._last_pixel = line * WIDTH + x
        self._last_value = value
        self._last_pixel_time = self.time
        mask = self.mask
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
                if index == 31:
                    self._oam2_frozen = True  # full: the address overflowed
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
                if not 0 <= line - value < height:
                    # As in a normal copy, the last byte gets the range check and
                    # out of range masks the address back into alignment: after a
                    # misaligned find at $9F, $A0 $A1 $A2 then $A0 (AccuracyCoin
                    # "$2004 Stress Test" 3; PPUSim).
                    address &= 0xFC
                self._eval_done = True
        elif 0 <= line - value < height:
            # PPUSTATUS shows it a dot later (PPUSim; AccuracyCoin "$2002 flag
            # timing" 2, read as M2 falls).
            self._schedule(0, self._set_overflow)
            self._copying = 3
            address = (address + 1) & 0xFF
        else:
            # n++ and m++ without carry: the hardware bug.
            n = ((address >> 2) + 1) & 0x3F
            address = (n << 2) | ((address + 1) & 3)
            if n == 0:
                self._eval_done = True
        self.oam_addr = address

    def _set_overflow(self) -> None:
        self.status |= OVERFLOW

    def _sprite_fetch(self, line: int, dot: int, visible: bool) -> None:
        """Dots 257-320: per slot, Y, tile, attribute, X, then the pattern pair.

        On the pre-render line the range checks see line 261 & 255 = 5, so
        stale secondary OAM in range of line 5 is drawn on line 0
        (AccuracyCoin "Sprites On Scanline 0" 2; nesdev-forum t=26291).
        """
        if not visible:
            line &= 0xFF
        slot = (dot - 257) >> 3
        phase = (dot - 257) & 7
        oam2 = self.oam2
        # The counter steps on phases 1-3 and on each later slot's phase 0 (and
        # once more on dot 321), four a slot, unless the overflow freeze holds it
        # (Visual 2C02 inc_spr_ptr; AccuracyCoin "Frozen OAM2 Increment").
        if dot == 257:
            self._oam2_fetch = 0
        elif phase <= 3 and not self._oam2_frozen:
            self._oam2_fetch += 1
        address = self._oam2_fetch & 31
        lane = self._lanes[slot]
        if phase == 0:
            if slot == 0:
                self._sprite_count = min(self._oam2_index, 32) >> 2 if visible else 8
            self.oam_bus = self._fetch_y = oam2[address]
            self._garbage = 0x2000 | (self.v & 0x0FFF)
            if self._watch:
                self._ale(self._garbage)
        elif phase == 1:
            # /RD: the octal latch still holds the ALE's low byte, but A8-A13
            # come from v, whose copy from t (dot 257) came between: on dot
            # 258 $2542 reads as $2142 (PPUSim).
            self._fetch_tile = self.oam_bus = oam2[address]
            self.nt_latch = self._fetch((0x2000 | (self.v & 0x0F00)) | (self._garbage & 0xFF))
        elif phase == 2:
            self._fetch_attr = self.oam_bus = lane[2] = oam2[address]
            if self._watch:
                self._ale(0x2000 | (self.v & 0x0FFF))
        elif phase == 3:
            # The fetch's attribute slot: no latch takes its byte, which a
            # restart before dot 321 shows (PPUSim, tests/ppusim_scenes.py lanes).
            self.oam_bus = x = oam2[address]
            self._fetch(0x2000 | (self.v & 0x0FFF))
            lane[3] = x
            if lane[4] > self.time:  # still counting: it counts on from X
                lane[4] = self.time + x * self.dot_ticks
        elif phase == 4:
            if self._watch:
                self._ale(self._sprite_pattern(line, self._fetch_y))
        elif phase == 5:
            lo = self._fetch(self._sprite_pattern(line, self._fetch_y))
            lane[0] = self._lane_bits(slot, visible, line, self._fetch_y, lo)
        elif phase == 6:
            if self._watch:
                self._ale(self._sprite_pattern(line, self._fetch_y) | 8)
        else:
            hi = self._fetch(self._sprite_pattern(line, self._fetch_y) | 8)
            lane[1] = self._lane_bits(slot, visible, line, self._fetch_y, hi)
        if phase >= 3:
            self.oam_bus = oam2[address]

    def _lane_bits(self, slot: int, visible: bool, line: int, y: int, bits: int) -> int:
        """A pattern byte as its lane takes it: first pixel in bit 7 (the
        attribute's flip applied), or none for a slot with no sprite in range."""
        height = 16 if self.ctrl & 0x20 else 8
        if slot >= self._sprite_count or not (visible or 0 <= line - y < height):
            return 0
        return REVERSE[bits] if self._fetch_attr & 0x40 else bits

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

    def _plan_sprites(self, x1: int) -> None:
        """The line's sprite pixels from pixel ``x1`` on, rendering assumed to
        stay on (a stop calls :meth:`_lanes_shifted`; a restart plans again).

        Each lane is PPUSim's FIFO lane: an X down-counter that steps every
        dot, rendering or not, until it reaches 0, and a pair of shifters
        that shift out a pixel on each rendered visible dot once it has. A
        lane's pixel x is due on dot x (the pixel shows on dot x + 2, with
        the background's). Dot 339 starts the counters of lanes loaded with
        a nonzero X; without it every lane keeps drawing, so a lane that has
        not shifted out its pattern draws the rest from the next rendered
        pixel (AccuracyCoin "Stale Sprite Shift Regs", "Stale BG Shift
        Registers" 4). Lower lanes win.
        """
        buffer = self.sprite_line
        for i in range(WIDTH):
            buffer[i] = 0
        now = self.time  # dot x1's
        ticks = self.dot_ticks
        sprite0 = self._sprite0_line
        plan = []
        for n, (lo, hi, attr, _, zero) in enumerate(self._lanes):
            start = x1 if zero <= now else x1 + (zero - now) // ticks
            plan.append(start)
            if start >= WIDTH or not (lo | hi):
                continue
            flags = 0x10 | ((attr & 3) << 2) | (BEHIND if attr & 0x20 else 0)
            if n == 0 and sprite0:
                flags |= IS_SPRITE0
            x = start
            for bit in range(7, -1, -1):
                if x >= WIDTH:
                    break
                pixel = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)
                if pixel and not buffer[x]:
                    buffer[x] = flags | pixel
                x += 1
        self._plan = plan

    def _lanes_shifted(self, x0: int) -> None:
        """Lanes stop shifting at pixel ``x0`` (rendering stopped, or the
        visible dots ended): shift out what each drew. The planes load
        separately (:meth:`_sprite_fetch`), so one can be new while the
        other is spent."""
        for lane, start in zip(self._lanes, self._plan, strict=True):
            if start < x0:
                n = min(8, x0 - start)
                lane[0] = (lane[0] << n) & 0xFF
                lane[1] = (lane[1] << n) & 0xFF
        self._plan = [WIDTH] * 8

    # -- the PPU bus -----------------------------------------------------

    def _ale(self, address: int) -> None:
        self.cartridge.ppu_address(address, self.time)

    def _fetch(self, address: int) -> int:
        """A rendering fetch (/RD), at this dot's time: PA8-13 from the address
        now, PA0-7 from the octal latch (its ALE's, unless ``_octal`` says)."""
        octal = self._octal
        if octal is not None:
            self._octal = None
            address = (address & 0x3F00) | octal
        if address >= 0x2000:
            a10 = self.cartridge.ciram_a10(address)
            if a10 is not None:
                value = self.ciram[(a10 << 10) | (address & 0x3FF)]
                self._bus_data = value
                if self._refill_from_fetch:
                    self._refill_from_fetch = False
                    self.buffer = value
                return value
        value = self.cartridge.ppu_read(address, self.time)
        value = address & 0xFF if value is None else value
        self._bus_data = value
        if self._refill_from_fetch:
            self._refill_from_fetch = False
            self.buffer = value
        return value

    def _fetch_address(self, dot: int) -> int:
        """The address the rendering fetch whose /RD is on even ``dot`` (2-340)
        reads, from the state now (the fetch functions' own arithmetic)."""
        v = self.v
        if dot <= WIDTH or 321 <= dot <= 336:
            phase = (dot - 1) & 7
            if phase == 1:
                return 0x2000 | (v & 0x0FFF)
            if phase == 3:
                return 0x23C0 | (v & 0x0C00) | ((v >> 4) & 0x38) | ((v >> 2) & 0x07)
            return self._bg_pattern(v) | (8 if phase == 7 else 0)
        if dot <= 320:
            phase = (dot - 257) & 7
            if phase == 1:
                return self._garbage
            if phase == 3:
                return 0x2000 | (v & 0x0FFF)
            line = self.line if self.line < HEIGHT else self.line & 0xFF
            return self._sprite_pattern(line, self._fetch_y) | (8 if phase == 7 else 0)
        return 0x2000 | (v & 0x0FFF)  # 338, 340

    def _settle(self, high: int, low: int, steps: int) -> int:
        """ALE and /RD at once: the octal latch takes the byte it makes the bus
        read, once per master half-cycle that both last (AccuracyCoin "ALE +
        Read"). PPUSim, half-cycle by half-cycle: a $2007 read's ALE on a
        fetch's /RD dot lasts the dot (7 steps from the fetch's low byte), its
        /RD on a fetch's ALE dot half of it (3 steps from the byte on the bus).
        Analogue on hardware (AccuracyCoin leaves such bytes out of its key)."""
        for _ in range(steps):
            low = self.bus_read(high | low)
        return low

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
        (0 once full); from 257 the fetch counter (4 a slot; 0 again after
        dot 321's wrap)."""
        dot = self.dot
        if 1 <= dot <= 64:
            return (dot - 1) >> 1
        if 65 <= dot <= 256:
            index = self._oam2_index
            return 0 if index >= 32 else ((index + 3) & ~3) & 31
        return self._oam2_fetch & 31  # 257-340: the fetch counter

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

    def _wake(self, line: int, dot: int) -> None:
        """The first dot rendering is back on (PPUSim, scripts/ppusim_compare.py
        c12): an ALE dot puts its address out, an attribute fetch's still the
        nametable address (its /RD then reads a hybrid of the two), but
        nothing shifts, latches or increments; the next dot's pixel is still
        the backdrop (``_dark``), and a reload there stands for a load this
        dot did not do. (A /RD dot strobes /RD with a stale byte; no latch
        takes it and the board leaves it out.) Sprite lanes draw again from
        this dot's pixel."""
        visible = line < HEIGHT
        if visible and 2 <= dot <= WIDTH + 1:
            self._fill_backdrop(line, dot, dot)
        if dot & 1 and dot <= 339:
            if dot <= WIDTH or dot >= 321:
                phase = (dot - 1) & 7
                if phase <= 2 or dot >= 337:
                    address = 0x2000 | (self.v & 0x0FFF)
                else:
                    address = self._fetch_address(dot + 1)
                if phase == 2:
                    self._octal = address & 0xFF
            else:
                address = self._fetch_address(dot + 1)
            if self._watch:
                self._ale(address)
        if visible and dot < WIDTH:
            self._plan_sprites(dot)
        self._dark = True

    def _latch_mux(self, bits: int, value: int) -> None:
        self._mux = (self._mux & ~bits) | (value & bits)

    def set_mask(self, value: int) -> None:
        """PPUMASK as if written long ago: rendering state follows at once."""
        self.mask = self._mux = value
        self._on = self._target = bool(value & 0x18)
        self._waking = self._dark = False
        self._fading = 0

    def _wake_up(self) -> None:
        self._on = True
        self._waking = True
        self._fading = 0

    def _fade(self, line: int, dot: int) -> None:
        """The dot after rendering stops (PPUSim, scripts/ppusim_compare.py
        c12): ALE, /RD and pixels have stopped, but the shifters still shift
        and the fetch stage runs one more dot. Its latches load, with no /RD,
        the AD bus, which still carries the low byte of the address the PPU
        drives: the attribute address on the attribute fetch's dot, the
        nametable address (v) on the others. Reloads and increments happen
        as on a rendered dot.
        """
        if line < HEIGHT and 2 <= dot <= WIDTH + 1:
            # The background has gone to the backdrop; a sprite still shows.
            x = dot - 2
            sprite = self.sprite_line[x]
            mux = self._mux
            if sprite and mux & 0x10 and (x >= 8 or mux & 0x04):
                value = self.palette[sprite & 0x1F]
                self._prev_pixel = self._last_pixel
                self._prev_value = self._last_value
                self._prev_pixel_time = self._last_pixel_time
                self._last_pixel = line * WIDTH + x
                self._last_value = value
                self._last_pixel_time = self.time
                if self.mask & 0x01:
                    value &= 0x30
                self.picture[line * WIDTH + x] = value | ((self.mask & 0xE0) << 1)
            else:
                self._fill_backdrop(line, dot, dot)
        if 2 <= dot <= WIDTH + 1 or 322 <= dot <= 337:
            self._shift()
        if 1 <= dot <= WIDTH or 321 <= dot <= 336:
            phase = (dot - 1) & 7
            v = self.v
            if phase == 0:
                if dot >= 9:
                    self._reload()
            elif phase == 1:
                self.nt_latch = v & 0xFF
            elif phase == 3:
                self.at_byte = 0xC0 | ((v >> 4) & 0x38) | ((v >> 2) & 0x07)
            elif phase == 5:
                self.lo_latch = v & 0xFF
            elif phase == 7:
                self.hi_latch = v & 0xFF
                self.at_latch = (self.at_byte >> (((v >> 4) & 4) | (v & 2))) & 3
                self.v = (v & ~0x1F) ^ 0x0400 if v & 0x1F == 31 else v + 1
                # The shifters load now; the board's reload, which follows a
                # dot's shift, stands for that at the next shift, rendering's
                # first.
                self._reload_pending = True
            if dot == WIDTH:
                self._increment_y()
        elif dot == WIDTH + 1:
            self._reload()
            self.v = (self.v & ~0x041F) | (self.t & 0x041F)
        elif WIDTH + 1 < dot <= 320:
            self._sprite_fade(line, dot)
        elif dot == 337:
            self._reload()

    def _after_fade(self, line: int, dot: int) -> None:
        """The second dot after rendering stops (PPUSim, tests/ppusim_scenes.py
        lanes): the background shifters shift once more, taking a load the
        fade dot left pending; the pixel is the backdrop. Rendering's first
        full dot back does not shift (:meth:`_render`, ``_dark``), so a stop
        and a restart within the shifting dots cancel, but not a stop in the
        sprite fetch, where nothing shifts."""
        if line < HEIGHT and 2 <= dot <= WIDTH + 1:
            self._fill_backdrop(line, dot, dot)
        if 2 <= dot <= WIDTH + 1 or 322 <= dot <= 337:
            self._shift()
            if self._reload_pending:
                self._reload_pending = False
                self._reload()

    def _sprite_fade(self, line: int, dot: int) -> None:
        """The sprite fetch's part of :meth:`_fade`: secondary OAM is still
        read and the lane loads, its pattern planes from the AD bus."""
        visible = line < HEIGHT
        if not visible:
            line &= 0xFF
        slot = (dot - 257) >> 3
        phase = (dot - 257) & 7
        oam2 = self.oam2
        # The fade dot still reads secondary OAM, and the counter still steps.
        if dot == 257:
            self._oam2_fetch = 0
        elif phase <= 3 and not self._oam2_frozen:
            self._oam2_fetch += 1
        address = self._oam2_fetch & 31
        lane = self._lanes[slot]
        if phase == 0:
            self._fetch_y = oam2[address]
        elif phase == 1:
            self._fetch_tile = oam2[address]
        elif phase == 2:
            self._fetch_attr = lane[2] = oam2[address]
        elif phase == 3:
            x = oam2[address]
            lane[3] = x
            if lane[4] > self.time:
                lane[4] = self.time + x * self.dot_ticks
        elif phase == 5:
            lane[0] = self._lane_bits(slot, visible, line, self._fetch_y, self.v & 0xFF)
        elif phase == 7:
            lane[1] = self._lane_bits(slot, visible, line, self._fetch_y, self.v & 0xFF)

    def _turn_off(self) -> None:
        self._on = False
        self._waking = False
        self._fading = 2
        if self.line < HEIGHT and self.dot <= WIDTH:
            self._lanes_shifted(min(self.dot + 1, WIDTH))

    @property
    def rendering_now(self) -> bool:
        """Rendering is on and this is a line on which the PPU fetches."""
        return self._on and (self.line < HEIGHT or self.line == self.prerender_line)

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
                if self.rendering_now:
                    self._schedule(DELAYS["2007_read_ale"], self._read_2007_ale)
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

    def end_read(self, register: int, value: int) -> int:
        """A register read's value as M2 falls, the cycle's end. $2002 latches
        VBL as M2 rises but passes the sprite-0 and overflow flags through
        until M2 falls (AccuracyCoin "$2002 Flag Timing", whose notes give the
        RP2A03G's M2 duty of 15/24; C3)."""
        if register == 2:
            return (value & 0x9F) | (self.status & 0x60)
        return value

    def _read_2007_ale(self) -> None:
        """A $2007 read's ALE, 2 dots after the access (PPUSim ``vram_ctrl``:
        ``tmp_2``). On a rendering ALE dot the fetch's address wins; on a
        rendering /RD dot ALE and /RD meet and that fetch's address settles."""
        dot = self.dot + 1
        if self.rendering_now and not dot & 1 and 2 <= dot <= 340:
            address = self._fetch_address(dot)
            low = self._octal if self._octal is not None else address & 0xFF
            self._octal = self._settle(address & 0x3F00, low, 7)

    def _complete_2007_read(self) -> None:
        """The read's /RD, 4 dots after the access (PPUSim ``PD_RB``): the
        buffer takes the bus, and v increments (``TSTEP``). Outside rendering
        the bus reads v (the nametable under a palette address). While
        rendering, on a fetch's /RD dot the buffer takes that fetch, whose low
        byte its ALE latched before the increment (C31); on a fetch's ALE dot,
        ALE and /RD meet, and the buffer and the next fetch take the settled
        address."""
        if self.rendering_now:
            dot = self.dot + 1
            if not dot & 1 and 2 <= dot <= 340:
                if self._octal is None:
                    self._octal = self._fetch_address(dot) & 0xFF
                self._refill_from_fetch = True
            elif dot & 1:
                high = self._fetch_address(dot + 1) & 0x3F00
                low = self._settle(high, self._bus_data, 3)
                self.buffer = self.bus_read(high | low)
                self._octal = low
            else:  # dot 0, idle
                self._refill_from_fetch = True
        else:
            v = self.v & 0x3FFF
            value = self.bus_read(v - 0x1000 if v >= 0x3F00 else v)
            # The reset signal holds the buffer clear until it ends at the
            # pre-render line (PPU_power_up_state.wiki): a read before then
            # still reads the bus and increments v, but the buffer stays 0.
            # Argus and Family Stadium '87 check CHR-ROM in that window and
            # need the 0 (milestone 7's sweep; Mesen2 returns 0 too).
            if not self.resetting:
                self.buffer = value
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

    def write_register(self, register: int, value: int, early: int | None = None) -> None:
        """A CPU write; ``early`` is the open-bus value the data bus holds at
        the start of the write cycle, before the CPU drives ``value``
        (PPU_glitches.wiki "Early Writes"; None: valid for the whole cycle).
        On the 2C02G only PPUMASK's greyscale bit sees it (below)."""
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
                # Fetches, shifts and sprite lanes follow a dot later when
                # rendering stops, and two when it starts, the first of them
                # a wake dot (:meth:`_wake`; PPUSim, scripts/ppusim_compare.py
                # c12, undocumented-behavior.md C12).
                target = bool(value & 0x18)
                if target != self._target:
                    self._target = target
                    self._schedule(1, self._wake_up if target else self._turn_off)
                # The multiplexer's enable and clip bits are latched: the pixel
                # this dot computes still sees the old ones (the sprite bits,
                # the next one too). Emphasis acts a
                # stage after the palette lookup, so it reaches that pixel;
                # greyscale, asynchronous, the one before it too, with the
                # early-write value's bit there ("Any write to PPUMASK can ...
                # turn off the monochrome flag for one pixel", PPU_glitches.wiki;
                # PPUSim, scripts/ppusim_compare.py c12, both bus models).
                # The sprite bits a dot after the background's.
                self._schedule(1, lambda: self._latch_mux(0x0A, value))
                self._schedule(2, lambda: self._latch_mux(0x14, value))
                grey = 0x30 if value & 0x01 else 0x3F
                first = 0x30 if (value if early is None else early) & 0x01 else 0x3F
                picture = self.picture
                ticks = self.dot_ticks
                if self._prev_pixel_time == self.time - ticks:
                    index = self._prev_pixel
                    picture[index] = (self._prev_value & first) | (picture[index] & 0x1C0)
                if self._last_pixel_time == self.time:
                    colour = self._last_value & grey
                    picture[self._last_pixel] = colour | ((value & 0xE0) << 1)
                elif self._last_pixel_time == self.time - ticks:
                    index = self._last_pixel
                    picture[index] = (self._last_value & first) | (picture[index] & 0x1C0)
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
        """The second $2006 write's t -> v copy. Landing on a rendering fetch's
        /RD dot, it changes PA8-13 but not the low byte its ALE latched: a
        hybrid address (AccuracyCoin "Hybrid Addresses"; C31)."""
        if self.rendering_now:
            dot = self.dot + 1
            if not dot & 1 and 2 <= dot <= 340 and self._octal is None:
                self._octal = self._fetch_address(dot) & 0xFF
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
