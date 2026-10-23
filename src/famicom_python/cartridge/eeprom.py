"""Serial EEPROMs on Bandai's boards: the 24C02 (I²C, 256 bytes) and Xicor's X24C01 (128 bytes).

Written from the protocols as INES_Mapper_016.wiki, _157.wiki and _159.wiki
describe them (the parts' datasheets are not pinned): bits move on SCL's
rise, MSB first; SDA falling while SCL is high is a START, rising a STOP; the
receiver pulls SDA low on the ninth clock to acknowledge a byte.

- **24C02**: after a START, a device byte $A0 | R/W (device address 000, as
  Bandai wires it), then for a write a word address and data bytes (an
  8-byte page, the address wrapping within it), for a read the bytes from
  the current address on while the master acknowledges.
- **X24C01**: no device byte: the first byte after a START is the 7-bit
  address and R/W in D0; then data, as above (a 4-byte page). Bandai's code
  clocks bytes in LSB first (the wiki); the part takes them MSB first, so the
  addresses it stores at are the bit-reversed ones, consistently, and only
  multi-byte transfers step through them in another order. That is the
  part's behaviour, and kept.
"""

from __future__ import annotations

IDLE, DEVICE, ADDRESS, WRITE, READ = range(5)


class Eeprom:
    """The 24C02; :class:`X24C01` overrides what differs."""

    page = 8

    def __init__(self, size: int = 256) -> None:
        self.memory = bytearray(size)
        self.state = IDLE
        self.scl = self.sda = 1
        self.output = 1  # what the part drives on SDA (1 = released)
        self.clock = 0  # bits of the current byte; 8 = the acknowledge clock
        self.shift = 0
        self.address = 0
        self.ack = False  # acknowledge the byte just received
        self.after_ack = IDLE

    def lines(self, scl: int, sda: int) -> None:
        """The master's SCL and SDA (SDA released reads as 1)."""
        if scl and self.scl:
            if self.sda and not sda:
                self._start()
            elif sda and not self.sda:
                self.state = IDLE
                self.output = 1
        elif scl:
            self._rise(sda)
        elif self.scl:
            self._fall()
        self.scl, self.sda = scl, sda

    def _start(self) -> None:
        self.state, self.clock, self.shift, self.output = DEVICE, 0, 0, 1

    def _rise(self, sda: int) -> None:
        if self.state == IDLE:
            return
        if self.clock < 8:
            if self.state != READ:
                self.shift = ((self.shift << 1) | sda) & 0xFF
            self.clock += 1
            if self.clock == 8 and self.state != READ:
                self._received(self.shift)
        elif self.state == READ:  # the master's acknowledge
            if sda:
                self.state = IDLE
            else:
                self.address = (self.address + 1) % len(self.memory)
                self.clock = 0
        else:
            self.clock = 9  # the acknowledge clock seen

    def _fall(self) -> None:
        if self.state == IDLE:
            return
        if self.state == READ:
            if self.clock < 8:
                self.output = (self.memory[self.address] >> (7 - self.clock)) & 1
            else:
                self.output = 1
        elif self.clock == 8:
            self.output = 0 if self.ack else 1
        elif self.clock == 9:
            self.output = 1
            self.clock = 0
            self.shift = 0
            self.state = self.after_ack if self.ack else IDLE
            if self.state == READ:
                self.output = self.memory[self.address] >> 7

    def _received(self, byte: int) -> None:
        state = self.state
        if state == DEVICE:
            self.ack = byte & 0xFE == 0xA0
            self.after_ack = READ if byte & 1 else ADDRESS
        elif state == ADDRESS:
            self.ack, self.address, self.after_ack = True, byte % len(self.memory), WRITE
        else:
            self._store(byte)

    def _store(self, byte: int) -> None:
        self.memory[self.address] = byte
        page = self.page
        self.address = (self.address & ~(page - 1)) | ((self.address + 1) & (page - 1))
        self.ack, self.after_ack = True, WRITE


class X24C01(Eeprom):
    page = 4

    def __init__(self) -> None:
        super().__init__(128)

    def _received(self, byte: int) -> None:
        if self.state == DEVICE:
            self.address = byte >> 1
            self.ack, self.after_ack = True, READ if byte & 1 else WRITE
        else:
            self._store(byte)
