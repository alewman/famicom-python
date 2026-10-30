"""The PIC16C54, the protection microcontroller of mapper 355 (and the board around it).

From Microchip's PIC16C5X data sheet (``reference/docs/PIC16C5X.pdf``, DS30453E;
Table 10-2 the instructions, Table 5-3 the reset state): 12-bit instructions,
512 words of program memory, 32 registers (INDF, TMR0, PCL, STATUS, FSR, PORTA,
PORTB, then 25 of RAM), a two-level stack, and every instruction one cycle of
four clocks but those that change the PC, which take two. The watchdog and
SLEEP are not modelled (SLEEP waits for ever here). The microcontroller's
program is the NES 2.0 image's Misc ROM.
"""

from __future__ import annotations

from .banked import Banked
from .ines import RomImage

INDF, TMR0, PCL, STATUS, FSR, PORTA, PORTB = range(7)
C, DC, Z = 1, 2, 4


class PIC16C54:
    """The core. ``port_a``/``port_b`` are the pins' inputs, set by the caller between cycles."""

    def __init__(self, program: bytes) -> None:
        self.program = [
            (program[i] | program[i + 1] << 8) & 0xFFF for i in range(0, min(len(program), 1024), 2)
        ]
        self.memory = [0] * 32
        self.memory[STATUS] = 0x18
        self.memory[FSR] = 0xE0
        self.w = 0
        self.pc = 0x1FF  # the reset vector, the last word
        self.stack = [0, 0]
        self.tris_a = 0x0F
        self.tris_b = 0xFF
        self.option = 0x3F
        self.prescaler = 0
        self.timer_hold = 0  # a write to TMR0 stops it for two cycles
        self.port_a = self.port_b = 0
        self.waiting = 0  # cycles left of a two-cycle instruction
        self.skip = False

    # -- registers -------------------------------------------------------

    def _address(self, f: int) -> int:
        return self.memory[FSR] & 0x1F if f == INDF else f

    def read(self, f: int) -> int:
        f = self._address(f)
        if f == INDF:
            return 0
        if f == PORTA:
            return (self.port_a & self.tris_a | self.memory[PORTA] & ~self.tris_a) & 0x0F
        if f == PORTB:
            return self.port_b & self.tris_b | self.memory[PORTB] & ~self.tris_b & 0xFF
        if f == PCL:
            return self.pc & 0xFF
        return self.memory[f]

    def write(self, f: int, value: int) -> None:
        f = self._address(f)
        if f == PCL:
            self.pc = value  # bit 8 clears: DS30453, "Program Counter"
            self.waiting = 1
        elif f == FSR:
            self.memory[FSR] = value | 0xE0
        elif f == STATUS:
            self.memory[STATUS] = value & 0xE7 | self.memory[STATUS] & 0x18
        elif f == TMR0:
            self.memory[TMR0] = value
            self.prescaler = 0
            self.timer_hold = 2
        elif f != INDF:
            self.memory[f] = value

    def output_a(self) -> int:
        """Port A's pins: 1 where driven high or not driven (the /IRQ line's pull-up)."""
        return (self.memory[PORTA] | self.tris_a) & 0x0F

    def _flags(self, mask: int, carry: int, half: int, result: int) -> None:
        status = self.memory[STATUS] & ~mask
        if mask & C and carry:
            status |= C
        if mask & DC and half:
            status |= DC
        if mask & Z and not result & 0xFF:
            status |= Z
        self.memory[STATUS] = status

    # -- the instruction cycle -------------------------------------------

    def _tick_timer(self) -> None:
        if self.option & 0x20:  # T0CS: the external pin, never driven here
            return
        if self.timer_hold:
            self.timer_hold -= 1
            return
        if not self.option & 0x08:  # the prescaler on TMR0
            self.prescaler += 1
            if self.prescaler < 2 << (self.option & 7):
                return
            self.prescaler = 0
        self.memory[TMR0] = (self.memory[TMR0] + 1) & 0xFF

    def cycle(self) -> None:
        """One instruction cycle (four clocks)."""
        self._tick_timer()
        if self.waiting:
            self.waiting -= 1
            return
        word = self.program[self.pc & 0x1FF]
        self.pc = (self.pc + 1) & 0x1FF
        if self.skip:
            self.skip = False
            return
        self._execute(word)

    def _store(self, d: int, f: int, value: int) -> None:
        if d:
            self.write(f, value & 0xFF)
        else:
            self.w = value & 0xFF

    def _execute(self, word: int) -> None:
        top = word >> 8
        f, d, k = word & 0x1F, word & 0x20, word & 0xFF
        if word < 0x020:
            if 0x005 <= word <= 0x007:  # TRIS
                if word == 5:
                    self.tris_a = self.w & 0x0F
                elif word == 6:
                    self.tris_b = self.w
            elif word == 0x002:
                self.option = self.w & 0x3F
            elif word == 0x003:  # SLEEP
                self.pc = (self.pc - 1) & 0x1FF
        elif word < 0x400:
            self._byte_operation(word >> 6, f, d)  # bits 9-6 name it, D5 the destination
        elif top < 0x08:  # BCF, BSF, BTFSC, BTFSS
            bit = 1 << ((word >> 5) & 7)
            kind = (word >> 8) & 3
            value = self.read(f)
            if kind == 0:
                self.write(f, value & ~bit & 0xFF)
            elif kind == 1:
                self.write(f, value | bit)
            else:
                self.skip = bool(value & bit) == (kind == 3)
        elif top == 0x08:  # RETLW
            self.w = k
            self.pc = self.stack[0]
            self.stack[0] = self.stack[1]
            self.waiting = 1
        elif top == 0x09:  # CALL
            self.stack[1] = self.stack[0]
            self.stack[0] = self.pc
            self.pc = k
            self.waiting = 1
        elif top < 0x0C:  # GOTO
            self.pc = word & 0x1FF
            self.waiting = 1
        elif top == 0x0C:  # MOVLW
            self.w = k
        else:
            value = {0x0D: self.w | k, 0x0E: self.w & k, 0x0F: self.w ^ k}[top]
            self.w = value
            self._flags(Z, 0, 0, value)

    def _byte_operation(self, op: int, f: int, d: int) -> None:
        w = self.w
        kind = op
        if kind == 0:  # MOVWF (D5 set; clear is the control group, decoded by the caller)
            self.write(f, w)
            return
        value = self.read(f)
        carry_in = self.memory[STATUS] & C
        if kind == 1:  # CLRW, CLRF
            self._store(d, f, 0)
            self._flags(Z, 0, 0, 0)
        elif kind == 2:  # SUBWF
            result = value - w
            self._flags(C | DC | Z, result >= 0, (value & 0xF) >= (w & 0xF), result)
            self._store(d, f, result)
        elif kind == 3:  # DECF
            self._store(d, f, value - 1)
            self._flags(Z, 0, 0, value - 1)
        elif kind == 4:  # IORWF
            self._store(d, f, value | w)
            self._flags(Z, 0, 0, value | w)
        elif kind == 5:  # ANDWF
            self._store(d, f, value & w)
            self._flags(Z, 0, 0, value & w)
        elif kind == 6:  # XORWF
            self._store(d, f, value ^ w)
            self._flags(Z, 0, 0, value ^ w)
        elif kind == 7:  # ADDWF
            result = value + w
            self._flags(C | DC | Z, result > 0xFF, (value & 0xF) + (w & 0xF) > 0xF, result)
            self._store(d, f, result)
        elif kind == 8:  # MOVF
            self._store(d, f, value)
            self._flags(Z, 0, 0, value)
        elif kind == 9:  # COMF
            self._store(d, f, value ^ 0xFF)
            self._flags(Z, 0, 0, value ^ 0xFF)
        elif kind == 10:  # INCF
            self._store(d, f, value + 1)
            self._flags(Z, 0, 0, value + 1)
        elif kind == 11:  # DECFSZ
            self._store(d, f, value - 1)
            self.skip = not (value - 1) & 0xFF
        elif kind == 12:  # RRF
            self._flags(C, value & 1, 0, 0)
            self._store(d, f, value >> 1 | carry_in << 7)
        elif kind == 13:  # RLF
            self._flags(C, value & 0x80, 0, 0)
            self._store(d, f, value << 1 | carry_in)
        elif kind == 14:  # SWAPF
            self._store(d, f, (value & 0x0F) << 4 | value >> 4)
        else:  # INCFSZ
            self._store(d, f, value + 1)
            self.skip = not (value + 1) & 0xFF


class Block355(Banked):
    """Mapper 355 (3D-BLOCK): NROM-256 with CHR-RAM and a PIC16C54 watching the CPU's address bus.

    NES_2.0_Mapper_355.wiki: the PIC runs at a quarter of M2. RA1-RA3 read CPU A6, A5,
    A4; RB0-RB7 CPU A12, A7, A10, A11, A9, A8, A13, A14; RA0 drives /IRQ. Its
    512 words are the image's Misc ROM. The data bus does not reach it.
    """

    counts_m2 = True
    snoops_cpu_reads = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.pic = PIC16C54(image.misc)
        self.map_prg(0, 32, 0)
        self.map_chr(0, 8, 0)
        self.address = 0
        self.divider = 0

    def _inputs(self) -> None:
        a, pic = self.address, self.pic
        pic.port_a = ((a >> 6) & 1) << 1 | ((a >> 5) & 1) << 2 | ((a >> 4) & 1) << 3 | 1
        pic.port_b = (
            (a >> 12) & 1
            | ((a >> 7) & 1) << 1
            | ((a >> 10) & 1) << 2
            | ((a >> 11) & 1) << 3
            | ((a >> 9) & 1) << 4
            | ((a >> 8) & 1) << 5
            | ((a >> 13) & 1) << 6
            | ((a >> 14) & 1) << 7
        )

    def cpu_read(self, address: int, t: int) -> int | None:
        self.address = address
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        self.address = address

    def m2(self, t: int) -> None:
        self.divider = (self.divider + 1) & 3
        if not self.divider:
            self._inputs()
            self.pic.cycle()
            self.irq = not self.pic.output_a() & 1
