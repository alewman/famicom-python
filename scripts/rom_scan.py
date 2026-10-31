#!/usr/bin/env python3
"""What a dump's PRG-ROM says about its mapper, without running it.

    python scripts/rom_scan.py ROM.nes

Prints the header, which 8 KiB banks hold plausible vectors (where the fixed bank
must be), and the absolute writes and reads outside RAM and the PPU, by count:
the first pass at an undocumented board's registers. Bytes that merely look like
such instructions are counted too, so read it as hints.
"""

from __future__ import annotations

import argparse
import collections
from pathlib import Path

WRITES = (0x8D, 0x8E, 0x8C, 0x9D, 0x99)
READS = (0xAD, 0xAE, 0xAC, 0x2C)


def scan(prg: bytes) -> tuple[collections.Counter[int], collections.Counter[int]]:
    """Counts of the absolute addresses written ($4018 up) and read ($4018-$7FFF)."""
    written: collections.Counter[int] = collections.Counter()
    read: collections.Counter[int] = collections.Counter()
    for i in range(len(prg) - 2):
        address = prg[i + 1] | prg[i + 2] << 8
        if prg[i] in WRITES and address >= 0x4018:
            written[address] += 1
        elif prg[i] in READS and 0x4018 <= address < 0x8000:
            read[address] += 1
    return written, read


def vector_banks(prg: bytes) -> list[tuple[int, str]]:
    """8 KiB banks whose last six bytes hold a reset vector into $8000-$FFFF."""
    banks = []
    for bank in range(len(prg) // 0x2000):
        end = (bank + 1) * 0x2000
        if prg[end - 3] >= 0x80:
            banks.append((bank, prg[end - 6 : end].hex()))
    return banks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    data = parser.parse_args().rom.read_bytes()
    prg = data[16 : 16 + data[4] * 0x4000]
    mapper = data[6] >> 4 | data[7] & 0xF0 | (data[8] & 0x0F) << 8
    print(f"mapper {mapper}.{data[8] >> 4} PRG {len(prg) // 1024} KiB CHR {data[5] * 8} KiB")
    print("header", data[:16].hex())
    print("vectors", vector_banks(prg))
    written, read = scan(prg)
    print("written", [(f"{a:04X}", n) for a, n in written.most_common(16)])
    print("read", [(f"{a:04X}", n) for a, n in read.most_common(8)])


if __name__ == "__main__":
    main()
