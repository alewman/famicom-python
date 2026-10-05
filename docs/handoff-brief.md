# Handoff: build `famicom-python`, the Famicom / NES board

## Context you are inheriting

The family's shape is **chips are cores, boards compose cores**. Each core is
certified on its own against its oracles and pinned by the boards that use it;
each board is validated against hardware-tier test programs, with MAME and
other emulators as detectors only. `sms-python` (Master System, on
z80-python) and `megadrive-python` (on m68000-python and z80-python) are the
boards to model this one on; `6502-python` (`/data/emu/6502-python`, github
alewman/6502-python, import name `sixfiveohtwo`) is the core it embeds. Its
0.2.0 rebuild (merged as PR #1, `25877b3`) makes every CPU cycle one bus
callback, in chip order: that property is what lets this board be exact.

Read, in order, before writing code:

1. `README.md`: scope, what is fetched.
2. `docs/start-here.md`: the machines, clocks, CPU map and I/O, the PPU
   programming model and output format, the APU, the module shape.
3. `docs/timing.md`: interrupt polling, the DMA cycle diagrams and the
   DMA-inside-`read_byte` design, the PPU dot schedule and frame events, the
   APU frame counter.
4. `docs/cartridge.md`: the connector protocol, file formats, nes20db,
   measured coverage, the per-mapper table and judges.
5. `docs/undocumented-behavior.md`: quirks, revisions, **contradictions C1–C21**,
   open items.
6. `docs/validation.md`: every oracle with its tier and pin, the result
   protocols, Mesen2 as a headless detector.
7. `docs/mame-oracle.md`: the verified MAME 0.285 recipe and its traps.
8. 6502-python's `README.md`, `docs/start-here.md`, `docs/validation.md`
   ("Limits") and `src/sixfiveohtwo/cpu.py`, `_control.py`: the contract you
   embed.
9. sms-python's `src/sms_python/` for the family's board conventions (machines
   as data, `take_samples`, `frontend.py`, the MAME trace scripts).

Then `python scripts/fetch_references.py` (or `--verify`): 468 pinned files and
29 pinned repositories; it fetches with `curl` because nesdev.org refuses
Python's `urllib`.

## Decisions already made

- **Name `famicom-python`**: the Famicom is the superset (expansion audio, the
  Disk System). **NTSC first**; PAL and Dendy exist from the start only as rows
  of the machine table. Reference model: NES-001 with RP2A03G + RP2C02G.
- **Python floor 3.11** (the newest PyPy supports), CPython and PyPy;
  `requires-python = ">=3.11"`, ruff `target-version = "py311"`, ruff pinned as
  in sms-python.
- **The board stays dependency-free** apart from its cores; the frontend
  (pygame-ce) is an optional extra; the board runs headless and produces frames
  and audio as data.
- **Mappers live in this repository**, in `famicom_python/cartridge/`, behind
  the connector protocol, with a test that forbids imports from the board
  ([cartridge.md](cartridge.md) has the reasons).
- **The PPU is dot-accurate and puts every bus access on the connector.** No
  scanline renderer.
- **The APU and PPU are written behind pin-shaped interfaces** so that either
  can later be extracted with its history into its own core (the way
  `ym2612-python` came out of megadrive-python), when a second user appears
  (an NSF player, the Vs. System). Not now.
- **Expansion sound chips that are real chips become shared cores**: VRC7 →
  a YM2413 core with a VRC7 variant (shared with sms-python's FM unit; judge
  Nuked-OPLL `opll_type_ds1001`); Sunsoft 5B → an AY-3-8910/YM2149 core. Not in
  this brief's milestones; VRC6, N163, MMC5 audio and FDS stay here.
- **Reference boards are correct, not fast.** Speed is a later `-fast` project's
  job.

## Prerequisites: pull requests on 6502-python

The family rule: a board that finds a corner of its core raises it **on the
core** (a PR there, re-certification is fine), not as a workaround here. Three
are needed; open each as a PR on alewman/6502-python from a branch off
`origin/main`, with the core's own gates (SingleStepTests, Dormann, mutation
check) green and a seeded fault shown to fail the new gate. The user merges.
Until they land, pin a 6502-python git revision in `pyproject.toml`, never a
local path.

1. **RP2A03 variant: decimal mode disconnected** (required for milestone 1).
   ADC, SBC, USBC, RRA, ISC and ARR compute in binary; D remains a real flag.
   Judge: SingleStepTests `65x02` `nes6502/v1` at `2f6980a2`, 2,560,000 cases with
   bus cycles, through the harness 6502-python already has for `6502/v1`. Today's
   core fails only D-set cases there ([undocumented-behavior.md](undocumented-behavior.md)
   item 1).
2. **Interrupt polling at the end of the penultimate cycle** (required for
   milestone 3), as seen *after* each bus callback returns, with BRK and
   interrupt entries suppressing their own poll, the NMI hijack decided on the
   state at the end of cycle 4, CLI/SEI/PLP/RTI unchanged, and `CPUState`
   carrying the new state. Judge in the core: unit tests with a scripted bus that
   raises IRQ/NMI on a chosen cycle of each instruction shape, against the rules
   in [timing.md](timing.md) "Interrupts". Judge on the board: blargg
   `cpu_interrupts_v2` 1–5 and AccuracyCoin page 12.
3. **Branch poll points** (with 2 or right after): a taken same-page branch
   polls only at the end of cycle 1; a page-crossing one at cycle 1 or 3. Judge:
   `5-branch_delays_irq`, AccuracyCoin "Interrupt Flag Latency" 9/A/B/E.
4. *Optional, last*: a flag by which the board says "the cycle before this write
   was stalled by DMA", so SHA/SHX/SHY/TAS drop their AND. Judge: AccuracyCoin
   unofficial-opcode codes 7–C. No game needs it.

**Not** needed: an RDY input (DMA runs inside `read_byte`, [timing.md](timing.md)
"The design"), power-on noise (registers are plain attributes the board sets).

## Your task

Build the board as `src/famicom_python/`. The module shape in
[start-here.md](start-here.md) is a suggestion; the requirements are:

- **Machines as data**: NES-001, Famicom (RF), AV Famicom, NES-101, with the
  fields listed in start-here.md (CPU/PPU variant, `reset_resets_ppu`,
  `joypad_oe_per_cycle`, `famicom_audio_through_cart`,
  `dmc_unexpected_reload_bug`, and the power-on parameters: CPU/PPU alignment,
  APU parity, RAM fill, CPU registers). PAL and Dendy rows may exist as data
  with "not certified" on them. Each quirk field carries a comment naming its
  source and tier.
- **One master-clock timeline.** The board advances the PPU and APU inside the
  CPU's bus callbacks (3 dots and 1 CPU cycle each), never adding `step()`'s
  count on top; DMA runs inside `read_byte`; the cartridge receives every
  CPU and PPU event in time order with its master-tick time.
- **The cartridge connector protocol** of [cartridge.md](cartridge.md), settled
  in milestone 1 and changed only with a reason recorded there; the import
  boundary enforced by a test. Board identification by nes20db (read the pinned
  7z at runtime; never commit it), MAME's `nes.xml` as the secondary source
  (read at runtime from `/usr/share/games/mame/hash/`), with the override order
  and disagreement log described there.
- **Output**: frames as rows of 9-bit values (6-bit palette index + 3 emphasis
  bits); palette to RGB in the frontend (default `2C02G_U_wiki.pal`, computed by
  pally from measured voltages); audio as `take_samples()` floats, mixed at CPU
  rate with blargg's formula, box-filtered to the host rate, then a labelled
  "fitted" analogue stage per console.
- **Tooling at the family bar**: `state.py` (save/restore the whole machine,
  including the cartridge), a debugger reusing 6502-python's `DebugSession`
  with board watchpoints (PPU registers, VRAM, OAM, APU, mapper registers), a
  JSONL trace in 6502-python's schema plus bus events with master-tick times,
  `py.typed`, `python -m famicom_python ROM --frames N --png out.png --wav out.wav`,
  and a test-ROM harness that reads blargg's `$6000` protocol, the old `$F8`
  protocol, AccuracyCoin's `$0400–$04FF`, and nametable text for the
  screen-only ROMs.

### Milestones, each with its acceptance test, in oracle-tier order

1. **The CPU on the board: NROM, the bus, open bus, controllers, the
   connector.** Memory map, mirrors, open-bus latch, $4016/$4017 with both
   joypad clocking modes, power/reset, the cartridge protocol with mapper 0, the
   loader and nes20db. PPU and APU may be register stubs that keep time.
   **Acceptance**: nestest in automation mode matches `nestest.log` on all
   8,991 lines in PC, A, X, Y, P (masked $CF), SP and CYC (stating the
   power-on values used for lines 1–2), and its `$02`/`$03` codes are 0;
   blargg `instr_test-v5` (all_instrs), `instr_timing`, `cpu_timing_test6`,
   `branch_timing_tests`, `instr_misc`, `cpu_dummy_reads`, `cpu_dummy_writes_ppumem`,
   `cpu_exec_space_ppuio` pass under PyPy, with instruction counts and wall time
   recorded. Needs core PR 1.
2. **The PPU, dot by dot.** Registers, v/t/x/w, the fetch schedule (every
   access on the connector), sprite evaluation with the overflow bug, sprite-0
   hit, frame events, the $2002 and NMI races, the odd-frame skip, power-up
   write ignore, the I/O latch with decay (C1), palette RAM. **Acceptance**:
   `ppu_vbl_nmi` 10/10 in the chosen alignment, `vbl_nmi_timing` 7/7,
   `sprite_hit_tests_2005.10.05` 11/11, `sprite_overflow_tests` 5/5,
   `blargg_ppu_tests_2005.09.15b` (except the console-specific
   `power_up_palette`), `ppu_open_bus`, `ppu_read_buffer`, `oam_read`, and
   `oam_stress` in the alignment where hardware passes it. Then settle open item
   1 of undocumented-behavior.md on PPUSim (build it from the pinned breaknes; a
   pin-level comparison of bus addresses, ALE/RD and /INT for the same register
   writes), first showing PPUSim reproduces `ppu_vbl_nmi`'s expected values; if
   it does not, record that and decide C12/C13/C15 from the tests and Mesen2
   instead. Frames of the 240p Test Suite and a handful of homebrew compared
   with Mesen2 as a detector.
3. **The APU, DMA and interrupts together.** Five channels, frame counter,
   $4015, DMC with DMA, OAM DMA, the re-read side effects and the address
   composition quirk, the mixer. **Acceptance**: `apu_test` 8/8, `apu_reset`
   6/6 (the harness presses reset on `$81`), `blargg_apu_2005.07.30` 11/11,
   `cpu_interrupts_v2` 5/5 (needs core PRs 2 and 3), `dmc_dma_during_read4`
   and `sprdma_and_dmc_dma` with the CRCs valid for the chosen alignment,
   `read_joy3`. Audio: the sample stream of `apu_mixer` and `volume_tests`
   compared with Mesen2's (detector); APUSim's digital channel outputs compared
   per cycle on register dumps, once APUSim is shown to pass `apu_test` (open
   item 2), else recorded as not usable.
4. **AccuracyCoin.** Run all 144 tests at a pinned SHA in the chosen machine and
   alignment; record the score and, for every failure, its cause (board bug,
   alignment, revision success code, or a hardware disagreement with its
   source). Fix board bugs; a failure that disagrees with a higher tier is
   documented, not fixed.
5. **The big six mappers: 0, 1, 2, 3, 4, 7** (83 % of licensed dumps), with
   submappers (bus conflicts 2.x/3.x/7.x, 1.5, 4.0/4.1/4.3/4.4) and 155.
   **Acceptance**: Holy Mapperel 0.02 reports 0000 on every build for these
   mappers; `mmc3_test_2` passes 1–4 on both behaviours, 5 on 4.0 and 6 on 4.4;
   `mmc3_irq_tests` and `mmc3_test` (6-MMC6 noted against C18); rainwarrior's
   2/3/7/34 tests show the forum's expected values; `mmc1atest` and `serom`
   behave as documented. A claims table (`docs/claims.md`) lists per mapper which
   judge passed.
6. **Lockstep against Mesen2 (detector).** Mesen2's trace (instruction + PPU
   scanline and dot) against the board's on at least five games for at least 60
   seconds each, CPU state identical, N stated; the first divergence diagnosed to
   a source before a run is extended. MAME's trace is the secondary detector
   for instruction-level CPU questions only (its PPU and DMA are not exact:
   mame-oracle.md).
7. **Compatibility sweep (detector).** Every licensed No-Intro dump whose mapper
   is implemented, in place from `/data/emu/source/...` (never copied), for N
   seconds, frame compared with Mesen2's at the same frame; publish the table of
   divergences with causes. Then extend mappers in coverage order (206, 5, 19,
   18, 23, 16, 87, 69, 66, 210, 25, 185, 9, …) to 95 % of licensed dumps
   (26 mappers), each with its judge or, where none exists
   ([cartridge.md](cartridge.md)), a stated detector-only claim.
8. **Frontend and Famicom specifics.** pygame-ce window on PyPy, the Famicom
   microphone and expansion-port pads, the Famicom audio path, VRC6, N163 and
   MMC5 audio with the measured mix levels; mapper 30 for homebrew.

Do not skip a rung. The early ones make the later ones cheap to diagnose.

Later, not in this brief: PAL and Dendy certification, the Famicom Disk System,
the Vs. System and PlayChoice-10 (the latter adds a Z80: z80-python), the YM2413
and AY-3-8910 cores, extracting the APU/PPU, Rust and `-fast` forks.

## Constraints

- **Oracle tiers are not negotiable.** Mesen2, MAME and every other emulator
  are detectors; die-level models are judges only for circuits checked against
  hardware-corrected tests. A disagreement with a detector is a question for a
  higher tier.
- **Never commit ROMs, test ROMs, traces, fetched documents or databases.**
  `reference/`, `tests/test_roms/`, `tests/mame_traces/` are ignored.
  `nes-test-roms` and nes20db carry no licence. Commercial cartridges are read
  in place from `/data/emu/source/myrient.erista.me/files/No-Intro/...` or
  `/data/emu/roms/nes`; never hand-fix a romset.
- **Never copy GPL code**: Mesen2/MesenCE (GPL-3), puNES, Nestopia, FCEUX
  (GPL-2), MAME's `nes_apu.cpp` (GPL-2+). Read, cite by file and line, write
  our own. The Breaks/Breaknes material is CC0 and AccuracyCoin MIT, but cite
  them anyway.
- **Pins in every claim**: 6502-python revision, test ROM SHA-256,
  AccuracyCoin SHA, Mesen2/MAME versions, alignment, Python versions, wall time,
  instruction and frame counts. A gate that cannot fail proves nothing: seed a
  fault and show it fails.
- **CI minimal** (private Actions minutes cost money): PyPy only, on pushes to
  `main` and on pull requests, `concurrency` cancel, a job timeout; the test-ROM
  milestones fetch their pinned ROMs; anything heavy runs by hand.
- **The machine is shared**: `nice`, at most 16 parallel processes, check
  `uptime` before long runs.
- **Do not touch other directories under `/data/emu`.** Core changes go as PRs
  on the core. Commit in reviewable units with `git -c user.name=alewman -c
  user.email=alewman@gmail.com commit` and the attribution lines the session's
  system reminder gives. Do not push or create the GitHub repository until the
  user asks; it will be private.

## Size and speed, honestly

- **Code**: the PPU is the bulk (registers, fetch schedule, evaluation, output,
  races): 2,000–3,000 lines. The APU about 1,000; board, DMA and I/O about
  1,000; the cartridge package grows with each mapper (the big six about 800,
  MMC5 alone about 600); tooling about as much again.
- **Speed**: the CPU runs 1.79 M cycles/s, about 0.6 M instructions/s;
  6502-python measured 2.2 M instr/s on CPython and 45 M on PyPy, so the CPU is
  not the problem. **The PPU is**: 5.37 M dots/s, each a Python step plus a
  connector call on fetch dots (about 5.4 M calls/s). Full speed on CPython is
  not expected and is not a milestone; record frames per second on CPython and
  PyPy at every milestone. Keep the per-dot path simple and measurable.

## What done looks like

`README.md` states which milestones pass, with counts and pins;
`docs/validation.md` turns from "the oracles found" into "the certification
record"; `docs/claims.md` says per mapper and per subsystem what is strong,
provisional or undecidable here; the 6502-python PRs are merged and pinned;
the project has a manifest in `/data/emu/emulator-lineage/projects/` with its
`[[depends]]` on 6502-python.

Before starting, tell the user in a few sentences how you read this brief and
what you will do first.
