#!/usr/bin/env python3
"""Decode the 2A03's and 2A07's noise and DMC period ROMs from their die masks.

BreakingNESWiki (reference/src/breaks, pinned) prints each decoder's second
stage as transistor bitmasks: the 2A03's in APU/noise.md and APU/dpcm.md with
the load values they produce, the 2A07's in APU/pal.md without them. Each
period counter is an LFSR loaded from that ROM and reloaded on reaching 1
(Breaknes APUSim noise.cpp, dpcm.cpp: 11 bits fed back from bits 0 and 2 for the
noise, 9 bits from 0 and 4 for the DMC), one step per APU cycle. So:

1. the 2A03's documented loads, counted down the LFSR, give the NTSC tables of
   apu.TABLES (checks the counter model);
2. the bit and row order that turns the 2A03's masks into those loads,
   applied to the 2A07's masks, gives the PAL tables, checked against
   apu.TABLES["PAL"] (die-derived, where the wiki's tables are specification).

    python scripts/apu_period_roms.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from famicom_python.apu import TABLES

WIKI = (
    Path(__file__).resolve().parents[1] / "reference" / "src" / "breaks" / "BreakingNESWiki_DeepL"
)


def blocks(path: Path) -> list[list[str]]:
    """The fenced code blocks of a page, as lists of non-empty lines."""
    found = re.findall(r"```\n(.*?)```", path.read_text(), re.S)
    return [[line.strip() for line in block.splitlines() if line.strip()] for block in found]


def loads_table(path: Path) -> list[int]:
    """The "Decoder In | Decoder Out" table of a 2A03 page."""
    return [int(v, 16) for v in re.findall(r"^\|\d+\|(0x[0-9a-fA-F]+)\|$", path.read_text(), re.M)]


def period(load: int, bits: int, tap: int) -> int:
    """APU cycles from a load to the next: steps until the LFSR reads 1, then the reload."""
    state, steps = load, 0
    while state != 1:
        feedback = 1 if state == 0 else (state ^ (state >> tap)) & 1
        state = (state >> 1) | (feedback << (bits - 1))
        steps += 1
    return steps + 1


def noise_loads(masks: list[str]) -> list[int]:
    """11 rows (output bits, top row = bit 10) of 16 columns (inputs, right to left);
    a transistor pulls its bit low."""
    rows = [[int(c) for c in row.replace(" ", "")] for row in masks]
    return [sum((rows[r][15 - i] ^ 1) << (10 - r) for r in range(11)) for i in range(16)]


def dpcm_loads(masks: list[str]) -> list[int]:
    """16 rows (inputs, bottom row = input 0) of 9 columns (output bits, left = bit 0);
    a transistor pulls its bit low."""
    rows = [[int(c) for c in row] for row in masks]
    return [sum((rows[15 - i][k] ^ 1) << k for k in range(9)) for i in range(16)]


def main() -> int:
    if not WIKI.exists():
        print("reference/src/breaks missing: python scripts/fetch_references.py", file=sys.stderr)
        return 1
    noise_page, dpcm_page, pal_page = (WIKI / "APU" / n for n in ("noise.md", "dpcm.md", "pal.md"))
    # The second stage is the page's second code block (the first is the demultiplexer).
    ntsc_noise, ntsc_dpcm = blocks(noise_page)[1], blocks(dpcm_page)[1]
    pal_blocks = blocks(pal_page)
    pal_dpcm, pal_noise = pal_blocks[2], pal_blocks[4]
    failures = 0
    for name, documented, masks_ntsc, masks_pal, decode, bits, tap, key in (
        (
            "noise",
            loads_table(noise_page),
            ntsc_noise,
            pal_noise,
            noise_loads,
            11,
            2,
            "noise_periods",
        ),
        ("DMC", loads_table(dpcm_page), ntsc_dpcm, pal_dpcm, dpcm_loads, 9, 4, "dmc_rates"),
    ):
        checks = (
            ("2A03, documented loads", documented, "NTSC"),
            ("2A03, decoded from its masks", decode(masks_ntsc), "NTSC"),
            ("2A07, decoded from its masks", decode(masks_pal), "PAL"),
        )
        for label, loads, table in checks:
            got = tuple(2 * period(v, bits, tap) for v in loads)  # CPU cycles
            want = getattr(TABLES[table], key)
            same = got == want
            failures += not same
            verdict = f"= apu.TABLES[{table!r}]" if same else "DIFFERS"
            print(f"{name:5} {label:30} {verdict}: {got}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
