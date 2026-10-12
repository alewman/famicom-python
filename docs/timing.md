# Timing: the cycle, the dot, and when things happen

Most NES behaviour that games and test ROMs notice is timing: when the CPU
samples an interrupt, which cycle a DMA steals, which dot a $2002 read lands on,
which APU half-cycle a $4017 write takes effect. Every number names its source;
tiers are in [validation.md](validation.md). Paths as in
[start-here.md](start-here.md).

## The units and the one timeline

- **Master tick**: 1/21,477,272 s (NTSC). CPU cycle = 12 ticks, PPU dot = 4
  ticks, so 3 dots per CPU cycle exactly.
- **APU cycle** = 2 CPU cycles; its first half is *get*, its second *put*
  (`DMA.wiki` "Cadence"; APU cycle N's put = CPU cycle 2N+1).
- **Alignment**: the CPU ÷12 and PPU ÷4 dividers are separate, so at power or
  reset the CPU lands in one of **4** phases relative to the dot (blargg,
  hardware-captured over 50–60 power cycles: 27/15/31/27 % at power;
  `nesdev-forum/6186.html`). "The third synchronization is the preferred one for
  emulators and test ROMs, due to the least special cases, and highest
  likelihood." Independently, the CPU powers up on a get or a put (2
  possibilities, `DMA.wiki`). So there are 8 NTSC power-on phases. *Settled in
  milestone 2*: the board models blargg's third synchronization only; the APU
  parity stays a parameter (`PowerOn.apu_put_first`). Within a CPU cycle the
  PPU sees a register access **two dots (8 master ticks) in**, while M2 is
  high; the CPU samples /NMI and /IRQ at the cycle's end. Of the three dot
  positions for reads and for writes, only that pair passes `ppu_vbl_nmi` and
  `vbl_nmi_timing` (17 ROMs; docs/validation.md, milestone 2). With accesses at
  whole-dot positions the four alignments cannot differ, so `PowerOn` has no
  alignment field; blargg's table shows the other three moving single events
  by a dot each, which needs per-event sub-dot phases nothing pinned gives
  (undocumented-behavior.md, open items).
- Alignment-sensitive tests, by their own readmes: `dmc_dma_during_read4/dma_2007_read`
  (two valid CRCs), `double_2007_read` (four), `cpu_interrupts_v2/2-nmi_and_brk`
  ("occasionally fails on NES"), `oam_stress` (passes in 1 of 4), `oam_read`,
  palette-RAM read corruption, `ppu_vbl_nmi/10-even_odd_timing`. A test that
  passes on hardware in only some alignments judges only those.

**The board clocks from inside the bus callbacks.** 6502-python makes exactly
one `read_byte`/`write_byte` call per CPU cycle, dummy reads and RMW dummy
writes included (verified: 60,000 SingleStepTests `nes6502` cases, 0 bus
mismatches). So the board advances the PPU by 3 dots and the APU by one CPU
cycle in each callback, before or after the access as the access's phase
requires, and never adds `step()`'s return value on top. Mid-instruction
register timing then falls out exactly, which the Z80 boards had to approximate
with access-time tables.

## Interrupts

### What the hardware does

`CPU_interrupts.wiki` (derived from Visual 6502), the Visual6502 wiki pages
mirrored on NESdev (die-derived), blargg `cpu_interrupts_v2` and AccuracyCoin
page 12 (hardware-corrected):

1. **Detectors.** NMI: an edge detector samples /NMI in φ2 of every cycle; a
   high→low change raises an internal signal in the next cycle, held until
   serviced. IRQ: a level detector samples in φ2; its output is high in the
   next cycle only.
2. **Poll point.** The detectors' outputs are polled in the instruction's last
   cycle, so "it's really the status of the interrupt lines at the end of the
   second-to-last cycle that matters". Two-cycle instructions poll at the end of
   cycle 1.
3. NMI and IRQ both pending: NMI is taken; the IRQ is forgotten and re-detected
   later if still asserted.
4. **Interrupt sequences and BRK do not poll**: "at least one instruction from
   the interrupt handler will execute before another interrupt is serviced".
5. **CLI, SEI, PLP** change I after their poll; **RTI** restores I before its
   poll. blargg `1-cli_latency`: exactly one instruction after CLI runs before
   the IRQ; CLI SEI, CLI PLP, PLP SEI and PLP PLP each let exactly one IRQ
   through; CLI RTI lets none.
6. **Branches**: "Interrupts are always polled before the second CPU cycle (the
   operand fetch), but not before the third CPU cycle on a taken branch.
   Additionally, for taken branches that cross a page boundary, interrupts are
   polled before the PCH fixup cycle". So: not taken (2 cycles) is normal;
   taken on the same page (3 cycles) polls only at the end of cycle 1, so an
   interrupt arriving in cycle 2 waits one more instruction; taken across a page
   (4 cycles) polls at the end of cycle 1 *or* cycle 3. Judges:
   `cpu_interrupts_v2/5-branch_delays_irq`, AccuracyCoin "Interrupt Flag
   Latency" codes 9, A, B, E.
7. **Hijacking**: the vector is chosen after cycle 4 of BRK/IRQ/NMI (the PCL
   push), before cycle 5. An NMI asserted during the first four cycles of BRK or
   of an IRQ sequence makes it fetch $FFFA (BRK still pushes B = 1). Judges:
   `2-nmi_and_brk`, `3-nmi_and_irq`, AccuracyCoin "NMI Overlap BRK/IRQ".
8. **During DMA** a halted CPU "repeats the last read cycle indefinitely, making
   no forward progress nor handling interrupts" (`DMA.wiki`). blargg
   `4-irq_and_dma`: an IRQ anywhere during an OAM DMA (+11 … +526 after the
   `STA $4014`) is taken **after the instruction that follows** the STA.

### What 6502-python does today, and the pull requests that follow

`MOS6502.step()` decides at the **instruction boundary** from the latched NMI,
the IRQ line and I (or `_polled_i` after CLI/SEI/PLP). Its own
`docs/validation.md` "Limits" says: "an IRQ that a device raises from inside a
bus callback during the last cycle is, on hardware, taken one instruction later
than here." Because this board raises its interrupts from inside the callbacks,
today's core:

- takes an IRQ or NMI asserted in an instruction's **last** cycle one
  instruction early;
- misses an IRQ asserted at the end of the penultimate cycle and released in
  the last (an instruction ending in a $4015 read that acknowledges the frame
  IRQ);
- runs no handler instruction before an NMI that arrives during an IRQ entry or
  BRK's vector reads;
- checks the hijack after cycle 5 (one cycle too late);
- treats a taken same-page branch like any instruction;
- gets `4-irq_and_dma` wrong when DMA runs inside the stalled read.

These are the core pull requests in [handoff-brief.md](handoff-brief.md)
("Prerequisites"). The cheapest readable design: before each bus access the 2A03
variant copies the current NMI-latch and IRQ-line state into "seen" fields, and
`step()` decides from the fields as they stood at the end of the penultimate
cycle, with BRK and interrupt entries suppressing their own poll, the hijack
decided on the state at the end of cycle 4, and the branch rule above.
`CPUState` carries the seen state so capture and restore stay exact.

## DMA

### OAM DMA ($4014)

`DMA.wiki` "OAM DMA" (secondary over Breaks `APU/dma.md`, die-derived, and
hardware tests by blargg, Disch and Fiskbit):

```
          (get) CPU writes $4014
 (halted) (put) CPU reads A        <- halt cycle: A is the read the CPU attempted next
 (halted) (get) DMA reads $xx00
 (halted) (put) DMA writes $2004
   ... 256 get/put pairs ...
 (halted) (put) DMA writes $2004
          (get) CPU reads A        <- the CPU resumes and performs the stalled read
```

If the $4014 write lands on a put, the halt lands on a get and one alignment
cycle (another read of A) is added: **513 or 514 cycles**. The halt takes effect
only on a CPU *read* cycle (Breaks: "RDY clearing is ignored on the 6502 write
cycles"), so a write sequence (RMW: 2 writes; an interrupt entry: 3) delays it.
The page is the last value written to $4014.

### DMC DMA

```
Load (after a $4015 write enables the DMC with an empty buffer; halts on the get
of the 2nd APU cycle after the write):
 (halted) (get) CPU reads A   <- halt
 (halted) (put) CPU reads A   <- dummy
 (halted) (get) DMA reads B
          (put) CPU reads A   <- resume
Reload (the sample buffer emptied; halts on a put):
 (halted) (put) CPU reads A   <- halt
 (halted) (get) CPU reads A   <- dummy
 (halted) (put) CPU reads A   <- alignment
 (halted) (get) DMA reads B
          (put) CPU reads A   <- resume
```

Load costs 3 cycles, reload 4, unless write cycles delay the halt (`DMA.wiki`
"DMC DMA"). blargg's 2010 hardware measurement in the older framing: "4 cycles
normally, 3 if it lands on a CPU write, 2 if it lands on the $4014 write or
during OAM DMA, 1 if on the next-to-next-to-last DMA cycle, 3 if on the last"
(`nesdev-forum/6100-p62690.html`); the get/put model reproduces it. Bugs
(hardware-captured by Fiskbit, `DMA.wiki` "Bugs"): stopping playback in the APU
cycle before a scheduled reload produces a lone halt cycle; on late RP2A03G and
H an implicit stop on the reload's APU cycle schedules an extra reload
(AccuracyCoin "Implicit DMA Abort" codes 1/2).

### What the re-reads do

- The halted 6502 **repeats its stalled read** on every DMA cycle that is not a
  DMA access, visibly on the bus. A stalled `LDA $2007` therefore increments v
  2–3 extra times (blargg `dma_2007_read`; since milestone 2 each increment
  lands 4 dots after its read, with the buffer refill, and a read in those 4
  dots is ignored: so of the CPU's reads on consecutive cycles only every
  other one counts, and `dma_2007_read` shows two extra reads, as PPUSim
  does at the board's skew; undocumented-behavior.md C22); a stalled $4015
  read clears the
  frame IRQ flag (AccuracyCoin "DMA + $4015 Read"); a stalled $2002 read clears
  VBL.
- $4016/$4017: pads are clocked by /OE, not by the address, so on the NES-001 a
  contiguous run of reads is one clock (blargg `dma_4016_read` prints
  `08 08 07 08 08`); on the RF Famicom each read clocks.
- **Address composition quirk**: the 2A03's register decode takes bits 4–0 from
  the DMA-multiplexed address bus but bits 15–5 from the 6502 core's. With the
  core halted on a read of $4000–$401F, a DMC fetch from, say, $C017 also clocks
  joypad 2 (AccuracyCoin "DMC DMA Bus Conflicts", "APU Register Activation";
  Breaks `APU/core.md` signal table).
- Writes are never stalled: "DMC DMA during $2007 write has no effect" (blargg).
- The 2A07 fixes the register conflicts (mechanism unknown, PAL later).

### The design: DMA inside `read_byte`, no RDY input

During a 2A03 DMA the core is stalled on a read, every idle DMA cycle is a
visible repeat of that read, the real read comes last, and DMA never halts a
write. 6502-python makes one `read_byte` call per read cycle. So the board runs
both DMAs **inside its `read_byte` callback**: when a DMA is due and the current
cycle is a read of A, it runs the halt, dummy and alignment cycles as reads of A
(clocking PPU and APU each cycle, with their side effects, and the decode quirk
using A's high bits), the get/put DMA cycles, then the real read of A, and
returns that value. A DMA that becomes due in `write_byte` waits for the next
read. The core needs no RDY input. Two consequences the board owns: `step()`'s
cycle count excludes stolen cycles (the board's own clock is the truth), and
stall cycles are visible only in a board-level trace. This is exact only once
the core polls interrupts as above (otherwise `4-irq_and_dma` returns 7 where
hardware returns 8).

As built (milestone 3, `board.py` "DMA"): one loop serves both units. Its
first cycle is the halt; a DMC fetch reads on the first get at least two
cycles after its halt cycle (halt, dummy, then alignment if needed), and a
fetch requested while the CPU is already halted counts the cycle it appears
in as its halt; OAM DMA reads on a get the DMC does not take and writes on
the next put; every other cycle repeats the CPU's read. The APU raises the
request (`APU.dmc_request`): a load on the get of the second APU cycle after
the enabling `$4015` write, a reload on the put of the APU cycle whose output
clock emptied the buffer. Not yet modelled: the address-composition quirk
(the halted CPU's `$4000–$401F` read combined with the DMC address) and the
two DMC bugs, both AccuracyCoin's (milestone 4).

The one place DMA changes the CPU's own result: SHA/SHX/SHY/TAS drop their
"AND (high byte + 1)" when RDY was low before the write cycle (AccuracyCoin
unofficial-opcode codes 7–C). An optional tiny core hook; no game is known to
need it.

## The PPU

### The dot schedule (visible lines 0–239 and the pre-render line 261)

`PPU_rendering.wiki`, `PPU_scrolling.wiki`, and the frame-timing diagram
`reference/nesdev-wiki/images/Ntsc_timing.png` (Ulfalizer, beannaich, Quietust;
its dot numbering is Visual 2C02's, so die-derived). "Rendering enabled" means
PPUMASK bit 3 OR bit 4.

| Dots | PPU bus (each fetch: address with ALE on the 1st dot, /RD on the 2nd) | v | Other |
| --- | --- | --- | --- |
| 0 | idle (the bus shows the address of the next pattern fetch) | | skipped on line 0 of odd frames with rendering on |
| 1–256 | 32 × [NT, AT, pattern low, pattern high] | coarse X++ at 8, 16, …, 256; **Y++ at 256** | shift reload at 9, 17, …, 257; pixels out |
| 257 | | **hori(v) = hori(t)** (bits 10, 4–0) | OAMADDR = 0 on each of 257–320 |
| 257–320 | 8 × [garbage NT, garbage NT, sprite pattern low, high] | | |
| 280–304, pre-render only | | **vert(v) = vert(t)** on every dot (bits 14–11, 9–5) | |
| 321–336 | 2 × [NT, AT, low, high]: tiles 1–2 of the next line | coarse X++ at 328, 336 | |
| 337–340 | NT, NT (the next line's first NT address again) | | MMC5 counts these as the third of three equal reads |

Addresses: NT = $2000 | (v & $0FFF); AT = $23C0 | (v & $0C00) | ((v >> 4) & $38)
| ((v >> 2) & $07); pattern = table + 16·tile + fine Y (v[14:12]), +8 for the
high plane. Empty sprite slots fetch **tile $FF** (secondary OAM is $FF-filled):
$0FF0/$1FF0 in 8×8 mode, the $1000 table in 8×16 mode. That fetch is what
keeps MMC3's A12 counter clocking once per line. **Outside rendering the PPU
drives v on the address bus continuously**, so a $2006 write can clock MMC3.

### Pixels

Two 16-bit pattern shift registers plus attribute shifters; shifting on dots
2–257 and 322–337; fine x selects the bit. The first pixel comes out on dot 4,
sprite-0 hit can be set from dot 2 (`Ntsc_timing.png` notes). Priority:
transparent BG and sprite → backdrop; the sprite picked is the lowest-numbered
one with an opaque pixel *before* the BG test (the sprite-priority quirk,
`PPU_sprite_priority.wiki`). With rendering off every dot shows the backdrop
($3F00), unless v points into $3F00–$3FFF, when it shows that palette entry
("backdrop override", `PPU_palettes.wiki`).

### Frame events (NTSC)

| Event | When | Source |
| --- | --- | --- |
| VBL flag set | line 241, dot 1 | `PPU_rendering.wiki`; blargg `02-vbl_set_time`; PPUSim (die-derived) shows H = 1, V = 241 |
| VBL, sprite-0 and overflow cleared | line 261, dot 1 | `PPU_registers.wiki`; blargg `03-vbl_clear_time`; PPUSim |
| /NMI | low while VBL flag AND PPUCTRL.7 | `NMI.wiki` |
| Odd-frame skip | (339, 261) → (0, 0) on odd frames with rendering on | `PPU_frame_timing.wiki` |
| Writes accepted after power/reset | from the same signal as the VBL clear (~29,658 CPU cycles) | `PPU_power_up_state.wiki` |

**The $2002 read race** (relative to the VBL set dot, in blargg's preferred
alignment; hardware-corrected by `vbl_nmi_timing/5.nmi_suppression` and
`ppu_vbl_nmi/06-suppression`):

| Read starts at | Reads | Flag afterwards | NMI this frame |
| --- | --- | --- | --- |
| ≤ −2 dots | 0 | sets normally | yes |
| −1 (line 241 dot 0) | 0 | **never set** | **no** |
| 0 (dot 1) | 1 | cleared | **no** |
| +1 | 1 | cleared | **no** |
| ≥ +2 | 1 | cleared | yes (already fired) |

**NMI enable races** (`ppu_vbl_nmi`, `vbl_nmi_timing` readmes): setting
PPUCTRL.7 while VBL is set asserts /NMI at once and the NMI is taken after the
*next* instruction; rewriting $80 while enabled does not refire, 1→0→1 does;
disabling 1 dot before, on, or 1 dot after the set suppresses the NMI, 2+ dots
after does not.

**Odd-frame skip**: blargg `09-even_odd_frames` (`00 01 01 02`) and
`10-even_odd_timing` (`08 08 09 07`) pin when rendering is sampled. *Settled in
milestone 2*: with register writes two dots into the CPU cycle, the board
samples rendering **as dot 338 runs**: a $2001 write that lands after dot 338,
enabling or disabling, is too late for that frame's skip (logged on
`10-even_odd_timing`: enables landing after dots 337 and 338, one skipping and
one not, as the expected `08 08` requires). Mesen2 gets the same answer from a
1-dot delayed rendering flag sampled at 339 (`NesPpu.cpp` 946–954); the two
cannot be told apart by this test. Whether BG alone or BG-or-sprites gates it
(C13) the test cannot say (it uses BG only); the board uses either.

**Turning rendering off or on mid-frame**: v stops incrementing and is driven on
the bus (backdrop override if it points at the palette); during evaluation it
corrupts OAMADDR logic; turning on late means no skip that frame. The PPUMASK
effect latency is "approximately 3-4 dots" by the wiki and 1 dot in Mesen2: a
contradiction for PPUSim.

### Sprite evaluation (visible lines only)

`PPU_sprite_evaluation.wiki` (timed $2004 reads, confirmed on Visual 2C02):

- dots 1–64: secondary OAM := $FF (a $2004 read returns $FF);
- dots 65–256: odd dots read OAM[n][m], even dots write secondary OAM. After 8
  sprites are found writes stop; on a miss both n **and** m increment (the
  "diagonal" overflow bug), and a hit sets the overflow flag (blargg
  `sprite_overflow_tests/4.Obscure` pins the byte pattern);
- dots 257–320: each slot reads Y, tile, attribute, X, then X four more times;
- the starting n is OAMADDR at dot 65: a misaligned OAMADDR shifts which entry
  acts as sprite 0.

**Sprite-0 hit**: opaque sprite-0 pixel over opaque BG, with both enabled; not
at x = 0–7 when either left-clip bit is 0; **never at x = 255**; once per
frame (`PPU_OAM.wiki`; blargg `sprite_hit_tests_2005.10.05`).

## The APU

### Frame counter, in CPU cycles after the frame counter resets

`APU_Frame_Counter.wiki` (APU cycle N's put = CPU cycle 2N+1); identical to
Mesen2 `ApuFrameCounter.h` l.19–22.

| Mode | Event | NTSC | PAL |
| --- | --- | ---: | ---: |
| 4-step | quarter frame | 7457 | 8313 |
| | quarter + half | 14913 | 16627 |
| | quarter | 22371 | 24939 |
| | IRQ flag set | 29828 | 33252 |
| | quarter + half, IRQ flag set | 29829 | 33253 |
| | IRQ flag set; wraps | 29830 | 33254 |
| 5-step | quarter | 7457 | 8313 |
| | quarter + half | 14913 | 16627 |
| | quarter | 22371 | 24939 |
| | nothing | 29829 | 33253 |
| | quarter + half | 37281 | 41565 |
| | wraps | 37282 | 41566 |

Counted from the **$4017 write** (blargg 2005 readme, "Mode 0 Timing"): mode 0
gives 7459, 14915, 22373, then the IRQ flag on 29830/29831/29832; mode 1 gives
an immediate quarter + half, then 7459, 14915, 22373, 29829 (nothing), 37283.
Those are the table + 2 at blargg's alignment. Further facts:

- `apu_test/6-irq_flag_timing`: flag set three times in a row 29831 clocks after
  writing $00; blargg 2005 `08.irq_timing`: handler entered at least 29833
  clocks after.
- **Write delay**: a $4017 write takes effect 3 CPU cycles later if written
  during an APU cycle, 4 if between (`APU_Frame_Counter.wiki` l.18–20; Mesen2
  3 on even, 4 on odd). "During" is a write on a **put** (board, milestone 3:
  the other reading fails `cpu_interrupts_v2/4-irq_and_dma`'s "8 +526";
  undocumented-behavior.md C6). Bit 7 set clocks quarter + half immediately
  (at that delayed point) (`apu_test/1-len_ctr` #4/#5).
- **Jitter**: mode changes take effect on even APU clocks only
  (`apu_test/4-jitter`).
- **IRQ flag**: set on 29828 and 29829 *even with inhibit set*, not on 29830 if
  inhibited, and no IRQ results (AccuracyCoin "Frame Counter IRQ" J–M); a $4015
  read 1 cycle before, on, or 1 cycle after the first set does not clear it, 2
  after does (E–H): the clear takes effect at the next put→get transition.
- **Length counter races** (blargg 2005 10/11, `apu_test/5-len_timing`): a halt
  write takes effect one clock late; a length load on the same cycle as a
  length clock is ignored if the counter was non-zero.

### Channel clocks and tables

| Channel | Timer clocked | Output frequency |
| --- | --- | --- |
| Pulse | every APU cycle | f_CPU / (16 (t + 1)) |
| Triangle | **every CPU cycle** | f_CPU / (32 (t + 1)) |
| Noise | every APU cycle; periods in CPU cycles below | |
| DMC | every APU cycle; rates in CPU cycles below | f_CPU / rate per bit |

Noise period (CPU cycles), index 0–F:
NTSC `4 8 16 32 64 96 128 160 202 254 380 508 762 1016 2034 4068`;
PAL `4 8 14 30 60 88 118 148 188 236 354 472 708 944 1890 3778` (`APU_Noise.wiki`).

DMC rate (CPU cycles per bit), index 0–F:
NTSC `428 380 340 320 286 254 226 214 190 160 142 128 106 84 72 54`;
PAL `398 354 316 298 276 236 210 198 176 148 132 118 98 78 66 50` (`APU_DMC.wiki`).

Length table (index → length), `APU_Length_Counter.wiki`:

```
     0   1   2   3   4   5   6   7   8   9   A   B   C   D   E   F
00: 10,254, 20,  2, 40,  4, 80,  6,160,  8, 60, 10, 14, 12, 26, 14
10: 12, 16, 24, 18, 48, 20, 96, 22,192, 24, 72, 26, 16, 28, 32, 30
```

**DMC**: the IRQ fires when the last byte is *fetched*, not when it finishes
playing; the address wraps $FFFF → $8000; the output level goes to the mixer
whether the channel is enabled or not; reading $4015 does not clear the DMC IRQ
(`apu_test/7-dmc_basics` #10). The first DMA after $4015 enables the DMC waits
for the write's 3-or-4-cycle delay (AccuracyCoin DMC tests L–N).

## Reset and power-up timing

- $4017 at power behaves as if $00 were written **9–12 CPU cycles before the
  first instruction** (blargg `apu_reset/4017_timing`).
- The PPU ignores $2000/$2001/$2005/$2006 until the end of the first VBL
  (~29,658 CPU cycles NTSC); VBL first sets at ~27,384 cycles, then ~57,165
  (`PPU_power_up_state.wiki`). On the Famicom and NES-101 the reset button does
  not reset the PPU, so this window follows power only.
- The 6502 reset sequence is 7 cycles with three suppressed stack writes;
  `CPU_pinout.wiki` says code starts "after 6 M2 clocks" (a counting
  difference, UNVERIFIED).
