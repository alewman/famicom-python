# Validation: the oracles found, ranked, and pinned

## The tier rule

Same rule as every board in this family: **hardware-captured >
hardware-corrected > die-derived > specification > emulator-derived**. A
lower-tier oracle is a *detector* (it finds where to look), never the *judge*.
When a detector and a judge disagree, the judge wins and the disagreement goes
in [undocumented-behavior.md](undocumented-behavior.md).

- *Hardware-captured*: output recorded from a real console.
- *Hardware-corrected*: a test program whose expected values its author
  established on real hardware.
- *Die-derived*: a model transcribed from the die (Visual 2A03/2C02, the Breaks
  reverse-engineering and its gate-level C++ PPUSim/APUSim). For the Mega Drive
  a die transcription (Nuked-OPN2) was the YM2612's judge. Here the
  die-derived models are **unproven**: Breaknes, the console built from them,
  scores 70/140 on AccuracyCoin. A die-derived result is a judge for a circuit
  only after that circuit's behaviour has been checked against the
  hardware-corrected tests that cover it.
- *Specification*: Nintendo published none for these chips; the NESdev wiki,
  blargg's references, loopy's and Brad Taylor's documents are secondary
  research. Where a wiki statement cites a hardware test or Visual 2C02/2A03, it
  inherits that tier for that statement only.

Two cautions apply to every tier:

- **CPU/PPU alignment is random at power-on** (4 phases on NTSC, plus the APU
  get/put parity; [timing.md](timing.md)). Hardware results come from random
  alignments: the TASVideos hardware column records `oam_read` passing 66 % of
  the time, `oam_stress` 25 %, `10-even_odd_timing` 25 %. The board picks and
  states one alignment; a test that passes only in some alignments judges only
  those.
- **Chip revisions differ.** AccuracyCoin targets RP2A03G + RP2C02G and reports
  revision-dependent success codes. The target here is NES-001 with 2A03G/2C02G.

Paths as in [start-here.md](start-here.md). Every file and repository is pinned
in `scripts/pinned_files.json` (468 files with SHA-256) and
`scripts/pinned_repos.json` (29 repositories at full commit SHAs);
`scripts/fetch_references.py` rebuilds `reference/` and `tests/test_roms/` from
them.

## Hardware-captured

| Oracle | What it judges | Where |
| --- | --- | --- |
| **TASVideos NES accuracy matrix, its three hardware columns** (NES-001 + PowerPak, Famicom AV + InviteNES, Famicom AV + EverDrive) | pass/fail of 156 test ROMs on real consoles, *including where hardware fails*: `cpu_dummy_writes_oam` fails on all three; `apu_reset`/`cpu_reset` are disturbed by flash-cart menus; `nes_instr_test/02-immediate` (unstable opcodes); timing tests "sometimes" | `reference/docs/tasvideos-NESAccuracyTests.{html,txt}` (snapshot 2026-10-05) |
| blargg's CPU/PPU alignment measurements | the 4 alignments and their likelihoods | `nesdev-forum/6186.html` |
| blargg's raw-vs-RCA audio recordings, rainwarrior's DAC/level/sweep measurements, lidnariq's video voltage levels | mixer curve shape, filter corners, NTSC signal levels | `nesdev-forum/4946.html`, `24288.html`, `17741.html`, `17745-p225699.html`, `13394-p159266.html` (prose and plots; raw data unpublished) |
| lidnariq's PPU open-bus decay test | decay time (C1) | `nesdev-forum/24639.html` |
| Damian Yerrick's `volumes.nes` recording on an NES-001 | APU volumes and non-linear mixing | `tests/test_roms/nes-test-roms/volume_tests/recordings/nes-001.ogg` (Vorbis: lossy) |
| `apu_mixer_recordings/*.mp3` | the mixer tests' audible output | provenance undocumented, lossy: illustrative only |
| AccuracyCoin README per-console notes; blargg's `power_up_palette` | power-on palette RAM (unique per console), register noise | `tests/test_roms/AccuracyCoin/README.md` |
| Nintendo factory test cartridges (local, not copied) | functional diagnostics: Control Deck Test Cartridge, NTF2 Test/System Cartridge, HVC Kensa Controller Test, Controller/Joystick/Port/Power Pad tests | `/data/emu/roms/nes/*(Test Program).zip` |
| MMC3 chip photographs, N-K's `mmc3irqtest` hardware photo | MMC3 revision behaviour | `nesdev-forum/p261236-*` |

## Hardware-corrected (self-checking programs)

### The result protocols the harness reads

**blargg's new shell (2009+): `$6000`.** From `common/text_out.s` (verified in
`instr_test-v5/source`; the readme's "$DE $B0 $G1" is a typo):

| Address | Meaning |
| --- | --- |
| `$6000` | `$80` running; `$81` "press reset, but no sooner than 100 ms from now"; `$00–$7F` finished: `$00` passed, `$01` failed, `$02+` "Error N" |
| `$6001–$6003` | `$DE $B0 $61`, written after `$6000 = $80`: data is valid only once present |
| `$6004…` | zero-terminated ASCII text, readable mid-run |

Needs PRG-RAM at `$6000`. Found by machine search in 114 ROMs. `cpu_reset` and
`apu_reset` use `$81`: the harness must press reset.

**blargg's old shell (2005): zero page `$F8`**, where **1 means pass** (the
opposite sense); no "finished" flag: detect the final loop or read the screen.
Used by `sprite_hit_tests_2005`, `sprite_overflow_tests`, `vbl_nmi_timing`,
`blargg_ppu_tests_2005`, `blargg_apu_2005`, `branch_timing_tests`,
`mmc3_irq_tests`, `pal_apu_tests` (check each before relying on it).

**Screen or beeps only**: `cpu_timing_test6`, `cpu_dummy_reads`,
`dmc_dma_during_read4`, `read_joy3`, Holy Mapperel and most mapper tests.

**AccuracyCoin**: RAM `$0400–$04FF`, one byte per test, low 2 bits 1 = pass,
2 = fail, upper bits the error code, `$FF` skipped.

### The suites (`nes-test-roms` at `95d8f62`)

| Suite | Author | Checks | Reports | Hardware claim |
| --- | --- | --- | --- | --- |
| instr_test-v5 | blargg | every opcode incl. unofficial (except KIL and the unstable 8B 93 9B 9F BB) | `$6000` | CRCs from runs on a NES |
| instr_timing | blargg | cycles of every instruction | `$6000` | as above |
| cpu_timing_test6 | blargg | cycles incl. page crossing | screen + beeps | "passes when run on an NTSC NES" |
| branch_timing_tests | blargg | branch timing | `$F8` | "on a NES they all give a passing result" |
| **cpu_interrupts_v2** (5) | blargg | CLI/SEI/PLP/RTI latency, NMI+BRK, NMI+IRQ, IRQ+DMA, branch delays | `$6000` | tables in the readme from hardware |
| cpu_dummy_reads, instr_misc | blargg | dummy reads, wraps | screen / `$6000` | |
| cpu_dummy_writes, cpu_exec_space | Bisqwit | RMW double writes; executing from I/O space | `$6000` | `_oam` fails on all hardware columns; `_apu` fails on both Famicom AVs |
| cpu_reset | blargg | power/reset CPU state | `$6000` + `$81` | |
| **ppu_vbl_nmi** (10) | blargg | VBL/NMI to one PPU clock, suppression, odd/even frames | `$6000` | alignment caveat |
| vbl_nmi_timing (7) | blargg | older VBL/NMI timing | `$F8` | "tested on an actual NES" |
| sprite_hit_tests_2005.10.05 (11) | blargg | sprite-0 hit | `$F8` | "tested on an actual NES" |
| sprite_overflow_tests (5) | blargg | overflow incl. the evaluation bug | `$F8` | "on a NES they all give a passing result" |
| blargg_ppu_tests_2005.09.15b (5) | blargg | palette RAM, sprite RAM, VRAM access, VBL clear | `$F8` | "tested on an actual NES" (`power_up_palette` console-specific) |
| ppu_open_bus, ppu_read_buffer | blargg, Bisqwit | the I/O latch; $2007 buffer | `$6000` | |
| oam_read, oam_stress | blargg | $2003/$2004 | `$6000` | passes in some alignments only |
| **apu_test** (8), apu_reset (6), blargg_apu_2005.07.30 (11) | blargg | lengths, frame IRQ, jitter, DMC, reset | `$6000` / `$F8` | 2005: "tested on an actual NES" |
| apu_mixer (4) | blargg | mixer non-linearity | `$6000` + listen | |
| dmc_dma_during_read4, sprdma_and_dmc_dma, read_joy3 | blargg | DMA re-reads, OAM + DMC DMA, pads under DMA | screen / `$6000` | alignment-dependent CRCs |
| mmc3_test, mmc3_test_2, mmc3_irq_tests | blargg | MMC3/MMC6 IRQ | `$6000` / `$F8` | several real MMC3 cartridges |
| pal_apu_tests | blargg | PAL frame sequencer | `$F8` | "tested on a PAL NES" |

### Other programs

| Program | Checks | Reports | Hardware? | Licence | Pin |
| --- | --- | --- | --- | --- | --- |
| **AccuracyCoin** (100th_Coin) | **144 tests** on 20 pages: CPU, every unofficial opcode, open bus, dummy accesses, interrupts, DMA × $2002/$2007/$4015/$4016, APU, frame counter, PPU registers, sprite evaluation, OAM corruption, power-on state | RAM `$0400–$04FF` and screen | written for RP2A03G + RP2C02G; tests removed when "several revision G PPUs" failed them | MIT | `4151899` (2026-10-04; changes almost daily: **re-pin before each certification**) |
| **nestest** (kevtris) | official + unofficial opcodes | automation from `$C000`: failure codes at `$02`/`$03` | "Nintendulator passes, as does a real NES" | none stated | in nes-test-roms |
| **nestest.log** | per-instruction PC, A X Y P SP, PPU scanline/dot, CYC (8,991 lines) | golden log | **emulator-derived** (Nintendulator), universally cross-checked; MAME 0.285 matches every line except power-on X/Z | none stated | in nes-test-roms |
| 240p Test Suite (Damian Yerrick) | geometry, colour, overscan, MDFourier audio, clock-rate detection | interactive | developed on hardware | GPL-2.0 | `12c20f8` |
| Holy Mapperel and the mapper tests | see [cartridge.md](cartridge.md) | | | | |
| nes-audio-tests (rainwarrior) | DAC (`dac_square`, `dac_tnd*`), expansion audio levels, NSF behaviour | audible; reference recordings external | yes | see repo | `99ef107` |

### The CPU core's own judge

**SingleStepTests `65x02` `nes6502/v1`** at `2f6980a2`: 256 opcodes × 10,000
cases with every bus cycle, 6502 with decimal mode disabled. Emulator-derived
(as are its `6502/v1` siblings that 6502-python already passes 2,560,000/2,560,000
on), so it judges the core together with the hardware-corrected ROMs above. It
belongs to the 2A03 pull request on 6502-python, not to this board.

## Die-derived

| Model | Covers | Licence | Runs here? |
| --- | --- | --- | --- |
| **PPUSim** (Breaknes, `fb7de61`) | gate-level 2C02G/H, 2C03/04/05, 2C07, UMC clones, from the Breaks schematics; pin-level API per master half-cycle (R/W, RS0–2, /DBE, /RES in; /INT, ALE, /RD, /WR and the full AD/A8–13 bus out, so every fetch is visible) | CC0-1.0 | **Yes**: compiles unchanged with g++ -std=c++20; a smoke test (scratchpad only) gave VBL set at H = 1 V = 241, clear at H = 1 V = 261, 89,342 dots per frame with rendering off, ~0.8 frames/s. Not yet checked against the PPU test ROMs (open item 1) |
| **APUSim** (Breaknes, `fb7de61`) | gate-level 2A03 (6502 + APU); RAW mode gives the 5 digital channel levels per half-clock, plus /IRQ, M2, the bus; `APUPlayerBoard.cpp` runs a bare APU from register dumps through a fake 6502 | CC0-1.0 | builds with g++/cmake (not run); effectively 2A03G only; DAC fitted to one voltage, so not a mixer judge (open item 2) |
| Breaks (emu-russia, `5a55bac`) | transistor→gate documentation of the 6502 core, APU, PPU, MMC1; Verilog HDL (PPU still work in progress) | CC0-1.0 | documentation; HDL needs iverilog (not installed) |
| Visual 2A03 / Visual 2C02 (Quietust) | transistor-level RP2A03G and 2C02G netlists in the visual6502 JS simulator | simulator MIT; **netlist data: no licence stated** | `reference/docs/visual2a03`, `visual2c02`; the simulator core has no DOM references and node 22 is installed, so a headless runner is feasible (not built); very slow |
| MetalNES (`6acddfb`) | transistor-level NES-001 from the Visual netlists plus the board | MIT | macOS only |
| VisualNes, AprVisual, FlawlessChips | other switch-level combinations | various | not tried |

FPGA cores (NES_MiSTer, `49a0a66`, GPL-3.0) are hand-written HDL: emulator tier.

## Specification and secondary research

No Nintendo or Ricoh manual for these chips is public. The secondary sources
pinned under `reference/`: the NESdev wiki (173 pages, raw wikitext snapshots of
2026-10-05), 46 NESdev forum threads with hardware results in them, blargg's
`apu_ref.txt`, Brad Taylor's 2A03 and 2C02 references and `NESSOUND.txt`,
loopy's `SKINNY.TXT`, the US patent 4,824,106 (PPU), and the frame-timing
diagram `Ntsc_timing.png`. Where they disagree,
[undocumented-behavior.md](undocumented-behavior.md) lists it.

## Emulator-derived (detectors)

AccuracyCoin scores from the doclic.eu leaderboard
(`reference/docs/doclic-nes-accuracy-leaderboard.html`, out of 140) unless noted.

| Emulator | AccuracyCoin | Notes | Licence | Pin |
| --- | ---: | --- | --- | --- |
| TriCNES (100th_Coin) | 140 | AccuracyCoin was written against it | MIT | `94f1b11` |
| mame_nes (fork of MAME 0.260) | 140 | reworked NES PPU/DMA | not asserted | `f8b7c1d` |
| **Mesen2 / MesenCE** | 137 | 100 % TASVideos; builds and runs headless here (below) | GPL-3.0 | Mesen2 `b9fa69d` (archived), MesenCE `a60e79f` (live successor) |
| Nintendulator | 103 | made `nestest.log` | no licence file | `1409c6a` |
| puNES | 101 | | GPL-2.0 | `b1758ec` |
| Nestopia UE | 97 | | GPL-2.0 | `7b5c87d` |
| FCEUX | 85 | | GPL-2.0 | `a62b868` |
| **MAME 0.285** (installed) | **81/144** (measured here, current AccuracyCoin) | CPU matches `nestest.log`; PPU scanline-based; recipe in [mame-oracle.md](mame-oracle.md) | BSD-3-Clause (driver, PPU, cart bus); **`nes_apu.cpp` GPL-2.0+** | `mame0285` = `f379cd0`, sparse |
| TetaNES | — | Rust | Apache-2.0/MIT | `a0a6b17` |
| Breaknes | 70 | gate-level (above) | CC0 | `fb7de61` |

`nes-test-roms/test_roms.xml` and `status.txt` (NESICIDE, Nestopia 1.40,
Nintendulator) are emulator-derived.

### Mesen2 as a second detector (measured 2026-10-05)

Mesen2's core builds here **without .NET**:

```sh
git clone https://github.com/SourMesen/Mesen2 reference/build-mesen2/Mesen2   # then check out b9fa69d
cd reference/build-mesen2/Mesen2
nice -n 10 make core USE_GCC=true LTO=false STATICLINK=false -j8
```

1 min 04 s wall on this machine (g++ 15.2, SDL2 2.32.10), producing
`InteropDLL/obj.linux-x64/MesenCore.so`. `scripts/mesen_run.py` drives it through
`ctypes` the way Mesen's own `TestRunner.cs` does (our code calling the GPL
library at run time; nothing copied), and `scripts/mesen_blargg.lua` stops it
when a blargg ROM reports through `$6000`:

```sh
python scripts/mesen_run.py tests/test_roms/nes-test-roms/apu_test/apu_test.nes \
    --lua scripts/mesen_blargg.lua --home tests/mame_traces/mesen-home --seconds 60
```

| ROM | Mesen2 result | Wall |
| --- | --- | ---: |
| `instr_test-v5/official_only.nes` | 0 (passed) | 4.5 s |
| `ppu_vbl_nmi/ppu_vbl_nmi.nes` | 0 | 3.5 s |
| `cpu_interrupts_v2/cpu_interrupts.nes` | 0 | 2.0 s |
| `apu_test/apu_test.nes` | 0 | 0.8 s |

These are exactly the suites MAME fails. **The gate can fail**: of 120 random
single-bit flips in the non-padding bytes of `instr_test-v5/rom_singles/01-basics.nes`,
two produced result codes 6 and 3, eight hung (a timeout is reported as −1, also
a failure), 110 still passed (flips in untested code). With `--trace` Mesen's
trace logger writes one line per instruction with the real PPU scanline and dot
(`CYC:[CycleCount] SL:[Scanline] DOT:[Cycle]`): 1,189,975 instructions of
nestest in 0.8 s. The Lua API also offers per-access memory callbacks;
logging them to a file needs `ScriptAllowIoOsAccess` set through
`SetDebugConfig` (not done yet). MesenCE should build the same way (not tried).

## What is *not* available

- **No logic-analyser capture of an NES bus** among the pinned material:
  cycle-level DMA and IRQ facts reach us through test programs and forum prose.
- **No lossless APU recording**; rainwarrior's reference FLACs are external
  links and his measurement data unpublished.
- **No die-level model validated against the test ROMs**: PPUSim and APUSim run
  but are unproven; Visual 2C02/2A03 need a node runner; MetalNES is macOS-only.
- **No hardware results under a fixed CPU/PPU alignment.**
- **Barely any PAL or Dendy hardware results** (`pal_apu_tests` and the 240p
  suite's clock detection).
- **AccuracyCoin is a moving target**: pin a SHA per certification.
- **`nes-test-roms` has no licence**; blargg's and Bisqwit's readmes say nothing
  about redistribution. Fetched, never committed. AccuracyCoin is MIT.

## Local romsets (not fetched, not committed)

| Set | Files |
| --- | ---: |
| No-Intro `Nintendo - Nintendo Entertainment System (Headered)` | 4,464 |
| No-Intro `… (Headered) (Aftermarket)` (homebrew, incl. 240p Test Suite builds) | 2,913 |
| No-Intro `… (Headered) (Private)` | 634 |
| No-Intro `2024 - … (Headered)` (older snapshot) | 5,836 |
| No-Intro Famicom Disk System (FDS), (FDS) (Aftermarket), (QD) | present |
| `/data/emu/roms/nes` | 8,001 (incl. the Nintendo test cartridges above) |
| MAME software lists `/usr/share/games/mame/hash/nes.xml` (+ `famicom_flop`, `famicom_cass`, `nes_ade`, `nes_datach`, `nes_kstudio`, `nes_ntbrom`) | 4,559 entries in `nes.xml` |

The No-Intro sets are under `/data/emu/source/myrient.erista.me/files/No-Intro/`.
`nes20db-2026-09-26.7z` (the header database) is in `reference/docs/`.

## Certification record

### Milestone 1: the CPU on the board (2026-10-11)

**Pins.** famicom-python at the commit that adds this record; 6502-python
`038aa5d7fe683c4ddee6ba06bac60ff770162bf8` (PR #6: RP2A03, polling at the
second-to-last cycle, the per-CPU ANE/LXA constant); `nes-test-roms`
`95d8f621ae55cee0d09b91519a8989ae0e64753b`. Machine NES-001 (RP2A03G +
RP2C02G), `PowerOn()` defaults: alignment 0, first cycle an APU get, RAM $00,
A = X = Y = 0; LXA's constant $FF, ANE's $EE. PyPy 7.3.20 (Python 3.11.13) and
CPython 3.14.4 on a shared 32-core machine.

**nestest** (`other/nestest.nes`, SHA-256 `f67d55fd…0004`) in automation mode
against `nestest.log` (`442c4dd5…6f8f`, emulator-derived: Nintendulator, and
MAME 0.285 agrees): **8,991 of 8,991 lines** match in PC, A, X, Y, P (masked
$CF), SP and CYC, and the PPU line and dot columns match too. Power-on for
lines 1-2: A = X = Y = 0, S = 0 and I set before the 7-cycle reset sequence,
which leaves S = $FD, P = $24, CYC = 7; then PC = $C000. Result codes $02 and
$03 are both 0. `tests/test_nestest.py`, in the quick loop.

**The CPU test ROMs** (hardware-corrected), `pytest -m slow` and
`scripts/run_test_roms.py --suite cpu`, all passing under PyPy and under
CPython, with identical cycle and instruction counts (wall time includes loading
nes20db, about 2 s; 10 ran at a time):

| ROM | SHA-256 | Reports | CPU cycles | Instructions | Wall s, PyPy | Wall s, CPython |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `instr_test-v5/all_instrs.nes` | `353870c1…c785` | $6000: "All 16 tests passed" | 70,936,630 | 23,018,000 | 10.9 | 34.8 |
| `instr_timing/instr_timing.nes` | `3d1bca14…0fb0` | $6000: both passed | 38,653,018 | 11,060,000 | 8.2 | 18.5 |
| `instr_misc/instr_misc.nes` | `b6762e20…1243` | $6000: all 4 passed | 6,641,245 | 2,478,000 | 4.4 | 4.4 |
| `cpu_timing_test6/cpu_timing_test.nes`, B held (official + all unofficial) | `6ab4fe8a…5b85` | screen: PASSED | 29,482,697 | 8,748,978 | 8.5 | 14.3 |
| `branch_timing_tests/1.Branch_Basics.nes` | `7b69e304…86cd` | screen: PASSED ($F8 = 1) | 893,417 | 327,328 | 2.7 | 1.5 |
| `branch_timing_tests/2.Backward_Branch.nes` | `f7966e9b…29a4` | screen: PASSED | 893,419 | 335,742 | 2.6 | 1.6 |
| `branch_timing_tests/3.Forward_Branch.nes` | `d0fbc6b1…9c9b` | screen: PASSED | 893,417 | 335,534 | 2.4 | 1.1 |
| `cpu_dummy_reads/cpu_dummy_reads.nes` | `db4f91b8…17c9` | screen: Passed | 1,786,832 | 629,668 | 2.8 | 1.6 |
| `cpu_dummy_writes/cpu_dummy_writes_ppumem.nes` | `f59ac329…a6b3` | $6000: Passed | 6,494,373 | 1,866,000 | 4.4 | 3.9 |
| `cpu_exec_space/test_cpu_exec_space_ppuio.nes` | `9f7f24d4…9251` | $6000: Passed | 1,192,027 | 344,000 | 2.7 | 1.2 |

**One finding against a lower tier.** With 6502-python's default LXA constant
($EE, SingleStepTests') `all_instrs` fails `03-immediate` on `AB ATX #n`; with
$FF it passes, and blargg's CRCs were taken on an NES. The board sets $FF
([undocumented-behavior.md](undocumented-behavior.md) CPU item 3); 6502-python
PR #6 made the constant a per-CPU setting rather than a board workaround.

**The gates can fail.** Each seeded fault below, in a copy of `src/`, makes its
gate fail (11 of 11):

| Fault | Gate that fails |
| --- | --- |
| undriven reads return 0, not open bus | `test_board` |
| a $4015 read updates open bus | `test_board` |
| the NES-001 clocks its pad on every read cycle | `test_board` |
| OAM DMA without its alignment cycle | `test_board` (513/514) |
| RAM mirrored every 4 KiB | `test_board` |
| LXA's constant $EE | `all_instrs` (test 3 of 16) |
| no half-frame clock at 14913 | `instr_timing` (test 1) |
| a frame one line longer | `1.Branch_Basics` (#3, NMI period) |
| $2007 reads unbuffered | `cpu_dummy_writes_ppumem` (#2) |
| /NMI's edge never latched | `1.Branch_Basics` (no verdict) |
| write-only PPU registers read 0, not the I/O latch | `cpu_exec_space_ppuio` (#3) |

Not gated yet: MMC1's consecutive-write ignore and CNROM's bus conflicts
(milestone 5's judges), the alignment and APU parity (milestones 2 and 3).

**Speed** (`cpu_timing_test6`, 300 frames after 60 of warm-up, rendering off):
PyPy 180 frames/s (5.4 M CPU cycles/s, 3.0x real time); CPython 79 frames/s
(2.4 M CPU cycles/s, 1.3x real time). The PPU advances dots 2-339 in one step
while nothing happens on them; dot by dot, PyPy managed 1.8x real time,
because its JIT handles a three-iteration loop per CPU cycle badly.
