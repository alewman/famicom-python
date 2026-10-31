# Mappers: where they stand

**Closed as an active effort on 2026-10-30.** 294 mappers are implemented.
That is feature complete, with the gaps listed below; it is not a claim that
each is verified. This file is the place to start if you want to reopen the
work: the [registry](#registry) is generated, the rest is written by hand.

| Set | Dumps on an implemented mapper | |
| --- | ---: | ---: |
| Main (`Nintendo Entertainment System (Headered)`) | 4,455 of 4,464 | 99.80 % |
| Aftermarket | 2,905 of 2,913 | 99.73 % |
| Private | 634 of 634 | 100 % |

Of the licensed dumps only the StudyBox BIOS (186) is left.

The final sweep, every dump in the four No-Intro sets against Mesen2: **8,221 of 8,807
identical**, 477 differ, 109 refused, no crash, no regression among the 1,312 dumps with
an earlier result. By evidence, of the 294: 19 mappers have a judge ROM, 200 match
Mesen2 on at least one dump, 13 differ on every dump it runs, 56 only by eye because
Mesen2 and MesenCE refuse them, and 6 have no dump, so unit tests only. MesenCE closes
52 of the differences. All 198 slow tests pass, and AccuracyCoin 147 of 147.

## How far to trust a row

The registry's **Evidence** column is the strongest thing that has passed,
in the order of [validation.md](validation.md)'s tiers, and "Described by"
is what the code's own docstrings cite.

- **judge ROM**: a test ROM that can fail it passed ([claims.md](claims.md)).
- **matches Mesen2**: at least one dump's frames 60, 300 and 600 are identical,
  within the sweep's one frame of slack. Mesen2 is a detector, not a judge: it
  has been wrong against die-level evidence and games (C54, C57), and these
  frames say nothing about a game's later levels. MesenCE, its successor, is the
  second detector: `MESEN_LIB` selects it, and it closes the single-pixel differences
  (upstream-findings.md).
- **differs, by eye**: every dump Mesen2 runs differs. Often it is Mesen2 that is
  blank: plain green is palette entry $09, the 2C02's power-on value, with
  rendering off, so it never got as far as drawing.
- **by eye (Mesen2 refuses)**: reaches a title or menu to the eye. None of these
  was played.
- **unit tests only**: no dump, or none swept; `tests/test_mappers*.py` state the
  model, and cannot fail it the way hardware could.

A game's own code counts as evidence: it is what ran on the real board. Where
a game overrules a page, or a page is silent, the entry is in
[undocumented-behavior.md](undocumented-behavior.md) (C47 onward), and the
registry names it. Docstrings say which source each fact came from.

## Sources

Fetched by `scripts/fetch_references.py` from `scripts/pinned_files.json`, with
hashes, into the gitignored `reference/`: read a file before relying on its
claims here, because none of it is committed.

- `reference/nesdev-wiki/`: the first stop. **Read the whole page.** The first
  pass wrote off 547 and 446 as undocumented; both pages are detailed.
- `reference/nesdev-forum/`: analyses of PALs and schematics the wiki links
  to. Read the raw post: a summary of one invented a contradiction here once.
- `reference/mame-nes/`: MAME's NES cartridge sources at a pinned commit, **BSD-3**,
  so they may be read. They have boards the wiki does not. Cited per class.
- **Never** read or copy FCEUX or Mesen2 source: GPL. Mesen2 is run as a binary
  only (`scripts/mesen_run.py`). Some docstrings cite FCEUX's behaviour as the
  wiki reports it; that is the wiki's statement.

Reading traps that have bitten: `A~` diagrams are address bits and `D~` data
bits; the wiki's "Horizontal (A10)" is arrangement naming, so it means vertical
mirroring; `BBBBBB..` fields may be bank numbers; `Banked.chr_offsets` start at
0, so a CHR-RAM board must map its 8 KiB itself.

## How to add a mapper with no description

This is how 170, 216, 222, 238, 244, 258, 42.2 and 530's details were found.

1. `scripts/rom_scan.py ROM`: the header, which banks hold vectors (the fixed bank
   must be there), and the registers the code touches.
2. Search `reference/mame-nes/` by game title, not only by mapper number.
3. `scripts/mapper_trial.py ROM --as N`: run it on its nearest relative. The
   writes show what it wants; `--hot` disassembles where it is stuck.
4. Read the code at the stuck point (`scripts/disasm6502.py`). Protection is checked
   by code that states the right answer (C68), tables in ROM may hold the
   whole mapper (C69), and decryption tells you when you are right (258).
5. Write the board, then a test in `tests/test_mappers_remaining.py` for the
   arithmetic, then sweep with a **fresh `--out`**: `compat_sweep.py` resumes from
   its output and silently skips what is already there.
6. Record where each fact came from in the docstring, a contradiction in
   undocumented-behavior.md, and rerun `scripts/mapper_registry.py`.

## What is not implemented

| Mapper | Dumps | What is known |
| ---: | --- | --- |
| 186 | StudyBox BIOS | a tape drive, which is a subsystem; nothing to run without tapes |
| 682 | *Super Tilt Bro.*, *Tactus* | Rainbow: Broke Studio's Wi-Fi mapper, documented outside the wiki; needs an ESP model |
| 256 | 5 OneBus multicarts | VT02+: a famiclone more than a mapper |
| 405 | 1 | UM6578 "enhanced" mode: a famiclone |
| 127 | *Double Dragon II* bootleg | the page names the game; `mapper_trial.py --as 4` stops early, registers around `$8000-$8003`, `$8030-$8053` |
| 169 | Yuxing VCD BIOS | hardware that plays VCDs |
| 559 | *Sangokushi II* (Subor) | no page found |
| 563 | *TMNT II* bootleg | no page found |
| 564 | NTDEC 22-in-1 | no page found |
| 576 | 100-in-1 | no page found |
| 585 | Super 72-in-1 | no page found |

Not modelled on boards that are implemented: audio on 266 (DAC), 284 and 594
(ADPCM), 451's MP3 controller, 517's ADC and 413's `$D000`; 400's LCD and LEDs;
555's RJ11; 446's FPGA boards no dump chooses; 399.1 does not run (C60).

## What differs and why

The licensed set against Mesen2, at the commit that closed this work: **2,573 of 2,662
identical**, 79 differ, 10 refused (446, 470, 547, 555). MesenCE closes 15 of the 79:
the single-pixel class and *Baseball Simulator*, so those were Mesen2's. The 64 left,
sorted against MesenCE by `scripts/sweep_triage.py`:

| Dumps | Cause | Standing |
| ---: | --- | --- |
| 39 | A register access while rendering | the board follows PPUSim (validation.md, milestones 2, 6, 7) |
| 6 | A rendering toggle mid-line (C12) | the board follows PPUSim |
| 7 | The MMC5's in-frame onset, one fetch apart on row 0 (C34) | open, no judge |
| 5 | A mid-line toggle, then an MMC3 IRQ on another line | the board follows PPUSim for the toggle |
| 2 | TC0690's IRQ delay (C48): *Flintstones*, *Jetsons* | open; both Mesens differ alike |
| 1 | An M2-counted IRQ one cycle apart (C33): *TMNT 2* | open, no judge |
| 1 | The render-start OAM copy (C32): *Tatakai no Banka* | open |
| 1 | *Bionic Commando* Mini Mix `[b]` | a bad dump |
| 2 | *International Cricket* (sprite-shaped blocks at frame 600), *KlashBall* (6 pixels) | undiagnosed; both stay in CPU lockstep with Mesen2 for 620 frames, so neither is a mapper or game-logic matter |

The differences on the unlicensed and homebrew sets are listed dump by dump in
`tests/sweep_failures.tsv`; they are mostly the same PPU classes on pirate dumps of the same
games. The largest groups are 4 (69 on MesenCE), 163 (50, an older model in both
Mesens, C54) and 268 (32). The ones that remain open are in
validation.md, "The remaining mappers": 314's Brazilian dumps, 242.3, *Drip*, *Racermate*,
*DBZ 5*, 165, 268, 91. Where Mesen2 and MesenCE are both blank and the board runs the game (27, 304,
513 on Mesen2 alone, 519, 313.3, 199, 195), nothing says the board is right but the game
itself.

## Registry

Generated: `NO_INTRO_DIR=... python scripts/mapper_registry.py --results
tests/mame_traces/sweep-final`. Do not edit by hand. The non-identical dumps are
in `tests/sweep_failures.tsv`, which is also the next quick-sweep list.

<!-- registry begin -->

| Mapper | Class | Module | Main | Aftermarket | Private | Identical / differs / refused | Described by | Evidence |
| ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| 0 | NROM | discrete | 438 | 636 | 71 | 1282 / 33 / 0 | wiki | judge ROM |
| 1 | MMC1 | mmc1 | 923 | 108 | 16 | 1056 / 37 / 0 | wiki | judge ROM |
| 2 | UxROM | discrete | 388 | 291 | 49 | 804 / 18 / 0 | wiki | judge ROM |
| 3 | CNROM | discrete | 236 | 81 | 5 | 341 / 9 / 0 | wiki | judge ROM |
| 4 | mmc3_for | mmc3 | 1037 | 240 | 60 | 1348 / 78 / 0 | wiki | judge ROM |
| 5 | MMC5 | mmc5 | 33 | 5 | 0 | 27 / 15 / 0 | wiki, forum | matches Mesen2 |
| 7 | AxROM | discrete | 77 | 14 | 1 | 93 / 3 / 0 | wiki | judge ROM |
| 9 | MMC2 | mmc2 | 10 | 0 | 0 | 10 / 0 / 0 | wiki, forum | judge ROM |
| 10 | MMC4 | mmc2 | 5 | 0 | 0 | 5 / 0 / 0 | wiki | judge ROM |
| 11 | ColorDreams | unlicensed | 64 | 4 | 2 | 68 / 5 / 0 | wiki | matches Mesen2 |
| 12 | SL5020B | mmc3_clones | 1 | 0 | 0 | 0 / 1 / 0 | wiki | differs, by eye |
| 13 | CPROM | discrete | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 14 | SL1632 | chinese | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 15 | K1029 | multicart | 3 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 16 | BandaiFCG | bandai | 17 | 1 | 0 | 18 / 0 / 0 | wiki | matches Mesen2 |
| 18 | SS88006 | jaleco | 20 | 1 | 0 | 21 / 0 / 0 | wiki | matches Mesen2 |
| 19 | Namco163 | namco | 32 | 0 | 0 | 32 / 0 / 0 | wiki | matches Mesen2 |
| 21 | VRC24 | konami | 3 | 0 | 0 | 3 / 0 / 0 | wiki | judge ROM |
| 22 | VRC24 | konami | 2 | 0 | 0 | 2 / 0 / 0 | wiki | judge ROM |
| 23 | VRC24 | konami | 25 | 0 | 0 | 25 / 0 / 0 | wiki | judge ROM |
| 24 | VRC6 | konami | 3 | 6 | 0 | 6 / 4 / 0 | wiki | matches Mesen2 |
| 25 | VRC24 | konami | 15 | 1 | 0 | 15 / 1 / 0 | wiki | judge ROM |
| 26 | VRC6 | konami | 2 | 4 | 0 | 9 / 0 / 0 | wiki | matches Mesen2 |
| 27 | MiHunChe27 | chinese | 3 | 0 | 0 | 0 / 3 / 0 | wiki | differs, by eye |
| 28 | Action53 | homebrew | 0 | 40 | 0 | 50 / 4 / 0 | wiki | judge ROM |
| 29 | SealieRET | homebrew | 0 | 3 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 30 | UNROM512 | discrete | 1 | 1045 | 316 | 1557 / 4 / 0 | wiki | matches Mesen2 |
| 31 | NSF31 | homebrew | 0 | 3 | 0 | 3 / 0 / 0 | wiki | judge ROM |
| 32 | G101 | irem | 7 | 0 | 0 | 7 / 0 / 0 | wiki | matches Mesen2 |
| 33 | TC0190 | taito | 11 | 0 | 0 | 11 / 0 / 0 | wiki | matches Mesen2 |
| 34 | mapper_34 | discrete | 7 | 27 | 17 | 74 / 0 / 0 | wiki | judge ROM |
| 35 | JYCompany | jycompany | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 36 | ProtectedLatch | txc | 6 | 0 | 0 | 6 / 0 / 0 | wiki | matches Mesen2 |
| 37 | MMC3Multicart | mmc3 | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 38 | BitCorp38 | unlicensed | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 40 | NTDEC2722 | kaiser | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 41 | Caltron41 | unlicensed | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 42 | Kaiser42 | kaiser | 5 | 0 | 0 | 3 / 2 / 0 | wiki, the game (C65) | matches Mesen2 |
| 43 | TonyI43 | kaiser | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 45 | GA23C | mmc3_clones | 6 | 7 | 0 | 15 / 0 / 0 | wiki | matches Mesen2 |
| 46 | RumbleStation46 | unlicensed | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 47 | MMC3Multicart | mmc3 | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 48 | TC0690 | taito | 7 | 0 | 0 | 5 / 2 / 0 | wiki | matches Mesen2 |
| 50 | N32Mapper50 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 52 | Outer52 | mmc3_clones | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 56 | KaiserSMB3 | kaiser | 1 | 0 | 0 | 0 / 1 / 0 | wiki | differs, by eye |
| 57 | GK57 | multicart | 3 | 0 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 58 | AddressLatch58 | multicart | 12 | 0 | 0 | 16 / 0 / 0 | wiki | matches Mesen2 |
| 59 | AddressLatch59 | multicart | 8 | 0 | 0 | 7 / 4 / 0 | wiki | matches Mesen2 |
| 60 | ResetMulticart60 | multicart | 4 | 1 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 61 | Latch61 | multicart | 0 | 1 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 62 | Super700 | multicart | 1 | 0 | 0 | 0 / 1 / 0 | wiki | differs, by eye |
| 63 | Powerful63 | multicart | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 64 | RAMBO1 | tengen | 10 | 0 | 0 | 2 / 8 / 0 | wiki | matches Mesen2 |
| 65 | H3001 | irem | 3 | 0 | 0 | 3 / 0 / 0 | wiki, forum | matches Mesen2 |
| 66 | GxROM | discrete | 18 | 11 | 6 | 36 / 0 / 0 | wiki | judge ROM |
| 67 | Sunsoft3 | sunsoft | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 68 | mapper_68 | sunsoft | 7 | 0 | 0 | 7 / 0 / 0 | ? | matches Mesen2 |
| 69 | FME7 | sunsoft | 19 | 2 | 0 | 21 / 1 / 0 | wiki | judge ROM |
| 70 | Bandai74161 | bandai | 4 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 71 | Camerica | unlicensed | 32 | 3 | 0 | 26 / 12 / 0 | wiki | matches Mesen2 |
| 72 | JF17 | jaleco | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 73 | VRC3 | konami | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 74 | MixedCHR | waixing | 4 | 1 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 75 | VRC1 | konami | 9 | 1 | 0 | 10 / 0 / 0 | wiki | matches Mesen2 |
| 76 | Namco3446 | namco | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 77 | LROG017 | irem | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 78 | JF16 | jaleco | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 79 | NINA03 | unlicensed | 59 | 0 | 1 | 58 / 2 / 0 | wiki | matches Mesen2 |
| 80 | X1005 | taito | 10 | 0 | 0 | 10 / 0 / 0 | wiki | matches Mesen2 |
| 81 | NTDEC81 | multicart | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 82 | X1017 | taito | 0 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 83 | Cony | cony | 10 | 0 | 0 | 10 / 0 / 0 | wiki | matches Mesen2 |
| 85 | VRC7 | konami | 5 | 0 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 86 | JF13 | jaleco | 8 | 0 | 0 | 9 / 0 / 0 | wiki | matches Mesen2 |
| 87 | J87 | discrete | 16 | 0 | 0 | 16 / 0 / 0 | wiki | matches Mesen2 |
| 88 | Namco3433 | namco | 5 | 0 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 89 | Sunsoft2 | sunsoft | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 90 | JYCompany | jycompany | 19 | 0 | 0 | 18 / 3 / 0 | wiki | matches Mesen2 |
| 91 | JY830623C | jycompany | 11 | 0 | 0 | 8 / 3 / 0 | wiki | matches Mesen2 |
| 92 | JF17 | jaleco | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 93 | Sunsoft2 | sunsoft | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 94 | UN1ROM | discrete | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 95 | Namco3425 | namco | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 96 | OekaKids | bandai | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 97 | TAMS1 | irem | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 103 | DokiDoki103 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 104 | Pegasus104 | unlicensed | 1 | 0 | 0 | 1 / 0 / 0 | wiki, the game | matches Mesen2 |
| 105 | NESEvent | mmc1 | 1 | 0 | 1 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 106 | SMB3Bootleg106 | kaiser | 1 | 0 | 0 | 0 / 1 / 0 | wiki | differs, by eye |
| 107 | MagicDragon107 | chinese | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 108 | FDSConversion108 | chinese | 5 | 1 | 0 | 6 / 0 / 0 | wiki | matches Mesen2 |
| 111 | GTROM | homebrew | 0 | 11 | 64 | 79 / 0 / 0 | wiki | matches Mesen2 |
| 112 | Asder112 | chinese | 7 | 0 | 0 | 5 / 2 / 0 | wiki | matches Mesen2 |
| 113 | NINA03 | unlicensed | 4 | 4 | 0 | 8 / 0 / 0 | wiki | matches Mesen2 |
| 114 | SuperGame | mmc3_clones | 6 | 0 | 0 | 5 / 1 / 0 | wiki | matches Mesen2 |
| 115 | Kasheng | mmc3 | 9 | 0 | 0 | 9 / 0 / 0 | wiki | matches Mesen2 |
| 116 | Huang116 | chinese | 6 | 0 | 0 | 4 / 2 / 0 | wiki | matches Mesen2 |
| 117 | FutureMedia117 | chinese | 2 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 118 | TxSROM | mmc3 | 12 | 0 | 0 | 12 / 0 / 0 | wiki | judge ROM |
| 119 | TQROM | mmc3 | 5 | 0 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 120 | LH15 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 121 | A9711 | mmc3_clones | 10 | 0 | 0 | 10 / 0 / 0 | wiki | matches Mesen2 |
| 122 | JY043 | multicart | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 123 | SuperGame | mmc3_clones | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 125 | Whirlwind125 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 126 | ING003C | mmc3_clones | 0 | 0 | 0 | 0 / 0 / 0 | wiki | unit tests only |
| 127 | **not implemented** |  | 1 | 0 | 0 |  |  |  |
| 132 | ProtectedLatch | txc | 10 | 0 | 0 | 6 / 4 / 0 | wiki | matches Mesen2 |
| 133 | SachenLatch | sachen | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 134 | T4A54A | mmc3_clones | 2 | 1 | 0 | 1 / 3 / 0 | wiki | matches Mesen2 |
| 136 | ProtectedLatch | txc | 4 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 137 | Sachen8259D | sachen | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 138 | Sachen8259 | sachen | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 139 | Sachen8259 | sachen | 4 | 0 | 0 | 3 / 1 / 0 | wiki | matches Mesen2 |
| 140 | JF11 | jaleco | 4 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 141 | Sachen8259 | sachen | 15 | 0 | 0 | 15 / 0 / 0 | wiki | matches Mesen2 |
| 142 | KS7032 | kaiser | 4 | 1 | 0 | 6 / 0 / 0 | wiki | matches Mesen2 |
| 143 | Sachen143 | sachen | 2 | 0 | 0 | 1 / 1 / 0 | wiki | matches Mesen2 |
| 144 | DeathRace | unlicensed | 3 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 145 | SachenLatch | sachen | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 147 | ProtectedLatch | txc | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 148 | SachenLatch | sachen | 18 | 0 | 0 | 19 / 0 / 0 | wiki | matches Mesen2 |
| 149 | SachenLatch | sachen | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 150 | SachenLS374N | sachen | 20 | 0 | 0 | 19 / 1 / 0 | wiki | matches Mesen2 |
| 152 | Bandai74161 | bandai | 6 | 0 | 0 | 5 / 1 / 0 | wiki | matches Mesen2 |
| 153 | BandaiFCGRAM | bandai | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 154 | Namco3433 | namco | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 155 | MMC1A | mmc1 | 2 | 0 | 0 | 2 / 0 / 0 | wiki | judge ROM |
| 156 | Daou156 | chinese | 5 | 0 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 157 | Datach | bandai | 7 | 0 | 0 | 7 / 0 / 0 | wiki | matches Mesen2 |
| 158 | RAMBO1TLS | tengen | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 159 | BandaiX24C01 | bandai | 7 | 0 | 0 | 7 / 0 / 0 | wiki | matches Mesen2 |
| 162 | FS304 | nanjing | 0 | 10 | 0 | 7 / 3 / 0 | wiki | matches Mesen2 |
| 163 | FC001 | nanjing | 4 | 66 | 0 | 21 / 50 / 0 | wiki | matches Mesen2 |
| 164 | Dongda164 | nanjing | 5 | 0 | 0 | 4 / 1 / 0 | wiki | matches Mesen2 |
| 165 | Latched165 | mmc3_clones | 6 | 0 | 0 | 5 / 1 / 0 | wiki | matches Mesen2 |
| 167 | Subor167 | unlicensed | 1 | 0 | 0 | 0 / 1 / 0 | wiki | differs, by eye |
| 168 | Racermate | unlicensed | 6 | 0 | 0 | 0 / 6 / 0 | wiki | differs, by eye |
| 169 | **not implemented** |  | 2 | 0 | 0 |  |  |  |
| 170 | Fujiya170 | discrete | 1 | 0 | 0 | 1 / 0 / 0 | wiki, the game (C69) | matches Mesen2 |
| 172 | ProtectedLatch | txc | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 173 | ProtectedLatch | txc | 7 | 0 | 0 | 7 / 0 / 0 | wiki | matches Mesen2 |
| 176 | FK23C | waixing | 52 | 44 | 0 | 84 / 20 / 0 | wiki | matches Mesen2 |
| 177 | Hengge | chinese | 8 | 6 | 0 | 14 / 0 / 0 | wiki | matches Mesen2 |
| 178 | Education178 | chinese | 13 | 26 | 0 | 41 / 0 / 0 | wiki | matches Mesen2 |
| 180 | UNROM180 | discrete | 1 | 0 | 1 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 182 | SuperGame | mmc3_clones | 0 | 0 | 0 | 0 / 0 / 0 | wiki | unit tests only |
| 183 | ShuiGuan183 | konami | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 184 | Sunsoft1 | sunsoft | 8 | 0 | 0 | 8 / 0 / 0 | wiki | matches Mesen2 |
| 185 | CNROMProtected | discrete | 11 | 0 | 0 | 12 / 0 / 0 | wiki | matches Mesen2 |
| 186 | **not implemented** |  | 1 | 0 | 0 |  |  |  |
| 187 | SuperGame | mmc3_clones | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 188 | Karaoke | bandai | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 189 | PRG32Override | mmc3_clones | 11 | 0 | 0 | 11 / 0 / 0 | wiki | matches Mesen2 |
| 190 | Zemina190 | chinese | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 191 | MixedCHR | waixing | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 192 | MixedCHR | waixing | 3 | 1 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 193 | TC112 | chinese | 4 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 194 | MixedCHR | waixing | 0 | 4 | 0 | 6 / 0 / 0 | wiki | matches Mesen2 |
| 195 | MixedCHR | waixing | 2 | 6 | 0 | 5 / 3 / 0 | wiki | matches Mesen2 |
| 196 | MRCM196 | mmc3_clones | 12 | 0 | 0 | 10 / 11 / 0 | wiki | matches Mesen2 |
| 197 | Rewired197 | mmc3_clones | 5 | 0 | 0 | 4 / 1 / 0 | wiki | matches Mesen2 |
| 198 | Xiangfeng198 | waixing | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 199 | FS309 | waixing | 1 | 5 | 0 | 0 / 7 / 0 | wiki | differs, by eye |
| 205 | JC016 | mmc3_clones | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 206 | Namco108 | namco | 76 | 0 | 0 | 74 / 3 / 0 | wiki | matches Mesen2 |
| 207 | X1005 | taito | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 208 | Gouder208 | mmc3_clones | 2 | 0 | 0 | 1 / 1 / 0 | wiki | matches Mesen2 |
| 209 | JYCompany | jycompany | 4 | 0 | 0 | 3 / 1 / 0 | wiki | matches Mesen2 |
| 210 | Namco175 | namco | 15 | 0 | 0 | 14 / 1 / 0 | wiki | matches Mesen2 |
| 211 | JYCompany | jycompany | 3 | 0 | 0 | 2 / 1 / 0 | wiki | matches Mesen2 |
| 212 | AddressLatch212 | multicart | 5 | 0 | 0 | 6 / 0 / 0 | wiki | matches Mesen2 |
| 213 | AddressLatch58 | multicart | 0 | 0 | 0 | 0 / 0 / 0 | wiki | unit tests only |
| 215 | SuperGame | mmc3_clones | 14 | 0 | 0 | 13 / 1 / 0 | wiki | matches Mesen2 |
| 216 | RCM216 | unlicensed | 5 | 0 | 0 | 4 / 1 / 0 | wiki, forum, MAME, the game | matches Mesen2 |
| 218 | MagicFloor | homebrew | 0 | 2 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 219 | A9461 | mmc3_clones | 1 | 0 | 0 | 0 / 1 / 0 | wiki | differs, by eye |
| 221 | N625092 | multicart | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 222 | Ninja222 | konami | 3 | 0 | 0 | 3 / 0 / 0 | wiki, forum | matches Mesen2 |
| 224 | mindkids_224 | mmc3 | 4 | 37 | 0 | 40 / 1 / 0 | wiki | matches Mesen2 |
| 225 | AddressLatch225 | multicart | 5 | 0 | 0 | 7 / 0 / 0 | wiki | matches Mesen2 |
| 226 | Latch226 | multicart | 6 | 0 | 0 | 6 / 0 / 0 | wiki | matches Mesen2 |
| 227 | AddressLatch242 | multicart | 7 | 3 | 0 | 11 / 0 / 0 | wiki | matches Mesen2 |
| 228 | Action52 | unlicensed | 4 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 229 | Latch229 | multicart | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 232 | Camerica | unlicensed | 13 | 0 | 0 | 12 / 1 / 0 | wiki | matches Mesen2 |
| 234 | Maxi15 | multicart | 4 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 235 | GoldenGame235 | multicart | 4 | 0 | 0 | 0 / 4 / 0 | wiki | differs, by eye |
| 238 | ContraFighter238 | mmc3_clones | 1 | 0 | 0 | 1 / 0 / 0 | wiki, the game (C68) | matches Mesen2 |
| 240 | Latch240 | chinese | 3 | 2 | 0 | 5 / 0 / 0 | wiki | matches Mesen2 |
| 241 | Hengge | chinese | 10 | 10 | 2 | 18 / 5 / 0 | wiki | matches Mesen2 |
| 242 | AddressLatch242 | multicart | 12 | 0 | 0 | 8 / 7 / 0 | wiki | matches Mesen2 |
| 243 | SachenLS374N | sachen | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 244 | Decathlon244 | chinese | 1 | 0 | 0 | 1 / 0 / 0 | wiki, MAME, the game (C69) | matches Mesen2 |
| 245 | F003 | mmc3_clones | 2 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 246 | Fengshenbang246 | chinese | 2 | 0 | 0 | 0 / 3 / 0 | wiki | differs, by eye |
| 249 | T9552 | waixing | 3 | 0 | 0 | 7 / 0 / 0 | wiki | matches Mesen2 |
| 250 | Nitra250 | mmc3_clones | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 252 | WaixingVRC4 | waixing | 0 | 1 | 0 | 1 / 0 / 0 | wiki, MAME | matches Mesen2 |
| 253 | WaixingVRC4 | waixing | 4 | 2 | 0 | 1 / 5 / 0 | wiki, MAME | matches Mesen2 |
| 254 | XorRAM254 | mmc3_clones | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 255 | AddressLatch225 | multicart | 0 | 0 | 0 | 0 / 0 / 0 | wiki | unit tests only |
| 258 | Board158B | mmc3_clones | 2 | 0 | 0 | 2 / 2 / 0 | wiki, MAME | matches Mesen2 |
| 260 | HPxx260 | mmc3_clones | 0 | 1 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 262 | SachenShero | mmc3_clones | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 263 | Rex263 | mmc3_clones | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 264 | Cony | cony | 2 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 266 | CityFighter266 | konami | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 268 | AA6023 | mmc3 | 25 | 67 | 7 | 107 / 34 / 0 | wiki | matches Mesen2 |
| 272 | KidDracula272 | konami | 1 | 0 | 0 | 0 / 0 / 1 | wiki, forum | by eye (Mesen2 refuses) |
| 284 | DripGame | homebrew | 0 | 4 | 0 | 0 / 7 / 0 | wiki | differs, by eye |
| 285 | A65AS | multicart | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 286 | BS5 | multicart | 0 | 10 | 0 | 20 / 0 / 0 | wiki | matches Mesen2 |
| 289 | Champion289 | multicart | 1 | 2 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 290 | Asder290 | multicart | 1 | 0 | 0 | 2 / 0 / 0 | wiki | matches Mesen2 |
| 292 | BMW8544 | mmc3_clones | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 298 | TF1201 | konami | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 299 | Latch299 | multicart | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 301 | AddressLatch242 | multicart | 1 | 0 | 0 | 0 / 0 / 0 | wiki | unit tests only |
| 302 | KS7057 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 303 | Kaiser303 | kaiser | 3 | 0 | 0 | 3 / 0 / 0 | wiki | matches Mesen2 |
| 304 | Board09034A | kaiser | 3 | 0 | 0 | 1 / 2 / 0 | wiki | matches Mesen2 |
| 305 | Kaiser305 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 306 | Kaiser306 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 307 | Kaiser307 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 308 | TH2131 | konami | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 309 | Whirlwind309 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 312 | KS7013B | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 313 | ResetTxROM | mmc3_clones | 2 | 0 | 0 | 1 / 1 / 0 | wiki | matches Mesen2 |
| 314 | NoRepeat314 | multicart | 1 | 2 | 0 | 1 / 2 / 0 | wiki, MAME (C61) | matches Mesen2 |
| 319 | HP898F | multicart | 2 | 15 | 0 | 8 / 15 / 0 | wiki | matches Mesen2 |
| 326 | Contra326 | kaiser | 1 | 0 | 0 | 0 / 0 / 1 | wiki, forum | by eye (Mesen2 refuses) |
| 328 | RT01 | chinese | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 330 | Sangokushi330 | chinese | 1 | 0 | 0 | 0 / 0 / 1 | wiki, forum | by eye (Mesen2 refuses) |
| 332 | WS332 | multicart | 5 | 0 | 0 | 6 / 0 / 0 | wiki | matches Mesen2 |
| 334 | Multicart334 | mmc3_clones | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 346 | KS7012 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 347 | KS7030 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 351 | Techline351 | multiasic | 1 | 1 | 0 | 0 / 0 / 2 | wiki | by eye (Mesen2 refuses) |
| 355 | Block355 | pic16c54 | 2 | 0 | 0 | 0 / 0 / 2 | wiki, data sheet | by eye (Mesen2 refuses) |
| 359 | SB5013 | multicart | 0 | 0 | 0 | 0 / 0 / 0 | wiki | unit tests only |
| 368 | Yung08 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 374 | ResetMMC1 | multicart | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 380 | Latch380 | multicart | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 389 | Caltron389 | multicart | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 394 | HSK007 | multiasic | 3 | 0 | 0 | 0 / 0 / 3 | wiki | by eye (Mesen2 refuses) |
| 396 | YY850437C | multicart | 2 | 0 | 0 | 0 / 0 / 2 | wiki | by eye (Mesen2 refuses) |
| 399 | BATMAP399 | mmc3_clones | 0 | 1 | 1 | 0 / 0 / 2 | wiki | by eye (Mesen2 refuses) |
| 400 | RetroUSB400 | multicart | 0 | 1 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 406 | Haradius406 | mmc3_clones | 0 | 0 | 3 | 0 / 0 / 3 | wiki | by eye (Mesen2 refuses) |
| 409 | DPCMCart409 | multicart | 0 | 0 | 1 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 412 | Henggedianzi412 | mmc3_clones | 0 | 5 | 0 | 0 / 0 / 5 | wiki | by eye (Mesen2 refuses) |
| 413 | BATMAPSRR | homebrew | 0 | 1 | 0 | 0 / 0 / 1 | wiki, MAME | by eye (Mesen2 refuses) |
| 415 | Board0353 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 417 | FineStudio417 | chinese | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 418 | LH42 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki, MAME | by eye (Mesen2 refuses) |
| 422 | ING003C | mmc3_clones | 1 | 0 | 4 | 0 / 0 / 5 | wiki | by eye (Mesen2 refuses) |
| 446 | Mindkids446 | multiasic | 4 | 0 | 2 | 0 / 0 / 6 | wiki, the game (C70) | by eye (Mesen2 refuses) |
| 451 | Haratyler451 | mmc3_clones | 0 | 0 | 2 | 0 / 0 / 2 | wiki | by eye (Mesen2 refuses) |
| 470 | AOROMMulticart | discrete | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 471 | ImpactSoft471 | multicart | 0 | 0 | 2 | 0 / 0 / 2 | wiki | by eye (Mesen2 refuses) |
| 487 | NINA08 | unlicensed | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 493 | Maxivision493 | multicart | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 512 | Zhongguo512 | mmc3_clones | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 513 | Board513 | mmc3_clones | 1 | 0 | 0 | 0 / 1 / 0 | wiki | differs, by eye |
| 515 | Noraebang515 | chinese | 5 | 0 | 0 | 0 / 0 / 5 | wiki | by eye (Mesen2 refuses) |
| 516 | Cocoma516 | mmc3_clones | 2 | 0 | 0 | 0 / 0 / 2 | wiki | by eye (Mesen2 refuses) |
| 517 | UxROM | discrete | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 518 | Dance2000 | chinese | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 519 | Latch519 | multicart | 4 | 0 | 0 | 4 / 1 / 0 | wiki | matches Mesen2 |
| 521 | Board521 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 522 | Kaiser522 | kaiser | 1 | 0 | 0 | 1 / 0 / 0 | wiki | matches Mesen2 |
| 523 | Jncota523 | waixing | 0 | 1 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 525 | KS7021A | kaiser | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 526 | Board526 | kaiser | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 529 | T230 | konami | 2 | 0 | 0 | 1 / 1 / 0 | wiki | matches Mesen2 |
| 530 | AX5705 | konami | 1 | 0 | 0 | 1 / 0 / 0 | wiki, the game (C66) | matches Mesen2 |
| 533 | Sachen3014 | sachen | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 534 | ING003C | mmc3_clones | 1 | 4 | 0 | 0 / 0 / 5 | wiki | by eye (Mesen2 refuses) |
| 535 | LH53 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 538 | SoccerChampion538 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 539 | Palthena539 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 540 | SB5013 | multicart | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 541 | LittleCom541 | multicart | 0 | 1 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 544 | FS306 | konami | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 547 | QTa | vrc5 | 4 | 0 | 0 | 0 / 0 / 4 | wiki | by eye (Mesen2 refuses) |
| 548 | CTC15 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 549 | KS7016B | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki, forum, MAME | by eye (Mesen2 refuses) |
| 551 | Jncota551 | chinese | 1 | 3 | 0 | 0 / 0 / 4 | wiki | by eye (Mesen2 refuses) |
| 552 | X1017 | taito | 4 | 0 | 0 | 4 / 0 / 0 | wiki | matches Mesen2 |
| 553 | Sachen3013 | sachen | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 554 | KS7010 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki | by eye (Mesen2 refuses) |
| 555 | Event2 | mmc3 | 1 | 0 | 0 | 0 / 0 / 1 | wiki, MAME | by eye (Mesen2 refuses) |
| 557 | LH42 | conversions | 1 | 0 | 0 | 0 / 0 / 1 | wiki, MAME | by eye (Mesen2 refuses) |
| 558 | YC0309 | nanjing | 4 | 6 | 0 | 0 / 0 / 10 | wiki | by eye (Mesen2 refuses) |
| 559 | **not implemented** |  | 1 | 0 | 0 |  |  |  |
| 563 | **not implemented** |  | 1 | 0 | 0 |  |  |  |
| 564 | **not implemented** |  | 1 | 0 | 0 |  |  |  |
| 576 | **not implemented** |  | 1 | 0 | 0 |  |  |  |
| 585 | **not implemented** |  | 1 | 0 | 0 |  |  |  |
| 594 | Rinco594 | mmc3_clones | 4 | 0 | 0 | 0 / 0 / 4 | wiki | by eye (Mesen2 refuses) |
| 682 | **not implemented** |  | 0 | 8 | 0 |  |  |  |

<!-- registry end -->
