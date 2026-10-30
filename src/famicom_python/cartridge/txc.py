"""The latch-adder-inverter protection chips and their boards: TXC's 05-00002-010 (36, 132, 173)
and the JV001 (136, 147, 172).

Each from its NESdev wiki page (INES_Mapper_036/132/136/147/172/173.wiki). The
boards wire the same chips to different data bits and bank lines; games check
the chip's arithmetic by reading it back. No judge ROM exists; the claims rest
on sweeps against Mesen2, a detector (docs/claims.md).
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .ines import RomImage


def reverse6(value: int) -> int:
    """D0-D5 in reverse order (mapper 172's board)."""
    return sum(((value >> bit) & 1) << (5 - bit) for bit in range(6))


class TXCChip:
    """The 05-00002-010: 3-bit P, R and output, S, increment (C) and invert (V).

    $4100: R += 1 if C, else R = P (inverted if V); $4101 D0: V; $4102: S (D3)
    and P (D2-D0); $4103 D0: C; a read gives R and S XOR V (D3-D0); a write to
    $8000-$FFFF copies R to the output pins.
    """

    def __init__(self) -> None:
        self.p = self.r = self.output = 0
        self.s = self.increment = self.invert = 0

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.r = (self.r + 1) & 7 if self.increment else self.p ^ (7 if self.invert else 0)
        elif register == 1:
            self.invert = value & 1
        elif register == 2:
            self.s, self.p = (value >> 3) & 1, value & 7
        else:
            self.increment = value & 1

    def read(self) -> int:
        return self.r | (self.s ^ self.invert) << 3

    def latch(self) -> None:
        self.output = self.r


class JV001:
    """The JV001: 6-bit input, register and output, mode and invert.

    $4100: with mode 0 the register takes the input (D3-D0 inverted if
    invert), with mode 1 its low four bits count up; $4101 D0: invert; $4102:
    the input; $4103 D0: the mode; a read gives the register, D5-D4 inverted
    if invert; a write to $8000-$FFFF copies the register to the output.
    """

    def __init__(self) -> None:
        self.input = self.register = self.output = 0
        self.mode = self.invert = 0

    def write(self, register: int, value: int) -> None:
        if register == 0:
            if self.mode:
                self.register = (self.register & 0x30) | ((self.register + 1) & 0x0F)
            else:
                self.register = self.input ^ (0x0F if self.invert else 0)
        elif register == 1:
            self.invert = value & 1
        elif register == 2:
            self.input = value & 0x3F
        else:
            self.mode = value & 1

    def read(self) -> int:
        return self.register ^ (0x30 if self.invert else 0)

    def latch(self) -> None:
        self.output = self.register


class ProtectedLatch(Banked):
    """A board with one of the chips at $4100-$4103 (mask $E103) and its output latched by
    writes to $8000-$FFFF, each board wiring the data bits and the outputs its own way:

    - 132 (TXC 01-22xxx): output D2 PRG A15, D1-D0 CHR A14-A13; reads at $4100
      (mask $E100) give D3-D0.
    - 173 (Idea-Tek): CHR A13 from output D0, A15 from D1, A14 the inverse of
      V; no PRG banking.
    - 36 (TXC 01-22000-400): the chip on D5-D4: PRG A16-A15 from its output;
      CHR from a separate latch at $4200 (mask $E200), D3-D0.
    - 136 (Sachen 3011): JV001 on D5-D0; CHR A15-A13 from output D2-D0, PRG
      A15 from D4; reads give D5-D0.
    - 147 (Sachen 3018): JV001 on D7-D2; PRG A15 from output D0 and A16 from
      D5, CHR A16-A13 from D4-D1.
    - 172 (Super Mega P-4070): JV001 on D0-D5 reversed; CHR A13/A14 from
      the chip's output bits 0/1 (the page's CPU D5/D4, reversed); the
      latching write also sets the mirroring (horizontal with invert clear,
      vertical with it set).

    Power-on: every register 0, but 172's Invert 1: the page gives no power-on
    state, and Venice Beach Volleyball's reset writes $8000 and uploads its
    title long before it first writes $4101, which only comes out right if
    that first write leaves vertical mirroring.
    """

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        self.board = image.board.mapper
        self.chip: TXCChip | JV001 = TXCChip() if self.board in (36, 132, 173) else JV001()
        self.chip.invert = 1 if self.board == 172 else 0
        self.chr_latch = 0
        self.prg_ram_enabled = False
        self._update()

    def _chip_value(self, value: int) -> int:
        """The written byte as the chip's data pins see it."""
        if self.board == 36:
            return (value >> 4) & 3
        if self.board == 147:
            return value >> 2
        if self.board == 172:
            return reverse6(value & 0x3F)
        return value

    def _update(self) -> None:
        out, board, chip = self.chip.output, self.board, self.chip
        prg = 0
        if board == 132:
            prg, chr8 = (out >> 2) & 1, out & 3
        elif board == 173:
            chr8 = (out & 1) | ((~chip.invert & 1) << 1) | ((out >> 1) & 1) << 2
        elif board == 36:
            prg, chr8 = out & 3, self.chr_latch
        elif board == 136:
            prg, chr8 = (out >> 4) & 1, out & 7
        elif board == 147:
            prg, chr8 = ((out >> 5) & 1) << 1 | out & 1, (out >> 1) & 0x0F
        else:  # 172
            chr8 = out & 3
        self.map_prg(0, 32, prg)
        self.map_chr(0, 8, chr8)

    def cpu_read(self, address: int, t: int) -> int | None:
        board, chip = self.board, self.chip
        if board in (36, 132, 173) and address & 0xE100 == 0x4100:
            if board == 36:
                return (chip.read() & 3) << 4 | 0xCF << 8
            return chip.read() | 0xF0 << 8
        if board in (136, 147, 172) and address & 0xE100 == 0x4100:
            value = chip.read()
            if board == 147:
                return value << 2 | 0x03 << 8
            if board == 172:
                return reverse6(value) | 0xC0 << 8
            return value | 0xC0 << 8
        return super().cpu_read(address, t)

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x8000:
            self.chip.latch()
            if self.board == 172:
                self.set_mirroring(VERTICAL if self.chip.invert else HORIZONTAL)
            self._update()
        elif self.board == 36 and address & 0xE200 == 0x4200:
            self.chr_latch = value & 0x0F
            self._update()
        elif address & 0xE100 == 0x4100:
            register = address & 3
            data = self._chip_value(value)
            if register in (1, 3) and self.board == 172:
                data = (value >> 5) & 1
            self.chip.write(register, data)
            if self.board == 173:
                self._update()  # V is CHR A14 at once
        else:
            super().cpu_write(address, value, t)
