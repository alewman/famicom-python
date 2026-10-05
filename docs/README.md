# Documents

Read in this order.

| Document | What it holds |
| --- | --- |
| [start-here.md](start-here.md) | The Famicom and NES models as data, clocks, the CPU memory map, open bus, controllers, power-up; the PPU programming model, memory map and output format; the APU registers and mixer; expansion audio; a suggested module shape |
| [timing.md](timing.md) | The master-clock timeline and CPU/PPU alignment; interrupt polling (hardware vs 6502-python today); OAM and DMC DMA cycle diagrams and the DMA-inside-`read_byte` design; the PPU dot schedule, frame events and the $2002/NMI races; the APU frame counter and tables |
| [cartridge.md](cartridge.md) | Why mappers live here; the connector and the proposed signal protocol; iNES/NES 2.0; board identification by nes20db; mapper coverage measured over the local No-Intro sets; per-mapper table and judges |
| [undocumented-behavior.md](undocumented-behavior.md) | 2A03 vs 6502, PPU and APU quirks, revision tables, expansion-audio mix levels, contradictions C1–C21, open items |
| [validation.md](validation.md) | Every oracle by tier with pins and licences; blargg's and AccuracyCoin's result protocols; die-level models; emulator detectors; Mesen2 built and driven headless; what is not available; local romsets |
| [mame-oracle.md](mame-oracle.md) | The verified MAME 0.285 trace recipe, its measured output (nestest matches on all 8,991 lines) and fifteen traps |
| [handoff-brief.md](handoff-brief.md) | The task for the session that builds the board: decisions, the 6502-python pull requests, eight milestones with acceptance tests, constraints, size and speed |

## Findings made while gathering (2026-10-05)

These came out of checking the sources against each other, against the local
romsets, and by running MAME, Mesen2 and the die-level simulators, not out of
any single document:

1. **6502-python's bus already matches the 2A03 cycle for cycle**: on a
   60,000-case sample of SingleStepTests `nes6502/v1` it made 0 bus-sequence
   mismatches. Its only failures were decimal-mode cases (4,732 in `69.json`,
   2,790 in `6b.json`, every one with D set). The 2A03 variant is a small PR.
2. **The core needs no RDY input for DMA.** A halted 2A03 repeats its stalled
   read, DMA never halts a write, and 6502-python calls `read_byte` once per read
   cycle, so the board can run OAM and DMC DMA inside `read_byte`. What the core
   *does* need is interrupt polling at the end of the penultimate cycle; it
   polls at the instruction boundary today, which its own validation.md
   already lists as a limit.
3. **A gate-level 2C02 compiles and runs here.** Breaknes PPUSim (CC0) built
   unchanged with g++ and reproduced VBL set at 241/1, clear at 261/1, 89,342
   dots per frame. It is a candidate die-level judge for the PPU, but unproven:
   the whole Breaknes console scores 70/140 on AccuracyCoin.
4. **Mesen2's core builds without .NET** (1 min 04 s) and runs headless through
   `ctypes`; it passes the four blargg suites MAME 0.285 fails, and its trace
   logger gives the real PPU scanline and dot.
5. **MAME 0.285's 2A03 is exact against `nestest.log`** (all 8,991 lines bar its
   own power-on X/Z), but its PPU is scanline-based, its OAM DMA always 513
   cycles and its DMC DMA steals nothing: 81/144 on AccuracyCoin. A CPU detector
   only.
6. **Mappers 0, 1, 2, 3, 4, 7 cover 83.4 % of the 2,646 licensed No-Intro
   dumps; 95 % takes 26 mappers, 99 % takes 54.** For homebrew, mapper 30
   (UNROM-512) is 36–50 % of the aftermarket and private sets.
7. **No-Intro's NES headers are nes20db's**: all 4,464 + 2,913 + 634 dumps carry
   NES 2.0 headers and every licensed dump is in nes20db (2026-09-26 release),
   differing in 9 fields. MAME's list misses 15 % of licensed dumps, and nothing
   in MAME reads its own `mmc3_type`.
8. **The published NES analogue filter corners (90 Hz, 440 Hz, 14 kHz) do not
   follow from the coefficients they were derived from** (which give about
   28 Hz, 1.2 Hz and 11.9 kHz), and later sweeps fit ~16 Hz (NES) and ~32 Hz
   (Famicom). The board's analogue stage is a labelled fit.
9. **Nuked-OPLL already models the VRC7** (`opll_type_ds1001`), so a YM2413 core
   would serve both the Master System FM unit and the VRC7.
10. **The Famicom microphone is read at $4016 D2**, not $4017; and the RF
    Famicom clocks its pads on every read cycle where the NES-001 clocks once per
    run of reads, which changes what DMA re-reads do.
11. **nesdev.org answers Python's `urllib` with 403 and `curl` with 200**, so
    the fetch script uses curl. nescartdb.com cannot be fetched by script at all.
