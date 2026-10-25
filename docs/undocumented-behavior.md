# Undocumented behaviour, revision differences, contradictions, open items

Nintendo published no hardware manual for the 2A03 or 2C02; what is known comes
from test programs run on consoles, die analysis (Visual 2A03/2C02, Breaks) and
the NESdev community's write-ups of both. This page holds what a board needs
beyond [start-here.md](start-here.md): the quirks, how the chip revisions
differ, where the sources disagree, and what is still open. Paths as in
start-here.md; tiers in [validation.md](validation.md).

## The CPU (2A03 against the NMOS 6502)

1. **Decimal mode is disconnected.** D is set and cleared by SED/CLD, pushed and
   pulled normally; the decimal-adjust signals are cut ("cutting 5 pieces of
   polysilicon"), so ADC and SBC are binary with binary flags (Breaks
   `APU/core.md` "Embedded 6502 Core", die-derived; AccuracyCoin "The Decimal
   Flag", hardware-corrected). The undocumented opcodes that use the adder or
   the decimal fix-up are binary too: **RRA, ISC, USBC ($EB) and ARR**. Checked
   on SingleStepTests `nes6502/v1`: with D set, all 4,948 `ADC #imm` and 4,992
   `ARR` cases give the binary result. Unmodified 6502-python fails 4,732 cases
   of `69.json` and 2,790 of `6b.json`, every one with D set; opcodes 00, 8B, 9E,
   AB fail none. Affected opcodes: ADC 61 65 69 6D 71 75 79 7D; SBC E1 E5 E9 ED
   F1 F5 F9 FD; EB; ARR 6B; RRA 63 67 6F 73 77 7B 7F; ISC E3 E7 EF F3 F7 FB FF.
2. **The instruction decoder is otherwise identical** (Breaks: "No differences
   were found in the instruction decoder"). A few commercial games use
   unofficial opcodes ($80/$89/$04/$DA/$FA NOPs, SLO $07, LAX $B3;
   `CPU_unofficial_opcodes.wiki`).
3. **ANE ($8B) / LXA ($AB) magic constant varies from chip to chip.** AccuracyCoin
   tests only the cases it cannot affect. SingleStepTests `nes6502` uses $EE (the
   one constant that fits all 10,000 cases of each file), as 6502-python does by
   default. **Settled for LXA in milestone 1**: blargg's `instr_test-v5`
   `03-immediate`, whose CRCs were taken on an NES (hardware-corrected), fails
   with $EE and $00 and passes with **$FF**, so the board sets LXA's constant
   to $FF (`Machine.lxa_constant`; 6502-python PR #6 made it a per-CPU
   setting). The emulator-derived $EE loses to the hardware-corrected test.
   ANE ($8B) is excluded from `instr_test-v5` as unstable; no test fixes its
   constant, so it stays $EE.
4. **SHA/SHX/SHY/TAS**: with a DMA halt on the cycle before the write the
   "AND (H+1)" drops out (AccuracyCoin codes 7–C); the high-byte corruption on a
   page cross varies by manufacturer (AND with A&X, X only, A & magic, A | X;
   AccuracyCoin `TEST_SHA_93`). 6502-python implements the No More Secrets model.
   Which one an RP2A03G shows is open; no commercial game depends on it.
5. **Reset suppresses the three stack writes** (reads instead), as 6502-python
   already does.

## The PPU

### Power-up and reset

- Writes to **$2000, $2001, $2005, $2006** are ignored (and w does not flip)
  until the reset flag clears at the first pre-render line; $2002, $2003, $2004,
  $2007 and $4014 work at once (`PPU_power_up_state.wiki`, blargg 2008). The
  internal reset clears PPUCTRL, PPUMASK, t, x, w and the read buffer, **not v**.
- PPUSTATUS at power `+0+x xxxx` (VBL often set); the board powers on with
  overflow set and VBL clear, as PPUSim does (milestone 4). Palette RAM: undefined at
  power, unchanged at reset; blargg's console:
  `09 01 00 01 00 02 02 0D 08 10 08 24 00 00 04 2C 09 01 34 03 00 04 00 14 08 3A 00 02 00 20 2C 08`
  ("probably unique to my NES"); AccuracyCoin: "every console tested appears to
  have a unique and consistent power on state". Mesen2 boots with blargg's table;
  so does the board (`PowerOn.palette`).
  `blargg_ppu_tests_2005.09.15b/power_up_palette` checks that table, so it
  judges one console rather than the 2C02, and is not a gate.
- OAM is DRAM: undefined at power; it decays when not refreshed (holds at least
  one vblank, "not much longer"; `PPU_OAM.wiki`).

### The I/O latch ("PPU open bus")

Any write to $2000–$2007 loads it; $2004/$2007 reads load it; a $2002 read
loads bits 7–5 only; write-only registers read it back. **Decay is a
contradiction** (below, item C1). Proposal: per-bit decay with a configurable
timeout, default between 10 ms and 1 s so blargg's test passes, noting that
hardware is faster.

### OAM and OAMADDR

- 2C02G: a write to $2003 corrupts OAM by copying the old 8-byte row over the
  new (`PPU_registers.wiki`; `nesdev-forum/10189.html`). At render start, an
  OAMADDR ≥ 8 copies the 8 bytes at OAMADDR & $F8 to OAM[0–7] on revisions C,
  E, G, H (`Errata.wiki`). 2C03/04/05/07 don't.
- $2004 writes during rendering don't write OAM but bump OAMADDR's high bits
  ("probably best to completely ignore").

### Bus-level glitches

- **Early writes**: the CPU data bus holds open bus at the start of a write
  cycle, so for PPUCTRL bits 0–1, the first $2005 write and the second $2006
  write the PPU briefly sees the open-bus value for about one dot. A PPUCTRL
  write on dots 257–258 draws the next line from the left nametable (the Super
  Mario Bros. glitch, `nesdev-forum/10104.html`). Reproducible only if the board
  knows the open-bus value at the start of each write cycle; optional.
- **Internal bus conflict**: if the t→v copy of a second $2006 write lands on
  the same dot as a coarse-X or Y increment, the incremented part of v and t
  becomes old v AND t (`PPU_glitches.wiki`; `nesdev-forum/18092.html`).
- $2007 accesses during rendering increment coarse X and Y together.
- Y scroll 240–255 reads attribute bytes as tiles; coarse Y 31 wraps to 0
  without switching nametable.

## The APU

- Pulse 1's sweep negate adds the ones' complement (−c−1), pulse 2's the two's
  complement (−c). **Sweep muting applies whether or not the sweep is enabled**:
  period < 8 or target > $7FF mutes (`APU_Sweep.wiki`).
- The triangle is never silenced by the hardware: silencing halts it at its
  current step (DC hold, pops), and periods 0 and 1 give ultrasonic output that
  averages to 7.5 ("half way between 7 and 8", blargg `apu_ref.txt` l.476–478).
  Many emulators silence it; the reference board does not.
- A $4011 write can be lost when it coincides with a DMC output clock.
- $4015 reads are internal: the external data bus is not driven and open bus is
  not updated; bit 5 is the last open-bus value.
- **Mixing**: the DMC level attenuates triangle and noise (SMB and StarTropics
  use it as a volume control).

### Measured expansion-audio mix levels

dB of a full-volume tone against the APU square, 440 Hz RMS (hardware-captured):

| Chip | rainwarrior 2018 (AV Famicom) | James-F 2018 (HVC-CPU-07) | NSFe `mixe` default (mB) |
| --- | --- | --- | --- |
| APU triangle | −0.3 (Famicom), +0.1 (NES) | −0.03 | −20 |
| VRC6 | +0.2 | −1.11 | 0 |
| VRC7 (square-like patch) | +11.3 | +10.88 | 1100 |
| FDS | +6.6 | | 700 |
| MMC5 | +1.0 | +0.05 | 0 |
| N163, 1 channel | +17.2 to +19.2 | +11.58 to +18.16 | 1100 or 1900 by submapper |
| 5B (volume 12) | −1.3 | | −130 |

`nesdev-forum/17741.html`, `NSFe.wiki` l.207–242, `Namco_163_audio.wiki`
l.229–262. Levels vary by cartridge (N163 boards use different resistors) and
by console revision.

## Revisions as data

### CPU (`CPU_variants.wiki`, `CPU_Test_Mode.wiki`)

| Rev | Dates | Differences |
| --- | --- | --- |
| RP2A03 (letterless) | 1983–84 | M2 duty 17/24 (or 75 % measured, C3); frame counter and DPCM LFSR not reset by /RES; no short noise mode, noise table one LFSR stage shorter ($F = 2046) |
| RP2A03E | 1984–86 | pin 30 = external /RDY (PlayChoice uses it); no APU difference recorded |
| **RP2A03G** | 1987–93 | reference; pin 30 = test mode ($4018–$401A); late runs have the DMC unexpected-reload bug |
| RP2A03H | 1993– | no known differences from late G |
| RP2A07 (PAL) | | ÷16, M2 19/32, PAL noise/DMC/frame tables, DMA register-read glitches fixed |
| UMC clones (Dendy) | | ÷15, NTSC tables, DMC status cleared one APU cycle later |

### PPU (`PPU_variants.wiki`, `Errata.wiki`)

| Part | Differences |
| --- | --- |
| RP2C02 letterless, A, B | $2004 and palette not readable; A: PPUCTRL/PPUMASK asynchronous; A/B: sprite garbage at x = 255; no render-start OAM copy |
| C, D, E | not readable; C/E copy the OAM row at render start; "various OAM evaluation bugs" on E and earlier (UNVERIFIED detail) |
| **G** | $2004 and palette readable (palette read corrupt on one alignment); $2003 corruption; render-start copy. Visual 2C02 and PPUSim model it |
| H | as G; "thought to have fixed some glitches (which?)" |
| 2C07 (PAL) | 312 lines, no odd-frame skip, R/G emphasis swapped, forced OAM refresh lines 265–310, black border |
| 2C03/2C04/2C05 (RGB) | no odd-frame skip (except 2C05-99), emphasis = channel full scale; 2C04 scrambled palettes; 2C05 swaps $2000/$2001 and returns a constant in $2002's low bits |

### Region table (later phases)

| | 2C02 NTSC | 2C07 PAL | Dendy | RGB PPUs |
| --- | --- | --- | --- | --- |
| Lines | 262 | 312 | 312 | 262 |
| Post-render lines before VBL | 1 | 1 | **51** | 1 |
| VBL set line | 241 | 241 | 291 | 241 |
| VBL length | 20 lines | 70 or 71 (C7) | 20 | 20 |
| Odd-frame skip | yes | no | no | no |
| Emphasis bits 7/6/5 | B/G/R | B/R/G | B/R/G | full-scale |

## Contradictions found while gathering

Numbered so other documents can point at them. Each needs its judge named
before the board takes a side.

- **C1. PPU open-bus decay.** blargg `ppu_open_bus` readme: about 600 ms (its
  test #3 needs zero after 1 s, #5/#7 assume bits survive 10 ms). lidnariq's
  2023 hardware test: the fastest bit decays in 4–21 ms, faster when warm
  (`nesdev-forum/24639.html`). The wiki: "3 ms to 30 ms" and elsewhere "at least
  1 ms". Mesen2: 3 frames. *Board (milestone 2)*: per-bit decay, timeout
  `Machine.ppu_latch_decay_seconds`, default 0.6 s (blargg's figure, so his test
  passes); lidnariq's measurement says hardware is faster.
- **C2. NMI suppression window.** The wiki says suppression "may" extend to
  "the following dot or two"; blargg's tests give exactly −1, 0, +1 (other
  alignments shift it by ±1 dot).
- **C3. Letterless 2A03 M2 duty.** Wiki 17/24; Jarhmander's scope capture 75 %
  (18/24, `nesdev-forum/13993-p166761.html`); Breaks `old_2a03.md` states it the
  other way round (15/24 vs 17/24 for G). Matters only to M2-clocked cartridge
  hardware.
- **C4. CPU registers at power.** Wiki and blargg: A = X = Y = 0, P = $34.
  AccuracyCoin: "many consoles were found to have noise in these registers …
  the zero flag has been seen to be set". MAME powers on with X = $80, Z set.
- **C5. $4017 at reset.** Brad Taylor: both bits cleared. blargg (hardware
  tests) and the wiki: the last value is rewritten; IRQ inhibit "sometimes
  cleared".
- **C6. $4017 write delay.** `APU.wiki`: "2 or 3 cycles after the write";
  `APU_Frame_Counter.wiki`: "3 or 4 CPU clock cycles after the write cycle".
  Probably counted from different origins. *Settled in milestone 3* (the
  board counts from the write cycle): 3 cycles when the write lands on an APU
  put, 4 on a get. The other reading moves the frame IRQ one cycle against
  OAM DMA's get/put alignment and `cpu_interrupts_v2/4-irq_and_dma` prints
  "9 +526" where hardware prints "8 +526"; every other APU test passes either
  way (hardware-corrected).
- **C7. Frame IRQ flag while inhibited.** The wiki table: set only if inhibit is
  clear. AccuracyCoin J/K: set for two cycles even when inhibited. *Settled in
  milestone 4 (AccuracyCoin, hardware-corrected)*: set on 29828 and 29829
  whatever the inhibit, cleared on 29830 if inhibited, and no IRQ results; a
  `$4015` read's clear lands at the next put -> get transition.
- **C8. Noise LFSR at power.** Wiki and blargg: 1. `CPU_power_up_state.wiki`:
  $0000, the first clock shifts in a 1.
- **C9. Which 2A03 revisions lack short noise.** Brad Taylor: "revisions before
  F". Wiki and Breaks: only the letterless one.
- **C10. Analogue filter corners.** `APU_Mixer.wiki`: NES high-pass 90 Hz and
  440 Hz, low-pass 14 kHz. Those came from blargg's 2009 fits
  (`nesdev-forum/4946.html`), but his coefficients at 44.1 kHz work out to about
  28 Hz, 1.2 Hz and 11.9 kHz (our arithmetic, UNVERIFIED). rainwarrior's 2018
  sweeps fit a single high-pass of ~16 Hz (NES) and ~32 Hz (Famicom); lidnariq
  gives 37 Hz from the Famicom schematic. The board's analogue presets are
  "fitted" assumptions, cited, not facts.
- **C11. DMC DMA cost.** blargg 2010: "4 normally, 3 on a write"; the wiki:
  "load 3, reload 4". The wiki's get/put model reproduces blargg's table:
  a difference of framing, document the wiki's model. *Board (milestone 3)*:
  the wiki's model, cycle by cycle (`board.py` "DMA"); `sprdma_and_dmc_dma`
  (both) and `dmc_dma_during_read4` pass with it. The two DMC bugs (aborted
  DMA, unexpected reload) are not modelled yet: AccuracyCoin (milestone 4).
- **C12. Rendering-enable latency.** Wiki: 3–4 dots. Mesen2: 1 dot.
  AccuracyCoin: 2–5 dots depending on the PPU revision and the CPU/PPU
  alignment. *Settled on PPUSim (C12 work, after milestone 7)*, with
  PPUSim's internal signals traced (`scripts/ppusim/ppusim_shim.cpp`: the
  object FIFO's counters and shifters, the background shifters, their load
  and step strobes). D is the first dot after the access, where BLACK
  changes:
  - *Stopping*: D still renders. D+1 is a *fade* dot: no ALE, /RD or
    pixel, but the shifters shift and the fetch stage runs once more, its
    latches taking the AD bus, which still carries the low byte of the
    address the PPU drives (the attribute address on the attribute fetch's
    dot, v's nametable address on the others); reloads and increments
    happen. D+2 shifts the background once more (and takes a load D+1's
    ph7 left), and draws the backdrop.
  - *Starting*: D is off. D+1 is a *wake* dot: an ALE dot puts its address
    out (an attribute slot's still the nametable address, so its /RD reads
    a hybrid), nothing shifts, latches or increments. D+2 renders but its
    pixel is still the backdrop, its background does not shift, and its
    ph0 reload, standing for the load a wake dot did not do, is skipped.
    (The extra shift stopping and the missing one starting cancel when
    both fall where the shifters run, so a stop in the sprite fetch, where
    they do not, is what shows them: the PPUSim goldens' `lanes`.)
  - *The pixel multiplexer*: the background enable and clip bits reach the
    pixel a dot after D, the sprite bits a dot later still (a sprite shows
    on the fade dot). Emphasis reaches the pixel looked up on D-1;
    greyscale, asynchronous, also the one before, with the early-write
    value's bit there (PPU_glitches.wiki; the board passes the open-bus
    value at each write).
  - *Sprites*: eight lanes as PPUSim's FIFO: an X counter that steps every
    dot, rendering or not, a per-plane pair of shifters that shift only on
    rendered visible dots, and dot 339's start of the counters, so a lane
    not restarted draws what it has left from the next rendered pixel
    ("Stale Sprite Shift Regs", "Stale BG Shift Registers" 4). The
    overflowed secondary OAM address freezes the fetch at index 0 until
    dot 63, 255 or 339 renders ("Frozen OAM2 Increment"). Evaluation follows
    PPUMASK itself.
  - The attribute latch takes its quadrant on the tile's last fetch dot
    from v then, and the attribute shifters take its bits in serially; the
    tile latch also takes each sprite slot's first garbage nametable read
    (dot 258 reads $2142 where ALE put out $2542: A8-A13 come from v after
    dot 257's copy, the low byte from the octal latch), and no latch takes
    the second (dot 260).
  Every disable and enable at all 8 phases, BG and sprite enable toggles,
  32 off-windows of 1-4 CPU cycles, 49 stops late on a line with a restart
  on the next, and the c12 experiment (both bus models) match PPUSim pixel
  for pixel and ALE for ALE, on blargg's font and on the goldens' denser
  tiles (`tests/ppusim_goldens.json.gz`, replayed by the quick suite); two
  sprite-enable cases whose set-up stops evaluation mid-way do not (open
  item 18). AccuracyCoin's four toggle tests pass. Every revision but the
  2C02G stays open.
- **C13. Odd-frame skip condition.** Diagram and blargg's tests: BG enabled.
  Wiki text: rendering enabled (BG or sprites). *Board*: BG or sprites,
  sampled as dot 338 runs; `ppu_vbl_nmi/10-even_odd_timing` pins the dot (a
  `$2001` write landing after 337 counts, after 338 does not) but not which
  enable bit. *Settled on PPUSim*: sprites alone make the skip too (the wiki
  text, and the board).
- **C14. Sprite evaluation end.** `PPU_sprite_priority.wiki`: dot 240;
  `PPU_sprite_evaluation.wiki`: 256.
- **C15. The second garbage fetch of each sprite slot.** Diagram: an AT fetch;
  text: an NT fetch. *Settled on PPUSim*: a nametable fetch. And the first
  (dot 257) goes out before hori(v) is copied, so its address is v's from the
  end of the line; the board had it after (fixed in milestone 2).
- **C16. 2C07 vblank length.** 70 lines (cycle chart) vs 71 (variants page).
- **C17. MMC3 revision names.** The wiki says the IRQ behaviour splits Sharp vs
  NEC, not by letter; blargg's `mmc3_irq_tests` call the old behaviour "rev A",
  `mmc3_test_2` calls it "MMC3_alt" and notes a chip marked MMC3B behaving that
  way. **Name behaviours (new/Sharp = submapper 4.0, old/NEC = 4.4), never
  letters.**
- **C18. MMC6's IRQ.** blargg's `mmc3_test/6-MMC6` tests the *old* behaviour;
  the NES 2.0 submapper page says MMC6 "uses Sharp MMC3 IRQ behavior".
- **C19. MMC1 power-on bank.** "Reliably … the last bank" vs "fragile"
  (`MMC1.wiki`).
- **C20. Superseded documents.** loopy's 1999 scrolling document (needs both
  layers enabled; v = t at line 0) and Brad Taylor's 2004 2C02 reference (MMC3
  counts A13; both scroll copies at dot 256; 4 dots per evaluation step) are
  wrong where the wiki has since been corrected. Cite them for history only.
- **C21. $2006 t→v delay.** "1 to 1.5 dots after the write completes" vs "about
  3 dots after the register write begins": probably the same instant. *Settled
  on PPUSim*: the copy lands 2 dots after the board's access point (a dot
  after M2 falls), on either bus model; `ppu.DELAYS`. With rendering off,
  PPUSim emits no ALE for it (v reaches the cartridge on PA8–13 only); the
  board reports it as an ALE address, which gives a mapper the same A12.
- **C22. When a `$2007` access increments v.** Mesen2 increments one dot after
  the access, so with rendering off the backdrop override shows the *written*
  palette entry for one dot; the board incremented at the access. Found by
  pixel comparison: `full_palette` differed from Mesen2 in exactly one pixel
  per colour boundary (767). *Settled on PPUSim*: a write reaches palette RAM 3
  dots after the board's access point and v increments a dot later, after a
  read too, on either bus model; the override shows the old entry for 3 dots
  and the written one for 1. The board does that (`ppu.DELAYS`), so it now
  differs from Mesen2 the other way (validation.md, milestone 2). *Milestone
  3*, accesses one CPU cycle apart: a `$2007` read refills the buffer when its
  increment lands (4 dots on), and a second read before then returns the
  buffer and starts nothing; a write takes v as it lands, so after a read one
  cycle earlier it goes to the incremented address. PPUSim at the board's
  skew prints blargg's hardware results for both (`double_2007_read`
  F018C287, `dma_2007_read` 159A7A8F; `read_write_2007` passes), and the
  board matches.
- **C24. Does a `$4015` read drive the external bus?** `APU.wiki` l.204–205
  and the board: no, and open bus keeps its value. APUSim drives the data
  pads while `$4015` is read (`dma.cpp`: WR = NAND3(/R4015, /DBGRD, RW)), so
  open bus would take the status. *Settled in milestone 4 by AccuracyCoin
  "Internal Data Bus"*: the 2A03 has an internal data bus beside the external
  one. Every CPU read and write updates the internal bus, DMA reads do not;
  every access but a `$4015` read updates the external bus, which open bus
  returns. `$4015`'s bit 5 is the internal bus's. The board models both
  (`Board.internal_bus`, `Board.data_bus`).
- **C25. The 2A03's register decode during DMA.** DMA.wiki: bits 4-0 from the
  DMA's address, 15-5 from the halted 6502's. *Board (milestone 4), to
  AccuracyCoin's expected tables* ("APU Register Activation", "DMC DMA Bus
  Conflicts", "Controller Clocking"): with the core halted on `$4000-$401F`,
  any DMA read also selects register `$4000 | (address & $1F)`; `$4015`
  drives every bit but 5 (from the bus), the pad ports clock their pad and
  drive its bits onto the external bus under bits 7-5 of whatever else drives
  it, while a DMA with a device at its address takes that device's byte.
  With the core elsewhere, DMA reads of `$4000-$401F` see open bus.
- **C26. OAM corruption.** Errata.wiki lists several mid-access row copies,
  most alignment-dependent; AccuracyCoin "OAM Corruption" describes row 0
  copied over the row of the secondary OAM address when rendering was turned
  off, on "the first PPU cycle after rendering is enabled". blargg's
  `sprite_overflow_tests/5.Emulator` (also passing on hardware) re-enables
  rendering mid-frame and must see no corruption. *Board*: Errata's
  deterministic case only: the address freezes when rendering goes off
  mid-line, a visible-line re-enable lets it count again (back to 0 by the
  line's end), and if it is still frozen when rendering begins at the
  pre-render line, the OAMADDR row is copied over it. Both tests pass.
- **C23. PPUSim's `$2002` bit 7.** Breaknes PPUSim `fb7de61` drives it as the
  complement of the VBL flag (`fsm.cpp`, `db_latch.nget()`); its own wiki
  drawing, its author's Verilog and the Visual2C02 netlist all show the true
  flag. Reported as emu-russia/breaknes#529 (with the netlist trace);
  `scripts/ppusim_board.py` corrects it until a fixed pin.
- **C27. The PPU address bus at dot 0.** `PPU_rendering.wiki` "Cycle 0": the
  idle dot's address "appears to be" the CHR address of dot 5's low pattern
  fetch, "possibly calculated during the two unused NT fetches"; the board
  put nothing on the bus there. With BG at `$1000` that matters to an MMC3:
  A12 is otherwise low from the dot-337 nametable fetch to dot 5, 9 dots,
  exactly three M2 falls, so every line clocked twice and blargg's
  `4-scanline_timing` #12 failed. *Settled on PPUSim* (`fb7de61`, skew 3,
  rendering with `$2000=$10`): after a rendering line, dot 0 carries the
  pattern address (A12 high at (N, 0)); after the last vblank line it does
  not (A12 stays low to (261, 5)); and on odd frames, whose skip takes dot
  340, (0, 0) has no address either, so A12 is low for 8 dots and the MMC3
  may count twice: the wiki's "pre-render scanline will decrement the counter
  twice every other vertical redraw". *Board*: the address phase at dot 0 only
  when dot 340's nametable fetch was the previous dot.
- **C28. rainwarrior's expected results vs his ROMs.** `3_test.txt` says
  "PRG RAM: NO" and `34_test.txt` "CHR RAM: NO" for 34.1, but the ROMs in the
  same archives print YES on any board: each loads the result, then
  `PPU_LATCH_AT` loads A with the screen address's low byte (`$FA`, `$1A`)
  before `yes_no` tests A. `34_test`'s "BNROM BUS CONFLICTS" line is printed
  the same way, so BNROM's conflicts have no judge (a seeded fault removing
  them passed every one). The .txt cannot have come from these builds (or
  the source changed after); the harness claims only the other values.
- **C29. Does a taken branch delay an NMI, or only an IRQ?**
  `CPU_interrupts.wiki` says interrupts: a taken same-page branch "ignores
  IRQ/NMI during its last clock". Mesen2 (`b9fa69d`, `NesCpu.h`
  `BranchRelative`) says NMI too in its comment but delays only the IRQ in its
  code. *Settled on perfect6502* (`scripts/perfect6502_nmi_branch.c`): with
  /NMI falling 1-2 half-cycles after the opcode fetch, a JMP takes it after
  itself and a taken BEQ only after the next instruction. The board
  (6502-python's branch poll points) delays both. Found in lockstep: Mega Man
  2, Kirby's Adventure and Battletoads wait for VBL in `LDA; BEQ`/`BPL` loops.
- **C30. An interrupt raised while DMA halts the CPU.** No document says. The
  board ran DMA inside the read callback, so 6502-python saw a request raised
  during the stall only after the read, as if late. *Settled on perfect6502*
  with RDY held low for four cycles (`scripts/perfect6502_nmi_dma.c`): the
  halted chip repeats the read and keeps sampling, so an NMI falling during
  the halt is polled at the end of the read it stretched, whichever cycle: a
  JMP's penultimate or last read, a taken BEQ's operand or next-opcode read.
  *Board*: `Board.read_byte` calls 6502-python's `note_stall()` after a DMA
  (its PR #7). Found in lockstep: Kirby's Adventure, VBL's NMI during a DMC
  DMA inside its wait-loop `BEQ`.
- **C31. A $2007 read during rendering, on the PPU bus.** The wiki says the
  read "will cause" both increments and that the buffer gets "the value read";
  AccuracyCoin's notes ("ALE + Read", "Hybrid Addresses", "$2007 Stress Test",
  hardware answer keys) describe the octal latch: PA0-7 are latched on ALE,
  PA8-13 follow the address register every cycle. *Settled on PPUSim*
  (`fb7de61`, `vram_ctrl.cpp` and half-cycle pin traces): a $2007 read's own
  ALE comes 2 dots after the access (`tmp_2`) and its /RD 2 dots later
  (`PD_RB`, which also increments v). Rendering's ALE wins over the read's;
  ALE and /RD on the same dot feed the latch back on itself once per master
  half-cycle they overlap: the read's ALE on a fetch's /RD dot for the whole
  dot (7 steps from the fetch's low byte; the fetch reads at the result), its
  /RD on a fetch's ALE dot for half of it (3 steps from the byte on the bus;
  the buffer and the next fetch read at the result). On a fetch's /RD dot the
  buffer takes that fetch, whose low byte its ALE latched before the
  increment. A $2006 copy landing between a fetch's ALE and /RD gives the
  same hybrid address. *Board*: `PPU._octal`, `_read_2007_ale`,
  `_complete_2007_read`, `_copy_t`; 16 of 16 read phases leave PPUSim's
  buffer; the three AccuracyCoin tests pass. The feedback is analogue on
  hardware, PPUSim's step counts are its model of it. Not modelled: a $2007
  *write* during rendering (open item 8).
- **C32. OAMADDR when rendering starts.** Errata.wiki: on 2C02C-H, an OAMADDR
  of 8 or more when rendering starts copies the 8 bytes at OAMADDR & $F8 over
  OAM[0-7]; Mesen2 does (`DisableOamAddrBug` off by default). PPUSim does not:
  with OAMADDR left at $80 or $84 by $2004 writes (no $2003 write, which has
  its own corruption) and a sprite only in row $80, it shows no sprite-0 hit,
  as the board; the control, the sprite in row 0, hits in both
  (`scripts/ppusim_compare.py oam_start`). PPUSim's OAM is logic, and the
  Errata's effects are thought to be the DRAM's, so it may simply not model
  this; no hardware-corrected test was found. *Board*: no copy. Open. Found
  in milestone 7's sweep: *Tatakai no Banka* writes $2003 = $80 before its
  OAM DMA, and on Mesen2 a sprite-0 hit follows.
- **C33. Which M2 edge clocks a cycle-counting IRQ.** The VRC4's, the
  LZ93D50's, the FME-7's counters count M2 cycles; no document says on which
  edge, so whether /IRQ falls before or after the CPU samples it in that
  cycle. *Board*: the cartridge's `m2()` runs at the cycle's end and /IRQ is
  sampled at once (the APU's frame IRQ takes the same path, judged by
  blargg's timing ROMs). Mesen2 takes the IRQ one instruction later in three
  dumps' lockstep (*Racer Mini Yonku*, *TMNT 2* (J), *SD Gundam Gaiden 2*),
  and in the VRC6's (*Akumajou Densetsu*, milestone 8: 63,185 instructions
  in, the board's IRQ entry one instruction before Mesen2's).
  AWJ's `vrctest` times the IRQ on a 5-cycle slide and says itself its
  adjustment may be one off on hardware: no judge. Open.
- **C34. When the MMC5's in-frame flag starts the extended attributes.**
  `MMC5.wiki`: the scanline is detected at three identical nametable reads.
  *Board*: in-frame from the third read, the column-2 tile fetch of line 0,
  so its attribute fetch is the extended one; Mesen2 starts one fetch later
  (4-16 pixels of row 0 in seven Koei dumps). No judge. Open.
- **C35. Line 0's sprites from a stale slot 0.** With no sprite in range of
  line 239, evaluation leaves the last sprite's Y in secondary OAM slot 0
  (tile, attribute and X $FF); the pre-render line's fetches check every slot
  against 261 & 255 = 5 (AccuracyCoin "Sprites On Scanline 0"), so a
  last Y of 0-5 draws tile $FF's column 0 at x = 255 of line 0. *Settled on
  PPUSim* (`scripts/ppusim_line0.py`: Y $00 and $03 draw it in both, $F8
  neither, the same fetch addresses). Mesen2 draws nothing there: thirteen
  licensed dumps differ by that one pixel.
- **C36. Which end of its period the VRC6 pulse is high.** VRC6_audio.wiki:
  the duty generator counts down from 15 and the volume is output while the
  step is at or below D (the pulse high at the end of each period, "inverted
  compared to the 2A03"). Mesen2 counts up from 0 with the same test (high
  at the start). Kevin Horton's `vrcvi.txt`, the wiki's source, does not
  say. Same duty and level, so only the pulses' phase against the saw and
  each other moves: with Mesen2's direction *Akumajou Densetsu*'s VRC6
  alone matches Mesen2 to -7 to -16 dB, near the APU's own floor against
  it (milestone 3), and to -0.3 to -3 dB with the wiki's. *Board*: the
  wiki's. No judge (NewRisingSun's hardware recordings, which could settle
  it, are no longer reachable: open item 20).
- **C37. The N163's channels: taken in turn, or summed.** Namco_163_audio.wiki:
  the chip outputs one channel at a time, each held 15 CPU cycles, and
  "it is often preferred to simply sum the channel outputs, and divide";
  Mesen2 sums and divides. *Board*: in turn, as the chip, which with 7 or
  8 channels makes the whine the wiki describes (at 17.0 and 14.9 kHz).
  With 6 or fewer the switching is ultrasonic and the board's output stage
  must keep it from folding into the audible band: the APU's decimating
  low-pass (milestone 8) leaves it 20 dB under a 4-channel game's music
  (*Rolling Thunder*), where a plain box filter left it 3 dB under.

## Open items

1. **Settle on PPUSim (die-derived)**: *done in milestone 2* for C13, C15, C21,
   C22, the colour half of C12 and the empty-slot row (PPUSim: once n wraps
   nothing more lands in secondary OAM, so the next free slot keeps OAM[63]'s
   Y and the row is line − OAM[63].Y, flipped by the $FF attribute; Mesen2
   uses row 0). PPUSim first reproduced `ppu_vbl_nmi` 10/10, at one of eight
   half-cycle skews (validation.md). Still open: mid-line BG enable and
   disable (C12), whether the board's CPU-side bus timing (M2 duty, C3; the
   early-write value) is right, every PPU revision but 2C02G, and PPUSim's
   backdrop at the frame's first pixel (0, 0) (validation.md, milestone 2).
2. **APUSim (die-derived) as a per-cycle APU judge**: *checked in milestone 3,
   not usable at `fb7de61`*. On a stub board around the whole simulated chip
   (`scripts/apusim_board.py`) it passes 3 of 8 `apu_test` singles, the three
   frame-IRQ tests. The length tests fail because bits 0–3 of `$4015` never
   reach its 6502: the length counters drive them from `sim_SoundGenerators`,
   which runs only on PHI0 edges and after the core in each step, while the
   core samples the bus at that edge; bits 4 and 6, updated every half cycle,
   arrive (shown with a six-instruction program; the counters themselves
   load). `7-dmc_basics` #19 and `8-dmc_rates` #2 fail undiagnosed: the stub
   board may be the cause. Worth reporting upstream once checked further, with
   the user's agreement. It stores a revision but branches on none:
   effectively 2A03G only. Its DAC is fitted to one voltage, so it cannot
   judge the mixer.
3. AV Famicom and NES-101 reset wiring (does the button reset the PPU?).
4. The $4016 output latch after reset; exactly when OUT0–2 update.
5. Which SHA/SHS behaviour and which ANE/LXA magic an RP2A03G shows.
6. Reset is asynchronous on hardware; 6502-python takes it at a boundary.
   Harmless for a button; `apu_reset/4017_timing` measures 9–12 clocks and may
   care.
7. The palette-read corruption alignment, and whether 2C02G's "two variants"
   (PCLK distribution, `PPUSim ppu.h` l.149) change anything modelled.
8. What a $2007 *write* during rendering writes, and where.
9. 2C02H differences from G; the E-and-earlier OAM evaluation bugs.
10. PAL/Dendy VBL clear timing; PAL APU beyond the frame sequencer (only
    `pal_apu_tests` exist).
11. Per-console analogue presets need recordings (rainwarrior's raw data was
    never published; no NES MDFourier set was found).
12. FirebrandX's "Composite Direct" palette: the site answered HTTP 465 to our
    fetcher; download by hand if wanted, and its licence is unstated. The
    licence of the Visual 2C02/2A03 netlist data is also unstated.
13. The letterless 2A03's noise period table in text (Breaks has it as an image).
14. MMC6 IRQ behaviour (C18; the board gives MMC6 Sharp's, as the NES 2.0
    page says, and runs blargg's `6-MMC6` on 4.4), MC-ACC's prescaler phase,
    MMC3 Sharp vs NEC per licensed game (nes20db assigns 4.0 to all), MMC2 latch timing (no test ROM), MMC5's in-frame exit
    on $2001 and its $4014 snooping ("believed but not tested").
15. The other three CPU/PPU synchronizations. The board models blargg's third
    only (timing.md): accesses at whole-dot positions cannot tell the four
    apart, and the per-event sub-dot phases that would are not pinned by any
    oracle we have. Tests that pass on hardware in only some alignments
    (`oam_stress`, `double_2007_read`, ...) judge the board only in that one.
16. **Pulse edges against `$4011` writes.** `apu_mixer/dmc.nes` cancels pulse 1
    with `$4011` writes blargg timed on hardware; the board leaves a
    1-CPU-cycle step at every pulse edge (2 at the other APU power-on parity,
    and 2 if pulse timers clock on puts), while the triangle test, whose timer
    counts CPU cycles, cancels on the cycle. The test does not synchronise to
    the APU, so hardware may show the step too; Mesen2 cancels about 6 dB
    deeper. A pulse timer phase or output latency the tests cannot see:
    APUSim's question, once it works (open item 2).
17. **Triangle and DMC loudness.** Against the NES-001 recording of
    `volume_tests`, pulse levels agree within 0.3 dB but the triangle reads
    0.8 dB loud and the DMC tone 0.4–1.5 dB loud (validation.md, milestone 3).
    The recording's analogue path is uncharacterised, so this is evidence, not
    a verdict on blargg's formula.
18. **AccuracyCoin's remaining two**: "$2004 Stress Test" 3 (one byte, dot
    199, the overflow scan's fourth copy read) and "Misaligned OAM2 Address"
    4, which PPUSim fails as well. The five PPUSim passes are fixed: four
    mid-line toggles (C12) and "$2002 flag timing" 2, where the overflow
    flag reaches PPUSTATUS a dot after the evaluation's in-range check (the
    sprite-0 flag stays on its pixel's dot; a comparison that read our
    PPUSTATUS at the access and PPUSim's as M2 falls had suggested a dot
    earlier). Left of C12: when rendering stops during sprite evaluation and
    restarts before the line ends, PPUSim's secondary OAM takes one more,
    misaligned, entry (`53 02 65 68`) and ours none (the goldens' two
    `mux` cases, kept as KNOWN in `tests/test_ppusim_goldens.py`): the
    same corner as "Misaligned OAM2 Address", unmodelled.
19. **Milestone 7's open three**: the render-start OAM copy (C32), the M2
    edge of cycle-counting IRQs (C33), the MMC5's in-frame onset (C34). Each
    needs a hardware-corrected test; none was found.
20. **Expansion-audio recordings.** NewRisingSun's 2018 test ROMs
    (`VRC6TEST`/`VRC6TESA`, MMC5, `N163TEST`: fifteen volume steps of each
    chip's square and saw, the MMC5 DAC, N163 one and eight channels) were
    recorded on hardware (nesdev-forum/16910.html), which would judge the
    VRC6's and MMC5's volume curves, C36 and C37. On 2026-10-24 the forum
    answered "not authorised" to every attachment (the pinned `vrctest.zip`
    too), the recordings' host 404, and archive.org rate-limited the
    lookup: retry, or download by hand.
