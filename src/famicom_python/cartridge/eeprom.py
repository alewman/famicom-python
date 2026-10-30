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


class Microwire93C66:
    """Microchip's 93C66 with ORG low: 512 bytes on a 3-wire bus (93C66.pdf, Table 1-4).

    DI is clocked in on CLK's rise while CS is high; a 1 with CS and DI high is
    the start bit, then a 2-bit opcode and a 9-bit address: READ (10) drives a
    dummy 0 and then the byte MSB first on DO, the address counting on while
    clocks continue; WRITE (01) and WRAL (00 01) take 8 data bits; ERASE (11)
    and ERAL (00 10) set bytes to $FF; EWEN (00 11) and EWDS (00 00) allow and
    forbid programming (EWDS at power-on). CS low ends any instruction.
    Programming finishes at once, so DO reads ready (1) after it; DO is
    otherwise high-impedance, taken as 1 here.
    """

    size = 512
    address_bits = 9
    word_bits = 8

    def __init__(self) -> None:
        self.memory = bytearray([0xFF]) * self.size
        self.cs = self.clk = 0
        self.output = 1
        self.bits = 0  # bits shifted in since the start bit (0: no start bit yet)
        self.shift = 0
        self.write_enabled = False
        self.reading = False
        self.read_bits = 0
        self.address = 0
        self.words = self.size * 8 // self.word_bits

    def lines(self, cs: int, clk: int, di: int) -> None:
        if not cs:
            self.bits = 0
            self.reading = False
            self.output = 1
        elif clk and not self.clk:
            self._rise(di)
        self.cs, self.clk = cs, clk

    def _word(self, address: int) -> int:
        if self.word_bits == 8:
            return self.memory[address]
        return self.memory[address * 2] << 8 | self.memory[address * 2 + 1]

    def _store(self, address: int, word: int) -> None:
        if self.word_bits == 8:
            self.memory[address] = word
        else:
            self.memory[address * 2] = word >> 8
            self.memory[address * 2 + 1] = word & 0xFF

    def _rise(self, di: int) -> None:
        if self.reading:
            if self.read_bits == self.word_bits:  # sequential read: on to the next word
                self.address = (self.address + 1) % self.words
                self.read_bits = 0
            word = self._word(self.address)
            self.output = (word >> (self.word_bits - 1 - self.read_bits)) & 1
            self.read_bits += 1
            return
        if not self.bits:
            if di:
                self.bits, self.shift = 1, 0
            return
        self.shift = self.shift << 1 | di
        self.bits += 1
        if self.bits == 3 + self.address_bits:  # start bit + opcode + address
            self._instruction()
        elif self.bits == 3 + self.address_bits + self.word_bits:  # + the data
            self._program()

    def _instruction(self) -> None:
        opcode = self.shift >> self.address_bits
        address = self.shift & ((1 << self.address_bits) - 1)
        special = address >> (self.address_bits - 2)
        address %= self.words
        self.address = address
        if opcode == 0b10:  # READ
            self.reading, self.read_bits, self.output = True, 0, 0
        elif opcode == 0b11:  # ERASE
            if self.write_enabled:
                self._store(address, (1 << self.word_bits) - 1)
            self._done()
        elif opcode == 0b00:
            if special in (0b11, 0b00):  # EWEN, EWDS
                self.write_enabled = special == 0b11
                self._done()
            elif special == 0b10:  # ERAL
                if self.write_enabled:
                    self.memory[:] = bytes([0xFF]) * len(self.memory)
                self._done()
            # WRAL (01) takes its data bits first

    def _program(self) -> None:
        word_bits = self.word_bits
        opcode = (self.shift >> (self.address_bits + word_bits)) & 3
        data = self.shift & ((1 << word_bits) - 1)
        if self.write_enabled:
            if opcode == 0b01:  # WRITE
                address = (self.shift >> word_bits) & ((1 << self.address_bits) - 1)
                self._store(address % self.words, data)
            else:  # WRAL
                for address in range(self.words):
                    self._store(address, data)
        self._done()

    def _done(self) -> None:
        self.bits = 0
        self.output = 1  # ready


class Microwire93C56(Microwire93C66):
    """The 93C56 with ORG high: 128 16-bit words, 8 address bits (A7 unused), big-endian here."""

    size = 256
    address_bits = 8
    word_bits = 16
