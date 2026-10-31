# famicom-python

A readable, pure-Python emulator of **Nintendo's Family Computer and NES**,
built as a board on [6502-python](https://github.com/alewman/6502-python):
6502-python owns the instruction set; this repository owns everything
around it: the 2A03's sound unit, DMA and joypad ports, the 2C02 picture
processor dot by dot, the cartridge connector and the mappers behind it, and
the clock that ties them together.

**Status (2026-10-30): feature complete for its scope.** The reference
model is an NES-001 with an RP2A03G and RP2C02G, with the Famicom, PAL and
Dendy as rows of the same table: the CPU on the board, the PPU dot by dot, the
APU, DMA and interrupts on one master-clock timeline, AccuracyCoin 147 of
147, lockstep with Mesen2 instruction by instruction, a window to play in
(`famicom-python play`), expansion sound checked against NewRisingSun's
recordings of thirteen carts and VRC7 FM from ym2413-python, and the Famicom
Disk System with Nintendo's BIOS (yours: `FAMICOM_FDS_BIOS`).

**Mappers are closed as an active effort**: 294 of them, 99.80 % of the main
No-Intro set and every licensed dump but the StudyBox BIOS. Complete does not
mean verified: most boards have no judge ROM, and some Mesen2 cannot load, so
their titles were only looked at. [docs/mappers.md](docs/mappers.md) has every
mapper's source and evidence, what is left, and how to pick it up.

Not built, by choice for now: the Vs. System and PlayChoice-10, and the speed
work (reference boards aim to be correct; `*-fast` projects are for speed).
Open questions with no hardware answer are in
[docs/undocumented-behavior.md](docs/undocumented-behavior.md).

- **nestest**: 8,991 of 8,991 lines of `nestest.log` (PC, A, X, Y, P, SP, CYC
  and the PPU columns).
- **blargg's and Bisqwit's CPU ROMs**, all 14 passing on PyPy:
  `instr_test-v5` (all 16), `instr_timing`, `instr_misc`, `cpu_timing_test6`
  (official and unofficial), `branch_timing_tests` 1-3, `cpu_dummy_reads`,
  `cpu_dummy_writes_ppumem`, `cpu_exec_space_ppuio`, `cpu_reset` (2),
  `blargg_nes_cpu_test5` (official and all).
- **42 PPU ROMs**, all passing on PyPy: `ppu_vbl_nmi` (10),
  `vbl_nmi_timing` (7), `sprite_hit_tests` (11), `sprite_overflow_tests` (5),
  blargg's 2005 PPU tests (4), `ppu_open_bus`, `ppu_read_buffer`, `oam_read`,
  `oam_stress`, and `nmi_sync`'s demo, whose line is checked against the
  hardware picture its readme describes.
- **PPUSim, the gate-level 2C02G, as judge**: on the board in place of the
  PPU it passes `ppu_vbl_nmi` 10/10 (at one CPU/PPU skew); compared pin for
  pin, it settled the questions no test ROM pins (the `$2006`/`$2007` delays,
  the sprite garbage fetches, the empty-slot row, the odd-frame skip, the
  colour bits of `$2001`), and the board now matches it: `full_palette` and
  `flowing_palette` frames identical, every fetch address of rendered lines
  identical. Mid-line rendering toggles (C12) match it too, and 191 of its
  answers are kept as goldens the quick suite replays without it.
- **Mesen2, pixel for pixel** (a detector): identical frames for the 240p test
  suite, demos and scrolling tests; where it differs, PPUSim sides with the
  board or the case is open (docs/validation.md, milestone 2).
- **38 APU, DMA and interrupt ROMs**, all passing on PyPy and CPython:
  `apu_test` (8), `apu_reset` (6), blargg's 2005 APU tests (11),
  `cpu_interrupts_v2` (5), `dmc_dma_during_read4` (5, with the CRCs of the
  board's synchronization, which PPUSim prints too), `sprdma_and_dmc_dma`
  (2), `read_joy3/thorough_test`.
- **Sound against hardware**: the channels' relative levels in
  `volume_tests` match an NES-001 recording within 0.3 dB for the pulses;
  the triangle and DMC read about 1 dB loud (open). Against Mesen2 (a
  detector), `apu_mixer`'s tones agree in timing, pitch and level.
- **APUSim, the gate-level 2A03**, runs here but is not yet a judge: 3 of 8
  `apu_test`, for a cause found in its simulation order.
- **AccuracyCoin** (`b4b5952`, 147 tests): all 147 pass, from 116 on the first
  run, fixed against its hardware answer keys: the frame IRQ's clear and
  inhibit, the controller strobe, the 2A03's internal data bus, its register
  decode during DMA, the DMC's reload timing, enable hold and abort bug, SHx
  after a DMA (6502-python PR #7), OAM evaluation, corruption and `$2004`,
  sprites from the pre-render line, and the PPU's octal latch (`$2007` reads
  and `$2006` writes during rendering), mid-line rendering toggles (C12,
  settled on PPUSim's internal signals) and the overflow flag's set dot.
  The last two ("$2004 Stress Test", "Misaligned OAM2 Address") and the
  composite answer to "Sprites On Scanline 0" were settled on Visual 2C02,
  the transistor netlist run headless (`scripts/visual2c02/`), and on
  PPUSim with the four fixes reported as emu-russia/breaknes#535-#538.
- **Mappers, 66 judges** on PyPy and CPython ([docs/claims.md](docs/claims.md)
  per mapper): blargg's `mmc3_test_2`, `mmc3_test` and `mmc3_irq_tests` on
  the Sharp and NEC IRQs, every Holy Mapperel build for mappers 0-4 and 7,
  rainwarrior's bus-conflict tests (2, 3, 7, 34), `bntest`, `serom`, and
  `mmc1atest`'s MMC1A table. PPUSim settled what the MMC3 needed from the PPU:
  the address on the bus at dot 0.
- **Lockstep with Mesen2** (a detector, `scripts/mesen_lockstep.py`): *Super
  Mario Bros.*, *The Legend of Zelda*, *Mega Man 2*, *Kirby's Adventure* and
  *Battletoads* identical for 60 seconds from power-on (33.7-34.8 million
  instructions each). Every divergence on the way was settled by a higher
  tier: three were Mesen2's (patched for the comparison), one the board's (an
  interrupt during a DMA stall, settled on perfect6502 and fixed in
  6502-python). *Super Mario Bros. 3* too, once the board modelled the PPU's
  octal latch (a `$2007` read during rendering collides with the fetches,
  as PPUSim shows; Mesen2 does not model it, so those rows are passed over).
- Pins: 6502-python `9dc34bd` (main, with PR #7's `dma_stalled` and
  `note_stall`),
  `nes-test-roms` `95d8f62`, AccuracyCoin `6bee919`.
  The record, with SHA-256s, cycle and instruction counts, wall times and
  the seeded faults each gate catches, is in
  [docs/validation.md](docs/validation.md#certification-record).

The documents in [`docs/`](docs/README.md) hold what the build needs, every
fact with its source and tier; [docs/handoff-brief.md](docs/handoff-brief.md)
is the brief it was built from.

```sh
python -m pip install -e '.[dev]'
python scripts/fetch_references.py            # the test ROMs and references
python -m pytest                              # quick: nestest, board, PPU, APU, loader
python -m pytest -m slow                      # the CPU, PPU and APU test ROMs
python scripts/run_test_roms.py --suite cpu   # the same, as a certification table
python scripts/run_test_roms.py --suite ppu
python scripts/run_test_roms.py --suite apu
python scripts/accuracycoin.py --failures     # all of AccuracyCoin (--test NAME for one)
python -m famicom_python ROM --frames 600 --png out.png --wav out.wav
python -m pip install -e '.[frontend]'        # pygame-ce, for the window
famicom-python play ROM --machine famicom     # play (keys: famicom-python play -h)
```

The window is the reference board's: on PyPy it runs at a fraction of real
time on a loaded machine (docs/validation.md, milestone 8), and shows every
frame it makes. Battery saves (and UNROM 512's flash) go to `ROM.sav`.

## Scope

| Machine | Phase |
| --- | --- |
| NES-001 (RP2A03G + RP2C02G): the reference model | 1 |
| Famicom (RF), AV Famicom, NES-101: as fields on the same board | 1 |
| PAL NES (2A07 + 2C07), Dendy | later, as machine data |
| Famicom Disk System, Vs. System, PlayChoice-10 | later |

Mappers live in this repository behind a signal-level cartridge connector
([docs/cartridge.md](docs/cartridge.md)); the first six (0, 1, 2, 3, 4, 7)
cover 83 % of licensed cartridges, and the 34 done cover 95.8 % (2,551 of
2,662 licensed dumps).

## What is fetched

Nothing third-party is committed. `scripts/fetch_references.py` rebuilds
`reference/` and `tests/test_roms/` from `scripts/pinned_files.json` (759 files
pinned by SHA-256: NESdev wiki and forum snapshots, documents, test ROMs,
hardware captures) and `scripts/pinned_repos.json` (29 repositories at full
commit SHAs, sparse where large):

```sh
python scripts/fetch_references.py            # everything missing
python scripts/fetch_references.py --verify   # check what is present
```

It needs `git` and `curl`. Wiki and forum pages are live: a changed page is
reported and kept; everything else must match its hash.

**Game ROMs are not included and not fetched.** The test ROMs above are
freely distributed homebrew; to play a game, or to run the Mesen2 lockstep
(`scripts/mesen_lockstep.py`) and the compatibility sweep
(`scripts/compat_sweep.py`, `scripts/count_mappers.py`, which read No-Intro
sets from the directory in `NO_INTRO_DIR`), supply your own dumps. The referees (Mesen2, PPUSim and
APUSim, built locally from their pinned sources; MAME 0.285) are needed only
by the scripts that use them, not by the test suite.

## Scripts

| Script | What |
| --- | --- |
| `scripts/fetch_references.py` | the pinned references and test ROMs |
| `scripts/run_test_roms.py` | a milestone's test ROMs in parallel, as a certification table |
| `scripts/mame_trace.py` | MAME 0.285 per-instruction trace and register log of an NES cartridge ([docs/mame-oracle.md](docs/mame-oracle.md)) |
| `scripts/mesen_run.py`, `scripts/mesen_blargg.lua` | a locally built Mesen2 core driven headless, stopping on blargg's `$6000` result ([docs/validation.md](docs/validation.md)) |
| `scripts/mesen_frames.py` | a frame of the board against Mesen2's, pixel value for pixel value |
| `scripts/build_ppusim.py`, `scripts/ppusim/` | Breaknes PPUSim (gate-level 2C02G) built with our shim, which records its pins |
| `scripts/ppusim_board.py` | a test ROM on the board with PPUSim in place of the PPU |
| `scripts/ppusim_compare.py` | the board's PPU and PPUSim fed the same register accesses, compared pin for pin, or a whole frame (`frame ROM N`) |
| `scripts/accuracycoin.py` | AccuracyCoin run in full or test by test, each result with its error code |
| `scripts/ppusim_lockstep.py` | an AccuracyCoin test on the board and the PPUSim board in lockstep, to the first divergence |
| `scripts/ppusim_c12_probes.py` | the C12 investigation's probes: mid-line toggles on the board's PPU and PPUSim, with PPUSim's internal signals |
| `scripts/ppusim_goldens.py` | records PPUSim's answers to `tests/ppusim_scenes.py` for the quick suite (`--check`: where ours differs) |
| `scripts/mesen_audio.py` | the board's sound against Mesen2's recording, window by window (aligned, gain-fitted, residual) |
| `scripts/volume_levels.py` | the channels' relative levels in `volume_tests` against its NES-001 recording |
| `scripts/expansion_levels.py` | each sound chip's level in rainwarrior's `db_*` ROMs against the measured one |
| `scripts/nrs_recordings.py` | NewRisingSun's expansion-audio test ROMs on the board against his recordings of thirteen carts: volume steps, levels, the N163's switching, the MMC5 DAC |
| `scripts/build_apusim.py`, `scripts/apusim/` | Breaknes APUSim (gate-level 2A03) built with our shim: a stub board around the whole chip |
| `scripts/apusim_board.py` | a test ROM on APUSim, `$6000` result and per-cycle channel outputs |
| `scripts/count_mappers.py` | mapper coverage over the local No-Intro sets, read in place ([docs/cartridge.md](docs/cartridge.md)) |
| `scripts/mesen_lockstep.py` | a game on the board against Mesen2's trace, instruction by instruction, to the first divergence |
| `scripts/compat_sweep.py` | every licensed dump of an implemented mapper against Mesen2, frames 60, 300 and 600 |
| `scripts/mapper_registry.py` | generates the registry in [docs/mappers.md](docs/mappers.md) and `tests/sweep_failures.tsv` from a sweep |
| `scripts/rom_scan.py` | a dump's header, vector banks and absolute register accesses, without running it |
| `scripts/mapper_trial.py` | runs a dump on a chosen board and shows what it asks the cartridge for |
| `scripts/disasm6502.py` | a small 6502 disassembler for reading bank-switching and protection code |
| `scripts/sweep_triage.py` | the sweep's differing dumps sorted by what the board did on the differing lines |
| `scripts/ppusim_line0.py` | line 0's stale sprite slot 0 on the board's PPU and PPUSim (C35) |

## Licence

MIT (see `LICENSE`), for what is in this repository, except
`scripts/mesen2-detector-fixes.patch`: a patch to Mesen2, whose context lines
are Mesen2's, so it is under Mesen2's GPL-3.0. The fetched material keeps its
own terms, recorded per file in the pin lists.
