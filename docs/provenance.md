# Provenance: how this emulator came to know what it knows

An emulator is a pile of claims about a machine. This file says where the claims came from,
which sources are really separate witnesses, and how they are weighed, so that a reader can
tell a measurement from a repeated rumour. [validation.md](validation.md) has the tiers
and every result; this is the reasoning behind them.

## The rule

**hardware-captured > hardware-corrected > die-derived > specification > emulator-derived.**
A lower tier is a detector: it finds where to look, and never decides. Two emulators
agreeing is a vote, not a measurement. A game's own code counts as evidence, because it ran
on the real board, but it shows what that game needs, not everything the board does.

## Who is independent of whom

Agreement only adds weight if the witnesses did not copy each other.

| Source | What it rests on | Shares ancestry with |
| --- | --- | --- |
| AccuracyCoin | answers checked on hardware by its author | TriCNES, same author |
| blargg's and others' test ROMs | checked on hardware, unevenly | each other's folklore, less so |
| perfect6502, Visual 2C02 | netlists traced from die photographs | nothing here |
| PPUSim, APUSim (Breaknes) | the Breaks project's reverse-engineered schematics | a separate tracing from Visual 2C02 |
| NESdev wiki | hardware work, but also, as its pages sometimes say, emulator source | FCEUX, Nestopia, Mesen, sometimes each other |
| Mesen2, MesenCE | one code base, the second a continuation | count as **one** witness |
| MAME | its own code, with some boards from the same folklore | |
| mame_nes | MAME with its PPU and timing reworked (81 to 147 on AccuracyCoin); how, we have not read | MAME's cart code, count with MAME |
| nes20db | dumps and hardware inspection | the header data of every set |

Three consequences:

- **Mesen2 and MesenCE are one family.** When they agree that is one vote. MesenCE matching where Mesen2
  did not does show Mesen2 was wrong there, because a project fixed itself.
- **MAME and mame_nes are one family on mappers.** On the PPU, mame_nes's work is not ours, but
  it may rest on the same public sources, AccuracyCoin above all, so a shared pass is
  less independent than it looks.
- **The wiki is not independent of the emulators.** A page and an emulator agreeing may be one fact
  twice: pages that say they came from FCEUX's source are noted in the docstrings.

## Circular checks

A check cannot support the thing it was the source of. Mappers 413, 418, 549, 555 and 557 were written from
MAME's notes, so mame_nes matching them says the notes were followed, not that they are right. The
registry marks those rows. The same holds for the few places the board took a value from Mesen2
(its 50,000 cycles of FDS drive start, C39, measured from it closed-box), which a Mesen
comparison cannot then confirm.

Mappers 170, 216 and 244 were read from their games first and compared with MAME after,
which is why those count as two witnesses. Keep that order when it is possible.

## Working rules

1. Say what you expect before looking, and write down when it was wrong.
2. Never tune to a detector against a higher tier.
3. A majority of emulators is not a judge: see "Tatakai no Banka", where a judge is still wanted.
4. When two families agree against the board, look harder; it is usually the board.
5. When they disagree with each other, neither is evidence; find a higher tier or say it is open.
6. Record the source of each fact where the fact is: in the docstring, and in
   undocumented-behavior.md if sources conflict. An open question stays open.
7. Passing by eye is a weak result. 396.3 and 374 "reached their titles" with real bugs in them.
8. Results are checked by something that did not write them: an independent review of 37 classes
   found five real bugs after the sweeps and tests had passed.
9. Never copy GPL code. Mesen2 and MesenCE are run as binaries; mame_nes too, its licence
   being unclear. MAME's own NES cart files are BSD-3 and may be read. Four docstrings
   (`discrete.py`, `mmc5.py`, `namco.py`, `bandai.py`) once cited Mesen2 source paths; on
   2026-11-14 those facts and four more were re-established from the wiki, MAME's BSD-3
   files, the games' own code and closed-box runs, and the citations replaced ("Licence
   provenance" below, "Re-established").

## How it came together

The order mattered more than any single step: the CPU from 6502-python against SingleStepTests and nestest;
the PPU against PPUSim, which itself needed fixing (emu-russia/breaknes#529, and #535-#538
open); APU, DMA and interrupts against blargg and perfect6502; AccuracyCoin taken from 116 to 146 and
then 147; mappers through the sweeps, where most bugs were ours, then reading the games themselves
when the documents ran out; MesenCE and mame_nes as further detectors, the second one
finding bugs the first two could not, on boards they refuse.

Each step found errors in the one before, and in the references. That is the point of keeping several.

## Licence provenance (audit 2026-11-13)

The sections above are about how much to believe each fact. This one is about whether the
code may carry the MIT licence: where each part's behaviour came from, that source's
licence, and a verdict. **clean**: own work from facts or permissive sources, cited.
**cite**: clean, but a source must be named or a notice kept. **rewrite**: rests on
something we may not take. **unclear**: what would settle it is named. The standard is the
family charter's ("Licences and provenance"): nothing copied or transcribed from GPL or
LGPL code, facts are not code, closed-box runs are allowed, permissive sources keep their
notice, furrtek's work is excluded.

The audit read only this repository: comments, docs, commit messages, `scripts/pinned_*.json`
and the LICENSE files of the reference checkouts. No GPL or LGPL source was opened. It
ran `pcengine-python/scripts/provenance_check.py --repo src --reference reference/src/<X>
--licences scripts/pinned_repos.json` for X = breaknes, Mesen2, MesenCE, fceux, nestopia,
puNES, mame, tetanes, nintendulator (reading GPL trees was this project's documented
practice, `handoff-brief.md` "Constraints"). Its hits are the hardware's published tables
(length counter, noise and DMC periods, frame-counter steps: on the wiki, and decoded from
the die's masks by `scripts/apu_period_roms.py`), lists of mapper numbers, register
addresses, the Rec. 601 luma weights (`peripherals.luminance`), a wiki quote in `vs.py`,
and `WAIXING_GAL`, which `waixing.py` cites to MAME's BSD-3 `vrc_clones.cpp`. No code
shape and no table matched a GPL file beyond those facts.

**The earlier rule.** Until this audit the project's rule was "Read, cite by file and line,
write our own" for GPL emulators (`handoff-brief.md`), and `reference/src/` holds checkouts
of Mesen2, MesenCE, FCEUX, Nestopia and puNES. The charter now says GPL source is not
opened while writing the code it would inform. The record shows Mesen2's source was read:
four docstrings name its files (below, not two as working rule 9 says), and
`docs/timing.md` (`NesPpu.cpp` 946-954, `ApuFrameCounter.h` l.19-22) and
`docs/undocumented-behavior.md` C29 (`NesCpu.h` `BranchRelative`) compare with it. In each
of those three the board's answer came from elsewhere (blargg's tests, the wiki,
perfect6502); Mesen2 was the thing compared.

### Verdicts

| Part | Behaviour from | Licence of the source | Verdict |
| --- | --- | --- | --- |
| `ppu.py` | NESdev wiki, blargg's and others' test ROMs, PPUSim (Breaknes), BreakingNESWiki, Visual 2C02 run as a judge | wiki: facts; Breaknes and Breaks: CC0-1.0; Visual 2C02: simulator MIT (Silverman), netlist by Quietust with no stated licence, run locally only | clean |
| `apu.py`, `mmc5_sound.py` tables | APU wiki pages, Brad Taylor's and blargg's documents, BreakingNESWiki's die masks | facts; CC0 | clean |
| `video.py` | pally's palettes from lidnariq's measured voltages (fetched at run time, never committed); `RGB_DAC` from PPU_palettes.wiki (dumped chips) | MIT-0; facts | clean |
| `board.py`, `machine.py`, `system.py`, `joypad.py`, `state.py`, `testrom.py`, `frontend.py`, `dual.py`, `fds_auto.py` | own work from the wiki and test ROMs | | clean, except the MAME items in the `cite` row |
| Mapper modules (`cartridge/`) | NESdev wiki pages, Disch's notes, the games' own code, nes20db | facts | clean, except the rows below |
| Wiki pages that say they came from emulator source: mappers 14 (Nestopia), 27 (FCEUX r2947), 40 (FCEUX, Nestopia), 42 (FCEUX), 46, 71, 121, 137-141 (FCEU-mm), 156, 212, 219, 254 (MesenCE), 260, 304, 306, 513, 535 | the wiki's prose: register maps, masks, one number (535's 7560) | facts relayed by the wiki, not hardware; already cited in each docstring | clean (facts, not code; the weaker tier is already said) |
| MAME's BSD-3 files: `vs.py`, `dual.py`, `machine.py` (`vsnes.cpp`, `ppu2c0x.cpp`'s $1B), `playchoice.py`, `supervisor.py` (`playch10.cpp`: the palette weights, BIOS SHA-1s; `rp5h01.cpp`), `peripherals.py` (`suborkey.cpp` and `SUBOR_MATRIX`, `turbofile.cpp`, `konamibag.cpp`), `namco.py`, mappers from `vrc_clones.cpp` (`WAIXING_GAL`), `mmc3_clones.cpp`, `multigame.cpp`, `cne.cpp`, `bootleg.cpp`, `kaiser.cpp`, `rcm.cpp`, `batlab.cpp`, `event.cpp`, and mappers 413, 418, 549, 555, 557 | MAME's NES driver and cartridge files | BSD-3-Clause; holders per file: Fabio Priuli; kmg; Ernesto Corvi, Brad Oliver; Nicola Salmoria; Pierpaolo Prazzoli | **cite**: tables and structures were taken (keyboard matrix, palette weights, SHA-1s, GAL table), so keep MAME's BSD-3 notice with the holders' names (a NOTICE file, or one line beside each) |
| Facts once read from Mesen2's source: `discrete.py` (185's latch powers on enabled), `mmc5.py` (ExRAM writes outside rendering store 0), `namco.py` (the 163's counter counts only while enabled), `bandai.py` (test, then decrement); and choices probably read there: `mmc3_clones.py` `GA23C` (power-on registers), `Latched165` (the latch ranges), `kaiser.py` `TonyI43` (the file layout), `cartridge/fds.py` (50,000 cycles to drive ready) | re-established 2026-11-14 from the wiki, MAME's BSD-3 files (read for facts), the games' own code, and Mesen2 2.1.1 run closed-box (`scripts/provenance_probes.py`); "Re-established" below | facts; BSD-3; closed box | **clean**: no behaviour changed; citations replaced, each tagged with its evidence |
| `PROTECTION_208` (`mmc3_clones.py`) | recovered closed-box from Mesen2 2.1.1 (all 256 indices, data $00 and $FF: 512 answers), identical to the wiki's table; five entries confirmed by the game's own jumps | closed-box measurement, allowed by Aubrey's ruling of 2026-11-13; no hardware description exists | **clean** (OBSERVED, marked so in the code) |
| `vrc5.py:15` `PAGES` | the wiki's pageTable, "which it says FCEUX replicates from the hardware" | facts if the wiki's claim of hardware origin holds | **unclear** (likely clean): settled by the page's prose naming the hardware source (the middle rule) |
| `mmc3.py:22` the A12 filter ("three falling edges of M2"), also `docs/cartridge.md:136`, `docs/claims.md:79` | MMC3.wiki, "from Furrtek's MMC3C schematic"; the schematic pinned in `scripts/pinned_files.json` (commit `037726a`) | furrtek's VGChips repository; the pin's own note names Sean Gonsalves (2020) as the schematic's drawer | **rewrite** (re-source): furrtek's work is excluded. Drop the pin, and re-establish the filter from test ROMs or other research, or get Aubrey's ruling if the schematic is not furrtek's own work |
| VRC7 sound glue (`konami.py`, `state.py`) | the restarted ym2413-python's API; 72 clocks per sample (Yamaha); rainwarrior's `db_vrc7` | the restarted core says it is written from documents (its `docs/restart.md`) | clean (board side). The dependency is unpinned (a local install) |
| Sunsoft 5B glue (`sunsoft.py`) | ay8910-python's API; rainwarrior's `db_5b`; Sunsoft_5B_audio.wiki | | clean (board side). The pin, ay8910-python `5abe2df`, is older than that core's own audit (`20b0fe9`, "facts read from the GPL die model's source; four items to re-derive"): repin when the core is settled |
| `scripts/ppusim/`, `scripts/apusim/` shims, `build_ppusim.py`, `build_apusim.py` | Breaknes, compiled and run | CC0-1.0 | clean |
| `scripts/perfect6502_*.c` | perfect6502, linked and run | MIT (Steil, Silverman, Silverman) | clean |
| `scripts/visual2c02/` | Visual 2C02's files, loaded unchanged from `reference/` (not vendored) | simulator MIT; netlist licence unstated | clean |
| `scripts/mame_*.py`, `scripts/mame_nes_colours.json` | MAME and mame_nes run as programs; the colours measured from mame_nes's output | closed box | clean |
| `scripts/mesen_*.py`, `scripts/mesen_blargg.lua` | Mesen2/MesenCE's library driven through ctypes; `NesConfig` offsets measured with `offsetof()` against its header; `mesen_run.py` "mirrors UI/Utilities/TestRunner.cs" (its call sequence) | the program is GPL-3.0; these are our files driving it | clean as tools (charter item 6); not part of the emulator |
| `scripts/mesen2-detector-fixes.patch` | a patch to Mesen2's source | GPL-3.0 (a derivative of Mesen2) | **cite**: say in the file or beside it that it is GPL-3.0, as a tool's patch; it carries Mesen2's lines as context |
| `scripts/pinned_repos.json` notes | "read and cite only" (Mesen2), "read, run as referee, cite" (Nuked-OPLL, YM2203-LLE), Nuked-OPLL line numbers | | **cite**: change the notes to "closed box only" so the next reader does not take them as permission |
| `tests/ppusim_goldens.json.gz`, `tests/visual2c02_goldens.json.gz` | PPUSim's and Visual 2C02's outputs | CC0; MIT simulator | clean |

Counts (rows of the table): clean 16, cite 3, unclear 1, rewrite 1 (2026-11-14: the two
Mesen2/FCEUX rows settled, below).

### Re-established (wave 2, item 3, 2026-11-14)

Done by an agent that opened no GPL source (Mesen2's, MesenCE's, FCEUX's, Nestopia's) and
did not read the flagged code's history beyond its docstrings. Mesen2 2.1.1 (the hand-built
MesenCore.so of `scripts/mesen_run.py`) was run as a measuring instrument:
`scripts/provenance_probes.py` builds one small probe ROM per behaviour, written from the
wiki's register descriptions, runs it on the board and on Mesen2, and prints both answers.
All eight probes give the board's answers byte for byte except the FCG's cycle (below). A
Mesen2 answer is a detector's, not hardware's; each docstring says which tier it rests on.

| Item | Verdict | Evidence | Tag |
| --- | --- | --- | --- |
| 185's latch powers on enabled (`discrete.py` `CNROMProtected`) | holds, as a choice no game can see | the wiki gives no power-on state; all 11 licensed dumps draw the same 900 frames powered on enabled or disabled; Mesen2 powers on enabled (probe `185-power-on`) | OBSERVED closed-box; game A/B |
| MMC5 ExRAM writes outside rendering in modes 0/1 store 0 (`mmc5.py`) | holds within the wiki's range | MMC5.wiki $5104 note 3: "may be ignored or cause a corruption at that memory address"; MAME's BSD-3 `mmc5.cpp` writes 0; Mesen2 stores 0 (probe `mmc5-exram-blanking`). Which corruption the chip makes is unmeasured | DOC for the range; OBSERVED (two emulators) for 0 |
| The 163's counter counts only while enabled (`namco.py`) | holds, emulator tier | the wiki is silent; MAME's BSD-3 `namcot.cpp` counts only under its enable; Mesen2 holds the count while disabled (probe `n163-counter-disabled`). No hardware test | OBSERVED (two emulators) |
| The FCG/LZ93D50 counter tests, then decrements (`bandai.py`) | holds | INES_Mapper_016.wiki: an IRQ "when it holds a value of zero", and enabling it at zero gives one "immediately"; Mesen2 gives the immediate IRQ (probe `fcg-test-then-decrement`) | DOC. **Open**: Mesen2 asserts /IRQ one cycle sooner after counts of $100-$108; MAME's `bandai.cpp` decrements first. No hardware evidence for the cycle |
| Mapper 45: CHR registers 0, 2, 4, 5, 6, 7 at power-on; outer registers 0, 0, $0F, 0 at power-on and reset (`mmc3_clones.py` `GA23C`) | holds | MAME's BSD-3 `mmc3.cpp` `mmc3_common_initialize` (the same CHR values, for carts "that don't init banks properly") and `nes_bmc_hik8_device::pcb_reset` (the same masks); the wiki's "$6001 resets the outer bank registers as a soft reset would"; the three CHR-RAM dumps draw differently with registers of 0, two menus with a CHR-AND of 0; Mesen2 the same at power-on and after a reset (probe `45-power-on`) | OBSERVED closed-box; MAME (BSD-3); game A/B |
| Mapper 165's latch ranges, $xFD0-$xFD7 (0) and $xFE8-$xFEF (1) (`mmc3_clones.py` `Latched165`) | see the docstring | Mesen2 has the same ranges (probe `165-latch-ranges`, a 64 x 64 matrix per half); the games read $1FD0 and $1FE0 through $2007, as Disch's notes say | OBSERVED closed-box; the games' reads |
| Mapper 43's file layout (`kaiser.py` `TonyI43`) | holds | INES_Mapper_043.wiki now gives it: the two 32 KiB chips, the 2 KiB chip four times, the 8 KiB chip, 80 KiB | DOC |
| FDS drive ready 50,000 CPU cycles after the scan starts (`fds.py`) | holds as a detector's figure; unmeasured on hardware | FDS_Registers.wiki: "TODO: Ready flag behavior"; Mesen2 booting *Zelda no Densetsu* (Japan): the BIOS first reads ready 50,043 cycles after its scan-starting $4025 write (the board 49,962) (`provenance_probes.py --fds-ready`) | OBSERVED closed-box |
| `PROTECTION_208` (`mmc3_clones.py`) | holds | no hardware description of the chip exists; recovered closed-box from Mesen2, all 256 entries and their XOR (probe `208-protection`), identical to the table the board had; *Kuai Da Chuanshuo - Street Fighter IV* writes pre-XORed values at indices $09, $0D, $62, $8E and $B3 that come out as JMP $C134, $E40D, $F415 and $E32B, each decoding as its code (`test_mapper_208_protection_gives_the_games_jumps`); a sixth index, $53, it reads back as data | OBSERVED closed-box (Aubrey's ruling, 2026-11-13); five entries confirmed by the game |

The same docstrings also lost two remarks that rested on nothing cited: `GA23C`'s "Mesen2
makes it too" (CHR-RAM unmasked), now left as the assumption the wiki does not settle.
The old citations stay in the public history (`git log -S CnromProtect`).

### History (the repository is public)

- No file has ever been deleted, and no commit holds Nuked-derived code. The VRC7 was
  added in `43e18b9` with its sound from the old ym2413-python (later pinned at `13df60c`,
  `a46882a`, `09c4852`): a dependency pin, not code in this tree. That core was withdrawn on
  2026-11-12 as a translation of GPL code and its repository made private. The sound was
  switched off in `4ef9d3d` (`origin/main` and `vrc7-sound-off` both point there) and back
  on, from the restarted core, in `19a4f49` (local `main`, 13 commits ahead of
  `origin/main`, unpushed). `pinned_repos.json`'s notes cite Nuked-OPLL by line
  (`opll.c:114`, 280-282 and others): its source was read while planning the VRC7, though
  nothing from it is in this repository.
- The Sunsoft 5B's sound (`68ea474`) and the PlayChoice-10 are local only.
- `scripts/mesen2-detector-fixes.patch` (GPL-3.0 context lines) has been public since
  `e636819`.
- The furrtek pin has been public since `037726a`; the PDF itself was never committed.
- Mesen2 source citations in docstrings and docs (above) are in the public history.

### Not done here

No SPDX headers yet (0 of 145 source files): owed, as across the family.
