"""The Nintendo Vs. System's mainboard: what it adds around a 2A03 and an RGB PPU.

Vs._System.wiki (NESdev wiki; specification tier) is the source of every
statement here not marked otherwise; MAME's driver (``vsnes.cpp``, BSD-3,
pinned as reference/mame-nes/vsnes.cpp; emulator-derived) is the second.

The MDS mainboard carries two consoles side by side, each a letterless RP2A03,
an RGB PPU, 2 KiB of work RAM, 4 KiB of nametable RAM (always four screens)
and six EPROM sockets. A UniSystem cabinet uses one side. Against a Famicom,
each side has:

- **$4016/$4017 reads** through 74LS240 buffers that drive all eight data
  lines, so nothing here is open bus::

      $4016   P C C D  D S 0 B      $4017   D D D D  D D 0 B
              | | | |  | | | serial data, right stick     | | | | | | | serial data, left stick
              | | | |  | | always 0                       | | | | | | always 0
              | | | |  | service button                   DIP switches 8 .. 3
              | | | DIP switches 2, 1
              | coin acceptors 2, 1
              0: the primary side's CPU, 1: the secondary's

  The serial data are 4021 shift registers on the mainboard, read exactly as
  a controller is: the board's two ``pads``.
- **$4016 writes**: OUT0 strobes the sticks; OUT1 requests an interrupt on the
  other side and, from the primary side, hands the shared RAM over (the
  DualSystem); OUT2 goes to the ROM sockets (the CHR bank of mapper 99).
- **$4020-$5FFF**: one latch bit, the coin counter's electromagnet. "Reading
  from the register effectively writes the value of open bus."
- **$6000-$7FFF**: 2 KiB of RAM, mirrored, shared by the two sides and owned
  by one at a time; battery-backed.

On the :class:`~famicom_python.board.Board` this object stands where a
Famicom's expansion-port device stands (``set_out``, ``read``, ``clock``: the
same three signals), and the board asks it for $4020-$7FFF.

**Coins.** "The coin collectors will read as true for approximately 40 to
70ms"; MAME holds them 3 frames (50 ms) after hardware tests of 2.5 to 4 frames
(vsnes.cpp ``VS_COINS_AND_SERVICE``). Games reject a contact that lasts too
long or too short, so a coin is a pulse on the board's clock
(:meth:`VsMainboard.insert_coin`), 50 ms by default. "The default UniSystem
harness wiring connects both coin acceptors in parallel, and only to the $20s
bit", and "emulators should NOT set both bits high when a single virtual coin
has been inserted": acceptor 1 is D5, acceptor 2 is D6.

Not modelled: the service button's RC debounce (3-6 ms to read released; the
bit follows the button here), the coin counter's mechanics (the latch is kept
and its pulses counted), and the watchdog, which resets everything when the
secondary CPU has not read $4017 for about 1.2 s (no game that runs trips it).
"""

from __future__ import annotations

from collections.abc import Callable

from .joypad import DOWN, LEFT, RIGHT, SELECT, START, UP, A, B, StandardController
from .peripherals import Zapper

#: NES 2.0 "Default Expansion Device" numbers of the Vs. System (NES_2.0.wiki):
#: the sticks with player 1 on $4016 or on $4017, and the Vs. Zapper.
VS_1P_4016, VS_1P_4017, VS_ZAPPER = 0x04, 0x05, 0x07
VS_DEVICES = (VS_1P_4016, VS_1P_4017, VS_ZAPPER)

#: The panel's four numbered buttons, where a controller has Select and Start:
#: "Buttons for right stick (A, B, 1, 3, Up, Down, Left, Right)" on $4016 and
#: "left stick (A, B, 2, 4, ...)" on $4017. As (port, bit) by button number.
BUTTONS = {1: (0, SELECT), 2: (1, SELECT), 3: (0, START), 4: (1, START)}

COIN_SECONDS = 0.050


class VsStick(StandardController):
    """One stick and its buttons on the mainboard's 4021: a controller's report.

    ``jumper`` is bits that always read pressed. *Vs. Ice Climber*'s Japanese
    board and *Vs. Raid on Bungeling Bay* expect the fourth bit of both reports
    set (NES 2.0 Vs. hardware types 4 and 6; MAME's ``iceclmbj`` and
    ``bnglngby`` ports, "protection? START on a NES": emulator-derived, the
    wiring itself is not documented).
    """

    def __init__(self, jumper: int = 0) -> None:
        super().__init__()
        self.jumper = jumper

    def set_strobe(self, high: bool) -> None:
        if high or self.strobe:
            self.shift = self.buttons | self.jumper
        self.strobe = high

    def read(self) -> int:
        if self.strobe:
            return (self.buttons | self.jumper) & 1
        return self.shift & 1

    def clock(self) -> None:
        if self.strobe:
            self.shift = self.buttons | self.jumper
        else:
            self.shift = (self.shift >> 1) | 0x80


class VsZapper(Zapper):
    """The Vs. System's light gun: a report on $4016's 4021, not two port lines.

    Zapper.wiki: "0, 0, 0, 0, 1, 0, Light sense (inverted), Trigger ... the
    light sense status corresponds to Left and the trigger to Right, and Up is
    always pressed. Unlike the NES/Famicom Zapper, the Vs. Zapper's light sense
    is 1 when detecting". The sensor is the NES Zapper's model
    (peripherals.Zapper.light); the trigger is taken as a plain switch (MAME's
    port; the NES gun's half-pull timing is that gun's capacitor).
    """

    def __init__(self, ppu, palette) -> None:  # type: ignore[no-untyped-def]
        super().__init__(ppu, palette)
        self.shift = 0
        self.strobe = False

    def _report(self) -> int:
        return UP | (LEFT if self.light() else 0) | (RIGHT if self.trigger else 0)

    def set_strobe(self, high: bool) -> None:
        if high or self.strobe:
            self.shift = self._report()
        self.strobe = high

    def read(self) -> int:
        return (self._report() if self.strobe else self.shift) & 1

    def clock(self) -> None:
        if self.strobe:
            self.shift = self._report()
        else:
            self.shift = (self.shift >> 1) | 0x80


class SharedRAM:
    """The 2 KiB at $6000-$7FFF and which side holds it.

    "In the DualSystem it can be swapped between CPUs; in the UniSystem it is
    either ignored or a special jumper '2A04' was installed to give dedicated
    access." A UniSystem's one side always has it here (:attr:`owner` never
    moves); on a DualSystem the primary side's OUT1 chooses.
    """

    def __init__(self, owner: str, switched: bool = False) -> None:
        self.data = bytearray(0x800)
        self.owner = owner  # "primary" or "secondary"
        self.switched = switched  # the primary side's OUT1 moves it


class VsMainboard:
    """One side of the mainboard (see the module notes)."""

    def __init__(
        self,
        side: str,
        now: Callable[[], int],
        ticks_per_second: float,
        cartridge_out: Callable[[int], None],
        ram: SharedRAM | None = None,
    ) -> None:
        self.side = side
        self._now = now
        self._coin_ticks = round(COIN_SECONDS * ticks_per_second)
        self._cartridge_out = cartridge_out
        self.ram = ram if ram is not None else SharedRAM(side)
        #: DIP switches 1-8 as bits 0-7, 1 = on.
        self.dip = 0
        self.service = False
        # Each acceptor's coins: the master ticks at which a contact closes.
        self.coins: list[list[int]] = [[], []]
        self.out = 0
        self.coin_counter = 0  # the latch
        self.coins_counted = 0  # its 1 -> 0 edges: what the meter shows
        # The other side's /IRQ, on a DualSystem (set by VsDualSystem).
        self.other_irq: Callable[[bool], None] | None = None

    # -- the operator and the player -------------------------------------

    def insert_coin(self, acceptor: int = 0, at: int | None = None) -> None:
        """A coin through acceptor 0 or 1: its contact closes at master tick
        ``at`` (default: now) for :data:`COIN_SECONDS`."""
        self.coins[acceptor].append(self._now() if at is None else at)

    # -- the expansion-device protocol (board.py) ------------------------

    def set_out(self, value: int) -> None:
        """OUT0-2 moved (the 2A03 updates them on a put cycle)."""
        changed = self.out ^ value
        self.out = value
        if changed & 2:
            if self.other_irq is not None:
                # "When 0: asserts an IRQ request. When 1: releases" it.
                self.other_irq(not value & 2)
            if self.side == "primary" and self.ram.switched:
                # "When 1: the primary CPU has access and the secondary CPU
                # sees open bus. When 0: the secondary CPU has access."
                self.ram.owner = "primary" if value & 2 else "secondary"
        if changed & 4:
            self._cartridge_out(value)

    def read(self, port: int) -> int:
        """D2-D7 of $4016 (port 0) or $4017; D0 is the stick's, D1 is 0."""
        dip = self.dip
        if port:
            return dip & 0xFC
        now = self._now()
        bits = (dip & 3) << 3
        if self.service:
            bits |= 0x04
        for acceptor, coins in enumerate(self.coins):
            if coins:
                length = self._coin_ticks
                if coins[0] + length <= now:  # fallen through: forget it
                    coins[:] = [start for start in coins if now < start + length]
                if any(start <= now for start in coins):
                    bits |= 0x20 << acceptor
        if self.side == "secondary":
            bits |= 0x80
        return bits

    def clock(self, port: int) -> None:
        """The end of a read of ``port``: the sticks shift themselves."""

    # -- $4020-$7FFF (board.py) ------------------------------------------

    def write_coin_counter(self, value: int) -> None:
        """$4020-$5FFF: D0 is the electromagnet; "writing 1 then 0 will
        increment the counter". A read lands here too, with open bus."""
        value &= 1
        if self.coin_counter and not value:
            self.coins_counted += 1
        self.coin_counter = value

    def read_ram(self, address: int) -> int | None:
        ram = self.ram
        if ram.owner != self.side:
            return None  # the other side has it: open bus
        return ram.data[address & 0x7FF]

    def write_ram(self, address: int, value: int) -> None:
        ram = self.ram
        if ram.owner == self.side:
            ram.data[address & 0x7FF] = value

    def reset(self) -> None:
        """Reset: "this register is explicitly cleared on powerup and reset"."""
        self.coin_counter = 0


def panel(pads: list, players: list[int], first_on_4017: bool) -> None:
    """Put the players' buttons (``joypad`` bits, Select and Start standing for
    the panel's numbered buttons) on the two sticks.

    The cabinet wires "the left stick to $4017 and the right stick to $4016,
    but some games expect the first player to use the right stick, while others
    expect the first player to use the left stick": NES 2.0 device $04 says
    player 1 is read through $4016, $05 through $4017. The numbered buttons do
    not move with the sticks: buttons 1 and 3 are always on $4016, 2 and 4 on
    $4017, and player 1's Select and Start are taken as buttons 1 and 3,
    player 2's as 2 and 4.
    """
    stick = A | B | UP | DOWN | LEFT | RIGHT
    numbered = SELECT | START
    one = players[0] if players else 0
    two = players[1] if len(players) > 1 else 0
    on_4016, on_4017 = (two, one) if first_on_4017 else (one, two)
    if isinstance(pads[0], StandardController):
        pads[0].buttons = (on_4016 & stick) | (one & numbered)
    if isinstance(pads[1], StandardController):
        pads[1].buttons = (on_4017 & stick) | (two & numbered)
