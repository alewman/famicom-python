# MAME as a detector: the verified recipe

MAME 0.285 (`/usr/games/mame`) is a detector for this board, not a judge (see
[validation.md](validation.md)). For the CPU side it is a good one: its 2A03
trace matches `nestest.log` on every one of the 8,991 instructions (registers,
flags and cycle counts), and it passes blargg's instruction and instruction-timing
suites. For the PPU, APU and DMA it is a weak one: its PPU is scanline-based,
its OAM DMA is instantaneous, its DMC DMA steals no cycles, and it scores 81/144
on AccuracyCoin. Use it to find the first diverging *instruction*; never to
decide a PPU-dot or DMA-cycle question.

Everything on this page was run on 2026-10-05 against MAME 0.285 (source pinned
at tag `mame0285`, `f379cd0`, sparse in `reference/src/mame`).
`scripts/mame_trace.py` encodes it.

## The command

```sh
python scripts/mame_trace.py nes tests/test_roms/nes-test-roms/other/nestest.nes --nestest --seconds 1
python scripts/mame_trace.py nes tests/test_roms/nes-test-roms/ppu_vbl_nmi/ppu_vbl_nmi.nes --seconds 4
python scripts/mame_trace.py nes tests/test_roms/AccuracyCoin/AccuracyCoin.nes --no-trace --seconds 121 --press 120:Start:6
```

which runs, in a fresh directory under `tests/mame_traces/`:

```sh
mame <driver> -cart <rom>.nes -homepath <out> -snapshot_directory snap \
  -video none -sound none -nothrottle -noreadconfig -skip_gameinfo \
  -debug -debugger none -log -seconds_to_run <n> -autoboot_script <out>/trace.lua
```

with this Lua (identical for every NES driver):

```lua
local dbg = manager.machine.debugger
dbg.visible_cpu = manager.machine.devices[":maincpu"]
dbg:command('trace cpu.trace,,noloop,{logerror "%X %X %X %X %X %X %d %d %d %d\\n",pc,a,x,y,p,sp,totalcycles,beamy,beamx,frame}')
dbg:command('wpset 2000,8,r,1,{logerror "R %X %X %d\\n",wpaddr,wpdata,totalcycles; g}')
dbg:command('wpset 2000,8,w,1,{logerror "W %X %X %d\\n",wpaddr,wpdata,totalcycles; g}')
dbg:command('wpset 4000,18,r,1,{logerror "R %X %X %d\\n",wpaddr,wpdata,totalcycles; g}')
dbg:command('wpset 4000,18,w,1,{logerror "W %X %X %d\\n",wpaddr,wpdata,totalcycles; g}')
-- nestest automation only:  dbg:command('bpset C004,1,{pc=C000; g}')
dbg:command("go")
```

plus a frame notifier that logs blargg's `$6000` protocol to `status.txt` once a
second and presses controller buttons on request. `error.log` lands in the
working directory, not under `-homepath`. Without `-debug` (`--no-trace`) MAME
runs about 40x real time and only `status.txt` and the exit snapshot are made.
No BIOS and no `-rompath` are needed: `-listroms nes famicom famicomo nespal dendy`
all say "No ROMs required"; a plain headered iNES file loads with `-cart`
(the log prints the mapper, PRG/CHR sizes, mirroring and TV system it parsed).

## What it produced

| Run | Driver | Emulated | Wall | Instructions | Reg. reads | Reg. writes | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| nestest automation (`--nestest`) | `nes` | 1 s | 0.5 s | 9,041 | 0 | 5 | matches `nestest.log`, see below |
| nestest menu (no input) | `nes` | 3 s | 14.7 s | 1,797,562 | 10,118 | 11,606 | idles in menu |
| `ppu_vbl_nmi.nes` | `nes` | 4 s | 21.7 s | 2,658,523 | 90,401 | 16,489 | **Failed #7** in 01-vbl_basics ("VBL period is too short with BG off") |
| `apu_test.nes` | `nes` | 3 s | 15.0 s | 1,774,137 | 72,946 | 16,556 | **Failed #4** in 1-len_ctr ("Writing $80 to $4017 should clock length immediately") |
| `sprdma_and_dmc_dma.nes` | `nes` | 3 s | 18.5 s | 2,244,946 | 35,454 | 13,438 | still running ($6000 = $80) |
| `spritecans.nes` | `nes` | 1 s | 5.2 s | 595,646 | 7,193 | 16,007 (14,336 `W 2004`) | demo |
| `instr_timing.nes` | `famicom` / `famicomo` / `dendy` / `nespal` | 1 s each | ~5 s | 503,283 / 503,283 / 503,504 / 471,446 | | | running; all four drivers trace |

Status-only runs (`--no-trace`, blargg `$6000` read from Lua):

| ROM | MAME 0.285 result |
| --- | --- |
| `instr_test-v5/official_only.nes`, `all_instrs.nes` | `$00`, "All 16 tests passed" |
| `instr_timing/instr_timing.nes` | `$00`, "All 2 tests passed" |
| `cpu_interrupts_v2/cpu_interrupts.nes` | `$01`, 2-nmi_and_brk Failed (test 2 of 5) |
| `ppu_vbl_nmi/ppu_vbl_nmi.nes` | `$01`, 01-vbl_basics Failed #7 |
| `apu_test/apu_test.nes` | `$01`, 1-len_ctr Failed #4 |
| AccuracyCoin (`4151899`, 144 tests; Start at frame 120) | **81 / 144** (its own result screen and `$0400-$04FF` agree); 121 s emulated in 3.0 s wall. The doclic.eu leaderboard lists MAME 0.288 at 81/140 on an older AccuracyCoin. |

### nestest lockstep

`--nestest` against `nestest.log` (8,991 lines), comparing PC, A, X, Y, P masked
with `$CF`, S, and cycles:

- **every line matches** except the A/X/Y and P columns of lines 1-2;
- MAME's `totalcycles` is the log's `CYC` **plus 1** on every line (first
  instruction at 8 vs 7);
- lines 1-2 differ only by MAME's power-on state: X = `$80` and P = `$36`
  (Z set) where Nintendulator has X = `$00`, P = `$24`. The first `LDX #$00`
  (line 2) clears both. Hardware power-up X and Z are not defined (AccuracyCoin
  removed its power-on register test because consoles vary).

```
nestest.log: C5F5  A2 00     LDX #$00   A:00 X:00 Y:00 P:24 SP:FD PPU:  0, 30 CYC:10
MAME:        C5F5 0 80 0 36 1FD 11 240 25 0
```

### A sample: OAM DMA

```
C1B5 2 0 0 34 1FF 149074 241 130 4      STA $4014
W 4014 2 149074
W 2004 7C 149074                        ... 256 of these, all stamped 149074
C1B8 2 0 0 34 1FF 149591 246 15 4       next instruction: 149074 + 4 + 513
```

## The traps, all found the hard way

1. **Tags.** All NES-family drivers in `nintendo/nes.cpp` (`nes`, `famicom`,
   `famicomo`, `nespal`, `dendy`) name the 2A03 `:maincpu`; its APU is
   `:maincpu:nesapu`, the PPU `:ppu`, the pads `:ctrl1:joypad` / `:ctrl2:joypad`
   (input port `:ctrl1:joypad:JOYPAD`, fields `P1 A`, `P1 Start`, ...), the
   cartridge `:nes_slot:<pcb>` (`:nes_slot:nrom`). The PPU is not a CPU device:
   it has no debugger state, so there is no `scanline`/`dot` symbol.
2. **Lua notifier subscriptions die when garbage-collected.**
   `emu.add_machine_frame_notifier(...)` returns a subscription; if it is not
   kept in a global, the callback silently stops after about one emulated
   second (63 frames here). Every run before this was fixed "lost" its status
   log. `emu.add_machine_reset_notifier` never fired at all from an autoboot
   script (the reset has already happened).
3. **Setting PC from Lua before the first instruction skips the reset
   sequence**: S stays `$00` (shown as `100`), `totalcycles` starts at 0.
   For nestest's automation entry, break at the reset vector instead
   (`bpset C004,1,{pc=C000; g}`). The trace line printed for that first
   instruction still shows `C004`, but the instruction executed is `$C000`'s
   `JMP` (next line `C5F5` at +3 cycles).
4. **P has bits 4 and 5 forced on** (`$36`, `$34`, ...): mask with `$CF` before
   comparing. **SP is printed with its page** (`1FD`).
5. **`totalcycles` is one higher than nestest's `CYC`** throughout: compare
   deltas, or subtract 1.
6. **`beamy`/`beamx` are MAME's screen raster, not the PPU position.** The screen
   is 256 x 262 (`set_size(32*8, 262)`), so `beamx` covers the whole 341-dot line
   in 256 steps (range -1..255) and is not a dot number; at power-on
   `beamy` = 240. Derive the PPU dot from `totalcycles` x 3 and a reference
   point (e.g. the first `$2002` read returning bit 7: at `totalcycles` 29,892,
   `beamy` 240, `beamx` 251, and again 29,784 cycles later). `frame` is MAME's
   screen frame number.
7. **Register events are stamped with the instruction's start cycle**, not the
   bus cycle (`R 2002 0 16` carries the `LDA $2002` line's 16; the read itself is
   at 16 + 3). Same as on the Z80 boards. MAME says *which* instruction, not *when*
   within it.
8. **OAM DMA is instantaneous and always 513 cycles.** `W 4014` is followed by 256
   `W 2004` events with the same stamp, and the CPU resumes exactly 513 cycles
   later (`ppu2c0x_device::spriteram_dma`: `adjust_icount(-513)`), never 514.
   Hardware takes 513 or 514 depending on the cycle parity. Lockstep will
   drift by one cycle at every odd-aligned DMA.
9. **DMC DMA steals no CPU cycles.** `nes_apu.cpp` fetches the sample byte through
   a read callback with no halt. Every DMC fetch is a divergence (4 cycles on
   hardware, plus the dummy reads that `dmc_dma_during_read4` tests).
10. **The PPU is scanline-based** (`ppu2c0x.cpp` header: "PPU timing is imprecise
    for updates that happen mid-scanline"; the hblank timer is `cycles_to_attotime(260)/3`
    with a FIXME). That is why it fails ppu_vbl_nmi at the first test and scores
    81/144 on AccuracyCoin. Do not use MAME for VBL/NMI/sprite-0 timing.
11. **A malformed watchpoint action fails silently.** My first attempt used one
    `rw` watchpoint with `wpaccess==1?"R":"W"` and `%s`: it was accepted, and logged
    nothing, ever. Use one `r` and one `w` watchpoint per range.
12. **No 14-value `logerror` limit here.** The Z80 boards lost every line past 14
    values; on `nes` 16, 17 and 18 values all logged correctly. Ten are used.
13. **Lua memory reads have side effects on I/O.** `spaces["program"]:read_u8`
    goes through the real handlers: reading `$6000-$6FFF` (cartridge RAM) is safe;
    never read `$2002`/`$2007`/`$4015`/`$4016` from Lua.
14. **`-seconds_to_run` saves a snapshot at exit** (`snap/<driver>/NNNN.png`,
    256 x 240) even with `-video none`; `manager.machine.video:snapshot()` from a
    frame notifier also works.
15. **Speed.** With `-debug` and the trace, about 0.2x real time (5 s wall per
    emulated second) and ~15 MB of `error.log` per emulated second. Keep runs to a
    few seconds; for pass/fail use `--no-trace`.

## What MAME does not model (so lockstep will diverge there)

- PPU dot timing (scanline renderer; mid-line register writes approximate).
- DMC DMA cycle stealing and its dummy reads; OAM DMA parity (always 513).
- The `$4017`-write length-counter clock (apu_test 1-len_ctr #4).
- NMI/BRK interaction (cpu_interrupts 2-nmi_and_brk).
- The power-on CPU state is MAME's own (X = `$80`, Z set), not a hardware value.

## Driver facts

| Driver | CPU device | PPU device | Notes |
| --- | --- | --- | --- |
| `nes` | `RP2A03G` @ `NTSC_APU_CLOCK` | `PPU_2C02` | 60.0988 Hz, 262 lines; NES pads |
| `famicom` | `RP2A03G` | `PPU_2C02` | Famicom pads + expansion port; cart and FDS lists |
| `famicomo` | `RP2A03` (pre-G) | `PPU_2C02` | "earlier, with RP2A03" |
| `nespal` | `RP2A03G` re-clocked to `PAL_APU_CLOCK` (no separate 2A07 device) | `PPU_2C07` | 50.007 Hz, 312 lines |
| `dendy` | `RP2A03G` @ `PALC_APU_CLOCK` | `PPU_PALC` | UMC clone timing (`famipalc` config) |

`famitwin` and `fds` need the disk-system BIOS (`rp2c33a-02.bin`); not needed for
cartridges. MAME's software list `/usr/share/games/mame/hash/nes.xml` (4,559
entries) gives each cartridge's PCB by CRC (`-cart` with the list name instead
of a file uses it).

## A better MAME exists, and Mesen can be driven headless

- `theklap/mame_nes` (a fork of MAME 0.260 reworking the NES PPU/DMA) scores
  140/140 on the leaderboard: worth building if a MAME-family detector with
  correct PPU timing is wanted (pinned `f8b7c1d`, licence not asserted).
- Mesen2's core builds here without .NET and runs headless through `ctypes`:
  see "Mesen2 as a second detector" in [validation.md](validation.md).
