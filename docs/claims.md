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

**The MMC3's A12 filter** ("after the line has remained low for three
falling edges of M2", MMC3.wiki from Furrtek's MMC3C schematic) is three falls
on the schematic's word, not a judge's: seeded faults show the judges catch
two falls (`2-details`) but pass four, six, eight and sixteen; only 32 fails
(`3-A12_clocking`, `4-scanline_timing`). What does separate three from four,
the 8-dot A12 low after an odd frame's skip with BG at `$1000` (C27), no ROM
here measures. `4-scanline_timing` did need the PPU's address at dot 0 (C27,
settled on PPUSim): without it, `$2000=$10` counted every line twice.

**Not yet**: mapper 118 (TxSROM) and 119 (TQROM), though HM tests 118; the
coverage-order mappers of milestone 7; expansion audio (milestone 8).
