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
| Nintendo factory test cartridges (local, not copied) | functional diagnostics: Control Deck Test Cartridge, NTF2 Test/System Cartridge, HVC Kensa Controller Test, Controller/Joystick/Port/Power Pad tests | the author's dumps (`*(Test Program).zip`), not distributed |
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
| **PPUSim** (Breaknes, `215ab82`) | gate-level 2C02G/H, 2C03/04/05, 2C07, UMC clones, from the Breaks schematics; pin-level API per master half-cycle (R/W, RS0–2, /DBE, /RES in; /INT, ALE, /RD, /WR and the full AD/A8–13 bus out, so every fetch is visible) | CC0-1.0 | **Yes**: compiles unchanged with g++ -std=c++20 (`scripts/build_ppusim.py`, with our shim); on the board in place of the PPU (`scripts/ppusim_board.py`) it passes `ppu_vbl_nmi` 10/10 at one CPU/PPU skew, and `scripts/ppusim_compare.py` compares it with the board pin for pin (milestone 2 below). ~0.5 frames/s on the board. `$2002` bit 7 was inverted until `54caa4f` (C23, emu-russia/breaknes#529). AccuracyCoin 140/146 on it. Four more PPUSim bugs, each judged against Visual 2C02 (`scripts/visual2c02/`) and AccuracyCoin, are reported as emu-russia/breaknes#535-#538 with patches; with them PPUSim scores 145/146 |
| **APUSim** (Breaknes, `215ab82`; no APUSim change since `fb7de61`) | gate-level 2A03 (6502 + APU); RAW mode gives the 5 digital channel levels per half-clock, plus /IRQ, M2, the bus; `APUPlayerBoard.cpp` runs a bare APU from register dumps through a fake 6502 | CC0-1.0 | **Runs, not yet a judge**: built with our shim (`scripts/build_apusim.py`; the sparse checkout now includes `Chips/M6502Core`), a stub board around the whole chip runs blargg's ROMs (`scripts/apusim_board.py`, ~9,500 CPU cycles/s). It passes 3 of 8 `apu_test` singles: `$4015` bits 0-3 never reach its 6502 (open item 2; milestone 3 below). Effectively 2A03G only; DAC fitted to one voltage, so not a mixer judge |
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
| Breaknes | 70 | gate-level (above) | CC0 | `215ab82` |

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
For lockstep (milestone 6) apply `scripts/mesen2-detector-fixes.patch` first:
three corrections where a higher tier shows `b9fa69d` wrong.

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
| the author's own NES collection (GoodNES-named) | 8,001 (incl. the Nintendo test cartridges above) |
| MAME software lists `/usr/share/games/mame/hash/nes.xml` (+ `famicom_flop`, `famicom_cass`, `nes_ade`, `nes_datach`, `nes_kstudio`, `nes_ntbrom`) | 4,559 entries in `nes.xml` |

The No-Intro sets are read from `NO_INTRO_DIR` (`scripts/count_mappers.py`).
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

### Milestone 5: the big six mappers and their judges (2026-10-21)

**Pins.** famicom-python at the commit that adds this record; 6502-python
`fdef250` (PR #7 still open); `nes-test-roms` `95d8f62`; Holy Mapperel 0.02
binaries (`holy-mapperel-bin-0.02.7z`, source `4e48b594`); the forum's
mapper tests as pinned in `scripts/pinned_files.json`; Breaknes PPUSim
`fb7de61` at skew 3. Machine NES-001, `PowerOn()` defaults. PyPy 7.3.20
(Python 3.11.13) and CPython 3.14.4.

**What was built.** Mapper 4 (MMC3: Sharp and NEC IRQs, MMC6, MC-ACC, the
hard-wired 4.2, four-screen), 7 (AxROM), 34 (BNROM, NINA-001) and 155
(MMC1A); MMC1's board wirings (SUROM, SOROM, SXROM, SZROM, SNROM, SEROM) and
MMC1B's RAM disable; `Banked` gained a PRG-RAM bank offset, a mirroring mask
and write-protect. The A12 filter counts M2 falls from the connector's
timestamps (`mmc3.py`): no per-cycle `m2` call. Per mapper, which judge passed
and what is not claimed: [claims.md](claims.md).

**The harness.** `MAPPER_ROMS` (66 cases; `scripts/run_test_roms.py --suite
mappers`, `pytest -m slow tests/test_mapper_test_roms.py`). Holy Mapperel and
the forum tests are read inside their `.7z`/`.zip` in place
(`testrom.rom_bytes`). Cases may change the identified board
(`RomCase.board`): blargg's MMC3 ROMs run on 4.0 and on 4.4; nes20db lists
them on boards without PRG-RAM, so a `$6000`-protocol ROM gets 8 KiB (its
text has nowhere to go otherwise); HM runs once on an MMC3 with 8 KiB RAM
(none of its MMC3 builds has RAM, so `$A001` was untested) and once as SNROM
(none of its MMC1 builds is). Three screen fonts are decoded (`FONTS`):
rainwarrior's hex digits at `$A0`, tepples's 8×16 font, `mmc1atest`'s
two-tile bytes; Holy Mapperel's verdict is the mapper number, sizes, RAM and
CHR "OK" and the detailed code 0000 against the board it ran on.

**First run**: every judge but `4-scanline_timing` #12 ("Scanline 239 IRQ
should occur later when `$2000=$10`", on both IRQs and in both suites). The
board's MMC3 was clocked twice a line with BG at `$1000`: A12 was low from
the dot-337 nametable fetch to dot 5, 9 dots, three M2 falls. PPUSim showed
the address bus at dot 0 carrying dot 5's pattern address after a rendering
line, but not after vblank nor when the odd-frame skip took dot 340 (C27). With
that, all pass.

**Findings.** rainwarrior's `3_test` and `34_test` print YES for their RAM
lines and BNROM's bus conflicts on any board (C28): those lines are not
claimed, and BNROM's conflicts rest on the wiki and a unit test. Holy
Mapperel's MMC1 driver banks WRAM as SXROM does, so a SOROM board reads as "24K
PRG RAM PROBLEM", and it expects `$A000` D4 to disable RAM on any CHR-RAM
board of 256 KiB or less (MMC1.wiki: only SNROM); neither is claimed. N-K's
`mmc3irqtest` shows the consecutive-`$C001` pathology, which is not modelled.

**Certification record** (66 of 66 on both interpreters, identical counts;
`../nesdev-forum/` dropped from paths, "HM" = Holy Mapperel's `testroms/`;
wall times under a load of about 16 jobs):

| ROM (board changes) | SHA-256 (first 12) | CPU cycles | Instructions | PyPy s | CPython s |
| --- | --- | ---: | ---: | ---: | ---: |
| `mmc3_test_2/rom_singles/1-clocking.nes (submapper 0)` | `b06d8a97f0ca` | 780,005 | 274,000 | 5.7 | 6.3 |
| `mmc3_test_2/rom_singles/2-details.nes (submapper 0)` | `e7af16c764b1` | 866,261 | 302,000 | 9.9 | 7.3 |
| `mmc3_test_2/rom_singles/3-A12_clocking.nes (submapper 0)` | `b375f15b9f9d` | 779,826 | 274,000 | 10.3 | 7.4 |
| `mmc3_test_2/rom_singles/4-scanline_timing.nes (submapper 0)` | `14a220b9d127` | 9,502,259 | 3,792,000 | 25.3 | 57.1 |
| `mmc3_test_2/rom_singles/1-clocking.nes (submapper 4)` | `b06d8a97f0ca` | 780,005 | 274,000 | 10.5 | 6.4 |
| `mmc3_test_2/rom_singles/2-details.nes (submapper 4)` | `e7af16c764b1` | 866,261 | 302,000 | 6.9 | 8.3 |
| `mmc3_test_2/rom_singles/3-A12_clocking.nes (submapper 4)` | `b375f15b9f9d` | 779,826 | 274,000 | 10.2 | 6.1 |
| `mmc3_test_2/rom_singles/4-scanline_timing.nes (submapper 4)` | `14a220b9d127` | 9,502,259 | 3,792,000 | 28.0 | 52.2 |
| `mmc3_test_2/rom_singles/5-MMC3.nes (submapper 0)` | `e0824123d60b` | 808,512 | 282,000 | 5.8 | 6.8 |
| `mmc3_test_2/rom_singles/6-MMC3_alt.nes (submapper 4)` | `56698b691845` | 808,477 | 282,000 | 10.5 | 8.5 |
| `mmc3_test/1-clocking.nes (submapper 0)` | `57c77c66edde` | 745,057 | 260,000 | 10.3 | 6.4 |
| `mmc3_test/2-details.nes (submapper 0)` | `89e1f16514aa` | 774,020 | 272,000 | 8.9 | 6.4 |
| `mmc3_test/3-A12_clocking.nes (submapper 0)` | `dc6779b3d64e` | 744,893 | 260,000 | 10.0 | 3.0 |
| `mmc3_test/4-scanline_timing.nes (submapper 0)` | `0474550dbf81` | 9,380,624 | 3,746,000 | 31.1 | 54.6 |
| `mmc3_test/5-MMC3.nes (submapper 0)` | `f714089b5d05` | 683,107 | 242,000 | 5.9 | 4.0 |
| `mmc3_test/6-MMC6.nes (submapper 4)` | `e6bdbadf46cc` | 683,162 | 242,000 | 10.1 | 3.7 |
| `mmc3_irq_tests/1.Clocking.nes (submapper 0)` | `699d0644bd2b` | 893,419 | 361,884 | 2.3 | 6.7 |
| `mmc3_irq_tests/2.Details.nes (submapper 0)` | `0af95238b698` | 893,419 | 348,047 | 2.8 | 4.2 |
| `mmc3_irq_tests/3.A12_clocking.nes (submapper 0)` | `3b936e1079f1` | 893,418 | 361,931 | 2.4 | 5.6 |
| `mmc3_irq_tests/4.Scanline_timing.nes (submapper 0)` | `3369e8f73a96` | 2,680,258 | 1,052,362 | 7.3 | 14.0 |
| `mmc3_irq_tests/5.MMC3_rev_A.nes (submapper 4)` | `6b662c2d08ee` | 893,420 | 361,933 | 1.9 | 5.7 |
| `mmc3_irq_tests/6.MMC3_rev_B.nes (submapper 0)` | `d8a2af42cdaf` | 893,418 | 361,905 | 2.0 | 6.3 |
| `HM M0_P32K_C8K_V.nes` | `16ad27600799` | 1,786,833 | 591,533 | 4.5 | 15.4 |
| `HM M0_P32K_CR32K_V.nes` | `de10f742a93d` | 3,573,673 | 1,296,138 | 12.0 | 27.4 |
| `HM M0_P32K_CR8K_V.nes` | `1a33ba05af3e` | 3,573,673 | 1,296,138 | 9.8 | 24.5 |
| `HM M1_P128K.nes` | `d02b15ed43c8` | 3,573,675 | 1,296,390 | 9.5 | 34.9 |
| `HM M1_P128K_C128K.nes` | `a3f520601c1c` | 1,786,831 | 591,578 | 4.8 | 28.8 |
| `HM M1_P128K_C128K_S8K.nes` | `2263d212fe9c` | 3,573,676 | 1,230,198 | 11.4 | 23.8 |
| `HM M1_P128K_C128K_W8K.nes` | `f1d76578b706` | 3,573,676 | 1,230,198 | 10.9 | 29.3 |
| `HM M1_P128K_C32K.nes` | `77f77f779720` | 1,786,831 | 591,528 | 5.9 | 18.1 |
| `HM M1_P128K_C32K_S8K.nes` | `c6101b411ee9` | 3,573,673 | 1,230,146 | 11.6 | 28.4 |
| `HM M1_P128K_C32K_W8K.nes` | `3d330d32bb45` | 3,573,673 | 1,230,146 | 11.6 | 27.9 |
| `HM M1_P128K_CR8K.nes` | `0595f0896d71` | 3,573,675 | 1,296,385 | 11.4 | 35.4 |
| `HM M1_P512K_CR8K_S32K.nes` | `7db5b5191ce8` | 12,507,873 | 4,446,945 | 37.1 | 65.2 |
| `HM M1_P512K_CR8K_S8K.nes` | `c3f239ea8f2f` | 5,360,517 | 1,935,513 | 14.2 | 38.5 |
| `HM M1_P512K_S32K.nes` | `0d86aa1a48ce` | 12,507,873 | 4,446,949 | 31.3 | 83.2 |
| `HM M1_P512K_S8K.nes` | `d9ae34427b0c` | 5,360,516 | 1,935,519 | 12.5 | 37.1 |
| `HM M2_P128K_CR8K_V.nes` | `c7e83755bd9a` | 3,573,674 | 1,296,130 | 9.1 | 32.1 |
| `HM M2_P128K_V.nes` | `81bd36f2a0aa` | 3,573,674 | 1,296,135 | 8.3 | 33.6 |
| `HM M3_P32K_C32K_H.nes` | `499891c6d8c7` | 1,786,832 | 591,547 | 4.1 | 27.9 |
| `HM M4_P128K.nes` | `b145558f6d30` | 3,573,675 | 1,296,356 | 11.9 | 29.2 |
| `HM M4_P128K_CR32K.nes` | `428387f3178e` | 8,934,197 | 3,409,322 | 28.4 | 62.0 |
| `HM M4_P128K_CR8K.nes` | `edb301630dae` | 3,573,675 | 1,296,351 | 12.1 | 29.9 |
| `HM M4_P256K_C256K.nes` | `278041824af3` | 1,786,834 | 593,062 | 4.9 | 20.3 |
| `HM M7_P128K.nes` | `e4a63a3e290e` | 3,573,675 | 1,296,174 | 12.3 | 27.1 |
| `HM M7_P128K_CR8K.nes` | `4aa0050f36ae` | 3,573,673 | 1,296,173 | 9.5 | 29.3 |
| `HM M4_P256K_C256K.nes (prg_ram 8192)` | `278041824af3` | 3,573,676 | 1,231,549 | 11.1 | 24.1 |
| `HM M1_P128K.nes (prg_ram 8192)` | `d02b15ed43c8` | 5,360,517 | 1,935,004 | 15.9 | 39.5 |
| `2_test_src.zip/2_test_0.nes` | `8ba85a6150cc` | 8,934,160 | 2,964,856 | 22.1 | 124.2 |
| `2_test_src.zip/2_test_1.nes` | `e2cd2f477720` | 8,934,160 | 2,964,856 | 20.8 | 113.5 |
| `2_test_src.zip/2_test_2.nes` | `b069513cee90` | 8,934,160 | 2,964,857 | 21.2 | 124.3 |
| `3_test_src.zip/3_test_0.nes` | `badd1427300d` | 8,934,159 | 2,972,704 | 18.6 | 119.8 |
| `3_test_src.zip/3_test_1.nes` | `84f4542c387e` | 8,934,159 | 2,972,704 | 17.5 | 131.4 |
| `3_test_src.zip/3_test_2.nes` | `e1387b5f42cb` | 8,934,158 | 2,972,705 | 18.9 | 116.3 |
| `7_test_src.zip/7_test_0.nes` | `d969b4222b13` | 8,934,160 | 2,964,960 | 23.2 | 113.9 |
| `7_test_src.zip/7_test_1.nes` | `23658ffa3b1a` | 8,934,160 | 2,964,960 | 19.5 | 107.7 |
| `7_test_src.zip/7_test_2.nes` | `5fb4b7f4b15e` | 8,934,160 | 2,964,960 | 19.2 | 108.7 |
| `34_test_src.zip/34_test_1.nes` | `451ae4434c1f` | 8,934,161 | 2,971,809 | 22.4 | 101.1 |
| `34_test_src.zip/34_test_2.nes` | `889ff02395c1` | 8,934,162 | 2,965,667 | 22.5 | 106.7 |
| `bntest.zip/bntest_h.nes` | `1acbf7daf113` | 8,934,153 | 2,552,704 | 20.7 | 122.6 |
| `bntest.zip/bntest_v.nes` | `654bfa355ed7` | 8,934,153 | 2,552,704 | 14.5 | 74.6 |
| `bntest.zip/bntest_aorom.nes` | `efb4503a052b` | 8,934,153 | 2,552,704 | 12.1 | 65.9 |
| `serom.zip/serom.nes` | `f19917262de1` | 8,934,154 | 2,970,405 | 11.9 | 66.7 |
| `mmc1atest-0.01.zip/mmc1atest.nes` | `6539e05ef163` | 8,934,153 | 2,974,084 | 11.6 | 70.7 |
| `mmc1atest-0.01.zip/mmc1atest-sn.nes` | `43ac5a33667f` | 8,934,153 | 2,974,084 | 10.7 | 76.7 |
| `mmc1atest-0.01.zip/mmc1atest.nes (mapper 1)` | `6539e05ef163` | 8,934,153 | 2,974,084 | 10.3 | 66.6 |

**The gates can fail.** 21 of 23 seeded faults (each in a copy of `src/`) fail
at least one judge: the A12 filter at 2 falls; NEC's IRQ ignoring the reload
flag; NEC behaving as Sharp; `$E000` leaving the IRQ asserted; no CHR
inversion; no PRG mode swap; `$A001` write-protect ignored; `$C001` without
the reload flag; no dot-0 address, or one on every rendering line's dot 0;
AxROM's screen bit ignored; AxROM conflicts on 7.1; UxROM without conflicts on
2.2; conflicts as OR; SXROM's RAM bank from D3-D4; SUROM's outer bank ignored;
MMC1A's bypass missing; MMC1B's D4 keeping RAM; SNROM's E bit ignored; SEROM
banking PRG; NINA-001's CHR registers swapped. **Not caught**: the A12 filter
at 4 falls (the judges pass 4, 6, 8 and 16; 32 fails `3-A12_clocking` and
`4-scanline_timing`), and BNROM without conflicts (C28). Both are stated in
claims.md.

**Everything else again**: the CPU (10), PPU (41) and APU (38) ROMs pass on
PyPy, 80 with the recorded counts; `read_joy3/thorough_test` has milestone 4's
604 more instructions, and eight of the 2005 `sprite_hit_tests` stop one
instruction (and at most one cycle) from their milestone 2 counts, as
`01.basics` does at milestone 4's commit `668bc2e`: a milestone 4 change the
record did not show. AccuracyCoin: 136 of 146, the same 123,410,909 cycles.
The quick suite passes (58), including `tests/test_mappers.py` (7) and the
rendering test's address count, now 239 more per frame (C27). Smoke check,
not a judge: the title or attract frames of *Super Mario Bros. 3*, *Mega Man
3*, *Kirby's Adventure* (its split status bar), *StarTropics* (MMC6) and
*Battletoads* (AxROM) look right.

**Speed** (the 240p Test Suite's menu, 300 frames after 120 of warm-up; A/B
under the same load): PyPy 73.2 and 72.8 frames/s against milestone 4's 75.1
and 74.7 (about 2 % slower, near the noise); CPython 8.3. MMC3 games: *Kirby's
Adventure* attract 111 frames/s, *Super Mario Bros. 3* title 129 (1.9-2.1x
real time) on PyPy.

### Milestone 6: lockstep against Mesen2 (2026-10-22)

**Pins.** famicom-python at the commit that adds this record; 6502-python
`080fc80` (PR #7: `dma_stalled` and `note_stall`); Mesen2 `b9fa69d` built as
"Mesen2 as a second detector" says, with `scripts/mesen2-detector-fixes.patch`
applied (below); perfect6502 as pinned. Games from the local No-Intro
`Nintendo - Nintendo Entertainment System (Headered)` set, read in place.
PyPy 7.3.20.

**The tool.** `scripts/mesen_lockstep.py ROM --frames 3600` runs Mesen2
headless for 3,600 frames (60 s) with its trace logger (registers, CPU cycle,
scanline, dot: about 2.4 GB a game) and compares the board at every
instruction boundary from power-on, no input: A, X, Y, S, P (bits 5 and 4
aside), PC, the CPU cycle count and the PPU position, the two offsets fixed on
the first instruction and required constant (cycle 0; dot -1, the two
reading their position at different points of the cycle). The board's row is
taken at the opcode fetch's read, after any DMA that stalled it, as Mesen2
logs; its interrupt entries, which Mesen2 does not log, are dropped.

**Result: five games identical for 60 seconds.**

| Game (mapper) | Instructions identical | Frames |
| --- | ---: | ---: |
| *Super Mario Bros.* (World) (0) | 34,713,997 | 3,600 |
| *The Legend of Zelda* (USA) (Rev 1) (1) | 34,800,765 | 3,600 |
| *Mega Man 2* (USA) (1) | 34,643,339 | 3,600 |
| *Kirby's Adventure* (USA) (4) | 33,718,135 | 3,600 |
| *Battletoads* (USA) (7) | 33,934,780 | 3,600 |
| *Super Mario Bros. 3* (USA) (4) | 34,580,919 (2,593 passed over, below) | 3,600 |

**Every divergence, in the order met, with its source.** Each was diagnosed
before a run was extended.

| Divergence | Source | Resolved by |
| --- | --- | --- |
| SMB1's first `$2002` read: `$30` vs `$10` | power-on PPUSTATUS ("+0+x xxxx"): the board sets the overflow bit (PPUSim), Mesen2 does not | `PowerOn.ppustatus` (new; default unchanged); the lockstep machine uses Mesen2's |
| OAM DMA's 513 cycles in a different row | attribution: the board stalls the next opcode fetch, Mesen2 logs after the stall | rows taken at the opcode fetch's read |
| VBL's NMI one instruction apart | power-on phase: Mesen2's PPU starts a CPU cycle and a dot ahead (`NesCpu::Reset`) | `PowerOn.ppu_dot` (new; default 0); only 4, of 0-9, keeps SMB1's first 120 frames in step, and the board passes all 79 PPU and APU judges at 4 with the same synchronization CRCs |
| NMI after a taken same-page branch (MM2, Kirby, Battletoads) | **Mesen2**: delays only IRQs there; perfect6502 delays NMIs too (C29) | Mesen2 patch 1 |
| Zelda and Kirby read different SRAM | Mesen2 keeps battery saves in its home: a second run powered on with the first's | a fresh Mesen2 home per run |
| Kirby: a DMC fetch 4 cycles apart | power-on DMC rate timer: Mesen2 starts it at a full period | `PowerOn.dmc_timer` (new; default 0); only 213 APU cycles of 0 and 211-214, either APU parity, holds |
| Kirby: a DMC fetch 17 cycles apart | **Mesen2**: ignores a rate written in the timer's reload cycle, which AccuracyCoin's hardware answer key ("DMC Reload Timing") applies; Kirby's write lands there | Mesen2 patch 2 |
| Kirby: VBL's NMI during a DMC DMA inside its wait-loop `BEQ` | **the board**: 6502-python saw a request raised during a stall as late; perfect6502 with RDY held low polls it (C30) | 6502-python `note_stall` (PR #7); the board reports each stall boundary |
| AccuracyCoin "Interrupt flag latency" test A regressed (136 to 135) with the first `note_stall` | a taken branch's next-opcode read ignores a request raised in the stall's last cycle (perfect6502 too) | the refined `note_stall` (080fc80): 136 again, milestone 5's cycles |
| Kirby: rows lost after its IRQ | **the tool**: Mesen2 prints a zero-page PC with two digits ("0029  29"); the parser skipped those lines | parser |
| Kirby: `LDA $4015` bit 5 after a DMC DMA | **Mesen2**: `GetInternalOpenBus` returns the external bus, and DMA reads set the internal one; AccuracyCoin's key ("Internal Data Bus", C24) says neither | Mesen2 patch 3 |
| Zelda: `$2002` overflow bit | **Mesen2 setting**: OAM row corruption (C26, AccuracyCoin's key) is off by default; Zelda turns rendering off mid-frame on its title | `configure_for_comparison` turns it on |
| **SMB3: its status-bar IRQ's dummy `LDA $2007` (line 193)** | **the board, open**: a `$2007` read during rendering. Replayed on PPUSim (`ppusim_compare.py`'s harness, the game's access sequence), PPUSim loads its buffer from the first fetch at least 5 dots after the access (a garbage nametable fetch, still the old v), the board one fetch later with v already incremented; PPUSim also changes the fetch stream itself (a hybrid pattern address, an extra address phase). The family of AccuracyCoin's failing "ALE + Read", "Hybrid Addresses" and "$2007 Stress Test" (milestone 4) | the board's octal latch (C31, 2026-10-23, below); then Mesen2's: it does not model the collision, and the board now matches PPUSim on SMB3's sequence |

**The Mesen2 patches** (`scripts/mesen2-detector-fixes.patch`, against
`b9fa69d`; each where a higher tier shows Mesen2 wrong, and each checked
against blargg's `cpu_interrupts_v2`, `ppu_vbl_nmi`, `instr_test-v5` and
`apu_test`, all still passing): 1. a taken same-page branch holds an NMI edge
seen in its operand cycle, as it holds an IRQ (perfect6502); 2. a DMC rate
written in the timer's reload cycle is the one it reloads with (AccuracyCoin);
3. `$4015`'s bit 5 from the internal bus, which DMA reads do not drive
(AccuracyCoin). Reporting them upstream needs the user's agreement.

**The die experiments** (`scripts/perfect6502_nmi_branch.c`,
`scripts/perfect6502_nmi_dma.c`, against the pinned perfect6502): /NMI pulled
low at each half-cycle around a `LDA zp; BEQ` (taken, same page) and a `LDA
zp; JMP` loop, with RDY held low for 4 cycles on the BEQ's or JMP's operand
or next read. Free: an NMI falling 1-2 half-cycles after the opcode fetch is
taken after a JMP but only after the next instruction for the BEQ (C29). Held:
an NMI falling in the halt is taken after the instruction for every read held,
except in the last halted cycle of the branch's next-opcode read (C30).

**Everything else again**, with 6502-python `080fc80` and the board's stall
reporting: the CPU (10), PPU (41), APU (38) and mapper (66) ROMs pass on PyPy
with milestone 5's cycle and instruction counts, every one; AccuracyCoin 136
of 146, the same 123,410,909 cycles and the same ten failures; the quick
suite (59) passes. 6502-python: 1,950 passed; three seeded faults, one in
each rule of the stall (the confirm, the operand read, the next-opcode read's
last cycle), each fail its stall cases.

**Speed of the tool**: Mesen2 traces a minute in about a minute; the board
compares 20,000-35,000 instructions a second on PyPy (17-45 minutes a game,
six at once on this machine).

**Addendum (2026-10-23): the PPU's octal latch, SMB3, 6502-python main.**
6502-python's PR #7 and #8 (CPUFrame) merged; the board is pinned to main
`9dc34bd` and recertified on it (every ROM at milestone 5's counts,
AccuracyCoin unchanged, Kirby's Adventure identical for 60 s). Then SMB3's
divergence was fixed on the board's side (C31): rendering fetches read at
their ALE's latched low byte, and a $2007 read's own ALE and /RD (2 and 4
dots after the access, PPUSim's `tmp_2` and `PD_RB`) collide with the fetch
cadence as PPUSim's half-cycle traces show. Every one of 16 read phases now
leaves PPUSim's buffer (6 before), and SMB3's own access sequence, replayed
on both, too. **AccuracyCoin: 139 of 146** ("$2007 Stress Test", "ALE +
Read" and "Hybrid Addresses" pass); the CPU, PPU, APU and mapper ROMs keep
their counts. Mesen2 does not model the collision: SMB3's status-bar IRQ
reads $2007 mid-line every frame and discards the byte, so
`mesen_lockstep.py --tolerate-2007` passes over a row that differs only in a
register right after such a read (2,593 in the minute) and stops on
anything else; with it SMB3 is identical for 60 seconds. Six games.

Speed of the octal latch: not measured yet. A best-of-5 interleaved A/B on
the 240p Test Suite menu gave 6.2 frames/s before and 5.6 after, but at a load
average of 75 on this 32-core machine (other sessions' runs), where both are
a twelfth of the quiet-machine figures; to repeat when it is quiet.

### Milestone 7: the compatibility sweep, and mappers to 95 % (2026-10-23)

**Pins.** famicom-python at the commit that adds this record; 6502-python
main `9dc34bd`; Mesen2 `b9fa69d` with `scripts/mesen2-detector-fixes.patch`
(six hunks, below); PPUSim `fb7de61`. Dumps from the local No-Intro
`Nintendo - Nintendo Entertainment System (Headered)` and its 2024 set, read
in place, a dump the first set already gave (by its .nes CRC) skipped. PyPy
7.3.20.

**Coverage.** 31 mappers, 23 of them new: 5 MMC5; 9 MMC2 and 10 MMC4; 16,
157, 159 Bandai; 18 SS88006; 19 Namco 163; 21/22/23/25 VRC2 and VRC4; 32
G-101; 33 TC0190; 66 GxROM; 69 FME-7; 75 VRC1; 87; 118 TxSROM; 185; 206
Namco 108; 210 Namco 175/340; 268 AA6023. **2,545 of the 2,662 licensed
dumps (95.60 %)**; the rest are 80, 184, 48, 68, 88, 86, 152, 140, 70 and
others, a few dumps each. Their judges, where any exist, pass with the old
ones: **83 mapper cases** (`scripts/run_test_roms.py --suite mappers`; 17
new: Holy Mapperel's M9, M10 ×2, M66, M69 ×2 and M118, AWJ's `vrctest` on all
nine VRC2/4 boards, tepples's `fme7acktest`), each new one checked with a
seeded fault (a frozen MMC2 latch, A10 from the arrangement on TxSROM, a
344-step VRC prescaler, an FME-7 acknowledge on D0 only: each fails).
`tests/test_mappers_m7.py` pins what no ROM reaches (the EEPROMs' protocol,
counter edges, latch order).

**The tool.** `scripts/compat_sweep.py` runs every licensed dump of an
implemented mapper on Mesen2 and on the board, no input, from power-on
(`MACHINE`, milestone 6), and compares frames 60, 300 and 600 pixel value for
pixel value (Mesen2's frame N is the board's N − 1). Mesen2 runs as
milestone 6 configures it, plus: NTSC whatever the dump's region, and a
standard controller in each port without its game database's input (which
plugs a Zapper in for *Bayou Billy*). `scripts/sweep_triage.py` replays a
differing dump on the board to that frame and sorts it by what the board did
on the differing lines (a rendering toggle, a register access while
rendering); `mesen_lockstep.py` then finds the first instruction where the
large ones part.

**Result: 2,463 of 2,545 dumps identical (96.8 %); every one of the other 82
has its cause.**

| Dumps | Cause | Tier |
| ---: | --- | --- |
| 41 | A register access while rendering (`$2000`/`$2005`/`$2006`/`$2007` mid-line, or `$2007` with v in the palette while rendering is off): the board's latencies and bus are PPUSim's (C13, C15, C21, C22, C31), Mesen2's differ. *International Cricket* writes `$2007` 120 times with rendering on (CPU identical for 600 frames in lockstep) | die-derived, settled in milestones 2 and 6 |
| 13 | **Mesen2**: line 0's stale sprite slot 0 at x = 255 (C35); one pixel | die-derived: `scripts/ppusim_line0.py` |
| 8 | A rendering toggle mid-line (C12): Mesen2 enables in 1 dot | open, with a judge: the C12 work next |
| 9 | The same, then an MMC3 IRQ on another line, A12 following the changed fetches (*Terminator 2* ×3, *Incredible Crash Dummies* ×2, *Krusty's Fun House* ×2, *Tom & Jerry* (E), *Wayne Gretzky Hockey*; lockstep: T2's CPU parts at its IRQ) | as above |
| 7 | The MMC5's in-frame onset, one fetch apart on row 0 (C34): Koei's six and Demo Vision | open, no judge |
| 2 | An M2-counted IRQ one CPU cycle apart (C33): *Racer Mini Yonku*, *TMNT 2* (J) | open, no judge |
| 1 | The render-start OAM row copy (C32): *Tatakai no Banka*'s `$2002` sprite-0 bit | open: PPUSim and Errata.wiki disagree |
| 1 | *Bionic Commando* (Capcom Classics Mini Mix) `[b]`: a bad dump | |

**Board bugs the sweep found, fixed** (each a dump that then runs as on
Mesen2, in frames and in lockstep):

| Bug | Found by | Fix |
| --- | --- | --- |
| The `$2007` read buffer loaded during the PPU's reset | *Argus*, *Family Stadium '87* | held at 0 until the pre-render line (PPU_power_up_state.wiki); identical in lockstep for 130 frames |
| The Bandai EEPROMs saw a STOP when the master released SDA during an acknowledge: SDA is open drain, and the part still held it low | *Rokudenashi Blues*, *SD Gundam Gaiden* 2 and 3 (16.5) | the parts clocked with the line's level, the master's AND theirs; identical 600 frames in lockstep |
| Datach's unbanked CHR-RAM aliased one 1 KiB bank eight times | all seven Datach dumps | mapped straight through; all seven identical, Battle Rush in lockstep 600 frames |
| VRC1's four-bit PRG registers cannot reach *Ninja JaJaMaru*'s 256 KiB Switch reissue, which writes bank $1D | the reissue | every bit written selects (an extension, Mesen2's "oversized PRG"; identical for 128 KiB and less); identical 600 frames |

**The Mesen2 patches**, 4-6 new (each makes the detector agree with the
specification where Mesen2 departs from it, so lockstep can run past the
point): 4. Bandai's `$8000-$BFFF` mapped at power (bank 0, as the board;
Mesen2 left it open bus, and the Datach games read it before banking);
5. AA6023 (268) odd submappers' outer registers at `$5000` (NES 2.0 Mapper
268.wiki; Mesen2 decoded `$6000` only, so *Rod Land* and *Shadow of the
Ninja* never banked); 6. the LZ93D50's `$6000` read drives D4 alone,
D3 only with the Datach's barcode reader (INES_Mapper_016.wiki). Mesen2
settings, not patches, account for the rest: region, input, OAM corruption.

**Everything else again**, on the final tree: the CPU (10), PPU (41) and APU
(38) ROMs pass on PyPy; the mapper ROMs 83 of 83; AccuracyCoin 139 of 146
with milestone 6's 124,304,328 cycles and the same seven failures; the quick
suite passes.

**Speed of the tool**: per dump, Mesen2 a median 4.1 s and the board 101 s
(32-486 s) for 600 frames on PyPy, on a loaded machine; 80 board-hours for
the sweep, 12 at a time.

### C12: mid-line rendering toggles (2026-10-24)

**Pins.** famicom-python at the commit that adds this record; 6502-python
main `9dc34bd`; PPUSim `fb7de61` at skew 3, with the shim now recording
internal signals (`scripts/ppusim/ppusim_shim.cpp`: `PPUSimUnitTest::UnitTest`
is PPUSim's friend, so the shim reads the FSM, the object FIFO's counters and
shifters and the background colour unit's latches and strobes into each trace
entry, `TraceEntry.inner` and `.background`). PyPy 7.3.20.

**What was built.** The model in undocumented-behavior.md C12: PPUMASK's
rendering bits take effect through a fade dot (stopping) or a wake and a dark
dot (starting), the pixel multiplexer latches its bits a dot and two dots
after the access, sprites are eight FIFO lanes with their own X counters, the
overflowed secondary-OAM address freezes the fetch, and the attribute latch
and shifters work as PPUSim's. The board passes the open-bus value at each
write (`early`) for greyscale's early-write bit. And the overflow flag
reaches PPUSTATUS a dot after the evaluation's in-range check.

**The sweeps** (`scripts/ppusim_c12_probes.py`, each against PPUSim pixel for
pixel and ALE for ALE): `phases2` (disable and enable at all 8 fetch phases,
00↔0A and 00↔1E): every case equal. `mux` (1E↔16, 1E↔0E: BG and sprite
enables alone): equal. `sprblank`: equal. `window` (32 off-windows of 1-4 CPU
cycles, 0A and 1E): 0 of 32 differ, both. `ppusim_compare.py c12` (emphasis,
greyscale, BG off and on, clean and early-write bus): equal. `lanes` (49
stops late on a line with a restart on the next): 3 differ, each by one
background pixel after a restart whose wake falls on ph7 following a stop in
the sprite fetch (open item 18). `flagset` (PPUSTATUS read each dot around
line 128's sprite-0 hit and overflow): equal.

**A comparison error found on the way.** `ppusim_compare.Pair.access` took
our PPUSTATUS at the access point and PPUSim's as M2 falls, where the board
(`PPU.end_read`) takes the sprite flags. Read that way the sprite-0 flag
looked a dot late, and a dot-early hit was fitted to it; the board-against-
PPUSim-board lockstep (`scripts/ppusim_lockstep.py "$2002 flag timing"`)
then diverged at the read where the early hit showed. The pair now applies
`end_read` to both; the hit is back on its pixel's dot, and the overflow
flag, which was the dot early, moved instead. The `oam_start` and `c13`
experiments, the other reads, are unchanged. (`c21_c22` and
`c21_rendering` differ from PPUSim on `$2006` writes mid-line, ALE at dot 146
and 4-95 pixels; main `94cbda7` gives the same output, so they predate this
work and stay open.)

**AccuracyCoin: 144 of 146.** "Stale BG Shift Registers", "BG Serial In",
"Stale Sprite Shift Regs", "Frozen OAM2 Increment" and "$2002 flag timing"
now pass. Left: "$2004 Stress Test" 3 and "Misaligned OAM2 Address" 4, which
PPUSim fails too (open item 18). 127,878,004 cycles.

**Everything else again**: the CPU (10), PPU (41) and APU (38) ROMs pass on
PyPy; the mapper ROMs 83 of 83 (run on the tree before the last two fixes,
which touch no mapper-visible state); the quick suite (74) passes. The
certification run caught a crash first: a fade dot landing on dot 0 of a
line indexed a sprite lane that does not exist (regression test added).

**Speed** (240p Test Suite menu, 300 frames after 120 of warm-up, main and
this tree side by side, five pairs on a loaded machine): PyPy 8.4 frames/s
against main's 9.9, about 15 % slower, with a wide spread; CPython about 20 %
by profile. The new state first took the PPU to 80 instance attributes, the
count at which PyPy drops an object's fixed layout for a dict: a third of
the speed, with no other symptom. A test now keeps the PPU under 80.

### PPUSim goldens and four more ROMs (2026-10-24)

**Pins.** As the C12 record; PPUSim `fb7de61` at skew 3.

**The goldens.** `tests/ppusim_scenes.py` turns the C12 sweeps (`phases2`,
`mux`, `window` 0A and 1E, `lanes`, `flagset`) into scenes on a made-up
NROM cartridge whose tiles are dense (few transparent pixels, unlike
blargg's font), with tile $FF solid in both tables. `scripts/ppusim_goldens.py`
ran them once on PPUSim and kept its pixels, the traced line's ALE
addresses and the PPUSTATUS reads (191 cases, `tests/ppusim_goldens.json.gz`,
17 KB); `tests/test_ppusim_goldens.py` replays them on our PPU alone in the
quick suite (about 30 s on PyPy), with no PPUSim build and no fetched ROM.

**What the denser tiles found.** 14 of 191 cases differed where blargg's
font had shown 3. Traced in PPUSim's background shifters: they shift on
the fade dot *and* the dot after it, and not on the first full dot back,
where ours shifted once on each side; the two cancel unless the stop falls
in dots 257-320, where nothing shifts (12 `lanes` cases). Then the sprite
slot's garbage reads: dot 258 reads at A8-A13 from v after dot 257's copy
($2142 for an ALE of $2542), into the tile latch, and the dot-260 read goes
to no latch (2 more; a first try sending it to the attribute latch broke a
third case and was dropped). Left: two `mux` cases where the set-up stops
rendering mid-evaluation and PPUSim's secondary OAM takes a misaligned
entry ours does not (undocumented-behavior.md open item 18), kept in the
test as KNOWN, which fails if they start matching. `ppusim_compare.py c12`:
24 of 24 equal after the fixes.

**Four more hardware-checked ROMs** (`testrom.py`): `cpu_reset/registers`
and `ram_after_reset` (blargg, `$6000`, the harness presses reset);
`blargg_nes_cpu_test5` `official` and `cpu` (his 2005 instruction tests,
whose CRCs are a NES's; a pass is the whole list with no failing opcode
printed: the new `values` block); and `nmi_sync/demo_ntsc`, a line drawn
by greyscale writes timed from a synchronized NMI, whose readme describes
the hardware picture: its left edge with the reference sprites' (x 80) and
its first pixel flashing. The new `spans` protocol checks exactly that over
four frames (x 80-103 on lines 119 and 123; 80-103 and 81-103 on 121).
Not added: `dmc_tests` (blank screen, status.txt "not sure yet"),
`instr_test-v3` (superseded by v5), and the mapper ROMs that report only a
picture. Of those, Mesen2's frame 300 equals ours for `mmc1_a12`,
`m22chrbankingtest`, `mmc5exram`, `mmc5test` and `mmc5test_v2`;
`scanline-a1` differs in 10 pixels on one frame in four, which PPUSim
draws as ours does (frames 19, 23, 27; same pixels): the board sides with
the judge.

**Everything again**, on PyPy with these changes: CPU 14 of 14, PPU 42 of
42, APU 38 of 38, mappers 83 of 83, AccuracyCoin 144 of 146 (the same
two), the quick suite 80.

### Milestone 8: the window, the Famicom's sound and inputs, mapper 30 (2026-10-24)

**Pins.** As the C12 record; Mesen2 2.1.1 with the detector fixes; rainwarrior's
`nes-audio-tests` (`reference/src/nes-audio-tests`, its `build/` ROMs);
the NESdev wiki's `INES_Mapper_019/Submapper_table` (pinned this milestone);
pygame-ce 2.5.8 (SDL 2.32.10) on PyPy 7.3.20.

**The sound path.** A cartridge's sound chip sets the APU's `expansion`
level (mixer units) through `Cartridge.audio_out`, which the board connects
only where the console routes the cartridge's sound (the Famicom's pins
45/46: `famicom`, `av-famicom`); the APU adds it every CPU cycle. On the
NES-001 the chips play to nothing, as on the console.
`connector.expansion_gain(dB, steps)` turns a measured level, a chip's
full-volume square against a full-volume APU square, into mixer units.

**Levels** (`scripts/expansion_levels.py`: each `db_*` ROM on a Famicom, the
RMS of its chip square over its APU square, from the mixer's output):

| ROM | board | measured (rainwarrior, AV Famicom) |
| --- | ---: | ---: |
| `db_vrc6a` (24) | +0.20 dB | +0.2 dB |
| `db_vrc6b` (26) | +0.20 dB | +0.2 dB |
| `db_mmc5` | +1.00 dB | +1.0 dB |
| `db_n163` (submapper 0) | +18.00 dB | 18.0 dB, the nine games' median |

The gains are set from these measurements, so the match checks the path,
the registers (both VRC6 wirings) and the waveforms' duty, not the level
itself. Other consoles and cartridges measured differently (James-F: VRC6
-1.11 dB, MMC5 +0.05 dB on an HVC-CPU-07; N163 boards 11-19.5 dB by
resistor, which the submapper carries).

**A band-limited output.** The N163 outputs its channels in turn, 15 CPU
cycles each (C37): with 4 channels a 29.8 kHz switching tone, ultrasonic on
the console, which the plain box filter at 44.1 kHz folded to about 18 kHz,
3 dB under *Rolling Thunder*'s music. The APU's box filter now runs at four
times the host rate and `take_samples` low-passes it (96-tap Blackman sinc
at 20 kHz) and decimates: the switching is 20 dB under, a 30 kHz square 36
dB (the box stage's uneven 10/11-cycle windows set that floor). In band
nothing moved: `volume_tests` against the NES-001 recording within 0.03 dB
of milestone 3's table on every tone but the random noise, and the four
levels above unchanged.

**Against Mesen2** (detectors). Pictures of the three VRC6 games at frames
600 and 1800: 5 of 6 identical; *Akumajou Densetsu*'s frame 600 differs in
3 rows, and the lockstep (`mesen_lockstep.py`) finds the board's VRC IRQ
taken one instruction before Mesen2's at instruction 63,185: C33 again.
Sound: Mesen2 mixes the VRC6 2.4 dB quieter against the APU than the
measurement (`db_vrc6a`: its fitted gain 1.238 on the APU square, 1.637 on
the VRC6's), and counts the VRC6 pulse's steps the other way from the wiki
(C36); *Akumajou Densetsu*'s VRC6 alone (`mesen_audio.py --expansion-only`)
matches Mesen2's to -0.3 to -3 dB as built, and to -7 to -16 dB with
Mesen2's direction, about the APU's own floor against it (milestone 3).
Mesen2 sums the N163's channels where the board takes them in turn (C37).

**UNROM 512** (30). `tests/test_mappers_m8.py` pins the banking, the
nametable wirings and the flash's command sequences. Against Mesen2's
frames 60, 300 and 600, one in 20 of the Aftermarket set's mapper-30 dumps
(`compat_sweep.py --aftermarket --mappers 30 --every 20`): 53 of 53
identical.

**Inputs.** Machine data says which `$4016`/`$4017` lines a console leaves
to open bus (the Famicom's `$4016` D3-D4, the NES-101's D2) and whether
player 2's pad has the microphone (`$4016` D2, the RF Famicom); the board
reads a pad on each port's D1 through the expansion port, the four-player
adapters' players 3 and 4 (`tests/test_board.py`).

**The window** (`famicom-python play`, `frontend.py`). sms-python's design:
SDL through pygame-ce, a frame-sized surface scaled on the GPU, sound
through SDL's audio callback pacing the loop where the board keeps up;
keyboard and gamepads (four on a Famicom), the microphone on M, reset,
power cycle, pause, fast forward, screenshots; battery memory (and UNROM
512's flash) read from and written to `ROM.sav`
(`Cartridge.restore_battery`, the inverse of `battery_ram`). Tested
through SDL's dummy drivers (`tests/test_frontend.py`: frames run, a save
written and restored); not tested on a display here.

**Not reached.** NewRisingSun's hardware recordings of his expansion-audio
test ROMs (open item 20); the 5B (an AY-3-8910 core, later), the VRC7
(YM2413, later) and the FDS.

**Everything again**, on PyPy with milestone 8: CPU 14 of 14, PPU 42 of 42,
APU 38 of 38, mappers 83 of 83, AccuracyCoin 144 of 146 (the same two, the
same 127,878,004 cycles), the quick suite 105 (the window's test included
where pygame-ce is installed).

**Follow-ups (2026-10-24).** *Reachability*: every one of the 470 pinned
files and 29 repositories answers when fetched with curl and the fetcher's
User-Agent; the NESdev forum serves a 403 page only to curl's default one
(and nesdev.org to Python's urllib), so open item 20's first reading was
wrong. NewRisingSun's test ROMs are now pinned; his recordings are not
(404, and archive.org offline that day). *The N163 against Mesen2*: the
games' music starts two frames apart (Mesen2 1,602 samples earlier in
*Rolling Thunder*), beyond `mesen_audio.py`'s 1 ms alignment; with
`--lag-ms 50`, *Rolling Thunder*'s 4 channels match to -10 to -15 dB, and
*King of Kings*' 8 to only -2 dB: there the switching (14.9 kHz) is in band
and the board plays it, where Mesen2 averages (C37). *Speed*: milestone
3's board measures what milestone 8's does (three concurrent pairs, 240p
menu, CPU time: 4.3/5.7, 7.1/5.3, 5.0/6.0 frames/s), with either 6502-python
pin; every milestone between falls in the same 3-7 band. Nothing in the
code lost the 53.6 frames/s of milestone 3's record: the machine did (load
average 76-90 on 32 threads, most of them E-cores), and `perf` is not
available to count instructions instead. Measure on an idle machine.

### AccuracyCoin 146 of 146 (2026-10-26)

**Pins.** famicom-python at the commit that adds this record; Breaknes
`215ab82` (`54caa4f` fixed `$2002` bit 7, so `scripts/ppusim_board.py` no
longer corrects it); AccuracyCoin `6bee919`. PyPy 7.3.20.

**Judges.** Visual 2C02 (Quietust's transistor netlist of the 2C02G, run
headless by `scripts/visual2c02/v2c02.js`) is a die model independent of
PPUSim; `scripts/visual2c02/compare.py` drives the board's PPU, PPUSim and
Visual 2C02 with one register schedule and compares reads, pixels and
internal signals half-cycle by half-cycle (the BreakingNESWiki maps PPUSim's
signal names to the netlist's nodes). It found four PPUSim bugs, reported
with patches as emu-russia/breaknes#535-#538; with them PPUSim scores 145
of 146 (only OAM Corruption, analogue, fails) and judges the three below.
Visual 2C02 is not a judge in the sprite overflow scan: there it steps the
address by 4 where the hardware answer key, PPUSim and the board agree on
the buggy step.

| Test | Was | Cause | Judge |
| --- | --- | --- | --- |
| Misaligned OAM2 Address | 4 | the sprite fetch's secondary OAM address is a counter that steps only while rendering (four a slot, a last step on dot 321 that wraps and raises the freeze); the board derived it from the dot | Visual 2C02 `spr_ptr`; lockstep with patched PPUSim |
| `$2004` Stress Test | 3 | in the overflow scan the copy's last byte gets the range check, as in a normal copy: out of range, the address is masked back (`$A0 $A1 $A2 $A0 $A4` after a find at `$9F`) | the test's two 341-byte hardware answer keys, now equal on every dot; PPUSim's address probe |
| Sprites On Scanline 0 | passed as an RGB PPU | after the odd-frame skip a lane still active from the pre-render fetch shifts out its first pixel at x = 0 (the rest at X+1 on): `#0/H` comes a dot late against line 0, `/VIS` at H=1 as always | Visual 2C02 lane 0 per half-cycle; patched PPUSim's pixels for three tile rows; the test now reports a composite PPU |

The study also suspected the board's `$2004` reads around dots 250-256;
both answer keys cover them and now match, so that was the comparison's
one-dot alignment, not the board.

**Everything again**, on PyPy: CPU 14 of 14, PPU 42 of 42, APU 38 of 38,
mappers 83 of 83, AccuracyCoin **146 of 146** (127,878,003 CPU cycles,
4,294 frames, 132 s), the quick suite 105.


### Expansion-audio recordings, and speed on an idle machine (2026-10-26)

**Pins.** famicom-python at the commit that adds this record; NewRisingSun's
`2018-08-06_ExpansionAudio.7z` (archive.org's copy of 2018-08-17, SHA-256
`048a7bb4…`) and his `ExpAudio_testroms.7z`. PyPy 7.3.20, CPython 3.14.

**The recordings.** NewRisingSun loaded his test ROMs into a Sharp
AN-505-BK Twin Famicom (C205 removed) from an EverDrive, hot-swapped each
cartridge in so its own chip played them, and recorded Audio Out at 96 kHz
with one gain for all (nesdev-forum/16910.html): two MMC5 carts, ten N163,
one VRC6, each ending with some of the game. The tests play fifteen volume
steps of a 440 Hz square on the APU, then on the chip (the VRC6 also its
saw, the N163 eight channels, the MMC5 its DAC). `scripts/nrs_recordings.py`
runs the same ROMs on the board (Famicom, 96 kHz, before the analogue stage)
and compares each step's fundamental, which the console's filters scale
alike at one pitch. Its numbers reproduce NewRisingSun's own N163 column of
the wiki's mixing table within 0.1 dB.

| Chip | Hardware | Board | |
| --- | --- | --- | --- |
| APU square, steps 1-15 | steps 1-7 0.1 dB high against 8-15, on all 13 | the mixer formula | the 2A03's bit 3 a little light on this console; not modelled (one console) |
| MMC5 square | +1.08, +0.70 dB against the APU's; linear within 0.13 dB | +1.0 dB, linear | agrees |
| MMC5 DAC, $02/$22 | 4.3, 5.1 dB under a full MMC5 square | was 3.6 dB *over*; now 4.7 under | **fixed** (C38) |
| N163, one channel | 9 carts within 1 dB of their submapper's level (11-13, 16-17, 18-19.5 dB bands); *Namco Classic II* +2.1 dB | the band's middle | agrees but *Namco Classic II* (open item 20) |
| N163, eight channels | 0.22 dB under one channel | 0.34 dB under | taken in turn (C37) |
| N163 switching | a line at 1,789,773 / 120 Hz, +39-44 dB, on every cart; in *King of Kings*' music +22 dB | the same | settles C37 |
| VRC6 square | -0.35 dB against the APU's; steps 1-7 up to 0.4 dB high against 8-15 | +0.2 dB (rainwarrior's AV Famicom), linear | consoles differ (James-F: -1.1 dB); the DAC's bit 3 light on this cart |
| VRC6 saw | +2.03 dB against the APU square | +2.83 dB | 0.25 dB against the VRC6's own square: within its DAC's spread |

The VRC6's duty direction (C36) stays open. *Madara*'s music on the board
(Start, then A, from power-on) lines up with the recording's by its
loudness envelope (correlation 0.87; the recording is the board plus
132.81 s), but no filter fitted on 8 s maps either direction's output onto
the next 30 s (residuals within 2 dB of the recording itself, in the full
band and in 1.5-8 kHz): the APU's triangle and noise, whose phase the game's
writes do not set, sound as loud as the VRC6 throughout, and the test ROM
plays the VRC6's pulse alone.

**Speed.** Milestone 8's follow-up blamed the machine alone for the lost
frames; on an idle machine (load 4-7 on 32 threads) the code lost some too.
The 240p Test Suite's menu, CPython, each version pinned to its own
5.5 GHz P-core, three rounds with the cores rotated (frames/s):

| Milestone 3 | 4 | 5 | 7 | 8 | main |
| --- | --- | --- | --- | --- | --- |
| 8.3, 8.5, 8.7 | 7.7, 7.8, 7.9 | 7.7, 7.8, 7.8 | 7.5, 7.1 (5.7) | 6.5, 6.7 (5.0) | 6.5, 6.5, 6.1 |

About 25 % in all, in steps: milestone 4 (AccuracyCoin's fixes) 8 %,
milestones 5-7 about 4 % (near the noise; not traced), and between 7 and 8
10 %, where C12 and the expansion-sound path landed: the PPU's per-dot
`_step` costs 56 % more than at milestone 7 (cProfile; sprite evaluation
following PPUMASK itself, the wake and fade states checked on every dot).
Correctness bought it; no one change lost it. PyPy, one run at
a time on one core, 900 frames after 120 of warm-up, `PYTHONHASHSEED` 0 and
1: milestone 3 63-78 frames/s, main 57-60 (0.95-1.0x real time). PyPy's
300-frame windows vary from 32 to 74 frames/s for the same code, so the
earlier records' PyPy figures carry about that spread.

**Everything again**, on PyPy with the DAC change: CPU 14 of 14, PPU 42 of
42, APU 38 of 38, mappers 83 of 83, the quick suite 105 (AccuracyCoin, an
NROM cart, does not reach the change).

### Milestone 9, part 1: the FDS RAM adapter and its drive (2026-10-26)

**Pins.** famicom-python at the commit that adds this record; the BIOS is
No-Intro's "Rev 1" (CRC32 `5E607DCF`, FDS-disksys's Rev 01A), read from the
local set and never committed; the test disks pinned in
`scripts/pinned_files.json` (`tests/test_roms/fds/`); Mesen2 2.1.1 as for
milestone 6 with the same BIOS in its Firmware folder. PyPy 7.3.20.

**What was built.** `cartridge/fds_disk.py` turns a `.fds` side into the
stream on the disk (FDS_disk_format.wiki: a 28,300-bit pre-gap, each block
behind a $80 mark with its CRC-16/KERMIT, 976-bit gaps) and back.
`cartridge/fds.py` is the RAM adapter: 32 KiB PRG-RAM, 8 KiB CHR-RAM, the
BIOS, the registers as User:TakuikaNinja/FDS_Registers.wiki has them (the
hardware-verified rewrite), the timer IRQ, the DRAM refresh watchdog, and a
drive moving a byte every 1,792 master ticks. The loader recognises disk
images (`.fds` or inside a `.zip`) as mapper 20. The BIOS's own disk code
(disassembled locally with TakuikaNinja's FDS-disksys configs, not kept)
fixed the read protocol: `$4025` D6 waits for the gap's 1 bit, D4 after the
first CRC byte, `$4030` D4 after the second.

**Judges** (`scripts/run_test_roms.py --suite fds`, `tests/test_fds_test_roms.py`):

| Disk | Hardware answer | Board |
| --- | --- | --- |
| Sour's FdsIrqTests v7 | rainwarrior's RAM adapter, 2017-09-23 (nesdev-forum 16507): all 21 tests O, with each test's IRQ count | the same 21 lines |
| TakuikaNinja's FDS-Mirroring-Test v1.1 | Twin Famicom screenshot: three passes | three passes |
| TakuikaNinja's FDS-4030D1-Addr v1.0 | Twin Famicom screenshot: watchdog IRQs return to $67FF and $6E25 | $67FF and $6E25 (C41) |

The watchdog screenshot also shows grey lines where the test's handler
switches on greyscale at each IRQ; their spacing in the capture (126 px, 4.07
to 4.36 px a scanline depending on how the glyphs are measured) puts the
period at 29 to 31 lines, and the board's is 29.8: within the reading, not a
judge.

**Against Mesen2** (frames, a detector): 13 games booted from side A,
compared at frames 600-2400 in a ±40-frame window: *Zelda no Densetsu*,
*Link no Bouken*, *Metroid*, *Super Mario Bros. 2*, *Hikari Shinwa*,
*Akumajou Dracula*, *Doki Doki Panic*, *Nazo no Murasamejou*, *Famicom
Grand Prix*, and the four whose timer IRQs no emulator ran together in 2017
(*Druid*, *Kaettekita Mario Bros.*, *Lutter*, *Putt Putt Golf*): every frame
identical, 4-6 frames apart (the byte time is 149 1/3 cycles here, 149 in
Mesen2; C39). Two board bugs found on the way: CHR-RAM left on `Banked`'s
default windows (all at 0: every 1 KiB aliased), and a `$4025` stop pulse
missed between byte times (C40).

**Everything again**, on PyPy: CPU 14 of 14, PPU 42 of 42, APU 38 of 38,
mappers 83 of 83, FDS 3 of 3, the quick suite 114 (with `tests/test_fds.py`).
Not reached in this part: open item 21.

### Milestone 9, part 2: the FDS's sound (2026-10-26)

**Pins.** As part 1; nes-audio-tests `db_fds.fds` as pinned.

**What was built.** `cartridge/fds_sound.py`, clocked by the RAM adapter
every cycle. Sources: FDS_audio.wiki with loopy's 2019 test-register findings
(C42); the master volume from Yuri213212's die schematic of the DAC (an R-2R
ladder whose switches ground 2R and R: 1, 2/3, 1/2, 2/5, the wiki's ratios);
rainwarrior's 2 kHz one-pole fit for the RAM adapter's filter
(nesdev-forum/10233.html: lidnariq's simulation of the circuit gives 1.75 kHz
and two poles near 20 kHz instead); `$4023` D1 as FDS_Registers.wiki's audio
reset.

**Level.** `scripts/expansion_levels.py` now runs disks: `db_fds` measures
+6.60 dB against rainwarrior's +6.6 (by construction, the filter's 0.61 dB
loss on the 440 Hz square put back), and the four other chips are unchanged.

**Against Mesen2** (`mesen_audio.py --expansion-only`, a detector): C43.

**Everything again**, on PyPy: FDS 3 of 3, the quick suite 120 (six sound
tests added to `tests/test_fds.py`); the expansion levels as above.
