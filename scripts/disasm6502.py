#!/usr/bin/env python3
"""A small 6502 disassembler for reading a dump's bank-switching and protection code.

    python scripts/disasm6502.py ROM.nes OFFSET [BYTES] [--at ADDRESS]

OFFSET is into the PRG-ROM (hex); ADDRESS the CPU address to print it at. Official
opcodes only: anything else prints as ``.byte``, as data usually is.
"""

from __future__ import annotations

import argparse
from pathlib import Path

#: opcode: (mnemonic, addressing mode)
OPCODES = {
    0x00: ("BRK", "i"),
    0x01: ("ORA", "x"),
    0x05: ("ORA", "z"),
    0x06: ("ASL", "z"),
    0x08: ("PHP", "i"),
    0x09: ("ORA", "#"),
    0x0A: ("ASL", "i"),
    0x0D: ("ORA", "a"),
    0x0E: ("ASL", "a"),
    0x10: ("BPL", "r"),
    0x11: ("ORA", "y"),
    0x15: ("ORA", "zx"),
    0x16: ("ASL", "zx"),
    0x18: ("CLC", "i"),
    0x19: ("ORA", "ay"),
    0x1D: ("ORA", "ax"),
    0x1E: ("ASL", "ax"),
    0x20: ("JSR", "a"),
    0x21: ("AND", "x"),
    0x24: ("BIT", "z"),
    0x25: ("AND", "z"),
    0x26: ("ROL", "z"),
    0x28: ("PLP", "i"),
    0x29: ("AND", "#"),
    0x2A: ("ROL", "i"),
    0x2C: ("BIT", "a"),
    0x2D: ("AND", "a"),
    0x2E: ("ROL", "a"),
    0x30: ("BMI", "r"),
    0x31: ("AND", "y"),
    0x35: ("AND", "zx"),
    0x36: ("ROL", "zx"),
    0x38: ("SEC", "i"),
    0x39: ("AND", "ay"),
    0x3D: ("AND", "ax"),
    0x3E: ("ROL", "ax"),
    0x40: ("RTI", "i"),
    0x41: ("EOR", "x"),
    0x45: ("EOR", "z"),
    0x46: ("LSR", "z"),
    0x48: ("PHA", "i"),
    0x49: ("EOR", "#"),
    0x4A: ("LSR", "i"),
    0x4C: ("JMP", "a"),
    0x4D: ("EOR", "a"),
    0x4E: ("LSR", "a"),
    0x50: ("BVC", "r"),
    0x51: ("EOR", "y"),
    0x55: ("EOR", "zx"),
    0x56: ("LSR", "zx"),
    0x58: ("CLI", "i"),
    0x59: ("EOR", "ay"),
    0x5D: ("EOR", "ax"),
    0x5E: ("LSR", "ax"),
    0x60: ("RTS", "i"),
    0x61: ("ADC", "x"),
    0x65: ("ADC", "z"),
    0x66: ("ROR", "z"),
    0x68: ("PLA", "i"),
    0x69: ("ADC", "#"),
    0x6A: ("ROR", "i"),
    0x6C: ("JMP", "n"),
    0x6D: ("ADC", "a"),
    0x6E: ("ROR", "a"),
    0x70: ("BVS", "r"),
    0x71: ("ADC", "y"),
    0x75: ("ADC", "zx"),
    0x76: ("ROR", "zx"),
    0x78: ("SEI", "i"),
    0x79: ("ADC", "ay"),
    0x7D: ("ADC", "ax"),
    0x7E: ("ROR", "ax"),
    0x81: ("STA", "x"),
    0x84: ("STY", "z"),
    0x85: ("STA", "z"),
    0x86: ("STX", "z"),
    0x88: ("DEY", "i"),
    0x8A: ("TXA", "i"),
    0x8C: ("STY", "a"),
    0x8D: ("STA", "a"),
    0x8E: ("STX", "a"),
    0x90: ("BCC", "r"),
    0x91: ("STA", "y"),
    0x94: ("STY", "zx"),
    0x95: ("STA", "zx"),
    0x96: ("STX", "zy"),
    0x98: ("TYA", "i"),
    0x99: ("STA", "ay"),
    0x9A: ("TXS", "i"),
    0x9D: ("STA", "ax"),
    0xA0: ("LDY", "#"),
    0xA1: ("LDA", "x"),
    0xA2: ("LDX", "#"),
    0xA4: ("LDY", "z"),
    0xA5: ("LDA", "z"),
    0xA6: ("LDX", "z"),
    0xA8: ("TAY", "i"),
    0xA9: ("LDA", "#"),
    0xAA: ("TAX", "i"),
    0xAC: ("LDY", "a"),
    0xAD: ("LDA", "a"),
    0xAE: ("LDX", "a"),
    0xB0: ("BCS", "r"),
    0xB1: ("LDA", "y"),
    0xB4: ("LDY", "zx"),
    0xB5: ("LDA", "zx"),
    0xB6: ("LDX", "zy"),
    0xB8: ("CLV", "i"),
    0xB9: ("LDA", "ay"),
    0xBA: ("TSX", "i"),
    0xBC: ("LDY", "ax"),
    0xBD: ("LDA", "ax"),
    0xBE: ("LDX", "ay"),
    0xC0: ("CPY", "#"),
    0xC1: ("CMP", "x"),
    0xC4: ("CPY", "z"),
    0xC5: ("CMP", "z"),
    0xC6: ("DEC", "z"),
    0xC8: ("INY", "i"),
    0xC9: ("CMP", "#"),
    0xCA: ("DEX", "i"),
    0xCC: ("CPY", "a"),
    0xCD: ("CMP", "a"),
    0xCE: ("DEC", "a"),
    0xD0: ("BNE", "r"),
    0xD1: ("CMP", "y"),
    0xD5: ("CMP", "zx"),
    0xD6: ("DEC", "zx"),
    0xD8: ("CLD", "i"),
    0xD9: ("CMP", "ay"),
    0xDD: ("CMP", "ax"),
    0xDE: ("DEC", "ax"),
    0xE0: ("CPX", "#"),
    0xE1: ("SBC", "x"),
    0xE4: ("CPX", "z"),
    0xE5: ("SBC", "z"),
    0xE6: ("INC", "z"),
    0xE8: ("INX", "i"),
    0xE9: ("SBC", "#"),
    0xEA: ("NOP", "i"),
    0xEC: ("CPX", "a"),
    0xED: ("SBC", "a"),
    0xEE: ("INC", "a"),
    0xF0: ("BEQ", "r"),
    0xF1: ("SBC", "y"),
    0xF5: ("SBC", "zx"),
    0xF6: ("INC", "zx"),
    0xF8: ("SED", "i"),
    0xF9: ("SBC", "ay"),
    0xFD: ("SBC", "ax"),
    0xFE: ("INC", "ax"),
}

OPERAND_BYTES = {"i": 0, "#": 1, "z": 1, "zx": 1, "zy": 1, "x": 1, "y": 1, "r": 1}
OPERAND_BYTES |= {"a": 2, "ax": 2, "ay": 2, "n": 2}
FORMATS = {
    "i": "",
    "#": "#${:02X}",
    "z": "${:02X}",
    "zx": "${:02X},X",
    "zy": "${:02X},Y",
    "x": "(${:02X},X)",
    "y": "(${:02X}),Y",
    "a": "${:04X}",
    "ax": "${:04X},X",
    "ay": "${:04X},Y",
    "n": "(${:04X})",
}


def disassemble(code: bytes, address: int) -> list[str]:
    """One line per instruction of ``code``, which sits at CPU ``address``."""
    lines = []
    i = 0
    while i < len(code):
        opcode = code[i]
        if opcode not in OPCODES:
            lines.append(f"{address + i:04X} .byte ${opcode:02X}")
            i += 1
            continue
        mnemonic, mode = OPCODES[opcode]
        size = OPERAND_BYTES[mode]
        value = int.from_bytes(code[i + 1 : i + 1 + size], "little")
        if mode == "r":
            operand = f"${address + i + 2 + (value - 256 if value > 127 else value):04X}"
        else:
            operand = FORMATS[mode].format(value)
        lines.append(f"{address + i:04X} {mnemonic} {operand}".rstrip())
        i += 1 + size
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("offset", type=lambda text: int(text, 16))
    parser.add_argument("bytes", nargs="?", type=lambda text: int(text, 16), default=0x40)
    parser.add_argument("--at", type=lambda text: int(text, 16), default=0)
    args = parser.parse_args()
    data = args.rom.read_bytes()
    prg = data[16 : 16 + data[4] * 0x4000]
    print("\n".join(disassemble(prg[args.offset : args.offset + args.bytes], args.at)))


if __name__ == "__main__":
    main()
