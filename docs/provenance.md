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
(its 50,000 cycles of FDS drive start, C39), which a Mesen comparison cannot then confirm.

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
   being unclear. MAME's own NES cart files are BSD-3 and may be read. Two old docstrings
   (`discrete.py`, `mmc5.py`) cite Mesen2 source paths and are left as an honest record.

## How it came together

The order mattered more than any single step: the CPU from 6502-python against SingleStepTests and nestest;
the PPU against PPUSim, which itself needed fixing (emu-russia/breaknes#529, and #535-#538
open); APU, DMA and interrupts against blargg and perfect6502; AccuracyCoin taken from 116 to 146 and
then 147; mappers through the sweeps, where most bugs were ours, then reading the games themselves
when the documents ran out; MesenCE and mame_nes as further detectors, the second one
finding bugs the first two could not, on boards they refuse.

Each step found errors in the one before, and in the references. That is the point of keeping several.
