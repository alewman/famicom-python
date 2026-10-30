# Cartridges and mappers

On the NES the cartridge is half the machine: it decides what the CPU sees at
$4020–$FFFF, what the PPU sees at $0000–$2FFF, how the nametables are
arranged, and on a Famicom what you hear. "Mapper" numbers (iNES, NES 2.0)
name cartridge circuits; about 250 are in use. This page is the cartridge side
of the board: the connector as an interface, the file formats, how a board is
identified, how much of the library each mapper covers (measured), and what
judges each mapper. Paths as in [start-here.md](start-here.md).

## Where mappers live, and why

Mappers live **inside famicom-python**, as the subpackage
`famicom_python/cartridge/`, behind one interface: the **cartridge connector as
signals**. A test forbids any module there from importing anything of the board
except the connector protocol. A separate repository was considered and
rejected: our cores are separate projects because they have judges that need no
board (SingleStepTests, Nuked-OPN2), but a mapper's judges are test cartridges
that need a whole console to run, so a mapper project would have to depend on
famicom-python to test itself. The exceptions are the expansion **sound chips**
that are real chips with die-level judges: those become cores (see
[start-here.md](start-here.md), "The APU").

## The connector

`Cartridge_connector.wiki`:

- **Famicom, 60 pins**: CPU A0–A14, D0–D7, R/W, M2, /ROMSEL, /IRQ; PPU A0–A13,
  /A13, D0–D7, /RD, /WR; CIRAM A10 and CIRAM /CE (outputs from the cartridge);
  audio from the 2A03 (pin 45) and audio to RF (pin 46).
- **NES, 72 pins**: the same CPU and PPU signals, plus the 21.48 MHz master
  clock, the CIC pins and EXP0–EXP9 to the bottom expansion port, and **no
  audio** (EXP6 carries expansion audio on modified consoles). PPU A10 and A11
  are swapped on the NES connector's pins 62 and 63.

Facts the protocol must honour:

- **A15 is not on the connector.** /ROMSEL = NAND(M2, A15): low only for
  $8000–$FFFF *while M2 is high*. Boards that decode $6000 from "/ROMSEL high"
  also answer $E000–$FFFF writes, because /ROMSEL is high whenever M2 is low
  (mappers 38 and 86, `INES_Mapper_086.wiki`).
- Address and R/W are valid while M2 is high; read data is taken at M2's fall.
- /IRQ is wired-OR with a pull-up.
- The PPU's AD0–7 carry address and then data: each PPU access is ALE plus the
  address on one dot, /RD on the next. Palette accesses never assert /WR. An
  undriven PPU read returns the **low byte of the address** (mapper 185's copy
  protection depends on it).

### The protocol (settled in milestone 1)

`src/famicom_python/cartridge/connector.py` is the protocol; `Cartridge` there
is its do-nothing default, which every mapper extends. What was proposed, and
what milestone 1 decided:

1. **One timeline.** Every call carries `t` in master ticks (NTSC CPU cycle = 12,
   dot = 4); the board delivers CPU and PPU events in `t` order. *Decided*: for
   a CPU access `t` is the **end** of its cycle (M2's fall, when read data are
   latched and a write completes); for a PPU access, the dot of its /RD or /WR.
   A mapper that needs M2's rise (MMC5) places it inside the cycle itself:
   M2 on an RP2A03G is high for 15/24 of the cycle (`CPU_pinout.wiki`).
2. **What the cartridge sees of the CPU.** Proposed: every cycle. *Decided*:
   every **write**, whatever its address (MMC1's consecutive-write ignore
   counts any write; MMC5 snoops $2000-$2006 and $4014); every **read of
   $4020-$FFFF**; reads of $0000-$401F only for a mapper that sets
   `snoops_cpu_reads`. Those reads are most of the CPU's cycles and no
   licensed mapper decodes them; a cycle count is `Δt / 12`, so nothing is
   lost. A mapper whose counter must raise /IRQ on an exact cycle (VRC4, FME-7,
   N163, Bandai) sets `counts_m2` and gets `m2(t)` every cycle.
3. **"Not driven" is a value**: a read returns `None` and the board supplies
   open bus (the CPU data latch, or the PPU address's low byte). *Changed in
   milestone 7*: a CPU read may drive only some lines, returned as `driven |
   undriven << 8` with the undriven lines taken from the data latch. Bandai's
   $6000 read drives D4 (the EEPROM) and, on the Datach, D3 (the barcode),
   and nothing else (`INES_Mapper_016.wiki`, `_157.wiki`). It costs one
   comparison per cartridge read; the alternative, a whole-byte guess at the
   open bus, is wrong for any game that reads the port with an indexed mode.
4. **Nametables.** Proposed: `nametable(address) -> (CIRAM /CE, CIRAM A10)`.
   *Decided*: `ciram_a10(address) -> int | None`, `None` meaning CIRAM is
   disabled and the cartridge answers through `ppu_read`/`ppu_write` (four-screen
   RAM, MMC5 ExRAM, ROM nametables). One call, no tuple per access.
5. No reset method: the reset button never reaches the cartridge; MMC5 detects
   reset from a gap in M2, which the timestamps make visible.

```python
class Cartridge:
    snoops_cpu_reads = False  # also receive reads of $0000-$401F
    counts_m2 = False  # receive m2(t) every CPU cycle
    watches_ppu_address = False  # receive ppu_address(address, t) on every ALE
    irq: bool  # /IRQ, wired-OR on the board

    # the CPU side
    def cpu_read(self, address: int, t: int) -> int | None: ...
    def cpu_write(self, address: int, value: int, t: int) -> None: ...
    def m2(self, t: int) -> None: ...

    # the PPU side
    def ppu_address(self, address: int, t: int) -> None: ...
    def ciram_a10(self, address: int) -> int | None: ...
    def ppu_read(self, address: int, t: int) -> int | None: ...
    def ppu_write(self, address: int, value: int, t: int) -> None: ...

    # outputs the board samples
    def audio(self, apu_in: float, t: int) -> float: ...  # Famicom pins 45 -> 46
    def battery_ram(self) -> bytes | None: ...
```

**Milestone 2 settled the PPU side** (the one change since milestone 1, with
its reason): `ppu_address` and `ppu_read` stay two calls, because MMC2/MMC4
latch *after* a pattern read and MMC3 sees A12 on the address phase; but
`ppu_address` is an opt-in, **`watches_ppu_address`**, like the CPU side's
`snoops_cpu_reads`. The address phases are about 4 M calls a second while
rendering (four per tile and per sprite slot, plus dots 337 and 339), only
MMC3 (A12) and MMC5 (three equal nametable addresses) and their relatives
look at them, and a call per phase cost every other mapper for nothing. Every
/RD and /WR still reaches the cartridge: pattern fetches (34 tiles and 8 sprite
slots, two planes each, per rendering line; tile $FF for empty slots) through
`ppu_read`, nametable and attribute fetches through `ciram_a10` and, when it
returns `None`, `ppu_read`. Outside rendering v is on the bus, so a $2006
write or a $2007 access gives watchers an address phase too.
`tests/test_ppu_rendering.py` counts them on a synthetic NROM.

Milestone 1 implements mappers 0 (NROM), 1 (MMC1) and 3 (CNROM), because the
CPU test ROMs need them (`all_instrs`, `instr_timing` and `instr_misc` are MMC1
boards; `cpu_dummy_reads` is CNROM); milestone 2 adds 2 (UxROM) for the 240p
Test Suite. Milestone 5 adds 4 (MMC3 with MMC6, MC-ACC and both IRQs), 7
(AxROM), 34 (BNROM, NINA-001) and 155 (MMC1A), the MMC1 board wirings
(SUROM, SOROM, SXROM, SZROM, SNROM, SEROM), and judges for all of them:
[claims.md](claims.md). Milestone 5 also put the PPU's dot-0 address on the
connector (C27): an MMC3 counting with BG at `$1000` needs it.

### Which mappers stress which part

| Stress | Mappers |
| --- | --- |
| Every CPU write with its cycle (consecutive-cycle writes ignored, the reset bit never) | MMC1 (1, 155). *Bill & Ted* needs the ignore |
| A12 rises filtered by M2: "after the line has remained low for three falling edges of M2" | MMC3/MMC6 (4), 118, 119 (`MMC3.wiki`, from Furrtek's MMC3C schematic) |
| A12 falls ÷8 | MC-ACC (4.3) |
| Every PPU read + M2 counting + CPU snooping | MMC5: 3 equal NT reads = a scanline; in-frame exit after 3 M2 rises without /RD; snoops $2000/$2001/$2002/$2005/$2006/$4014 and $FFFA/B reads |
| Specific pattern reads ($0FD8, $0FE8, $1FD8–$1FDF, $1FE8–$1FEF) | MMC2 (9), MMC4 (10) |
| CPU-cycle IRQ counters (`m2`) | VRC4/6/7, FME-7 (69), N163 (19), Bandai FCG (16/157/159), Jaleco SS88006 (18) |
| Bus conflicts (effective value = CPU value AND ROM byte) | 0, 2, 3, 7 (some boards), 11, 66, 34 BNROM, 185, 30 |
| Registers in $4020–$7FFF | N163 ($4800–$5FFF), MMC5 ($5000–$5FFF), 34 NINA, 87, 184, 80 ($7EF0), 268 |
| CIRAM replaced or extended | four-screen 4 and 206 (*Rad Racer II*, *Gauntlet*), MMC5 ExRAM and fill, N163, 68 (ROM nametables), 118 (CHR A17 → CIRAM A10), 30 |

## File formats

**iNES 1.0** (`INES.wiki`): "NES\x1A"; byte 4 PRG in 16 KiB; byte 5 CHR in
8 KiB (0 = CHR RAM); byte 6 mirroring (bit 0), battery, trainer, four-screen,
mapper low nibble; byte 7 Vs./PlayChoice, NES 2.0 marker, mapper high nibble.
"DiskDude!" junk in bytes 7–15 is common in old rips. **Terminology hazard**:
the wiki says "vertical arrangement" where older documents say "horizontal
mirroring".

**NES 2.0** (`NES_2.0.wiki`; detect with `(h[7] & 0x0C) == 0x08`): 12-bit mapper
plus a 4-bit **submapper**; ROM sizes with an exponent-multiplier form; PRG-RAM,
PRG-NVRAM, CHR-RAM and CHR-NVRAM as shift counts (64 << n); timing (NTSC, PAL,
multi, Dendy); console type; Vs. PPU type; default expansion device. "An
emulator must not assume that … no CHR-ROM [means] 8 KiB of CHR-RAM".
Submappers that matter for licensed games (`NES_2.0_submappers.wiki`):

- 1.5: SEROM/SHROM fixed 32K PRG (29 licensed dumps).
- 2.x, 3.x, 7.x: 1 = no bus conflicts, 2 = AND bus conflicts.
- 4.0 Sharp MMC3 ("new"), **4.1 MMC6**, **4.3 MC-ACC**, 4.4 NEC MMC3 ("old").
- 21/23/25.x: which VRC4 or VRC2 address-line wiring; 22 = VRC2a.
- 34.1 NINA-001, 34.2 BNROM; 206.1 unbanked; 210.1 Namco 175, 210.2 Namco 340;
  16.4 FCG, 16.5 LZ93D50 + 24C02; 19.x the N163 mixing resistor; 85.1/85.2
  VRC7b/a.

**UNIF** is deprecated, and the local No-Intro sets contain none: no loader in
phase 1. **FDS** images (fwNES `.fds`, 65,500 bytes per side, with or
without the 16-byte header; No-Intro's are headerless) load as the RAM
adapter (`cartridge/fds.py`, milestone 9): the loader recognises the data,
not the extension, and needs the BIOS (`FAMICOM_FDS_BIOS`, or No-Intro's
under `NO_INTRO_DIR`; Nintendo's, never fetched or committed). `.QD` images
(Nintendo's re-release format: 65,536 bytes a side, each block's CRC stored)
load the same way, their stored CRCs kept as they are. Sides a game writes
are saved beside the image (`<image>.sav`: the written sides, as `.fds`
sides), the image itself never changed.

## Identifying the board

**Primary: nes20db** (NewRisingSun), release **2026-09-26**, 21,339 entries
(`reference/docs/nes20db-2026-09-26.7z`, from forum thread t=19940; no licence
stated, so fetched and never committed). Each entry has whole-ROM, PRG and CHR
SHA-1 and CRC32, the full NES 2.0 description, and the source set. Measured
against the local No-Intro sets (every dump's header stripped, the rest
SHA-1'd):

| Set | Dumps | Found in nes20db | PRG found in MAME `nes.xml` | Header fields differing from nes20db |
| --- | ---: | ---: | ---: | --- |
| Headered, licensed | 2,646 | **2,646 (100 %)** | 2,261 (85.4 %) | 9 (3 region, 6 submapper) |
| Headered, non-licensed | 1,818 | 1,818 (100 %) | 1,126 (61.9 %) | 26 |
| Aftermarket | 2,913 | 2,911 (99.9 %) | 241 (8.3 %) | ~1,900, nearly all the mapper-30 battery→submapper convention change in the 2026-09-26 release |
| Private | 634 | 634 (100 %) | 23 (3.6 %) | same pattern |

No-Intro's headered set is effectively nes20db-headered (every header is NES
2.0). **Secondary: MAME's `/usr/share/games/mame/hash/nes.xml`** (CC0, read at
runtime as sms-python reads its lists), keyed by PRG SHA-1, for what nes20db
lacks: the PCB name, `mmc1_type`, `mmc3_type`, `bus_conflict`. Its PCB names
are only hardware-sourced where Bootgod documented the cartridge, and **no code
in MAME 0.285 reads `mmc3_type`**; MAME's MMC3 IRQ is a per-scanline callback
(`mmc3.cpp:207`), so MAME is at most a detector for MMC3 timing. NesCartDB
(Bootgod) sits behind a Cloudflare challenge: a manual reference for chip
markings, never a runtime dependency.

Override order: user override > nes20db by whole-ROM SHA-1 > nes20db by
PRG+CHR SHA-1 > the file's NES 2.0 header > the iNES 1.0 header with
heuristics. Log every disagreement.

## Coverage, measured

`scripts/count_mappers.py` streams the 16-byte header of every `.nes` inside
the local No-Intro zips (nothing extracted), run 2026-10-05. "Licensed" = none
of (Unl), (Pirate), (Aftermarket), (Proto), (Beta), (Sample), (Demo),
(Program). Main set `Nintendo - Nintendo Entertainment System (Headered)`:
4,464 dumps, all NES 2.0; 2,646 licensed dumps over 75 mappers.

| Rank | Mapper | Dumps | % | Cumulative % |
| ---: | --- | ---: | ---: | ---: |
| 1 | 1 MMC1 | 760 | 28.72 | 28.72 |
| 2 | 4 MMC3/MMC6 | 640 | 24.19 | 52.91 |
| 3 | 0 NROM | 289 | 10.92 | 63.83 |
| 4 | 2 UxROM | 286 | 10.81 | 74.64 |
| 5 | 3 CNROM | 171 | 6.46 | 81.10 |
| 6 | 7 AxROM | 61 | 2.31 | 83.41 |
| 7 | 206 Namco 108 / DxROM | 51 | 1.93 | 85.34 |
| 8 | 5 MMC5 | 32 | 1.21 | 86.55 |
| 9 | 19 Namco 129/163 | 32 | 1.21 | 87.76 |
| 10 | 18 Jaleco SS88006 | 19 | 0.72 | 88.47 |
| 11 | 23 VRC2b/VRC4e/f | 17 | 0.64 | 89.12 |
| 12 | 16 Bandai FCG | 16 | 0.60 | 89.72 |
| 13 | 87 J87 | 15 | 0.57 | 90.29 |
| 14 | 69 FME-7 | 15 | 0.57 | 90.85 |
| 15 | 66 GxROM | 15 | 0.57 | 91.42 |
| 16 | 210 Namco 175/340 | 14 | 0.53 | 91.95 |
| 17 | 25 VRC2c/VRC4b/d | 11 | 0.42 | 92.37 |
| 18 | 185 CNROM + diodes | 10 | 0.38 | 92.74 |
| 19 | 9 MMC2 | 10 | 0.38 | 93.12 |
| 20 | 268 (modern reissues) | 9 | 0.34 | 93.46 |
| 21 | 33 Taito TC0190 | 9 | 0.34 | 93.80 |
| 22 | 118 TxSROM | 8 | 0.30 | 94.10 |
| 23 | 75 VRC1 | 8 | 0.30 | 94.41 |
| 24 | 32 Irem G-101 | 7 | 0.26 | 94.67 |
| 25 | 157 Bandai Datach | 7 | 0.26 | 94.94 |
| 26 | 159 Bandai LZ93D50 + 24C01 | 7 | 0.26 | 95.20 |

- **Mappers 0, 1, 2, 3, 4, 7 cover 83.41 % of licensed dumps** (82.15 % of
  1,720 distinct titles).
- Mappers needed: **80 % → 5, 90 % → 13, 95 % → 26, 98 % → 43, 99 % → 54,
  100 % → 75.** Without BIOS images and modern reissues: 83.94 %, 95 % → 24,
  99 % → 50.
- Licensed submappers: 1.5 ×29, 4.1 (MMC6) ×6, 4.3 (MC-ACC) ×14, **4.4 ×0**,
  7.1 ×27 / 7.2 ×34.
- Non-licensed (1,818 dumps, 232 mappers): 95 % takes 142 mappers.
- Homebrew: **mapper 30 (UNROM-512) is 36 % of the Aftermarket set and 50 % of
  the Private set**, ahead of every licensed mapper but 0.

## Mappers, in coverage order

Sources are the NESdev wiki pages named; "judge" is a test cartridge that can
fail the mapper. HM = Holy Mapperel 0.02; NTR = `tests/test_roms/nes-test-roms`;
nf = `tests/test_roms/nesdev-forum/`.

| Mapper | Banking | Mirroring | IRQ | Quirks | Judge |
| --- | --- | --- | --- | --- | --- |
| **1** MMC1 (155 = MMC1A) | 5-write serial port; PRG 16K+fixed or 32K; CHR 4K×2 or 8K; SUROM/SXROM PRG A18 from CHR bit 4 | switchable incl. 1-screen | — | consecutive-cycle write ignore; RAM disable differs MMC1A/B; power-on bank (C19) | HM; `serom` (1.5); `mmc1atest` (155 vs 1) |
| **4** MMC3 / MMC6 / MC-ACC | PRG 8K×2 + fixed (mode swap); CHR 2K×2 + 1K×4 (A12 inversion) | switchable; four-screen RAM | A12 rise after 3 M2 falls low; Sharp vs NEC on latch 0 | 8×16 sprites can clock it up to 4×/line; MMC6 RAM halves | **blargg `mmc3_test_2`** (5 = Sharp, 6 = NEC); `mmc3_irq_tests` (hardware-run); `mmc3_test/6-MMC6` (C18); `mmc3irqtest`; HM |
| **0** NROM | — | fixed | — | 8K PRG images exist | HM |
| **2** UxROM | 16K + last fixed | fixed | — | bus conflicts (2.2) | rainwarrior `2_test` (submapper conformance); HM |
| **3** CNROM | 8K CHR | fixed | — | bus conflicts (3.2); 185 diodes | `3_test`; HM via 66 |
| **7** AxROM | 32K | **1-screen select** | — | conflicts on AMROM/AOROM only | `7_test`, `bntest_aorom`; HM |
| **206** Namco 108 | MMC3 subset | fixed / four-screen | — | 88 = superset | none known |
| **5** MMC5 | PRG modes 0–3, RAM in $6000–$DFFF; CHR 1/2/4/8K, separate BG/sprite sets in 8×16 | per quadrant: CIRAM, ExRAM, fill | scanline from 3 equal NT reads; in-frame flag; IRQ at dot 4 | snoops; M2-gap reset; vertical split; multiplier | `mmc5test`, `mmc5test_v2`, `exram`, `mmc5ramsize` |
| **19** N163 | PRG 8K×3 + fixed; CHR 1K×8, CIRAM as CHR | via NT registers | 15-bit up counter per CPU cycle | 128 B internal RAM not in header | none for banking |
| **18** Jaleco SS88006 | PRG 8K×3; CHR 1K×8 | H/V/1sc | down counter, 4/8/12/16 bits | | none |
| **21/22/23/25** VRC2/VRC4 | PRG 8K×2 + 16K fixed; CHR 1K×8, nibble-split | VRC2 H/V; VRC4 +1sc | VRC4: VRC IRQ (prescaler 341 −3) | address-line wiring per PCB (submappers); 23.3 needs 1 bit of RAM at $6000 | AWJ `vrctest` (9 ROMs); `m22chrbankingtest` |
| **16/157/159** Bandai | PRG 16K + fixed; CHR 1K×8 | H/V/1sc | 16-bit down counter per M2 | registers at $6000 (16.4) or $8000 (16.5); I²C EEPROMs | none |
| **87** J87 | 8K CHR via $6000 | fixed | — | CHR bits reversed (101 = misdump) | none |
| **69** FME-7 | PRG 8K×4 (RAM at $6000) + fixed; CHR 1K×8 | H/V/1sc | 16-bit down counter per CPU cycle | 5B audio | `fme7acktest`, `fme7ramtest`; HM |
| **66** GxROM | 32K PRG + 8K CHR | fixed | — | bus conflicts | HM |
| **210** Namco 175/340 | as N163, no audio/IRQ | 175 fixed; 340 switchable | — | | none |
| **185** CNROM + diodes | — | fixed | — | CHR disabled unless the diode pattern matches → PPU open bus | none |
| **9 / 10** MMC2 / MMC4 | CHR 4K×2 latched pairs | H/V | — | latch flips *after* the trigger read | HM (no latch-timing ROM) |
| **118** TxSROM | MMC3 | CHR A17 → CIRAM A10 | MMC3 | | HM |
| **24/26** VRC6 | PRG 16K + 8K + fixed; CHR 1K×8 | H/V/1sc | VRC IRQ | 26 swaps A0/A1; sound (milestone 8) | NewRisingSun's `VRC6TEST`/`VRC6TESA` with hardware recordings (nesdev-forum/16910.html; archive.org's copy pinned 2026-10-26, `scripts/nrs_recordings.py`); rainwarrior's `db_vrc6a`/`b` for the level |
| **85** VRC7 | PRG 8K×3 + fixed; CHR 1K×8 | H/V/1sc | VRC IRQ | 85.1 VRC7b (A3), 85.2 VRC7a (A4); FM sound (ym2413-python's DS1001) | rainwarrior's `db_vrc7` for the level |
| **85** VRC7 | PRG 8K×3 + fixed; CHR 1K×8 | H/V/1sc | VRC IRQ | 85.1 A3, 85.2 A4; OPLL audio | none for banking |
| **30** UNROM-512 (homebrew) | 16K + fixed; CHR-RAM 8K×4 | header/register | — | self-flash save; submappers redefined 2026-09-26 | none |
| **28** Action 53 (homebrew) | 32K, or 16K + fixed, in an outer bank of 32-256K; CHR-RAM 8K×4 | register: 1-screen, V, H | — | the multicart mapper; Action_53_mapper.wiki | none |
| **31** NSF subset (homebrew) | 4K×8 from $5000-$5FFF | header | — | NSF music compilations; INES_Mapper_031.wiki | none |
| **111** GTROM (homebrew) | 32K×16 from $5000/$7000; CHR-RAM 8K×2 | 4 screens of cartridge RAM, 2 pages, unmirrored to $3EFF | — | self-flash save; the register latches open bus on reads; GTROM.wiki | none |

The licensed gaps closed on 2026-10-29 (validation.md "The licensed gaps"), from
their wiki pages, all without a judge ROM:

| Mapper | Banking | Mirroring | IRQ | Quirks |
| --- | --- | --- | --- | --- |
| **13** CPROM | CHR-RAM 4K fixed + 4K×4 | fixed | — | bus conflicts |
| **37/47** Nintendo multicarts | MMC3 inside an outer latch at $6000 | MMC3 | MMC3 | the latch takes writes only with the MMC3's "RAM" enabled |
| **48** Taito TC0690 | PRG 8K×2 + fixed; CHR 2K×2 (2K units) + 1K×4 | H/V | MMC3's counter, later | the delay (C48) |
| **64** Tengen RAMBO-1 | PRG 8K×3 + fixed (R6/RF swap); CHR 2K or 1K at $0000 | H/V | A12 or every 4 CPU cycles | reload + 1 "kick" |
| **65** Irem H3001 | PRG 8K×2 + 2 fixed (mode swap); CHR 1K×8 | H/V/1sc | 16-bit down counter, stops at 0 | power-on $8000 = 0, $A000 = 1 (C49) |
| **67** Sunsoft-3 | PRG 16K + fixed; CHR 2K×4 | H/V/1sc | 16-bit down counter, pauses on wrap | count written high then low |
| **68** Sunsoft-4 | PRG 16K + fixed; CHR 2K×4 | H/V/1sc, CHR-ROM nametables | — | 68.1: the cassette ROM and licensing timer (C52) |
| **70/152** Bandai 74161 | PRG 16K + fixed; CHR 8K | fixed / 1-screen select (152) | — | bus conflicts |
| **71/232** Camerica | PRG 16K + fixed (232: in 64K outer banks) | fixed / 1-screen (Fire Hawk) | — | 71.0 waits for a $9000 write; 232.1 swaps the outer bits |
| **72/92** Jaleco JF-17/19 | PRG 16K + fixed (92: first fixed); CHR 8K | fixed | — | banks load on a command bit's rise; speech chip not modelled |
| **73** VRC3 | PRG 16K + fixed; CHR-RAM 8K | fixed | 16- or 8-bit up counter | |
| **76/88/95/154** Namco 108 boards | as 206 | fixed / CHR A15 → CIRAM A10 (95) / 1-screen (154) | — | 76: 2K CHR×4; 88/154: PPU A12 as CHR A16 |
| **77** Irem LROG017 | PRG 32K; CHR-ROM 2K + RAM | two cartridge nametables + CIRAM | — | $3000-$3EFF open bus |
| **78** Jaleco JF-16 / Holy Diver | PRG 16K + fixed; CHR 8K | 1-screen select (78.1) or H/V (78.3) | — | |
| **80/207** Taito X1-005 | PRG 8K×3 + fixed; CHR 2K×2 + 1K×4 | H/V (C47) / per-2K CIRAM A10 (207) | — | 128 B RAM behind $A3; registers ignore A7 |
| **82/552** Taito X1-017 | as X1-005, CHR A12 inversion | H/V | 16× prescaled counter (no game) | 552 reverses PRG lines; reads of $4020-$7FFF 0 |
| **86** Jaleco JF-13 | PRG 32K; CHR 8K, at $6000 | fixed | — | speech chip not modelled |
| **89/93** Sunsoft-2 | PRG 16K + fixed; CHR 8K (89) | 1-screen (89) / fixed | — | bus conflicts; 93's CHR-RAM enable |
| **94** UN1ROM | UxROM, bank in D4-D2 | fixed | — | |
| **96** Oeka Kids | PRG 32K; CHR-RAM 4K by the last nametable entered | fixed | — | the tablet is not modelled |
| **97** Irem TAM-S1 | last 16K fixed at $8000, $C000 switched | H/V | — | |
| **105** NES-EVENT | MMC1 over two PRG chips | MMC1 | 30-bit timer, DIP switches | locked until I goes 0 then 1 |
| **11** Color Dreams, **79/113** AVE NINA-03/06 | PRG 32K; CHR 8K | fixed / H/V (113) | — | 79's register at $4100-$5FFF with A8 high |
| **115** Kǎshèng | MMC3 + NROM override, outer CHR | MMC3 | MMC3 (Sharp) | C51 |
| **119** TQROM | MMC3, CHR ROM and RAM by bank bit 6 | MMC3 | MMC3 | |
| **140** Jaleco JF-11/14 | GNROM at $6000 | fixed | — | |
| **153** Bandai LZ93D50 + RAM | PRG 16K in 256K outer + fixed; CHR-RAM | H/V/1sc | Bandai's | 8 KiB battery RAM |
| **180** UNROM (AND) | first 16K fixed, $C000 switched | fixed | — | |
| **184** Sunsoft-1 | CHR 4K×2 from $6000 | fixed | — | |
| **188** Karaoke Studio | PRG 16K internal or expansion + fixed | H/V | — | the microphone reads idle |
| **470** INX_007T_V01 | AOROM in 256K outer banks | 1-screen | — | Retro-Bit's Battletoads & Double Dragon |

The remaining mappers followed on 2026-10-30 (validation.md "The remaining
mappers" and "second pass"; 294 in all): `conversions.py` the FDS conversions,
`multiasic.py` the multi-chip multicarts and Mindkids' FPGA (446), `vrc5.py`
Konami's Q-Ta adapter (547), `pic16c54.py` the microcontroller on 355, and the
rest beside their nearest relatives. Each class's docstring gives its source:
a wiki page, a forum analysis (`reference/nesdev-forum/`) or MAME's notes
(`reference/mame-nes/`, BSD-3).

Not implemented: 186 (the StudyBox tape drive), 682 (Rainbow, Broke Studio's
Wi-Fi mapper, documented outside the wiki), 256 and 405 (the VT02+ and UM6578
famiclones). No description found: 127, 169, 171, 559, 563, 564, 576, 585.

## Mapper test ROMs and what they can judge

| ROM | Mappers | Reports | Tier |
| --- | --- | --- | --- |
| **Holy Mapperel 0.02** (Damian Yerrick) | 0, 1, 2, 4, 7, 9, 10, 11, 28, 34, 66, 69, 78.3, 118, 180 | screen code (0000 = good) + beeps | built as a PCB manufacturing test for INL boards: "no substitute for an exhaustive mapper-specific test" |
| **mmc3_test_2** (blargg) | 4 | **$6000** | hardware-corrected |
| mmc3_test (blargg) | 4, MMC6 | $6000 | hardware-corrected |
| **mmc3_irq_tests** (blargg) | 4 | screen + beeps | "tested on an actual NES with several MMC3 cartridges" |
| mmc3irqtest (N-K) | 4 | screen | hardware photo pinned |
| mmc5test, mmc5test_v2, exram | 5 | screen | community, hardware-checked in the forum |
| mmc5ramsize (rainwarrior) | 5 RAM sizes | screen | conformance to NES 2.0, not hardware |
| 2/3/7/34_test (rainwarrior) | submapper bus conflicts | screen, expected values in the forum post | conformance |
| fme7acktest, fme7ramtest (tepples) | 69 | screen | IRQ ack verified on hardware |
| vrctest (AWJ) | 21–25 | screen | community |
| mmc1atest, serom, test28, bntest, 31_test | 155, 1.5, 28, 7/34, 31 | screen | community |

Only blargg's MMC3 suites speak the `$6000` protocol; the rest print to the
screen, so the harness needs a nametable text reader or the RAM addresses from
each ROM's source (Holy Mapperel's source is pinned). **No judge ROM exists**
for 206, 18, 19 (banking/IRQ), 16/157/159, 87, 210, 185, 33/48, 75, 32, 80, 30
or 111: their claims rest on games compared against a detector, and the claims
table says so.

## Nametables, RAM, saves, open bus

- **Mirroring**: H/V by solder pad (header bit 0, ignored by mappers that
  control it); single-screen from a mapper latch; four-screen with 2 KiB extra
  VRAM on the cartridge (header bit 3 on 4 and 206; not counted as CHR-RAM);
  ROM or ExRAM nametables (68, 19, MMC5).
- **PRG-RAM enables**: MMC1B $E000 bit 4; MMC3 $A001 bits 7/6; MMC6 two 512-byte
  halves each with read/write enables and a master bit; MMC5 $5102/$5103 magic
  values; X1-005 $7EF8 = $A3.
- **Saves**: battery SRAM at $6000 (most), 24C01/24C02 EEPROMs (16.5, 157, 159),
  mapper-internal RAM (19, 80), self-flashed PRG (30, 111). Persisted through
  `battery_ram()`.
- **CHR-RAM**: explicit in NES 2.0. Every licensed mapper-2 and mapper-7 dump is
  CHR-RAM, as are 236 MMC1 and 39 MMC3 dumps.
- **Unmapped space**: CPU $4020–$7FFF with nothing mapped returns open bus
  (some cartridges weakly OR noise in, especially on D7); PPU unmapped returns
  the low address byte.
