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
| **PPUSim** (Breaknes, `fb7de61`) | gate-level 2C02G/H, 2C03/04/05, 2C07, UMC clones, from the Breaks schematics; pin-level API per master half-cycle (R/W, RS0–2, /DBE, /RES in; /INT, ALE, /RD, /WR and the full AD/A8–13 bus out, so every fetch is visible) | CC0-1.0 | **Yes**: compiles unchanged with g++ -std=c++20 (`scripts/build_ppusim.py`, with our shim); on the board in place of the PPU (`scripts/ppusim_board.py`) it passes `ppu_vbl_nmi` 10/10 at one CPU/PPU skew, and `scripts/ppusim_compare.py` compares it with the board pin for pin (milestone 2 below). ~0.5 frames/s on the board. `$2002` bit 7 inverted (C23, emu-russia/breaknes#529) |
| **APUSim** (Breaknes, `fb7de61`) | gate-level 2A03 (6502 + APU); RAW mode gives the 5 digital channel levels per half-clock, plus /IRQ, M2, the bus; `APUPlayerBoard.cpp` runs a bare APU from register dumps through a fake 6502 | CC0-1.0 | **Runs, not yet a judge**: built with our shim (`scripts/build_apusim.py`; the sparse checkout now includes `Chips/M6502Core`), a stub board around the whole chip runs blargg's ROMs (`scripts/apusim_board.py`, ~9,500 CPU cycles/s). It passes 3 of 8 `apu_test` singles: `$4015` bits 0-3 never reach its 6502 (open item 2; milestone 3 below). Effectively 2A03G only; DAC fitted to one voltage, so not a mixer judge |
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

**Repinned** to 6502-python `1ae3610015abcb643294fab986dbfb64a45d79b7` (main
after PRs #5 and #6, adding branch poll points): the quick suite and all ten
ROMs still pass on PyPy. Only `cpu_timing_test6` moved, to 29,482,696 cycles
and 8,748,987 instructions, as branches now poll where hardware does.

**Speed** (`cpu_timing_test6`, 300 frames after 60 of warm-up, rendering off):
PyPy 180 frames/s (5.4 M CPU cycles/s, 3.0x real time); CPython 79 frames/s
(2.4 M CPU cycles/s, 1.3x real time). The PPU advances dots 2-339 in one step
while nothing happens on them; dot by dot, PyPy managed 1.8x real time,
because its JIT handles a three-iteration loop per CPU cycle badly.

### Milestone 2: the PPU, dot by dot (2026-10-11)

**Pins.** famicom-python at the commit that adds this record; 6502-python
`1ae3610015abcb643294fab986dbfb64a45d79b7`; `nes-test-roms` `95d8f62`;
detectors Mesen2 `b9fa69d` (2.1.1) and, as a candidate die judge, Breaknes
PPUSim `fb7de61`. Machine NES-001 (RP2A03G + RP2C02G), `PowerOn()` defaults
(blargg's third synchronization, blargg's power-on palette, latch decay
0.6 s). PyPy 7.3.20 (Python 3.11.13) and CPython 3.14.4, on the shared
32-core machine with 2 ROMs at a time.

**The PPU test ROMs** (hardware-corrected), `pytest -m slow` and
`scripts/run_test_roms.py --suite ppu`: 41 of 41 pass under PyPy and under
CPython with identical cycle counts. `ppu_vbl_nmi` and `ppu_open_bus`,
`ppu_read_buffer`, `oam_read`, `oam_stress` report through `$6000`;
`vbl_nmi_timing`, `sprite_hit_tests` and `sprite_overflow_tests` on screen
("PASSED"/"FAILED"); blargg's 2005 PPU tests on screen as result `$01`.
`power_up_palette` is left out: it checks one console's power-on palette
(undocumented-behavior.md, "Power-up and reset").

| ROM | SHA-256 | CPU cycles | Instructions | Wall s, PyPy | Wall s, CPython |
| --- | --- | ---: | ---: | ---: | ---: |
| `ppu_vbl_nmi/rom_singles/01-vbl_basics.nes` | `06aea5af4eda` | 4,263,124 | 1,698,000 | 4.7 | 6.7 |
| `ppu_vbl_nmi/rom_singles/02-vbl_set_time.nes` | `dd9885613007` | 5,362,976 | 1,804,000 | 5.0 | 6.7 |
| `ppu_vbl_nmi/rom_singles/03-vbl_clear_time.nes` | `787fdaa4dd6c` | 5,005,262 | 1,712,000 | 5.3 | 10.9 |
| `ppu_vbl_nmi/rom_singles/04-nmi_control.nes` | `84722c75b896` | 1,044,526 | 342,000 | 0.7 | 2.0 |
| `ppu_vbl_nmi/rom_singles/05-nmi_timing.nes` | `72e515d689d7` | 6,494,195 | 2,210,000 | 3.1 | 7.4 |
| `ppu_vbl_nmi/rom_singles/06-suppression.nes` | `811dd5997bbf` | 6,583,873 | 2,188,000 | 3.5 | 7.5 |
| `ppu_vbl_nmi/rom_singles/07-nmi_on_timing.nes` | `1ed154363660` | 5,839,672 | 1,930,000 | 3.6 | 9.6 |
| `ppu_vbl_nmi/rom_singles/08-nmi_off_timing.nes` | `1d2a4093091c` | 6,556,211 | 2,316,000 | 3.0 | 7.5 |
| `ppu_vbl_nmi/rom_singles/09-even_odd_frames.nes` | `1ac04283021d` | 2,295,994 | 836,000 | 1.7 | 5.9 |
| `ppu_vbl_nmi/rom_singles/10-even_odd_timing.nes` | `7217d2d172ce` | 4,201,658 | 1,508,000 | 2.2 | 5.0 |
| `vbl_nmi_timing/1.frame_basics.nes` | `719bf4b4ea90` | 5,360,505 | 2,118,031 | 3.3 | 11.4 |
| `vbl_nmi_timing/2.vbl_timing.nes` | `39231f002784` | 5,360,515 | 2,073,526 | 3.2 | 10.5 |
| `vbl_nmi_timing/3.even_odd_frames.nes` | `268d5e305ab7` | 3,573,676 | 1,379,713 | 2.9 | 6.1 |
| `vbl_nmi_timing/4.vbl_clear_timing.nes` | `8552a65de49b` | 3,573,679 | 1,379,857 | 1.7 | 4.2 |
| `vbl_nmi_timing/5.nmi_suppression.nes` | `059c8df6a9b4` | 5,360,518 | 2,080,668 | 2.7 | 8.0 |
| `vbl_nmi_timing/6.nmi_disable.nes` | `4573dcff3c57` | 3,573,679 | 1,388,129 | 1.8 | 6.2 |
| `vbl_nmi_timing/7.nmi_timing.nes` | `26a2475828ef` | 3,573,678 | 1,377,608 | 1.6 | 6.1 |
| `sprite_hit_tests_2005.10.05/01.basics.nes` | `51819e8e502b` | 1,786,835 | 640,190 | 2.1 | 4.6 |
| `sprite_hit_tests_2005.10.05/02.alignment.nes` | `125bbb3ce1e6` | 893,419 | 299,935 | 0.5 | 2.4 |
| `sprite_hit_tests_2005.10.05/03.corners.nes` | `9dd57776bc62` | 893,417 | 330,210 | 0.6 | 2.1 |
| `sprite_hit_tests_2005.10.05/04.flip.nes` | `5f7142bddb51` | 893,417 | 335,367 | 0.7 | 2.4 |
| `sprite_hit_tests_2005.10.05/05.left_clip.nes` | `69b329658c17` | 893,419 | 309,398 | 0.8 | 1.8 |
| `sprite_hit_tests_2005.10.05/06.right_edge.nes` | `8e6653fcb869` | 893,418 | 325,017 | 0.9 | 2.6 |
| `sprite_hit_tests_2005.10.05/07.screen_bottom.nes` | `05849956f802` | 893,417 | 319,803 | 0.6 | 2.4 |
| `sprite_hit_tests_2005.10.05/08.double_height.nes` | `127fd966b6b3` | 893,418 | 330,211 | 0.7 | 2.2 |
| `sprite_hit_tests_2005.10.05/09.timing_basics.nes` | `311698c717e5` | 2,680,255 | 1,022,614 | 1.6 | 7.8 |
| `sprite_hit_tests_2005.10.05/10.timing_order.nes` | `0f36bc07bfe5` | 2,680,254 | 1,017,765 | 1.5 | 6.2 |
| `sprite_hit_tests_2005.10.05/11.edge_timing.nes` | `5a7c121f6e76` | 1,786,836 | 684,745 | 0.9 | 3.4 |
| `sprite_overflow_tests/1.Basics.nes` | `1a6782f63ccb` | 893,419 | 334,610 | 0.8 | 2.5 |
| `sprite_overflow_tests/2.Details.nes` | `6405a7ff1042` | 893,418 | 314,542 | 0.7 | 2.0 |
| `sprite_overflow_tests/3.Timing.nes` | `2252ec8fc359` | 3,573,679 | 1,376,130 | 1.8 | 7.2 |
| `sprite_overflow_tests/4.Obscure.nes` | `aebf21993443` | 893,418 | 323,128 | 0.6 | 2.4 |
| `sprite_overflow_tests/5.Emulator.nes` | `cf9944542196` | 893,416 | 333,378 | 0.7 | 4.6 |
| `blargg_ppu_tests_2005.09.15b/palette_ram.nes` | `11c1de16c677` | 893,419 | 322,724 | 0.8 | 2.2 |
| `blargg_ppu_tests_2005.09.15b/sprite_ram.nes` | `81275795ea64` | 893,417 | 313,855 | 0.9 | 2.0 |
| `blargg_ppu_tests_2005.09.15b/vbl_clear_time.nes` | `1a1d3ae8062c` | 893,418 | 313,594 | 0.7 | 1.7 |
| `blargg_ppu_tests_2005.09.15b/vram_access.nes` | `a0cde2a3c98d` | 893,417 | 322,621 | 0.5 | 2.7 |
| `ppu_open_bus/ppu_open_bus.nes` | `d4208a3ff634` | 7,444,120 | 3,046,000 | 3.8 | 11.0 |
| `ppu_read_buffer/test_ppu_read_buffer.nes` | `230a52fc557c` | 38,922,445 | 13,094,000 | 28.7 | 122.5 |
| `oam_read/oam_read.nes` | `f298973dabeb` | 804,396 | 234,000 | 0.8 | 2.1 |
| `oam_stress/oam_stress.nes` | `95882d72a7ac` | 50,746,904 | 16,398,000 | 17.2 | 57.7 |

**The CPU ROMs again**, with the PPU rendering: 10 of 10 pass on both. Cycle
counts moved from milestone 1 where a ROM waits on the PPU (its VBL polls and
screen writes now see a real PPU): `all_instrs`, `instr_timing`,
`cpu_dummy_reads`, `cpu_dummy_writes_ppumem`, `cpu_exec_space_ppuio`.

| ROM | SHA-256 | CPU cycles | Instructions | Wall s, PyPy | Wall s, CPython |
| --- | --- | ---: | ---: | ---: | ---: |
| `instr_test-v5/all_instrs.nes` | `353870c15724` | 71,536,744 | 23,192,000 | 36.9 | 125.9 |
| `instr_timing/instr_timing.nes` | `3d1bca14266f` | 38,687,273 | 11,070,000 | 19.0 | 109.9 |
| `instr_misc/instr_misc.nes` | `b6762e20a285` | 6,641,245 | 2,478,000 | 7.4 | 9.6 |
| `cpu_timing_test6/cpu_timing_test.nes` | `6ab4fe8af23b` | 29,482,696 | 8,744,746 | 16.4 | 96.0 |
| `branch_timing_tests/1.Branch_Basics.nes` | `7b69e3044eae` | 893,417 | 325,910 | 0.9 | 2.2 |
| `branch_timing_tests/2.Backward_Branch.nes` | `f7966e9b86b0` | 893,419 | 335,742 | 0.5 | 2.2 |
| `branch_timing_tests/3.Forward_Branch.nes` | `d0fbc6b1899b` | 893,417 | 335,534 | 0.4 | 2.2 |
| `cpu_dummy_reads/cpu_dummy_reads.nes` | `db4f91b80c5f` | 1,786,833 | 625,852 | 1.3 | 5.7 |
| `cpu_dummy_writes/cpu_dummy_writes_ppumem.nes` | `f59ac329f487` | 7,026,951 | 2,018,000 | 5.2 | 22.7 |
| `cpu_exec_space/test_cpu_exec_space_ppuio.nes` | `9f7f24d42003` | 1,220,282 | 352,000 | 1.8 | 3.2 |

**The access point.** Where in a CPU cycle the PPU sees a register access is
not documented to the dot. Of read and write points 4, 8 and 12 master ticks
into the cycle (one, two or three dots), swept over the 17 `ppu_vbl_nmi` and
`vbl_nmi_timing` ROMs, only reads and writes both at 8 pass all 17; the board
uses that (`PPU_ACCESS_TICKS`, timing.md). Sampling /NMI earlier than the
cycle's end makes NMI one cycle late (`05-nmi_timing`). The odd-frame skip's
sample dot came from the same kind of measurement: logging
`10-even_odd_timing`'s `$2001` writes shows one landing after dot 337 counts
for this frame and one after 338 does not.

**The gates can fail.** Each seeded fault below, in a copy of `src/`, makes
its gate fail (14 of 14):

| Fault | Gate that fails |
| --- | --- |
| VBL sets on dot 2, not 1 | `02-vbl_set_time` |
| no `$2002` read race at (241, 0) | `06-suppression` |
| register accesses at the cycle's end | `05-nmi_timing` |
| odd-frame skip sampled on dot 339 | `10-even_odd_timing` |
| no odd-frame skip | `09-even_odd_frames` |
| sprite-0 hit at x = 255 | `sprite_hit_tests/06.right_edge` |
| sprite-0 hit ignores the left clip | `sprite_hit_tests/05.left_clip` |
| fine X ignored | quick (`test_ppu_rendering`) |
| overflow scan without the m++ bug | `sprite_overflow_tests/4.Obscure` |
| secondary OAM not cleared on dots 1-64 | quick (`test_empty_sprite_slots_fetch_tile_ff`) |
| the I/O latch never decays | `ppu_open_bus` (#3) |
| OAMADDR never cleared on 257-320 | quick |
| palette reads buffered like VRAM | `blargg_ppu_tests/palette_ram` |
| hori(v) not copied at dot 257 | `sprite_hit_tests/02.alignment` |

Two needed stronger gates first: the empty-slot test now fills two slots on
another line so a stale secondary OAM shows; OAMADDR cleared only on 257 (not
258-320) is near-equivalent and nothing distinguishes it.

**Fetches on the connector** (`test_ppu_rendering`, 241 rendered lines): 84
pattern reads per line, 170 ALE addresses per line for a cartridge that
watches them (`Cartridge.watches_ppu_address`), A12 rising 8 times per line
with sprites at `$1000` but only once after a long low stretch: the rise
MMC3's filter counts.

**Speed** (the 240p Test Suite's menu, 300 frames after 120 of warm-up,
rendering on): PyPy 111 frames/s (1.85x real time), CPython 10.4 frames/s
(0.17x). Before the PPUSim changes below PyPy managed 59 (A/B, same load);
the frames are the same (Mesen2: 0 pixels differ), so this is PyPy's JIT
taking a better trace, not work dropped. With rendering off the PPU still
skips dots 2-337 in one step.

**Against Mesen2, pixel for pixel** (`scripts/mesen_frames.py`, a detector).
Mesen2 runs with a 512-entry identity palette, so its "RGB" is the PPU's 9-bit
value, plus its power-up write-ignore and zeroed RAM to match the board. Its
frame N is the board's N-3 (N-1 for some ROMs; the closest of ±3 is
reported). Differing pixels of 61,440:

| ROM | Frame 200 | Frame 600 | What differs |
| --- | ---: | ---: | --- |
| `240p-test-mini/240pee.nes` | 0 | 0 | |
| `nmi_sync/demo_ntsc.nes` | 0 | 0 | |
| `spritecans-2011/spritecans.nes` | 0 | 0 | |
| `nes15-1.0.0/nes15-NTSC.nes` | 0 | 0 | |
| `tvpassfail/tv.nes` | 0 | 0 | |
| `ny2011/ny2011.nes` | 0 | 0 | |
| `scrolltest/scroll.nes` | 0 | 0 | hangs in both: it enables NMI inside the power-up write-ignore, as on hardware |
| `blargg_litewall/litewall5.nes` | 0 | 0 | |
| `full_palette/full_palette.nes` | 6,129 | 6,129 | when a `$2007` write lands and v increments (C22): PPUSim sides with the board, 0 pixels differ |
| `full_palette/flowing_palette.nes` | 5,368 | 16,397 | the same, with mid-line `$2006`/`$2007` writes: PPUSim 0 |
| `scanline/scanline.nes` | 2 | 2 | mid-line BG toggle (C12, open): PPUSim differs from the board at the same 2 pixels |
| `window5/colorwin_ntsc.nes` | 8 | 8 | mid-line BG toggle (C12, open) |

Every difference is a dot-level effect of a register write mid-line, which no
test ROM pins; PPUSim judged them (below). Before that, the board applied
`$2006`/`$2007` writes at the access and differed from Mesen2 by 767 pixels in
`full_palette`; `litewall5` showed 2-4 pixels at the start of row 0, which
were the comparison's own fault (it read our picture a few dots into the next
frame; it now reads it at line 240).

**PPUSim as a judge** (die-derived; open item 1). `scripts/build_ppusim.py`
builds Breaknes PPUSim `fb7de61` with our shim (`scripts/ppusim/`), which owns
the NES-001 parts beside the PPU (the octal latch, CHR, CIRAM) and records the
pins per master half-cycle. `scripts/ppusim_board.py` puts it on the board in
place of our PPU: our CPU, bus and cartridge, each register access a /DBE
window while M2 is high (9 to 24 half-cycles into the CPU cycle), the
`$2002` bit 7 inversion corrected (C23).

*First, does it reproduce `ppu_vbl_nmi`?* The CPU/PPU phase at power is free,
so PPUSim was started 0-7 master half-cycles ahead of the CPU (one dot), and
each of the 10 singles run to its verdict (400 frames at most):

| ROM | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| `01-vbl_basics` | pass | pass | pass | pass | pass | pass | pass | pass |
| `02-vbl_set_time` | #1 | #1 | #1 | pass | #1 | #1 | #1 | #1 |
| `03-vbl_clear_time` | pass | pass | pass | pass | pass | pass | pass | pass |
| `04-nmi_control` | pass | pass | pass | pass | pass | pass | pass | pass |
| `05-nmi_timing` | #1 | #1 | #1 | pass | #1 | #1 | #1 | #1 |
| `06-suppression` | #1 | #1 | #1 | pass | #1 | #1 | #1 | #1 |
| `07-nmi_on_timing` | #1 | #1 | #1 | pass | #1 | #1 | #1 | #1 |
| `08-nmi_off_timing` | #1 | #1 | #1 | pass | #1 | #1 | #1 | #1 |
| `09-even_odd_frames` | pass | pass | pass | pass | pass | pass | pass | pass |
| `10-even_odd_timing` | #2 | #2 | #2 | pass | pass | pass | pass | pass |

At skew 3 PPUSim passes all ten, the board's own result. At the other seven,
02 and 05-08 print the same tables as each other, every VBL and NMI event one
row (one dot) early against the CPU, and 10 fails at skews 0-2 only: three
regions, as blargg's readme says other synchronizations make some of these
fail on hardware. That the passing region is one half-cycle wide is a
property of this pairing (our CPU's access window against PPUSim's clock
phases), not something hardware shows; so PPUSim judges below at skew 3, the
skew where it agrees with the hardware-corrected tests.

*Then the open questions, pin for pin* (`scripts/ppusim_compare.py`: both PPUs
fed the same register accesses on the same master-clock timeline, accesses
spaced as `STA`/`LDA abs` space them; ours reports through the connector and
`picture`, PPUSim through its pins; PPUSim shows pixel x at H = x + 4 and its
ALE a dot before ours, constant offsets found by `calibrate`):

| Question | PPUSim | The board before | Now |
| --- | --- | --- | --- |
| every ALE address of rendered lines with sprites (`fetches`) | | 2 of 170 per line differed | equal, 3 lines |
| first sprite-phase garbage fetch (dot 257) | v before the hori(v) copy | after | before (fixed) |
| second garbage fetch (C15) | nametable | nametable | settled |
| empty-slot row: secondary OAM after evaluation | the next free slot keeps OAM[63].Y once n wraps | kept copying after the wrap | equal (fixed) |
| odd-frame skip with sprites only (C13) | skips | skips | settled |
| second `$2006` write, t -> v (C21) | 2 dots after the access point | at it | `ppu.DELAYS` (fixed) |
| `$2007` write, and v's increment after a write or read (C22) | 3 and 4 dots after | at it | `ppu.DELAYS` (fixed) |
| greyscale and emphasis (C12) | reach the pixel looked up a dot earlier | did not | equal (fixed) |
| BG turned on or off mid-line (C12) | first 1-2 fetches and up to a pixel differ | | open |

Each was run with the CPU's data valid for all of M2 and with the early-write
open-bus value ($20) for its first dot; only greyscale differed (one pixel
further back with the clean bus), and the board follows the early-write
model, which hardware has (PPU_glitches.wiki). `test_ppu_rendering`'s
`test_register_effects_land_dots_after_the_access` pins the delays (7 of 7
seeded off-by-ones caught). The test ROMs gave identical verdicts and cycle
counts before and after.

*End to end*: `scripts/ppusim_compare.py frame ROM 60` runs a ROM on the board
with PPUSim, CPU and all, and compares frame 60 with ours. `full_palette` and
`flowing_palette` (mid-line `$2006`/`$2007` throughout): 0 pixels differ.
`scanline` 2 and `colorwin_ntsc` 5 (mid-line BG toggles, the open part of
C12). In `litewall5` (frames 60 and 61) and `colorwin_ntsc` PPUSim also shows
the backdrop at (0, 0), the frame's first pixel and no other x = 0: a
PPUSim-only observation nothing else confirms, left open. So in
`full_palette` and `flowing_palette` the differences from Mesen2 are
Mesen2's: it applies a `$2007` write a dot after the access, PPUSim and now
the board three dots after, the increment a dot later still.

### Milestone 3: the APU, DMA and interrupts (2026-10-12)

**Pins.** famicom-python at the commit that adds this record; 6502-python
`1ae3610015abcb643294fab986dbfb64a45d79b7` (penultimate-cycle polling and the
branch poll points, its PRs #3 and #5, are what `cpu_interrupts_v2` judges);
`nes-test-roms` `95d8f62`; detectors Mesen2 `b9fa69d` (2.1.1); die-derived
candidates Breaknes PPUSim and APUSim `fb7de61`. Machine NES-001, `PowerOn()`
defaults (APU get first). PyPy 7.3.20 (Python 3.11.13) and CPython 3.14.4,
14 ROMs at a time on the shared machine; short ROMs run faster on CPython
than on PyPy, whose JIT has not warmed up by the time they finish.

**The APU, DMA and interrupt test ROMs** (hardware-corrected),
`pytest -m slow` and `scripts/run_test_roms.py --suite apu`: 38 of 38 pass
under PyPy and under CPython with identical cycle and instruction counts.
`apu_test`, `apu_reset` report through `$6000` (the harness presses reset once
per `$81` request: `4017_timing`'s reset code measures for 420,000 cycles
before it clears the request); blargg's 2005 APU tests on screen as `$01`;
`cpu_interrupts_v2`, `dmc_dma_during_read4`, `sprdma_and_dmc_dma` and
`read_joy3` on screen (nes20db gives the interrupt singles no PRG-RAM).
`dma_2007_read` and `double_2007_read` print only a CRC, and blargg's sources
list one per CPU/PPU synchronization (2 and 4): the case accepts the one
PPUSim prints at the board's skew (`159A7A8F`, `F018C287`; below).
`read_joy3`'s `count_errors` ROMs only mark where DMC DMA met a pad read (no
verdict) and `test_buttons` needs a person; `thorough_test` is the judge.

| ROM | SHA-256 | CPU cycles | Instructions | Wall s, PyPy | Wall s, CPython |
| --- | --- | ---: | ---: | ---: | ---: |
| `apu_test/rom_singles/1-len_ctr.nes` | `aacf86c1d773` | 627,708 | 212,000 | 5.9 | 2.5 |
| `apu_test/rom_singles/2-len_table.nes` | `c002ff1483b4` | 482,018 | 148,000 | 9.2 | 2.3 |
| `apu_test/rom_singles/3-irq_flag.nes` | `dd8885516659` | 599,240 | 204,000 | 7.3 | 4.5 |
| `apu_test/rom_singles/4-jitter.nes` | `bff573d72d0f` | 567,369 | 190,000 | 6.2 | 2.7 |
| `apu_test/rom_singles/5-len_timing.nes` | `4d88f8cc0b21` | 3,396,916 | 1,358,000 | 11.3 | 14.5 |
| `apu_test/rom_singles/6-irq_flag_timing.nes` | `fc1daff82dd1` | 658,487 | 224,000 | 5.6 | 4.5 |
| `apu_test/rom_singles/7-dmc_basics.nes` | `547324867ee0` | 749,409 | 262,000 | 8.5 | 5.1 |
| `apu_test/rom_singles/8-dmc_rates.nes` | `5d9a79a505b3` | 835,365 | 302,000 | 7.6 | 2.8 |
| `apu_reset/4015_cleared.nes` | `ef83bc2831f0` | 926,825 | 278,277 | 9.7 | 7.3 |
| `apu_reset/4017_timing.nes` | `0e6072c6dcee` | 1,373,931 | 452,493 | 6.4 | 4.7 |
| `apu_reset/4017_written.nes` | `022bd3b45a73` | 1,671,052 | 533,066 | 12.6 | 8.6 |
| `apu_reset/irq_flag_cleared.nes` | `e2435b213bf2` | 898,525 | 272,766 | 6.8 | 4.0 |
| `apu_reset/len_ctrs_enabled.nes` | `e05546cbfaa1` | 1,048,381 | 328,499 | 8.8 | 8.2 |
| `apu_reset/works_immediately.nes` | `c750113762ee` | 1,047,596 | 334,328 | 5.8 | 5.5 |
| `blargg_apu_2005.07.30/01.len_ctr.nes` | `e1e3a29ab536` | 893,420 | 347,854 | 2.4 | 2.2 |
| `blargg_apu_2005.07.30/02.len_table.nes` | `63cc6a57fae3` | 893,418 | 330,317 | 1.8 | 3.1 |
| `blargg_apu_2005.07.30/03.irq_flag.nes` | `6f71c7e3de4b` | 893,417 | 348,686 | 2.3 | 2.6 |
| `blargg_apu_2005.07.30/04.clock_jitter.nes` | `46fa69b26fe8` | 893,418 | 342,755 | 2.2 | 2.7 |
| `blargg_apu_2005.07.30/05.len_timing_mode0.nes` | `606802d6849c` | 893,418 | 338,156 | 1.9 | 2.3 |
| `blargg_apu_2005.07.30/06.len_timing_mode1.nes` | `0f34e26d56ad` | 893,419 | 337,372 | 2.3 | 5.3 |
| `blargg_apu_2005.07.30/07.irq_flag_timing.nes` | `851c9698941d` | 893,418 | 341,300 | 3.0 | 6.1 |
| `blargg_apu_2005.07.30/08.irq_timing.nes` | `0a20a2b9ca9a` | 893,419 | 343,262 | 1.5 | 3.1 |
| `blargg_apu_2005.07.30/09.reset_timing.nes` | `bb04f8328a51` | 893,416 | 332,677 | 2.8 | 3.4 |
| `blargg_apu_2005.07.30/10.len_halt_timing.nes` | `cbdaa9a5cf9c` | 893,417 | 342,752 | 1.8 | 6.4 |
| `blargg_apu_2005.07.30/11.len_reload_timing.nes` | `40e633285a4a` | 893,418 | 335,237 | 2.1 | 3.0 |
| `cpu_interrupts_v2/rom_singles/1-cli_latency.nes` | `e402d36118f7` | 893,418 | 318,812 | 1.7 | 3.2 |
| `cpu_interrupts_v2/rom_singles/2-nmi_and_brk.nes` | `6e6bf6205930` | 3,573,682 | 1,123,000 | 6.1 | 8.4 |
| `cpu_interrupts_v2/rom_singles/3-nmi_and_irq.nes` | `3008a9524d17` | 4,467,095 | 1,475,014 | 7.5 | 10.2 |
| `cpu_interrupts_v2/rom_singles/4-irq_and_dma.nes` | `6d7b4c1947ad` | 2,680,246 | 982,600 | 5.7 | 11.2 |
| `cpu_interrupts_v2/rom_singles/5-branch_delays_irq.nes` | `f9e10b4a24d8` | 11,614,397 | 4,567,879 | 9.2 | 48.6 |
| `dmc_dma_during_read4/dma_2007_read.nes` | `a2e0fa3f6f15` | 893,420 | 297,956 | 1.8 | 2.2 |
| `dmc_dma_during_read4/dma_2007_write.nes` | `54c75d491c68` | 893,420 | 285,728 | 3.2 | 2.2 |
| `dmc_dma_during_read4/dma_4016_read.nes` | `c6af72e11c19` | 893,417 | 320,833 | 2.8 | 5.8 |
| `dmc_dma_during_read4/double_2007_read.nes` | `779e6e7db863` | 893,419 | 301,692 | 2.1 | 2.6 |
| `dmc_dma_during_read4/read_write_2007.nes` | `bc5281ca3f12` | 893,418 | 294,448 | 1.8 | 2.6 |
| `sprdma_and_dmc_dma/sprdma_and_dmc_dma.nes` | `db3199bc1b0b` | 4,467,098 | 1,648,619 | 6.4 | 8.3 |
| `sprdma_and_dmc_dma/sprdma_and_dmc_dma_512.nes` | `3789f5134b05` | 4,467,100 | 1,652,785 | 6.3 | 8.9 |
| `read_joy3/thorough_test.nes` | `e59de3d54204` | 4,467,078 | 1,677,602 | 6.9 | 19.2 |

**How they were reached.** With the stub of milestone 1 replaced, `apu_test`
1-6, `blargg_apu_2005` 1-9, `cpu_interrupts_v2` 1-3 and 5 passed at once.
The rest, in order:

- *Length-counter races* (2005 `10.len_halt_timing`, `11.len_reload_timing`):
  a halt or length write settles after the next cycle's length clock, and a
  load is dropped if that clock changed the counter.
- *Reset* (`apu_reset/irq_flag_cleared`): reset clears the frame IRQ flag.
- *DMC and its DMA* (`7-dmc_basics`, `8-dmc_rates`, `sprdma_and_dmc_dma`,
  `dma_4016_read`): the get/put model of DMA.wiki, one loop for both units
  (timing.md "The design"). `dma_4016_read` printed hardware's
  `08 08 07 08 08` on the first run: /OE contiguity was already right.
- *The `$4017` delay* (C6): `4-irq_and_dma` printed "9 +526" where hardware
  prints "8 +526" until "during an APU cycle" was read as a write on a put.
  Every other ROM passes either way.
- *`$2007` one CPU cycle apart* (C22): the two CRC ROMs printed values in no
  hardware list, and `read_write_2007` failed (its `STA $2007,X` reads, then
  writes, on consecutive cycles). Run on the board with PPUSim in place of
  the PPU (`scripts/ppusim_board.py`, all 8 skews), PPUSim prints at skew 3,
  the one where it passes `ppu_vbl_nmi`, `159A7A8F` and `F018C287`, both in
  blargg's hardware lists (`dma_2007_read` gives `159A7A8F` at all eight;
  `double_2007_read` gives `AD987CB5` at skews 0-2 and `31D9ED83` at 4-7,
  in no list: only skew 3 matches hardware, as with `ppu_vbl_nmi`). The board now does what skew 3 implies: a read's refill lands
  with its increment, a read in between is ignored, a write takes v as it
  lands. All three pass.

The CPU and PPU ROMs again: 10 of 10 and 41 of 41 on both interpreters. CPU
cycle counts are milestone 2's. Eight `sprite_hit_tests` ROMs moved by one
cycle and one or two instructions at the frame the harness stops on: they
enable the DMC, whose DMA now takes cycles (with DMC DMA disabled the counts
are milestone 2's exactly).

**The gates can fail.** Each seeded fault below, in a copy of `src/`, makes
its gate fail (17 of 17):

| Fault | Gate that fails |
| --- | --- |
| length table entry 1 = 253 | `apu_test/2-len_table` |
| a halt write takes effect at once | 2005 `10.len_halt_timing` |
| a length load during a length clock not dropped | 2005 `11.len_reload_timing` |
| `$4017` delay 3 after a get (the other reading of C6) | `cpu_interrupts_v2/4-irq_and_dma` |
| reset keeps the frame IRQ flag | `apu_reset/irq_flag_cleared` |
| the DMC IRQ never set | `apu_test/7-dmc_basics` (#9) |
| DMC rate 0 = 426 | `apu_test/8-dmc_rates` |
| DMC load DMA a cycle early | quick (`test_apu`) |
| DMC DMA without its dummy cycle | `dma_2007_read` |
| OAM DMA's get before the DMC's | `sprdma_and_dmc_dma` |
| adjacent `$2007` reads both count | `double_2007_read` |
| a `$2007` write's address taken at the access | `read_write_2007` |
| pulse 1 negates like pulse 2 | quick |
| noise feedback from bit 2 | quick |
| mixer pulse coefficient 8000 | quick |
| triangle clocked on APU cycles | quick |
| a `$4015` read keeps the frame IRQ flag | `apu_test/3-irq_flag` (#5) |

Two needed stronger gates first: `double_2007_read` accepted every
synchronization's CRC, so adjacent reads both counting printed another
hardware value (`85CFD627`); the case now takes only the board's. The
triangle test called the timer directly, missing the clock that drives it.

**Sound against hardware** (`scripts/volume_levels.py`; hardware-captured,
through an uncharacterised analogue path, so relative levels only).
`volume_tests` plays 12 tones near 1 kHz three times, the DMC held at 0, 48
and 96; its `recordings/nes-001.ogg` is an NES-001. Each tone's RMS over
pulse 1 at 1/2 duty in the same pass, the board through its fitted NES-001
stage:

| Tone | DMC 0: NES-001, board | DMC 48 | DMC 96 |
| --- | --- | --- | --- |
| pulse 1, 1/8 | 0.650, 0.651 (+0.02 dB) | 0.675, 0.651 (-0.32 dB) | 0.674, 0.673 (-0.02 dB) |
| pulse 1, 1/4 | 0.878, 0.871 (-0.07 dB) | 0.877, 0.871 (-0.06 dB) | 0.876, 0.871 (-0.05 dB) |
| pulse 1, 1/2 | 1.000, 1.000 (+0.00 dB) | 1.000, 1.000 (+0.00 dB) | 1.000, 1.000 (+0.00 dB) |
| pulse 1, 3/4 | 0.865, 0.865 (+0.00 dB) | 0.866, 0.866 (-0.00 dB) | 0.867, 0.896 (+0.29 dB) |
| pulses 1+2, 1/8 | 1.161, 1.126 (-0.26 dB) | 1.164, 1.125 (-0.29 dB) | 1.165, 1.165 (-0.00 dB) |
| pulses 1+2, 1/4 | 1.505, 1.506 (+0.00 dB) | 1.512, 1.505 (-0.04 dB) | 1.514, 1.506 (-0.04 dB) |
| pulses 1+2, 1/2 | 1.715, 1.729 (+0.07 dB) | 1.791, 1.728 (-0.31 dB) | 1.724, 1.728 (+0.02 dB) |
| pulses 1+2, 3/4 | 1.481, 1.496 (+0.09 dB) | 1.548, 1.496 (-0.30 dB) | 1.491, 1.547 (+0.32 dB) |
| triangle | 1.502, 1.652 (+0.83 dB) | 1.046, 1.140 (+0.75 dB) | 0.773, 0.860 (+0.92 dB) |
| noise, long | 0.476, 0.539 (+1.07 dB) | 0.382, 0.368 (-0.33 dB) | 0.259, 0.268 (+0.30 dB) |
| noise, short | 0.470, 0.509 (+0.70 dB) | 0.453, 0.348 (-2.30 dB) | 0.251, 0.285 (+1.12 dB) |
| DMC, 30 | 1.566, 1.867 (+1.53 dB) | 1.208, 1.270 (+0.44 dB) | 0.786, 0.865 (+0.83 dB) |

The pulses, alone and summed non-linearly, agree within 0.3 dB, and the
DMC's attenuation of the triangle as it rises (0.70 and 0.52 of its level at
0 on hardware, 0.69 and 0.52 here) is the formula's. The triangle reads
0.8-0.9 dB loud and the DMC tone 0.4-1.5 dB loud; noise is random and within
about 1 dB. Open item 17.

**Against Mesen2's sound** (`scripts/mesen_audio.py`, a detector). Mesen2
records its own mixer output (its channel volumes, 0 when headless, set to
100); both streams pass the same 90 Hz high-pass, each window gets its own
alignment (within 1 ms) and gain. `apu_mixer` (20 s each) plays a beep, a
tone cancelled by inverse `$4011` writes, then a beep: the beeps start on the
same sample in both, at the same pitch, Mesen2 1.64 times quieter
throughout (its output scale), with waveforms differing by -11 to -16 dB
(its integer mixer and band-limited synthesis). The cancellation depth,
residual over beep, window by window:

| Test | Board | Mesen2 |
| --- | --- | --- |
| `square` | -41 to -12 dB | -41 to -12 dB |
| `triangle` | -33 to -12 dB | -33 to -12 dB |
| `noise` (a fade, not a cancellation) | -25 to -11 dB | -25 to -10 dB |
| `dmc` | -34 to -16 dB | -40 to -14 dB |

In `dmc`, cycle by cycle, the board leaves a one-CPU-cycle step at every
pulse edge (the triangle test cancels on the cycle): open item 16. Mesen2
was not run on `volume_tests`: the NES-001 recording outranks it.

**APUSim** (die-derived candidate, open item 2). Built with our shim
(`scripts/build_apusim.py`): a stub board around the whole simulated 2A03,
its 6502 included, with work RAM, NROM PRG and PRG-RAM, a `$2002` that sets
bit 7 once a frame (`scripts/apusim_board.py`, about 9,500 CPU cycles/s).
`apu_test`: 3 of 8 pass (`3-irq_flag`, `4-jitter`, `6-irq_flag_timing`). The
length tests fail on `$4015` bits 0-3: a six-instruction program shows the
counters load (channel 0's reads $1D) and bits 4 and 6 reach the CPU, but bits
0-3 never do. The length counters drive them from `sim_SoundGenerators`,
which runs only on PHI0 edges and after the core in each step, while the core
samples the bus at that edge. `7-dmc_basics` #19 and `8-dmc_rates` #2 are not
diagnosed (the stub board may be the cause). Not a judge at `fb7de61`.

**Speed** (the 240p Test Suite's menu, 300 frames after 120 of warm-up):
PyPy 53.6 frames/s (0.89x real time), CPython 9.0 (0.15x). The APU's
per-cycle clock costs about half of PyPy's milestone 2 speed (A/B under the
same load: 94-102 before, 42-57 after); the mix is recomputed only when a
channel step can be heard. The board stays a reference, not a player
(reference boards are correct, not fast).

**Frames against Mesen2**, frames 200 and 600 of milestone 2's twelve ROMs: the
same counts as milestone 2, ROM for ROM.

### Milestone 4: AccuracyCoin (2026-10-12)

**Pins.** famicom-python at the commit that adds this record; AccuracyCoin
`6bee919529289c555803b612b8c9e4f7eaaeeabb` (2026-10-10, re-pinned from
`4151899` as this document asks: 146 tests and 5 DRAW pages); 6502-python
`fdef250` (its PR #7, `dma_stalled`, on main `1ae3610`; to repin once merged);
Breaknes PPUSim `fb7de61` at skew 3. Machine NES-001, `PowerOn()` defaults.
PyPy 7.3.20 (Python 3.11.13) and CPython 3.14.4.

**Score: 136 of 146**, identical result tables on PyPy and CPython
(123,410,909 CPU cycles, 4,144 frames; 91 s on PyPy, 276 s on CPython).
`scripts/accuracycoin.py` presses Start on the page index (run all) and reads
the result bytes at `$0400-$04FF`, names and addresses taken from the pinned
`.asm`; `--test NAME` runs one test through the menu. The first run scored
116. Every fix below was made against a hardware answer key in the test's
source or README, then shown to fail its test when seeded back in.

| Test (first result) | What the board lacked |
| --- | --- |
| Frame Counter IRQ (7) | a `$4015` read's clear waits for the next put -> get; the flag sets on 29828/29829 even when inhibited, clears on 29830, raises no IRQ (C7) |
| Controller Strobing (4) | `$4016`'s OUT0 reaches the pads at the next put |
| Controller Clocking (7), APU Register Activation (4), DMC DMA Bus Conflicts (2) | the register decode during DMA (C25), with the bus conflicts both expected tables pin |
| Internal Data Bus (2) | an internal data bus: `$4015` bit 5 comes from it, DMA reads do not change it (C24) |
| DMA + `$2002` Read (2) | passed once the frame IRQ's clear was right (its sync reads `$4015`) |
| DMC Reload Timing (1) | a rate written in the cycle the DMC timer reloads is used |
| Delta Modulation Channel (L) | an enabling `$4015` write holds reload DMAs off for 2 cycles |
| Explicit, Implicit DMA Abort (2, 2) | the abort bug, and a scheduled DMA surviving a disable (the answer key matched byte for byte) |
| SHA, SHS, SHY, SHX ×5 (7) | `dma_stalled` (6502-python PR #7, NMS p. 48) |
| Address `$2004` behavior (A) | a rendering-time `$2004` write masks OAMADDR to a multiple of 4 |
| Misaligned OAM behavior (4) | evaluation realigns: `+4 & $FC` for a Y out of range, the X byte range-checked too |
| `$2004` Stress Test (2) | attribute bytes stored without bits 4-2; after evaluation, even dots read secondary OAM at its address |
| OAM Corruption (2) | C26: a frozen secondary-OAM address corrupts its row when rendering begins at the pre-render line |
| Sprites On Scanline 0 (2) | the pre-render line's sprite fetch range-checks against line 5 |
| `$2002` flag timing (1) | the sprite flags pass through to M2's fall (`PPU.end_read`); now fails at 2 |

**The ten left, each with its cause** (open item 18). PPUSim ran each of the
fourteen PPU tests the board was failing at the time (on the board with
PPUSim in place of the PPU, skew 3, `scripts/ppusim_board.py`), and
`scripts/ppusim_lockstep.py` then ran board and PPUSim board side by side,
both CPUs in lockstep from power-on, to the first divergence. Lockstep needed
two power-on alignments: PPUSTATUS's overflow bit set at power (PPUSim's, and
"+0+x xxxx" allows it, so the board now does it too) and palette RAM zeroed
(PPUSim's; the board keeps blargg's table by default, so the lockstep run sets
`PowerOn.palette`).

| Test | Board | PPUSim | Cause |
| --- | --- | --- | --- |
| `$2002` flag timing | 2 | pass | the sprite-0 and overflow flags' set dots relative to each other (the board's fifth read sees both, hardware at most sprite 0); lockstep: first divergence at that read |
| `$2007` Stress Test | 2 | pass | a read's buffer refill against the fetch cadence: the board's stable bytes are hardware's shifted by one tile (its first four are the key's fifth to eighth; near the line's start its refill lands after its own increment has moved v); lockstep: first divergence at the buffer read |
| Stale BG Shift Registers | 3 | pass | mid-line rendering toggles (C12); lockstep: the sprite-0 hit differs |
| BG Serial In | 2 | pass | the same; on the lines with the gap PPUSim draws colour $30 where the board draws $2D, six pixels a line |
| ALE + Read | 2 | pass | the same family: a `$2007` read changing the fetch address |
| Hybrid Addresses | 2 | pass | the same family: a `$2006` write changing the fetch address |
| Stale Sprite Shift Regs | 3 | pass | mid-line toggles and the sprite shifters |
| Frozen OAM2 Increment | 2 | pass | mid-line toggles and the secondary OAM address |
| `$2004` Stress Test | 3 | fails at 2 | one byte of 341 (dot 199, the overflow scan's fourth copy read): no judge |
| Misaligned OAM2 Address | 4 | fails at 3 | no judge |

PPUSim also fails "OAM Corruption" (it models no analogue copying), "Misaligned
OAM behavior" (at 6) and "Sprites On Scanline 0" (at 3), all of which the
board passes against AccuracyCoin's hardware answers.

For the mid-line toggles, driving both PPUs with the same writes
(`ppusim_compare.py`'s harness: rendering off for 2 or 6 CPU cycles mid-line)
showed PPUSim fetching about 3 dots past the board's stop and resuming 2-3
dots after it, without the board's coarse-X increment. A 2-dot delay on
PPUMASK's bits 4-1 matched those fetches but changed no AccuracyCoin outcome
and made the PPUSim frame comparisons worse (`scanline` 16 pixels against 2,
`colorwin` 7 against 6), so it was taken out (C12).

**The gates can fail.** Each seeded fault below, in a copy of `src/`, fails
its AccuracyCoin test (16 of 16): `$4015` clearing the frame IRQ at once; no
flag while inhibited; the strobe at once; no decode composition; DMA reads
always reaching `$4015-$4017`; `$4015` bit 5 from the external bus; a
same-cycle `$4010` rate waiting; no enable hold; no abort bug; a disable
cancelling a scheduled DMA; `dma_stalled` never set; `$2004` writes keeping
OAMADDR's low bits; no X range check; attribute bytes stored whole; no OAM
corruption; no sprites from the pre-render fetch.

**Everything else again**: the CPU (10), PPU (41) and APU (38) ROMs pass on
both interpreters with milestone 3's cycle and instruction counts, except
`read_joy3/thorough_test`, 604 instructions more in the same cycles now that
the strobe waits for a put. The quick suite passes (51). The PPUSim frame
comparisons are milestone 2's (`scanline` 2, `colorwin` 6).

**Speed** (240p Test Suite menu, as before): PyPy 40 frames/s (0.67x real
time) and CPython 8.2 under today's load; milestone 3's code measures 41 on
PyPy in the same A/B, so milestone 4 costs about 3 %.
