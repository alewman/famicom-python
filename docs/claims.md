# Claims: what each mapper is shown to do, and by what

The handoff brief (milestone 5) asks for this table: per mapper and board
variant, which judge passed, and where a claim rests on less. Tiers are
[validation.md](validation.md)'s. Every judge below is run by
`scripts/run_test_roms.py --suite mappers` (`MAPPER_ROMS` in
`famicom_python/testrom.py`) and by `pytest -m slow
tests/test_mapper_test_roms.py`; the certification record with hashes and
counts is validation.md, milestone 5. `tests/test_mappers.py` pins what no
judge ROM reaches, on synthetic images: it is a statement of the model, not a
judge.

"HM" is Holy Mapperel 0.02 (a PCB manufacturing test: mapper detection,
PRG/CHR/WRAM sizes and bank tags, WRAM disable and write-protect where the
mapper has them, a rough IRQ check; code 0000). "conformance" means a test
written against the NES 2.0 definition, not measured on hardware.

| Mapper | Board / variant | Judges passed | Tier | Not claimed |
| --- | --- | --- | --- | --- |
| 0 NROM | 32 KiB, CHR ROM or RAM | HM ×3 | manufacturing test | |
| 1 MMC1B | SxROM: SGROM, SFROM, SJROM, SKROM, SLROM, SNROM (E bit) | HM ×8, and `M1_P128K` with 8 KiB RAM as SNROM; `mmc1atest` on mapper 1 (rows 10/18 repeat 00/08, as its README says of MMC1B); the CPU test ROMs of milestone 1 | manufacturing test; community, hardware-run | which CHR register drives the reused lines in 4 KiB mode (always CHR 0 here: mmc1.py) |
| 1 | SUROM (512 KiB, PRG A18), SXROM (32 KiB RAM banked by D2-D3) | HM `M1_P512K_*` ×4 | manufacturing test | SOROM and SZROM RAM banking (no judge: the model follows MMC1.wiki "Summary") |
| 1.5 | SEROM/SHROM/SH1ROM, PRG A14 = CPU A14 | `serom` "All tests passed" | community | |
| 155 MMC1A | `$E000` D4: RAM stays enabled, D3 drives PRG A17 past the fixed bank | `mmc1atest` and `mmc1atest-sn`: the whole MMC1A table in its README (KMLbay's donor cartridge) | hardware-run | |
| 2 UxROM | 2.1, 2.2 (AND conflicts) | `2_test_1`, `2_test_2` (every value of the forum's table); HM ×2 | conformance; manufacturing test | 2.0 is "unknown" in the test; the board treats it as 2.1 |
| 3 CNROM | 3.1, 3.2 | `3_test_1`, `3_test_2` (every value but PRG RAM, a test bug: validation.md); HM | conformance | as 2.0 |
| 4 MMC3, Sharp ("new") | 4.0 | blargg `mmc3_test_2` 1-5, `mmc3_test` 1-5, `mmc3_irq_tests` 1-4 and 6 (`rev_B`); HM ×4 (CHR ROM, CHR RAM 8 and 32 KiB) and HM with 8 KiB RAM ($A001 enable and write-protect) | hardware-corrected | blargg's consecutive-`$C001` pathology (no emulator models it; MMC3.wiki) |
| 4 MMC3, NEC ("old") | 4.4 | `mmc3_test_2` 1-4 and 6 (`MMC3_alt`), `mmc3_test` 6 (`MMC6`, which expects this IRQ: C18), `mmc3_irq_tests` 5 (`rev_A`) | hardware-corrected | |
| 4 | 4.2 (hard-wired arrangement) | none | model only | |
| 4 MMC6 | 4.1: 1 KiB RAM in two halves, Sharp IRQ | `tests/test_mappers.py` only | specification (MMC6.wiki) | the IRQ: the NES 2.0 page says Sharp, blargg's `6-MMC6` says NEC (C18) |
| 4 MC-ACC | 4.3: every eighth A12 fall, unfiltered | `tests/test_mappers.py` only | specification (forum test results) | the prescaler's power-on phase and reset |
| 7 AxROM | 7.1, 7.2; single screen | `7_test_1`, `7_test_2` (every value); `bntest_aorom` (16 banks, one-screen 00004444); HM ×2 | conformance; manufacturing test | 7.0 is treated as 7.1, as the wiki asks |
| 34 BNROM | 34.2: 32 KiB banks, AND conflicts | `34_test_2` (valid BNROM, 8 banks); `bntest_h`, `bntest_v` (16 banks, H and V) | conformance | the bus conflicts: `34_test`'s line for them prints YES on any board (C28); specification and `tests/test_mappers.py` only |
| 34 NINA-001 | 34.1: registers over RAM at `$7FFD-$7FFF` | `34_test_1` (valid NINA-001, 2 PRG, 16 CHR banks) | conformance | |
| 9 MMC2 | PNROM: latch 0 on `$0FD8`/`$0FE8` alone, latch 1 on `$1FD8-$1FDF`/`$1FE8-$1FEF`, switching after the read | HM `M9_P128K_C64K` (fails with the latch frozen) | manufacturing test | the latch's timing within a fetch (no ROM measures it; the sweep against Mesen2 only) |
| 10 MMC4 | FxROM: both latches over a range, 16 KiB PRG, 8 KiB RAM | HM `M10_*` ×2 | manufacturing test | as 9 |
| 66 GxROM | GNROM/MHROM, AND conflicts | HM `M66_P64K_C16K_V` | manufacturing test | |
| 69 FME-7 | commands 0-F, ROM/RAM/open bus at `$6000`, 16-bit cycle IRQ | HM `M69_*` ×2; tepples's `fme7acktest` (every `$0D` write acknowledges, `$0E`/`$0F` do not: Oliveira's 2015 hardware result) | manufacturing test; hardware-run | `fme7ramtest`'s 32 KiB RAM mod (no hardware result); the 5B's sound (milestone 8) |
| 21/22/23/25 VRC2, VRC4 | all nine boards of the submapper table: wiring, VRC2's 1-bit latch, VRC4's one-screen, swap mode, RAM enable, VRC IRQ in both modes | AWJ's `vrctest` identifies each of the nine boards and finds both IRQ modes on time (fails with a 344-step prescaler) | community | VRC2's microwire (no game uses it) |
| 118 TxSROM | CHR A17 to CIRAM A10 | HM `M118_P128K_C64K` (fails with the A10 from the arrangement) | manufacturing test | |
| 5 MMC5 | PRG modes 0-3 with RAM in `$8000-$DFFF`, CHR modes 0-3 with the 10-bit registers, 8x16 A/B sets, ExRAM modes, fill, extended attributes, vertical split ("CL" wiring), scanline IRQ and in-frame flag, multiplier | none (the `mmc5test` ROMs are viewers; Mesen2's frame equals ours for `mmc5test`, `mmc5test_v2`, `mmc5exram`) | detector only: the sweep | reset detection, MMC5A's `$5207-$520A` and `$5800`, the `$2002`/`$2005` snoops |
| 5 MMC5 sound | two pulses (no sweep, no low-period mute, 7424-cycle frame clock), PCM DAC in write and read mode with its IRQ, inverted, +1.0 dB; a DAC step 0.273 of a pulse step (C38) | rainwarrior's `db_mmc5` (the level, by construction); NewRisingSun's recordings of two carts (`scripts/nrs_recordings.py`: the pulses' level and curve, the DAC against the pulse and the DMC); `tests/test_expansion_audio.py` | hardware recordings (levels); the rest the wiki's | the DAC's power-on value ($EF/$FF on one MMC5A: 0 here, a DC offset); the DAC beyond $02-$22 |
| 16 Bandai FCG/LZ93D50 | 16.4 (ports at `$6000`), 16.5 (at `$8000`, latch), 24C02 EEPROM on an open-drain SDA | `tests/test_mappers_m7.py` (EEPROM protocol, the acknowledge held through the master's release, counter order) | detector only: the sweep | the counter's test-then-decrement order is Mesen2's, not documented |
| 157 Datach | 24C02 and Battle Rush's X24C01, unbanked CHR-RAM | `tests/test_mappers_m7.py` | detector only | the barcode reader (idle) |
| 159 Bandai X24C01 | | `tests/test_mappers_m7.py` | detector only | |
| 18 SS88006 | nibble registers, 4/8/12/16-bit counter | `tests/test_mappers_m7.py` | detector only | the µPD7755/56 speech chip |
| 19 Namco 163 | CHR banks, CIRAM or CHR-ROM nametables, chip RAM port, 15-bit up counter | `tests/test_mappers_m7.py` | detector only | pattern tables in CIRAM; counting only while enabled (Mesen2's reading) |
| 19 Namco 163 sound | 1-8 channels taken in turn every 15 cycles (C37), `$E000` D6 silence, level by submapper (3: 12.0, 4: 16.5, 5: 18.75, 0: 18.0 dB) | `db_n163` (the level, by construction); NewRisingSun's recordings of ten carts (`scripts/nrs_recordings.py`: levels in their submapper's band, the volume curve, one against eight channels, the switching line); `tests/test_expansion_audio.py` | hardware recordings | the Namco 129's any-length waves (no game); *Namco Classic II*'s 10 dB quieter cart (open item 20) |
| 24/26 VRC6 | PRG 16 + 8 KiB, CHR modes 0-3 with `$B003` D5, CIRAM nametables, PRG-RAM enable, VRC IRQ; 26's A0/A1 swap | `tests/test_expansion_audio.py`; frames against Mesen2 (5 of 6 identical, the sixth C33) | detector only | ROM nametables (`$B003` D4) and the D5-clear arrangements (no game) |
| 24/26 VRC6 sound | two pulses (duty counting down, C36) and the saw, `$9003` halt and shifts, +0.2 dB | `db_vrc6a`, `db_vrc6b` (the level, by construction; both wirings); NewRisingSun's recording of *Madara* (`scripts/nrs_recordings.py`: the square's and saw's level and curve, within 0.8 dB); `tests/test_expansion_audio.py` | hardware-measured level; the rest the wiki's | the duty direction (C36: no judge) |
| 85 VRC7 | PRG 8 KiB × 3 + fixed, CHR 1 KiB × 8, four mirrorings, PRG-RAM enable, VRC IRQ; register select A3 (85.1) or A4 (85.2) | `tests/test_mappers_vrc7.py`; *Lagrange Point* and *Tiny Toon Adventures 2* (J) frames equal Mesen2's | detector only | |
| 85 VRC7 sound | the DS1001 from ym2413-python (every internal cycle equal to Nuked-OPLL there), run two clocks per CPU cycle, MO averaged over its last sample; `$E000` D6 holds it in reset; +11.3 dB | `db_vrc7` (the level, by construction); `tests/test_mappers_vrc7.py` | the chip die-derived; the level hardware-measured | the resonator not locked to the CPU (taken as exactly 2:1); the analogue output stage |
| 20 FDS (RAM adapter) | 32 KiB PRG-RAM, 8 KiB CHR-RAM, BIOS; timer IRQ ($4020-$4022: reload, repeat, IRQ while the counter is 0, the acknowledgements); `$4023` resets; `$4025` arrangement, read/write, CRC; the byte transfer flag every 1,792 master ticks and its IRQ; CRC-16/KERMIT; the DRAM refresh watchdog ($4030 D1); the drive: gaps, marks, scan reset, spin-up, end of side | FdsIrqTests v7 (rainwarrior's hardware run: every test and IRQ count), FDS-Mirroring-Test and FDS-4030D1-Addr (Twin Famicom screenshots); `tests/test_fds.py`; frames against Mesen2 (13 games, see validation.md) | hardware answers (registers); detector only (the drive) | the drive's spin-up and head return (C39); `fds_auto.py`'s side changes are a convenience, not the console |
| 20 FDS sound | wavetable and modulator on a 16-cycle prescaler, loopy's pitch formula and accumulators (C42), volume latched at wave position 0, envelopes (4x under `$4083` D7), master volume 1, 2/3, 1/2, 2/5 (the die's ladder), a 2 kHz one-pole low-pass, `$4023` D1 reset, the readable `$4090`-`$4097`; +6.6 dB | `db_fds` (the level, by construction); `tests/test_fds.py`; Mesen2's audio (C43) | hardware-measured level; the units from loopy's test-register readings and the wiki | the DAC's non-linearity (lidnariq's R-2R fit, unmeasured), `$4095`'s high nibble, the 20 kHz poles |
| 30 UNROM 512 | PRG 16 KiB + fixed, 32 KiB CHR-RAM, header-wired nametables (one-screen switchable, cartridge four-screen), 30.3's switchable arrangement, bus conflicts by submapper, the SST39SF040 flash (`cartridge/flash.py`: program, sector and chip erase, ID mode) as the save | `tests/test_mappers_m8.py`, `tests/test_mappers_homebrew.py` (the flash's command sequences, from its data sheet); frames against Mesen2 (aftermarket sample, see validation.md) | detector only | the flash's busy time (program and erase finish at once), 30.4's LEDs (taken, not shown) |
| 28 Action 53 | registers $00/$01/$80/$81 through $5000 select; 32 KiB and UxROM-style PRG modes, outer bank sizes 32-256 KiB, 1-screen/V/H mirroring with D4 of $00/$01 in the 1-screen modes; 32 KiB CHR-RAM; the last 16 KiB at power-on, kept on reset | tepples's `test28` v0.04 (all 131,072 mode/outer/inner combinations, the CHR and mirroring tests, then reset: PASS); 40 of 43 Aftermarket dumps of 28 and 31 equal Mesen2 | community test | the 2012 `test28` in nes-test-roms reports a bus conflict v0.04's own check does not see (an earlier test, superseded); `$4444` (no hardware) |
| 31 NSF subset | PRG-ROM in eight 4 KiB slots switched by $5000-$5FFF (A2-A0), $F000's register $FF at power | rainwarrior's `31_test` at all seven PRG sizes, 16 KiB to 1 MiB (every register and its mirrors PASS, the startup bank the last) | community test | |
| 111 GTROM | 32 KiB PRG banks, 8 KiB CHR-RAM and nametable pages from one register at $5000-$5FFF/$7000-$7FFF that also latches the data bus on reads; four unmirrored screens through $3EFF (the bonus RAM); the SST39SF040 at the bank and A14-A0 as the save | `tests/test_mappers_homebrew.py` (GTROM.wiki, the flash data sheet); frames against Mesen2 (Aftermarket dumps, see validation.md) | detector only | the LEDs (taken, not shown); the register's power-on state (0, unspecified); the CHR-ROM MMC1 variant also numbered 111 (a translation of *Ninja Ryukenden*) |
| 210 Namco 175/340 | 175 RAM enable, 340 arrangements | none | detector only | |
| 206 Namco 108 | 206.0, 206.1 (unbanked 32 KiB) | none | detector only | the Namco 108's spurious bank switch (games avoid it) |
| 32 Irem G-101 | PRG mode, 32.1 one-screen | none | detector only | |
| 33 Taito TC0190 | | none | detector only | |
| 75 VRC1 | PRG registers past their four bits for images over 128 KiB (an extension: *Ninja JaJaMaru*'s 256 KiB reissue, as Mesen2's "oversized PRG") | none | detector only | |
| 87 J87 | swapped CHR bits | none | detector only | |
| 185 CNROM + diodes | 185.4-7 chip selects, D0 pulled up when disabled | `tests/test_mappers_m7.py` | detector only | 185.0 (no licensed dump) |
| 268 AA6023 | 268.0/1 and 268.8/9: outer PRG/CHR banks, GNROM mode, lockout, NEC IRQ | none | detector only | the "weird" modes, mixed CHR-ROM/RAM, mega-UNROM, other PCBs |

**The MMC3's A12 filter** ("after the line has remained low for three
falling edges of M2", MMC3.wiki from Furrtek's MMC3C schematic) is three falls
on the schematic's word, not a judge's: seeded faults show the judges catch
two falls (`2-details`) but pass four, six, eight and sixteen; only 32 fails
(`3-A12_clocking`, `4-scanline_timing`). What does separate three from four,
the 8-dot A12 low after an odd frame's skip with BG at `$1000` (C27), no ROM
here measures. `4-scanline_timing` did need the PPU's address at dot 0 (C27,
settled on PPUSim): without it, `$2000=$10` counted every line twice.

"Detector only" mappers have no judge ROM (docs/cartridge.md): their claim is
milestone 7's sweep, every licensed dump's frames against Mesen2's
(validation.md, milestone 7), plus the unit tests named. In it every dump of
every mapper above runs as on Mesen2 (identical frames, or identical CPU in
lockstep), except where a cause is named there. Two of those causes are
mapper questions no judge settles: the MMC5's in-frame onset (C34) and which
M2 edge clocks a cycle-counting IRQ (C33).

**Not yet**: the licensed dumps the 31 mappers do not reach (4.40 %: 80, 184,
48, 68, 88, 86, 152, 140, 70 and others, a few dumps each; 119 TQROM);
expansion audio (milestone 8).
