"""Controllers besides the standard pad, on the controller ports and the Famicom expansion port.

Input_devices.wiki: each controller port carries OUT0 (the strobe), its /OE and
D0-D4 (the NES connects D0, D3 and D4); the Famicom's expansion port carries
OUT0-OUT2, both /OEs, $4016 D1 and $4017 D0-D4. A device here answers one of two
small protocols, the board's business being only when each signal moves:

- a **port device** (``board.pads[0]`` or ``[1]``), like ``StandardController``:
  ``set_strobe(high)`` when OUT0 changes, ``read()`` for D0-D4 as positioned
  bits, ``clock()`` at the end of an /OE pulse;
- an **expansion device** (``board.expansion``): ``set_out(value)`` with OUT0-2,
  ``read(port)`` and ``clock(port)`` for $4016 (0) and $4017 (1).

``plug`` puts in the devices that NES 2.0's Default Expansion Device byte names
(NES_2.0.wiki; nes20db gives the same number), for the ones built here.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from .joypad import StandardController

if TYPE_CHECKING:
    from .board import Board
    from .ppu import PPU


# -- four players ------------------------------------------------------------------


class TapPort:
    """One port of a four-player adapter: two pads' reports, then a signature.

    Four_player_adapters.wiki: reads 0-7 are the first pad's, 8-15 the second's,
    16-23 a signature unique to the address, then 1s; the count resets while OUT0
    is 1. The Four Score answers on D0, the Hori 4 Players Adapter on D1.
    """

    def __init__(
        self, first: StandardController, second: StandardController, signature: int, bit: int
    ) -> None:
        self.first = first
        self.second = second
        self.signature = signature  # reads 16-23, the first in bit 0
        self.bit = bit
        self.count = 0
        self.strobe = False

    def set_strobe(self, high: bool) -> None:
        self.first.set_strobe(high)
        self.second.set_strobe(high)
        self.strobe = high
        if high:
            self.count = 0

    def read(self) -> int:
        count = self.count
        if count < 8:
            value = self.first.read()
        elif count < 16:
            value = self.second.read()
        elif count < 24:
            value = self.signature >> (count - 16) & 1
        else:
            value = 1
        return value << self.bit

    def clock(self) -> None:
        if self.strobe:
            self.first.clock()
            self.second.clock()
            return
        count = self.count
        if count < 8:
            self.first.clock()
        elif count < 16:
            self.second.clock()
        if count < 24:
            self.count = count + 1


class FourScore:
    """The NES Four Score (or NES Satellite) in its 4-player mode, on both ports.

    Players 1 and 3 on $4016 D0, 2 and 4 on $4017 D0; signatures: $4016's read
    19 is 1, $4017's read 18 (Four_player_adapters.wiki, "Four Score").
    """

    def __init__(self) -> None:
        self.pads = [StandardController() for _ in range(4)]
        self.ports = (
            TapPort(self.pads[0], self.pads[2], 0x08, 0),
            TapPort(self.pads[1], self.pads[3], 0x04, 0),
        )


class HoriAdapter:
    """The Hori 4 Players Adapter in 4-player mode, on the Famicom expansion port.

    The Four Score's protocol on D1, with the signatures swapped: $4016's read 18
    is 1, $4017's read 19. Players 3 and 4 here, with the hard-wired pads as 1-2;
    the adapter's own ports 1-4 are ``pads`` (Four_player_adapters.wiki).
    """

    def __init__(self) -> None:
        self.pads = [StandardController() for _ in range(4)]
        self.ports = (
            TapPort(self.pads[0], self.pads[2], 0x04, 1),
            TapPort(self.pads[1], self.pads[3], 0x08, 1),
        )

    def set_out(self, value: int) -> None:
        for port in self.ports:
            port.set_strobe(bool(value & 1))

    def read(self, port: int) -> int:
        return self.ports[port].read()

    def clock(self, port: int) -> None:
        self.ports[port].clock()


class ExpansionPads:
    """Two pads on the Famicom expansion port's D1 of $4016 and $4017: players 3
    and 4 of the "simple" adapters (JoyPair, Twin Adapter; Four_player_adapters.wiki)."""

    def __init__(self) -> None:
        self.pads = [StandardController(), StandardController()]

    def set_out(self, value: int) -> None:
        for pad in self.pads:
            pad.set_strobe(bool(value & 1))

    def read(self, port: int) -> int:
        return self.pads[port].read() << 1

    def clock(self, port: int) -> None:
        self.pads[port].clock()


# -- the Zapper --------------------------------------------------------------------

# Zap Ruder (Zapper.wiki "Output"): the photodiode stays on for about 26 lines on
# pure white, 24 on light grey and 19 on dark grey, palette entries $20, $10 and
# $00. The wiki's model: luminance charges a capacitor that drains exponentially,
# the bit on while the charge is above a threshold, so a colour of luminance Y
# stays on tau * ln(Y / Y0) lines. tau and Y0 are fitted to those three points
# through the board's own palette; dimmer colours light the bit for less, and
# none below Y0. **Fitted**, not measured: the real sensor's filter (tuned to the
# ~15 kHz line rate) and its field of view are not modelled; it sees one pixel.
ZAP_RUDER = ((0x00, 19.0), (0x10, 24.0), (0x20, 26.0))


def luminance(rgb: bytes) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def zapper_lines(palette: Sequence[bytes]) -> list[float]:
    """Lines the light bit stays on after the beam passes each 9-bit pixel value."""
    points = [(math.log(max(luminance(palette[c]), 1.0)), lines) for c, lines in ZAP_RUDER]
    # Least squares for lines = tau * (ln Y - ln Y0).
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    tau = sum((x - mean_x) * (y - mean_y) for x, y in points) / sum(
        (x - mean_x) ** 2 for x, _ in points
    )
    log_y0 = mean_x - mean_y / tau
    return [max(0.0, tau * (math.log(max(luminance(rgb), 1e-6)) - log_y0)) for rgb in palette]


class Zapper:
    """The NES Zapper on a controller port: D3 = light (0: sensed), D4 = trigger.

    Zapper.wiki. The trigger reads 1 while half-pulled; one host button stands for
    the whole pull, and its release holds the bit for 100 ms, the time the gun's
    10 uF and the console's 10k pull-up take to read "released". ``aim`` is the
    picture pixel (x, y) the gun points at, or None off the screen.
    """

    def __init__(self, ppu: PPU, palette: Sequence[bytes]) -> None:
        self.ppu = ppu
        self.aim: tuple[int, int] | None = None
        self._trigger = False
        timing = ppu.timing
        self._dots_per_line = 341
        self._frame_dots = timing.lines * 341
        self._hold_ticks = timing.master_hz // 10
        self._released_at: int | None = None
        self._lines = zapper_lines(palette)

    @property
    def trigger(self) -> bool:
        return self._trigger

    @trigger.setter
    def trigger(self, pulled: bool) -> None:
        if self._trigger and not pulled:
            self._released_at = self.ppu.time
        self._trigger = pulled

    def set_strobe(self, high: bool) -> None:
        pass

    def clock(self) -> None:
        pass

    def light(self) -> bool:
        """Whether the sensor sees light now, as the PPU's beam stands."""
        if self.aim is None:
            return False
        x, y = self.aim
        if not (0 <= x < 256 and 0 <= y < 240):
            return False
        ppu = self.ppu
        lines = self._lines[ppu.picture[y * 256 + x]]
        if not lines:
            return False
        # Dots since the beam drew the pixel (dot x + 1 of line y), this frame or
        # the last; the pixel's value is the one drawn then.
        since = (ppu.line * 341 + ppu.dot - (y * 341 + x + 1)) % self._frame_dots
        return since < lines * self._dots_per_line

    def _trigger_bit(self) -> bool:
        if self._trigger:
            return True
        released = self._released_at
        return released is not None and self.ppu.time - released < self._hold_ticks

    def read(self) -> int:
        return (0 if self.light() else 0x08) | (0x10 if self._trigger_bit() else 0)


class FamicomZapper:
    """The Famicom's Zapper, on the expansion port: the NES Zapper's bits on $4017 only."""

    def __init__(self, ppu: PPU, palette: Sequence[bytes]) -> None:
        self.zapper = Zapper(ppu, palette)

    def set_out(self, value: int) -> None:
        pass

    def read(self, port: int) -> int:
        return self.zapper.read() if port else 0

    def clock(self, port: int) -> None:
        pass


# -- the Arkanoid (Vaus) controller ---------------------------------------------------

# Arkanoid_controller.wiki "Conversion": a rising OUT0 starts a conversion, whose
# inner timer counts a 12-bit counter until the outer timer, set by the knob,
# expires; bits 8-1 are latched into the shift register and bit 0 is its serial
# in. Conversions take "up to 7 ms"; the counter step is taken as 7 ms over 512
# counts (a **fitted** rate: the scaling pot sets it on real controllers). The
# knob is treated as still during a conversion, which the wiki allows.
VAUS_STEP_SECONDS = 0.007 / 512


class Vaus:
    """The Vaus's knob and button, as both versions share them.

    ``position`` is the knob as the game reads it, 8 bits ($00-$FF; games expect a
    range of about $A0 steps: *Arkanoid* $62-$02 wrapping, *Arkanoid II* $4D-$E2).
    """

    def __init__(self, now: Callable[[], int], ticks_per_second: int) -> None:
        self.now = now
        self.position = 0x98
        self.fire = False
        self._step = ticks_per_second * VAUS_STEP_SECONDS
        self.shift = 0
        self.serial_in = 0
        self._out0 = False
        self._end: float | None = None  # when the conversion in progress ends
        self._counting_since: float | None = None  # OUT0 last fell, or the start

    def _counter(self, time: float) -> int:
        since = self._counting_since
        return 0 if since is None else max(0, int((time - since) / self._step))

    def _settle(self, time: float) -> None:
        end = self._end
        if end is None or time < end or self._out0:
            return  # running, or held by OUT0 at 1 until it falls
        counter = self._counter(end)
        self.shift = counter >> 1 & 0xFF
        self.serial_in = counter & 1
        self._end = None

    def set_out0(self, high: bool) -> None:
        time = self.now()
        if high == self._out0:
            return
        if high:
            self._settle(time)
            if self._end is None:  # a rise starts a conversion; one in progress runs on
                self._end = time + ((self.position << 1) | 1) * self._step
            self._counting_since = None  # the counter clears while OUT0 is 1
            self._out0 = True
        else:
            self._out0 = False
            self._counting_since = time
            if self._end is not None and self._end < time:
                self._end = time  # held past its end by OUT0: it ends at the fall
            self._settle(time)

    def data(self) -> int:
        """The shift register's output, inverted: the next knob bit, MSB first."""
        self._settle(self.now())
        return (~self.shift >> 7) & 1

    def shift_out(self) -> None:
        time = self.now()
        self._settle(time)
        serial = self._counter(time) & 1 if self._end is not None else self.serial_in
        self.shift = (self.shift << 1 | serial) & 0xFF


class VausNES:
    """The NES Vaus on a controller port: D3 = fire (1: pressed), D4 = knob data."""

    def __init__(self, now: Callable[[], int], ticks_per_second: int) -> None:
        self.vaus = Vaus(now, ticks_per_second)

    def set_strobe(self, high: bool) -> None:
        self.vaus.set_out0(high)

    def read(self) -> int:
        vaus = self.vaus
        return (0x08 if vaus.fire else 0) | vaus.data() << 4

    def clock(self) -> None:
        self.vaus.shift_out()


class VausFamicom:
    """The Famicom Vaus on the expansion port: $4016 D1 = fire, $4017 D1 = knob data.

    ``second``: a second Vaus in the *Arkanoid II* controller's own expansion port,
    which sees OUT0 and $4017's /OE and answers on $4017 D3 (fire) and D4 (knob)
    (Arkanoid_controller.wiki "Arkanoid II expansion port").
    """

    def __init__(self, now: Callable[[], int], ticks_per_second: int, second: bool = False) -> None:
        self.vaus = Vaus(now, ticks_per_second)
        self.second = Vaus(now, ticks_per_second) if second else None

    def set_out(self, value: int) -> None:
        self.vaus.set_out0(bool(value & 1))
        if self.second is not None:
            self.second.set_out0(bool(value & 1))

    def read(self, port: int) -> int:
        vaus = self.vaus
        if not port:
            return 0x02 if vaus.fire else 0
        value = vaus.data() << 1
        second = self.second
        if second is not None:
            value |= (0x08 if second.fire else 0) | second.data() << 4
        return value

    def clock(self, port: int) -> None:
        if port:
            self.vaus.shift_out()
            if self.second is not None:
                self.second.shift_out()


# -- mats ----------------------------------------------------------------------------

# Power_Pad.wiki: button numbers as on side B (1-4 top row, left to right).
POWER_PAD_LOW = (2, 1, 5, 9, 6, 10, 11, 7)  # D3, reads 0-7
POWER_PAD_HIGH = (4, 3, 12, 8)  # D4, reads 0-3, then 1s


class PowerPad:
    """The Power Pad (Family Fun Fitness) on a controller port: two 4021s, on D3 and D4.

    ``buttons``: bit n-1 for button n, numbered as on side B (side A's marks are
    the same sensors). Pressed reads 1; after 8 reads both bits read 1.
    """

    def __init__(self) -> None:
        self.buttons = 0
        self.strobe = False
        self._low = 0
        self._high = 0

    def _latch(self) -> None:
        buttons = self.buttons
        self._low = sum((buttons >> (n - 1) & 1) << i for i, n in enumerate(POWER_PAD_LOW))
        high = sum((buttons >> (n - 1) & 1) << i for i, n in enumerate(POWER_PAD_HIGH))
        self._high = high | 0xF0

    def set_strobe(self, high: bool) -> None:
        if high or self.strobe:
            self._latch()
        self.strobe = high

    def read(self) -> int:
        if self.strobe:
            self._latch()
        return (self._low & 1) << 3 | (self._high & 1) << 4

    def clock(self) -> None:
        if self.strobe:
            self._latch()
        else:
            self._low = self._low >> 1 | 0x80
            self._high = self._high >> 1 | 0x80


class FamilyTrainer:
    """The Family Trainer Mat (and the Tap-tap Mat) on the expansion port.

    Power_Pad.wiki "Family Trainer Mat": OUT2-OUT0 = 1 leave out the top, middle
    and bottom rows; $4017 D4-D1 are the columns from the left, 0 when a button in
    a selected row is pressed. ``buttons`` numbered as on the Power Pad's side B.
    """

    def __init__(self) -> None:
        self.buttons = 0
        self._out = 7

    def set_out(self, value: int) -> None:
        self._out = value & 7

    def read(self, port: int) -> int:
        if not port:
            return 0
        pressed = 0
        for row, ignore in enumerate((4, 2, 1)):  # top: OUT2, middle: OUT1, bottom: OUT0
            if not self._out & ignore:
                pressed |= self.buttons >> (4 * row) & 0x0F
        # Button 1 (left column) on D4, button 4 on D1.
        columns = sum((pressed >> c & 1) << (4 - c) for c in range(4))
        return 0x1E & ~columns

    def clock(self, port: int) -> None:
        pass


# -- the Family BASIC Keyboard ---------------------------------------------------------

# Family_BASIC_Keyboard.wiki "Matrix": per row, column 0 then column 1, each from
# $4017 D4 down to D1.
KEYBOARD_MATRIX = (
    (("]", "[", "RETURN", "F8"), ("STOP", "YEN", "RSHIFT", "KANA")),
    ((";", ":", "@", "F7"), ("^", "-", "/", "_")),
    (("K", "L", "O", "F6"), ("0", "P", ",", ".")),
    (("J", "U", "I", "F5"), ("8", "9", "N", "M")),
    (("H", "G", "Y", "F4"), ("6", "7", "V", "B")),
    (("D", "R", "T", "F3"), ("4", "5", "C", "F")),
    (("A", "S", "W", "F2"), ("3", "E", "Z", "X")),
    (("CTR", "Q", "ESC", "F1"), ("2", "1", "GRPH", "LSHIFT")),
    (("LEFT", "RIGHT", "UP", "CLR"), ("INS", "DEL", "SPACE", "DOWN")),
)
KEYBOARD_KEYS = frozenset(key for row in KEYBOARD_MATRIX for column in row for key in column)


class FamilyBasicKeyboard:
    """The Family BASIC Keyboard (HVC-007) on the expansion port.

    $4016 write: OUT0 resets to row 0; OUT1 selects the column, and a fall moves to
    the next row (from the keyless 10th, back to the first); OUT2 enables the
    matrix, else everything reads 0. $4017 D4-D1: the selected keys, 0 = held.
    ``keys``: the held keys' names (``KEYBOARD_KEYS``). ``recorder``: a Data
    Recorder on its jacks, OUT0 out and $4016 D1 back. The matrix's settling times
    are not modelled.
    """

    def __init__(self, recorder: DataRecorder | None = None) -> None:
        self.keys: set[str] = set()
        self.recorder = recorder
        self.row = 0
        self._column = 0
        self._enabled = False

    def set_out(self, value: int) -> None:
        if self.recorder is not None:
            self.recorder.output(value & 1)
        column = value >> 1 & 1
        if value & 1:
            self.row = 0
        elif self._column and not column:
            self.row = (self.row + 1) % 10
        self._column = column
        self._enabled = bool(value & 4)

    def read(self, port: int) -> int:
        if not self._enabled:
            return 0
        if not port:
            return self.recorder.input() << 1 if self.recorder is not None else 0
        if self.row >= len(KEYBOARD_MATRIX):
            return 0x1E
        names = KEYBOARD_MATRIX[self.row][self._column]
        held = sum(1 << (4 - i) for i, name in enumerate(names) if name in self.keys)
        return 0x1E & ~held

    def clock(self, port: int) -> None:
        pass


class KonamiHyperShot:
    """Konami's Hyper Shot pair on the expansion port (Konami_Hyper_Shot.wiki).

    OUT1/OUT2 = 0 enable players 1/2; $4017 D1-D4: player 1 Run, Jump, player 2
    Run, Jump (1: pressed). ``buttons``: those four bits, in that order.
    """

    def __init__(self) -> None:
        self.buttons = 0
        self._out = 6

    def set_out(self, value: int) -> None:
        self._out = value & 6

    def read(self, port: int) -> int:
        if not port:
            return 0
        enabled = (0 if self._out & 2 else 0x3) | (0 if self._out & 4 else 0xC)
        return (self.buttons & enabled) << 1

    def clock(self, port: int) -> None:
        pass


# -- serial reports: mice, SNES pads, the Hori Track ---------------------------------------


class SerialReport:
    """A controller-port device that latches a report when OUT0 falls and shifts it out.

    ``report()`` gives the bits in the order they are read; after them, ``fill``.
    While OUT0 is high every read returns the report's first bit, as a 4021's does.
    ``bit`` is the data line (0: D0; 1: D1 on the Famicom expansion port).
    """

    bit = 0
    fill = 1

    def __init__(self) -> None:
        self.strobe = False
        self._bits: list[int] = []
        self._index = 0

    def report(self) -> list[int]:
        raise NotImplementedError

    def set_strobe(self, high: bool) -> None:
        if self.strobe and not high:
            self._bits = self.report()
            self._index = 0
        self.strobe = high

    def read(self) -> int:
        if self.strobe:
            return self.fill << self.bit
        bits = self._bits
        value = bits[self._index] if self._index < len(bits) else self.fill
        return value << self.bit

    def clock(self) -> None:
        if not self.strobe:
            self._index += 1


def _msb_first(value: int, width: int) -> list[int]:
    return [value >> (width - 1 - i) & 1 for i in range(width)]


class _Pointer:
    """Motion a host feeds in (``move``), taken whole at each report."""

    def __init__(self) -> None:
        self.left = False
        self.right = False
        self._dx = 0
        self._dy = 0

    def move(self, dx: int, dy: int) -> None:
        self._dx += dx
        self._dy += dy

    def _take(self, limit: int) -> tuple[int, int]:
        dx = max(-limit, min(limit, self._dx))
        dy = max(-limit, min(limit, self._dy))
        self._dx -= dx
        self._dy -= dy
        return dx, dy


class SnesController(SerialReport):
    """A Super NES controller through an adapter (SNES_controller.wiki): 16 bits, B
    first, the last four 0, then 1s. ``buttons``: B Y Select Start Up Down Left Right
    A X L R in bits 0-11 (so its low byte is an NES pad's)."""

    def __init__(self) -> None:
        super().__init__()
        self.buttons = 0

    def set_strobe(self, high: bool) -> None:
        super().set_strobe(high)

    def read(self) -> int:
        if self.strobe:
            return self.buttons & 1
        return super().read()

    def report(self) -> list[int]:
        return [self.buttons >> i & 1 for i in range(12)] + [0, 0, 0, 0]


class SnesMouse(SerialReport, _Pointer):
    """The Super NES Mouse through an adapter (Super_NES_Mouse.wiki): 32 bits MSB
    first: $00; right, left, sensitivity, signature 0001; then Y and X as sign and
    magnitude (1: up, left), the magnitude's sign repeating the last when 0. A clock
    while OUT0 is high steps the sensitivity; motion is taken as setting 0's counts
    and mapped through the wiki's table for 1 and 2."""

    TABLES = ((0, 1, 2, 3, 4, 5, 6, 7), (0, 1, 2, 3, 8, 10, 12, 21), (0, 1, 4, 9, 12, 20, 24, 28))

    def __init__(self) -> None:
        SerialReport.__init__(self)
        _Pointer.__init__(self)
        self.sensitivity = 0
        self._up = 0
        self._leftward = 0

    def clock(self) -> None:
        if self.strobe:
            self.sensitivity = (self.sensitivity + 1) % 3
        else:
            super().clock()

    def _magnitude(self, value: int) -> int:
        size = min(abs(value), 63)
        if self.sensitivity:
            table = self.TABLES[self.sensitivity]
            size = table[min(size, 7)]
        return size

    def report(self) -> list[int]:
        dx, dy = self._take(63)
        if dy:
            self._up = int(dy < 0)
        if dx:
            self._leftward = int(dx < 0)
        second = self.right << 7 | self.left << 6 | self.sensitivity << 4 | 0x1
        third = self._up << 7 | self._magnitude(dy)
        fourth = self._leftward << 7 | self._magnitude(dx)
        return (
            _msb_first(0, 8) + _msb_first(second, 8) + _msb_first(third, 8) + _msb_first(fourth, 8)
        )


class SuborMouse(SerialReport, _Pointer):
    """The Subor Mouse (Subor_Mouse.wiki): 24 bits, bit 23 first: left, right, E,
    then up, down, left, right movement flags, then |X| and |Y| (0-127) when E is
    1 (movement beyond one unit). Its first 8 bits read as a pad moved by one unit."""

    def __init__(self) -> None:
        SerialReport.__init__(self)
        _Pointer.__init__(self)

    def report(self) -> list[int]:
        dx, dy = self._take(127)
        big = abs(dx) > 1 or abs(dy) > 1
        value = (
            self.left << 23
            | self.right << 22
            | big << 21
            | (dy < 0) << 19
            | (dy > 0) << 18
            | (dx < 0) << 17
            | (dx > 0) << 16
        )
        if big:
            value |= abs(dx) << 8 | abs(dy)
        return _msb_first(value, 24)


class MacroWinnersMouse(SerialReport, _Pointer):
    """The Macro Winners (GameStar) Mouse, and the Mega Book's (Macro_Winners_Mouse.wiki).

    One byte per strobe, MSB first. Motion within one unit each way: one byte; else
    three, one per strobe. Movement beyond 31 units is held for the next report.
    """

    def __init__(self, mega_book: bool = False) -> None:
        SerialReport.__init__(self)
        _Pointer.__init__(self)
        self.mega_book = mega_book
        self._pending: list[int] = []

    def report(self) -> list[int]:
        if not self._pending:
            dx, dy = self._take(31)
            buttons = self.left << 7 | self.right << 6
            if abs(dx) <= 1 and abs(dy) <= 1:
                x = 3 if dx < 0 else dx
                y = 3 if dy < 0 else dy
                byte = buttons | (x << 2 | y if self.mega_book else x << 4 | y << 2)
                self._pending = [byte]
            else:
                sx, sy = int(dx < 0), int(dy < 0)
                ax, ay = abs(dx), abs(dy)
                if self.mega_book:
                    first = buttons | 0x10 | sx << 3 | (ax >> 4) << 2 | sy << 1 | ay >> 4
                    self._pending = [first, 0x20 | (ax & 15), 0x30 | (ay & 15)]
                else:
                    first = buttons | sx << 5 | (ax >> 4) << 4 | sy << 3 | (ay >> 4) << 2 | 1
                    self._pending = [first, (ax & 15) << 2 | 2, (ay & 15) << 2 | 3]
        return _msb_first(self._pending.pop(0), 8)


class YuxingMouse(SerialReport, _Pointer):
    """The Yuxing Mouse (Yuxing_Mouse.wiki): a serial mouse with X and Y swapped,
    strobed by writing 0 then 1, its data inverted. Three 9-bit packets (0 start
    bit, seven data bits, 1 stop bit): sync, buttons and the top bits of Y and X,
    then Y's low six bits, then X's. The order the 7 data bits leave in is taken as
    MSB first (UNVERIFIED)."""

    fill = 0

    def __init__(self) -> None:
        SerialReport.__init__(self)
        _Pointer.__init__(self)

    def set_strobe(self, high: bool) -> None:
        if high and not self.strobe:  # the inverted strobe: a rise latches
            self._bits = self.report()
            self._index = 0
        self.strobe = high

    def read(self) -> int:
        bits = self._bits
        value = bits[self._index] if self._index < len(bits) else 1
        return (value ^ 1) << self.bit

    def clock(self) -> None:
        self._index += 1

    def report(self) -> list[int]:
        dx, dy = self._take(127)
        x, y = dx & 0xFF, dy & 0xFF
        first = 1 << 6 | (not self.left) << 5 | self.right << 4 | (x >> 6) << 2 | y >> 6
        bits: list[int] = []
        for data in (first, y & 0x3F, x & 0x3F):
            bits += [0, *_msb_first(data, 7), 1]
        return bits


class HoriTrack(SerialReport, _Pointer):
    """The Hori Track (Hori_Track.wiki) on the Famicom expansion port, $4016 D1
    (UNVERIFIED: the page does not say). Byte 1: its standard pad, A first; byte 2,
    MSB first: axis 1 and axis 2, signed 4 bits, XOR $F; byte 3: rotation mode (0:
    R), speed (0: Hi), ID 1, then 0000. Then 1s (UNVERIFIED). ``pad``: its buttons.
    In mode R (the default) axis 1 points left and axis 2 down."""

    bit = 1

    def __init__(self) -> None:
        SerialReport.__init__(self)
        _Pointer.__init__(self)
        self.pad = StandardController()
        self.rotation_l = False
        self.slow = False

    def report(self) -> list[int]:
        dx, dy = self._take(7)
        if self.rotation_l:
            axis1, axis2 = -dy, dx
        else:
            axis1, axis2 = -dx, dy
        axes = ((axis1 & 15) ^ 15) << 4 | ((axis2 & 15) ^ 15)
        third = self.rotation_l << 7 | self.slow << 6 | 1 << 4
        pad = [self.pad.buttons >> i & 1 for i in range(8)]
        return pad + _msb_first(axes, 8) + _msb_first(third, 8)

    def set_out(self, value: int) -> None:
        self.set_strobe(bool(value & 1))

    def read(self, port: int = 0) -> int:  # type: ignore[override]
        return super().read() if port == 0 else 0

    def clock(self, port: int = 0) -> None:  # type: ignore[override]
        if port == 0:
            super().clock()


# -- the Subor Keyboard ---------------------------------------------------------------------

# MAME's src/devices/bus/nes_ctrl/suborkey.cpp (BSD-3-Clause, Fabio Priuli): no
# NESdev wiki page describes it. 13 rows of 8 keys, bit 0 first; names as PC keys.
SUBOR_MATRIX = (
    ("4", "G", "F", "C", "F2", "E", "5", "V"),
    ("2", "D", "S", "END", "F1", "W", "3", "X"),
    ("INSERT", "BACKSPACE", "PAGEDOWN", "RIGHT", "F8", "PAGEUP", "DELETE", "HOME"),
    ("9", "I", "L", ",", "F5", "O", "0", "."),
    ("]", "ENTER", "UP", "LEFT", "F7", "[", "\\", "DOWN"),
    ("Q", "CAPSLOCK", "Z", "TAB", "ESC", "A", "1", "LCTRL"),
    ("7", "Y", "K", "M", "F4", "U", "8", "J"),
    ("-", ";", "'", "/", "F6", "P", "=", "LSHIFT"),
    ("T", "H", "N", "SPACE", "F3", "R", "6", "B"),
    ("", "", "", "", "", "", "", ""),
    ("LALT", "KP4", "KP7", "F11", "F12", "KP1", "KP2", "KP8"),
    ("KP-", "KP+", "KP*", "KP9", "F10", "KP5", "KP/", "NUMLOCK"),
    ("`", "KP6", "PAUSE", "SPACE2", "F9", "KP3", "KP.", "KP0"),
)
SUBOR_KEYS = frozenset(name for row in SUBOR_MATRIX for name in row if name)


class SuborKeyboard:
    """The Subor (Xiao Ba Wang) Keyboard on the expansion port, as MAME's suborkey.

    $4016 write, while OUT2 is 1: OUT1 selects the row's low (0) or high (1) four
    keys, its fall from 1 moves to the next row (past row 12, back to 0), OUT0
    resets to row 0. $4017 D1-D4: the selected four keys, 0 = held (a row past the
    matrix reads $1E). ``keys``: the held keys' names (``SUBOR_KEYS``).
    """

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.row = 0
        self._high = 0

    def set_out(self, value: int) -> None:
        if not value & 4:
            return
        high = value >> 1 & 1
        if self._high and not high:
            self.row = self.row + 1 if self.row < 12 else 0
        self._high = high
        if value & 1:
            self.row = 0

    def read(self, port: int) -> int:
        if not port:
            return 0
        if self.row >= len(SUBOR_MATRIX):
            return 0x1E
        names = SUBOR_MATRIX[self.row][4 * self._high : 4 * self._high + 4]
        held = sum(1 << i for i, name in enumerate(names) if name and name in self.keys)
        return ~(held << 1) & 0x1E

    def clock(self, port: int) -> None:
        pass


# -- storage: the Turbo File and the Data Recorder ------------------------------------------


class TurboFile:
    """ASCII's Turbo File (AS-TFO2) on the expansion port: 8 KiB of battery RAM read
    and written a bit at a time (Turbo_File.wiki; MAME's turbofile.cpp, BSD-3).

    $4016 write: OUT1 = 0 resets to address 0, bit 0; a fall of OUT2 (the clock)
    stores OUT0 in the current bit (LSB first) and steps to the next, the address
    after 8. $4017 D2: the current bit. ``data`` is the RAM, for saving; ``locked``
    is the write-protect switch.
    """

    def __init__(self, data: bytes | None = None) -> None:
        self.data = bytearray(data or bytes(0x2000))
        self.locked = False
        self._address = 0
        self._bit = 0
        self._out = 0

    def set_out(self, value: int) -> None:
        if not value & 2:
            self._address = 0
            self._bit = 0
        if self._out & 4 and not value & 4:
            if not self.locked:
                mask = 1 << self._bit
                byte = self.data[self._address] & ~mask
                self.data[self._address] = byte | (value & 1) << self._bit
            self._bit = (self._bit + 1) & 7
            if not self._bit:
                self._address = (self._address + 1) & 0x1FFF
        self._out = value

    def read(self, port: int) -> int:
        if not port:
            return 0
        return (self.data[self._address] >> self._bit & 1) << 2

    def clock(self, port: int) -> None:
        pass


class DataRecorder:
    """The Family BASIC Data Recorder (HVC-008), or any cassette deck on its jacks.

    Family_BASIC_Data_Recorder.wiki: OUT0 is a 1-bit audio output to the tape, and
    $4016 D1 the 1-bit input back; OUT2 = 0 forces the input to 0. "For an emulator,
    just play back the same bit stream as it was emitted": the tape is the list of
    level changes, at master-tick positions along it. ``play``, ``record`` and
    ``stop`` are the deck's keys; both start from the tape's beginning.
    """

    def __init__(self, now: Callable[[], int], tape: list[tuple[int, int]] | None = None) -> None:
        self.now = now
        self.tape: list[tuple[int, int]] = list(tape or [])
        self.mode = "stop"
        self._start = 0
        self._last = 0

    def play(self) -> None:
        self.mode, self._start = "play", self.now()

    def record(self) -> None:
        self.mode, self._start = "record", self.now()
        self.tape = []
        self._last = -1

    def stop(self) -> None:
        self.mode = "stop"

    def output(self, level: int) -> None:
        if self.mode == "record" and level != self._last:
            self.tape.append((self.now() - self._start, level))
            self._last = level

    def input(self) -> int:
        if self.mode != "play" or not self.tape:
            return 0
        position = self.now() - self._start
        if position > self.tape[-1][0] + 1_000_000:
            return 0
        index = bisect_right(self.tape, (position, 2)) - 1
        return self.tape[index][1] if index >= 0 else 0


# -- the tail: light guns, push buttons, dials, tablets, glasses, robots ----------------------


class BandaiHyperShot:
    """Bandai's Hyper Shot on the expansion port (Bandai_Hyper_Shot.wiki): a pad on
    $4016 D1 (its A never reads pressed) and a Zapper on $4017 D3-D4 whose trigger
    reads 1 while fully pulled. OUT1 and OUT2 run its vibration and speaker
    (``rumble``, ``sound``). ``pad`` and ``zapper`` are what the player drives."""

    def __init__(self, ppu: PPU, palette: Sequence[bytes]) -> None:
        self.pad = StandardController()
        self.zapper = Zapper(ppu, palette)
        self.rumble = False
        self.sound = False

    def set_out(self, value: int) -> None:
        self.pad.set_strobe(bool(value & 1))
        self.rumble = bool(value & 2)
        self.sound = bool(value & 4)

    def read(self, port: int) -> int:
        if not port:
            buttons = self.pad.buttons
            self.pad.buttons = buttons & ~1  # no A
            value = self.pad.read() << 1
            self.pad.buttons = buttons
            return value
        zapper = self.zapper
        return (0 if zapper.light() else 0x08) | (0x10 if zapper.trigger else 0)

    def clock(self, port: int) -> None:
        if not port:
            self.pad.clock()


class Partytap:
    """Yonezawa's Partytap on the expansion port (Partytap.wiki): six 1-button pads.
    After a strobe, $4017 D2-D4 give buttons 1-3, then 4-6, then $14 (a detection
    value); later reads repeat it (UNVERIFIED). ``buttons``: bits 0-5 for 1-6."""

    def __init__(self) -> None:
        self.buttons = 0
        self.strobe = False
        self._reads: list[int] = []
        self._index = 0

    def set_out(self, value: int) -> None:
        high = bool(value & 1)
        if self.strobe and not high:
            b = self.buttons
            self._reads = [(b & 7) << 2, (b >> 3 & 7) << 2, 0x14]
            self._index = 0
        self.strobe = high

    def read(self, port: int) -> int:
        if not port or self.strobe:
            return 0
        reads = self._reads
        return reads[min(self._index, len(reads) - 1)] if reads else 0

    def clock(self, port: int) -> None:
        if port and not self.strobe:
            self._index += 1


class ExcitingBoxing:
    """Konami's Exciting Boxing punching bag on the expansion port
    (Exciting_Boxing_Punching_Bag.wiki; active low, as MAME's konamibag.cpp).
    OUT1 picks the sensor group; $4017 D1-D4: left hook, move right, move left,
    right hook (OUT1 = 0) or left jab, body, right jab, straight (OUT1 = 1).
    ``sensors``: bits 0-3 the first group, 4-7 the second."""

    def __init__(self) -> None:
        self.sensors = 0
        self._group = 0

    def set_out(self, value: int) -> None:
        self._group = value >> 1 & 1

    def read(self, port: int) -> int:
        if not port:
            return 0
        return ~((self.sensors >> (4 * self._group) & 15) << 1) & 0x1E

    def clock(self, port: int) -> None:
        pass


class CoconutsPachinko(SerialReport):
    """Coconuts Japan's pachinko controller (Hori CJPC-102) on the expansion port,
    $4016 D1 (Coconuts_Japan_Pachinko_Controller.wiki): its pad's 8 bits, a 1, then
    the dial's 7-bit value inverted, MSB first, then 1s. The dial converts all the
    time, so a strobe takes the latest. ``pad``; ``dial``: $03 (rest) to about $73."""

    bit = 1

    def __init__(self) -> None:
        super().__init__()
        self.pad = StandardController()
        self.dial = 0x04

    def report(self) -> list[int]:
        dial = max(0, min(0x7F, self.dial))
        pad = [self.pad.buttons >> i & 1 for i in range(8)]
        return [*pad, 1, *_msb_first(dial ^ 0x7F, 7)]

    def set_out(self, value: int) -> None:
        self.set_strobe(bool(value & 1))

    def read(self, port: int = 0) -> int:  # type: ignore[override]
        if port:
            return 0
        if self.strobe:
            return (self.pad.buttons & 1) << 1
        return super().read()

    def clock(self, port: int = 0) -> None:  # type: ignore[override]
        if not port:
            super().clock()


JISSEN_MAHJONG_ROWS = (
    ("", "", "N", "M", "L", "K", "J", "I"),  # row 1
    ("H", "G", "F", "E", "D", "C", "B", "A"),  # row 2
    ("", "RON", "RIICHI", "CHII", "PON", "KAN", "START", "SELECT"),  # row 3
)


class JissenMahjong:
    """Capcom's Jissen Mahjong controller on the expansion port
    (Jissen_Mahjong_controller.wiki): while OUT0 is 1, OUT2-OUT1 pick the row (0:
    rows 1 and 2 ORed) that loads its 4021; after the fall, $4017 D1 gives 8 bits
    in the listed order (1: held), then 1s. ``keys``: held buttons' names."""

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.strobe = False
        self._row = 0
        self._shift = 0xFF

    def _load(self) -> None:
        rows = (
            (JISSEN_MAHJONG_ROWS[0], JISSEN_MAHJONG_ROWS[1])
            if self._row == 0
            else (JISSEN_MAHJONG_ROWS[self._row - 1],)
        )
        value = 0
        for row in rows:
            value |= sum(1 << i for i, name in enumerate(row) if name and name in self.keys)
        self._shift = value

    def set_out(self, value: int) -> None:
        self._row = value >> 1 & 3
        high = bool(value & 1)
        if high or self.strobe:
            self._load()
        self.strobe = high

    def read(self, port: int) -> int:
        if not port:
            return 0
        if self.strobe:
            self._load()
        return (self._shift & 1) << 1

    def clock(self, port: int) -> None:
        if port and not self.strobe:
            self._shift = self._shift >> 1 | 0x80


class OekaKidsTablet:
    """Bandai's Oeka Kids tablet on the expansion port (Oeka_Kids_tablet.wiki, which
    calls itself possibly incorrect). OUT0 = 0 latches a report; with OUT0 = 1, a
    rise of OUT1 moves to the next bit. $4017 D2: the acknowledgement, 0 while OUT0
    and OUT1 are both 1 (the slow MCU's delay is not modelled: it answers at once);
    D3: 0 while OUT0 is 0, else the current bit inverted. The report, MSB first: X
    (0-239), Y (0-255), touching, clicking. ``x``, ``y``, ``touching``, ``click``."""

    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self.touching = False
        self.click = False
        self._out = 0
        self._bits: list[int] = []
        self._index = 0

    def set_out(self, value: int) -> None:
        strobe, advance = value & 1, value >> 1 & 1
        if not strobe:
            x = max(0, min(239, self.x))
            y = max(0, min(255, self.y))
            self._bits = [
                *_msb_first(x, 8),
                *_msb_first(y, 8),
                int(self.touching),
                int(self.click),
            ]
            self._index = -1
        elif advance and not self._out >> 1 & 1:
            self._index += 1
        self._out = value & 3

    def read(self, port: int) -> int:
        if not port:
            return 0
        strobe, advance = self._out & 1, self._out >> 1 & 1
        ack = 0 if strobe and advance else 0x04
        if not strobe:
            return ack
        index = self._index
        bit = self._bits[index] if 0 <= index < len(self._bits) else 0
        return ack | (bit ^ 1) << 3

    def clock(self, port: int) -> None:
        pass


class Famicom3DSystem:
    """The Famicom 3D System's control box (Famicom_3D_System.wiki): OUT1 says which
    eye the next field is for (0 left, 1 right), kept as ``eye`` for a display; it
    passes the expansion port through, here to ``through`` (players 3 and 4)."""

    def __init__(self) -> None:
        self.eye = 0
        self.through = ExpansionPads()

    def set_out(self, value: int) -> None:
        self.eye = value >> 1 & 1
        self.through.set_out(value)

    def read(self, port: int) -> int:
        return self.through.read(port)

    def clock(self, port: int) -> None:
        self.through.clock(port)


class PortTestPort:
    """One port of the factory port test controller (Port_test_controller.wiki): a
    pad on D0, and a signature on D4 from a shift register that D3 taps two bits
    later (Q6). Port 1's signature is 1, 0, 1, 0... then 1s; port 2's the inverse."""

    def __init__(self, pad: StandardController, second: bool) -> None:
        self.pad = pad
        self.strobe = False
        self._pattern = [(i & 1) ^ (0 if second else 1) for i in range(8)]
        self._fill = 0 if second else 1
        self._index = 0

    def _bit(self, index: int) -> int:
        return self._pattern[index] if index < 8 else self._fill

    def set_strobe(self, high: bool) -> None:
        self.pad.set_strobe(high)
        self.strobe = high
        if high:
            self._index = 0

    def read(self) -> int:
        index = self._index
        return self.pad.read() | self._bit(index + 2) << 3 | self._bit(index) << 4

    def clock(self) -> None:
        self.pad.clock()
        if not self.strobe:
            self._index += 1


# R.O.B.'s commands (R.O.B..wiki): the four bits w x y z after 000101 in 000101w1x1y1z.
ROB_COMMANDS = {
    0b0101: "up 2",
    0b1100: "up 1",
    0b0010: "down 1",
    0b1101: "down 2",
    0b0100: "left",
    0b1000: "right",
    0b0110: "close arms",
    0b1010: "open arms",
    0b1001: "LED on",
    0b0001: "reset",
}


class Rob:
    """R.O.B. (the Family Computer Robot), which watches the TV, not the bus.

    R.O.B..wiki: one bit per frame, a bright screen 1 and black 0, a command being
    the 13 bits 000101w1x1y1z. ``see(picture)`` takes each frame the board drew; it
    reads the frame as bright when the middle of the picture is mostly lit (official
    games flash $2A green on $0F black). The decoded state is kept here (``height``
    0-5, ``turn`` -2 to 2, ``arms_closed``, ``led``, ``commands``); the robot's
    hands pressing pad 2's buttons in *Gyromite* is left to the player.
    """

    def __init__(self, palette: Sequence[bytes]) -> None:
        self._bright = [luminance(rgb) > 60 for rgb in palette]
        self._bits = 0
        self.height = 2
        self.turn = 0
        self.arms_closed = False
        self.led = False
        self.commands: list[str] = []

    def see(self, picture: Sequence[int]) -> str | None:
        bright = self._bright
        lit = sum(
            bright[picture[y * 256 + x]] for y in range(80, 160, 8) for x in range(64, 192, 8)
        )
        self._bits = (self._bits << 1 | (lit > 80)) & 0x1FFF
        # 000101w1x1y1z, oldest bit highest: the fixed bits are 12-7, 5, 3 and 1.
        if self._bits & 0b1111110101010 != 0b0001010101010:
            return None
        bits = self._bits
        command = (bits >> 6 & 1) << 3 | (bits >> 4 & 1) << 2 | (bits >> 2 & 1) << 1 | (bits & 1)
        name = ROB_COMMANDS.get(command)
        if name is None:
            return None
        self._bits = 0
        self._act(name)
        self.commands.append(name)
        return name

    def _act(self, name: str) -> None:
        if name.startswith("up"):
            self.height = min(5, self.height + int(name[-1]))
        elif name.startswith("down"):
            self.height = max(0, self.height - int(name[-1]))
        elif name == "left":
            self.turn = max(-2, self.turn - 1)
        elif name == "right":
            self.turn = min(2, self.turn + 1)
        elif name == "close arms":
            self.arms_closed = True
        elif name == "open arms":
            self.arms_closed = False
        elif name == "LED on":
            self.led = True
        elif name == "reset":
            self.led, self.arms_closed, self.height, self.turn = False, False, 2, 0


# -- choosing devices -------------------------------------------------------------------

# NES_2.0.wiki "Default Expansion Device": the numbers built here.
STANDARD = 0x01
FOUR_SCORE = 0x02
FAMICOM_FOUR_PLAYERS = 0x03
ZAPPER = 0x08
TWO_ZAPPERS = 0x09
POWER_PAD_A = 0x0B
POWER_PAD_B = 0x0C
FAMILY_TRAINER_A = 0x0D
FAMILY_TRAINER_B = 0x0E
VAUS_NES = 0x0F
VAUS_FAMICOM = 0x10
VAUS_TWO_AND_RECORDER = 0x11  # Arkanoid II: its recorder needs the keyboard, not built here
KONAMI_HYPER_SHOT = 0x12
TAPTAP_MAT = 0x1A
BANDAI_HYPER_SHOT = 0x0A
PACHINKO = 0x13
BOXING_BAG = 0x14
JISSEN_MAHJONG = 0x15
PARTYTAP = 0x16
OEKA_KIDS = 0x17
FAMICOM_3D = 0x1D
ROB_GYROMITE = 0x1F
ROB_STACK_UP = 0x2E
PORT_TEST = 0x37
DATA_RECORDER = 0x20
TURBO_FILE = 0x21
FAMILY_BASIC_KEYBOARD = 0x23
SUBOR_KEYBOARD = 0x26
SUBOR_KEYBOARD_MACRO_WINNERS = 0x27
SUBOR_KEYBOARD_MOUSE_4016 = 0x28
SNES_MOUSE_4016 = 0x29
SNES_CONTROLLERS = 0x2B
SUBOR_KEYBOARD_MOUSE_4017 = 0x36
YUXING_MOUSE = 0x43
SUBOR_KEYBOARD_YUXING = 0x44
SNES_MOUSE_4017 = 0x48
ZAPPER_4016 = 0x49
SUBOR_KEYBOARD_MEGA_BOOK = 0x4F
HORI_TRACK = 0x50

# Devices only the NES's controller ports take: such a cartridge runs on the NES.
NES_ONLY = frozenset({FOUR_SCORE, POWER_PAD_A, POWER_PAD_B, VAUS_NES, TWO_ZAPPERS})

DEVICE_NAMES = {
    STANDARD: "standard controllers",
    FOUR_SCORE: "NES Four Score",
    FAMICOM_FOUR_PLAYERS: "Famicom four-player adapter (simple)",
    ZAPPER: "Zapper",
    TWO_ZAPPERS: "two Zappers",
    POWER_PAD_A: "Power Pad (side A)",
    POWER_PAD_B: "Power Pad (side B)",
    FAMILY_TRAINER_A: "Family Trainer Mat (side A)",
    FAMILY_TRAINER_B: "Family Trainer Mat (side B)",
    VAUS_NES: "Arkanoid Vaus (NES)",
    VAUS_FAMICOM: "Arkanoid Vaus (Famicom)",
    VAUS_TWO_AND_RECORDER: "two Arkanoid Vaus (Famicom; no data recorder)",
    KONAMI_HYPER_SHOT: "Konami Hyper Shot",
    TAPTAP_MAT: "Tap-tap Mat",
    DATA_RECORDER: "Family BASIC Data Recorder",
    TURBO_FILE: "ASCII Turbo File",
    FAMILY_BASIC_KEYBOARD: "Family BASIC Keyboard and Data Recorder",
    SUBOR_KEYBOARD: "Subor Keyboard",
    SUBOR_KEYBOARD_MACRO_WINNERS: "Subor Keyboard and Macro Winners Mouse",
    SUBOR_KEYBOARD_MOUSE_4016: "Subor Keyboard and Subor Mouse ($4016)",
    SNES_MOUSE_4016: "Super NES Mouse ($4016)",
    SNES_CONTROLLERS: "two Super NES controllers",
    SUBOR_KEYBOARD_MOUSE_4017: "Subor Keyboard and Subor Mouse ($4017)",
    YUXING_MOUSE: "Yuxing Mouse ($4016)",
    SUBOR_KEYBOARD_YUXING: "Subor Keyboard and Yuxing Mouse ($4016)",
    SNES_MOUSE_4017: "Super NES Mouse ($4017)",
    ZAPPER_4016: "Zapper ($4016)",
    SUBOR_KEYBOARD_MEGA_BOOK: "Subor Keyboard and Mega Book Mouse",
    HORI_TRACK: "Hori Track",
    BANDAI_HYPER_SHOT: "Bandai Hyper Shot",
    PACHINKO: "Coconuts Japan Pachinko Controller",
    BOXING_BAG: "Exciting Boxing punching bag",
    JISSEN_MAHJONG: "Jissen Mahjong controller",
    PARTYTAP: "Partytap",
    OEKA_KIDS: "Oeka Kids tablet",
    FAMICOM_3D: "Famicom 3D System",
    ROB_GYROMITE: "R.O.B. (Gyromite)",
    ROB_STACK_UP: "R.O.B. (Stack-Up)",
    PORT_TEST: "port test controller",
}


def plug(
    board: Board, device: int, famicom: bool, palette: Sequence[bytes] | None = None
) -> object | None:
    """Put in the devices of NES 2.0 expansion number ``device``; return the one the
    player drives (None for standard pads, or a number not built here).

    ``famicom``: the console has the Famicom's expansion port, which takes the
    Famicom versions of the Zapper and the Vaus; the NES takes them on port 2.
    """
    ppu = board.ppu
    timing = ppu.timing
    ticks = timing.master_hz
    if palette is None:
        from .video import load_palette, palette_for

        palette = load_palette(palette_for(timing), timing.swapped_emphasis)
    if device == FOUR_SCORE:
        four = FourScore()
        board.pads = list(four.ports)
        return four
    if device == FAMICOM_FOUR_PLAYERS:
        board.expansion = ExpansionPads()
        return board.expansion
    if device == ZAPPER:
        if famicom:
            board.expansion = FamicomZapper(ppu, palette)
            return board.expansion.zapper
        board.pads[1] = Zapper(ppu, palette)
        return board.pads[1]
    if device == TWO_ZAPPERS:
        board.pads = [Zapper(ppu, palette), Zapper(ppu, palette)]
        return board.pads
    if device in (POWER_PAD_A, POWER_PAD_B):
        board.pads[1] = PowerPad()
        return board.pads[1]
    if device in (FAMILY_TRAINER_A, FAMILY_TRAINER_B, TAPTAP_MAT):
        board.expansion = FamilyTrainer()
        return board.expansion
    if device == VAUS_TWO_AND_RECORDER:
        board.expansion = VausFamicom(lambda: ppu.time, ticks, second=True)
        return [board.expansion.vaus, board.expansion.second]
    if device == VAUS_NES or (device == VAUS_FAMICOM and not famicom):
        vaus = VausNES(lambda: ppu.time, ticks)
        board.pads[1] = vaus
        return vaus.vaus
    if device == VAUS_FAMICOM:
        board.expansion = VausFamicom(lambda: ppu.time, ticks)
        return board.expansion.vaus
    if device == KONAMI_HYPER_SHOT:
        board.expansion = KonamiHyperShot()
        return board.expansion
    if device in (FAMILY_BASIC_KEYBOARD, DATA_RECORDER):
        recorder = DataRecorder(lambda: ppu.time)
        board.expansion = FamilyBasicKeyboard(recorder)
        return board.expansion if device == FAMILY_BASIC_KEYBOARD else recorder
    if device == TURBO_FILE:
        board.expansion = TurboFile()
        return board.expansion
    if device == ZAPPER_4016:
        board.pads[0] = Zapper(ppu, palette)
        return board.pads[0]
    if device in (SNES_MOUSE_4016, SNES_MOUSE_4017):
        mouse = SnesMouse()
        board.pads[0 if device == SNES_MOUSE_4016 else 1] = mouse
        return mouse
    if device == SNES_CONTROLLERS:
        board.pads = [SnesController(), SnesController()]
        return board.pads
    if device == YUXING_MOUSE:
        board.pads[0] = YuxingMouse()
        return board.pads[0]
    if device == HORI_TRACK:
        board.expansion = HoriTrack()
        return board.expansion
    simple = {
        PACHINKO: CoconutsPachinko,
        BOXING_BAG: ExcitingBoxing,
        JISSEN_MAHJONG: JissenMahjong,
        PARTYTAP: Partytap,
        OEKA_KIDS: OekaKidsTablet,
        FAMICOM_3D: Famicom3DSystem,
    }
    if device in simple:
        board.expansion = simple[device]()
        return board.expansion
    if device == BANDAI_HYPER_SHOT:
        board.expansion = BandaiHyperShot(ppu, palette)
        return board.expansion
    if device in (ROB_GYROMITE, ROB_STACK_UP):
        return Rob(palette)  # it watches the picture; nothing on the bus
    if device == PORT_TEST:
        pads = [StandardController(), StandardController()]
        board.pads = [PortTestPort(pads[0], False), PortTestPort(pads[1], True)]
        return board.pads
    if device in SUBOR_SETS:
        keyboard = SuborKeyboard()
        board.expansion = keyboard
        port, mouse_type = SUBOR_SETS[device]
        if mouse_type is None:
            return keyboard
        mouse = mouse_type()
        board.pads[port] = mouse
        return [keyboard, mouse]
    return None


# The Subor Keyboard's sets: the mouse's port and kind (NES_2.0.wiki).
SUBOR_SETS: dict[int, tuple[int, Callable[[], object] | None]] = {
    SUBOR_KEYBOARD: (0, None),
    SUBOR_KEYBOARD_MACRO_WINNERS: (1, MacroWinnersMouse),
    SUBOR_KEYBOARD_MOUSE_4016: (0, SuborMouse),
    SUBOR_KEYBOARD_MOUSE_4017: (1, SuborMouse),
    SUBOR_KEYBOARD_YUXING: (0, YuxingMouse),
    SUBOR_KEYBOARD_MEGA_BOOK: (1, lambda: MacroWinnersMouse(mega_book=True)),
}
