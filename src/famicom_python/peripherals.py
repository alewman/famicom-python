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
    """The Famicom Vaus on the expansion port: $4016 D1 = fire, $4017 D1 = knob data."""

    def __init__(self, now: Callable[[], int], ticks_per_second: int) -> None:
        self.vaus = Vaus(now, ticks_per_second)

    def set_out(self, value: int) -> None:
        self.vaus.set_out0(bool(value & 1))

    def read(self, port: int) -> int:
        vaus = self.vaus
        if port:
            return vaus.data() << 1
        return 0x02 if vaus.fire else 0

    def clock(self, port: int) -> None:
        if port:
            self.vaus.shift_out()


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
    ``keys``: the held keys' names (``KEYBOARD_KEYS``). The Data Recorder on $4016
    is not built; the matrix's settling times are not modelled.
    """

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.row = 0
        self._column = 0
        self._enabled = False

    def set_out(self, value: int) -> None:
        column = value >> 1 & 1
        if value & 1:
            self.row = 0
        elif self._column and not column:
            self.row = (self.row + 1) % 10
        self._column = column
        self._enabled = bool(value & 4)

    def read(self, port: int) -> int:
        if not port or not self._enabled:
            return 0
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
VAUS_TWO_AND_RECORDER = 0x11  # Arkanoid II: the first Vaus only is built here
KONAMI_HYPER_SHOT = 0x12
TAPTAP_MAT = 0x1A
FAMILY_BASIC_KEYBOARD = 0x23

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
    VAUS_TWO_AND_RECORDER: "Arkanoid Vaus (Famicom; the second Vaus is not built)",
    KONAMI_HYPER_SHOT: "Konami Hyper Shot",
    TAPTAP_MAT: "Tap-tap Mat",
    FAMILY_BASIC_KEYBOARD: "Family BASIC Keyboard",
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
        device = VAUS_FAMICOM
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
    if device == FAMILY_BASIC_KEYBOARD:
        board.expansion = FamilyBasicKeyboard()
        return board.expansion
    return None
