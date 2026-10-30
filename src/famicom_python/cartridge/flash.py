"""The SST39SF040 flash, the self-flashing homebrew boards' PRG (mappers 30, 111).

From Microchip's data sheet (DS20005022C, ``reference/docs/SST39SF040.pdf``,
Table 4): the chip reads like ROM until a command sequence is written to it.
Every sequence opens with $5555 = $AA, $2AAA = $55 (A14-A0; the higher lines
are don't-care), and the third write names the command:

- $A0, then the byte's address and data: Byte-Program, which only clears bits.
- $80, $5555 = $AA, $2AAA = $55, then the sector's address with $30: Sector-Erase
  (4 KiB to $FF); or $5555 with $10: Chip-Erase.
- $90: Software ID Entry. Reads with A18-A1 low give the manufacturer ($BF,
  A0 low) and the device ($B7, A0 high) until $F0 is written, alone or as a
  third command.

Any other write mid-sequence aborts to read mode. Program and erase finish at
once: the chip's 14 us and 18 ms are typical times, not fixed ones, and the
Data# Polling and Toggle Bit reads it gives meanwhile then show the finished
result, which ends a program's wait loop at its first read.
"""

from __future__ import annotations

MANUFACTURER, DEVICE = 0xBF, 0xB7  # Table 2 (SST39SF040)


class SST39SF040:
    """The command state machine over a cartridge's PRG bytes (``data``)."""

    def __init__(self, data: bytearray) -> None:
        self.data = data
        self.step = 0  # how many writes of a sequence have matched (6: program's)
        self.id_mode = False
        self.dirty = False  # the PRG differs from the image: the save

    def read(self, offset: int) -> int:
        """The byte at chip address ``offset`` (only differs in ID mode)."""
        if self.id_mode and offset >> 1 == 0:
            return DEVICE if offset & 1 else MANUFACTURER
        return self.data[offset]  # elsewhere in ID mode the data sheet says nothing

    def write(self, offset: int, value: int) -> None:
        """One write cycle at chip address ``offset``."""
        unlock = offset & 0x7FFF
        step = self.step
        self.step = 0  # unless the sequence goes on
        if (step in (0, 3) and unlock == 0x5555 and value == 0xAA) or (
            step in (1, 4) and unlock == 0x2AAA and value == 0x55
        ):
            self.step = step + 1
        elif step == 2 and unlock == 0x5555 and value in (0xA0, 0x80):
            self.step = 6 if value == 0xA0 else 3  # program's data next, or erase's unlock
        elif step == 2 and unlock == 0x5555 and value in (0x90, 0xF0):
            self.id_mode = value == 0x90
        elif step == 0 and value == 0xF0:  # Software ID Exit, the short form
            self.id_mode = False
        elif step == 5 and value == 0x30:  # Sector-Erase
            sector = offset & ~0xFFF
            self.data[sector : sector + 0x1000] = bytes([0xFF]) * 0x1000
            self.dirty = True
        elif step == 5 and unlock == 0x5555 and value == 0x10:  # Chip-Erase
            self.data[:] = bytes([0xFF]) * len(self.data)
            self.dirty = True
        elif step == 6:  # Byte-Program: bits only clear
            self.data[offset] &= value
            self.dirty = True
