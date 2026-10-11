"""The standard controller: a 4021 shift register behind the port.

Standard_controller.wiki, Controller_reading.wiki. While the strobe (OUT0) is
high the register reloads continuously, so every read returns A. When it is
low, each clock shifts the next button out: A, B, Select, Start, Up, Down,
Left, Right, then 1s on official pads. The pad shifts at the *end* of the /OE
pulse; when that is, per console model, is the board's business
(``Machine.joypad_oe_per_cycle``).
"""

from __future__ import annotations

A, B, SELECT, START, UP, DOWN, LEFT, RIGHT = (1 << bit for bit in range(8))


class StandardController:
    def __init__(self) -> None:
        self.buttons = 0  # pressed buttons, the bits above
        self.shift = 0
        self.strobe = False

    def set_strobe(self, high: bool) -> None:
        if high or self.strobe:
            self.shift = self.buttons
        self.strobe = high

    def read(self) -> int:
        """D0 as the CPU sees it: 1 = pressed."""
        if self.strobe:
            return self.buttons & 1
        return self.shift & 1

    def clock(self) -> None:
        """The end of an /OE pulse."""
        if self.strobe:
            self.shift = self.buttons
        else:
            self.shift = (self.shift >> 1) | 0x80
