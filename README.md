# famicom-python

A readable, pure-Python emulator of **Nintendo's Family Computer and NES**, to
be built as a board on [6502-python](https://github.com/alewman/6502-python):
6502-python owns the instruction set; this repository will own everything
around it: the 2A03's sound unit, DMA and joypad ports, the 2C02 picture
processor dot by dot, the cartridge connector and the mappers behind it, and
the clock that ties them together.

**Status (2026-10-05): groundwork only, no emulator code.** The documents in
[`docs/`](docs/README.md) gather what the build needs, every fact with its
source and tier: the hardware, the timing, the cartridges, the quirks and
contradictions, the oracles, a verified MAME recipe, and the brief for the
session that builds it ([docs/handoff-brief.md](docs/handoff-brief.md)).

## Scope

| Machine | Phase |
| --- | --- |
| NES-001 (RP2A03G + RP2C02G): the reference model | 1 |
| Famicom (RF), AV Famicom, NES-101: as fields on the same board | 1 |
| PAL NES (2A07 + 2C07), Dendy | later, as machine data |
| Famicom Disk System, Vs. System, PlayChoice-10 | later |

Mappers live in this repository behind a signal-level cartridge connector
([docs/cartridge.md](docs/cartridge.md)); the first six (0, 1, 2, 3, 4, 7)
cover 83 % of licensed cartridges, 26 cover 95 %.

## What is fetched

Nothing third-party is committed. `scripts/fetch_references.py` rebuilds
`reference/` and `tests/test_roms/` from `scripts/pinned_files.json` (468 files
pinned by SHA-256: NESdev wiki and forum snapshots, documents, test ROMs,
hardware captures) and `scripts/pinned_repos.json` (29 repositories at full
commit SHAs, sparse where large):

```sh
python scripts/fetch_references.py            # everything missing
python scripts/fetch_references.py --verify   # check what is present
```

It needs `git` and `curl`. Wiki and forum pages are live: a changed page is
reported and kept; everything else must match its hash.

## Scripts

| Script | What |
| --- | --- |
| `scripts/fetch_references.py` | the pinned references and test ROMs |
| `scripts/mame_trace.py` | MAME 0.285 per-instruction trace and register log of an NES cartridge ([docs/mame-oracle.md](docs/mame-oracle.md)) |
| `scripts/mesen_run.py`, `scripts/mesen_blargg.lua` | a locally built Mesen2 core driven headless, stopping on blargg's `$6000` result ([docs/validation.md](docs/validation.md)) |
| `scripts/count_mappers.py` | mapper coverage over the local No-Intro sets, read in place ([docs/cartridge.md](docs/cartridge.md)) |

## Licence

MIT (see `LICENSE`), for what is in this repository. The fetched material keeps
its own terms, recorded per file in the pin lists.
