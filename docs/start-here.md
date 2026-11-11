# Start here: the Famicom / NES as a board author needs it

The machine in one paragraph: a **Ricoh RP2A03** (a 6502 with decimal mode cut
off, plus the sound unit, two DMA engines and the joypad ports on one die), a
**Ricoh RP2C02** picture processor with its own 14-bit bus, 2 KiB of CPU RAM,
2 KiB of nametable RAM (CIRAM) whose address line the *cartridge* controls, and
a cartridge connector through which the cartridge sees the CPU bus, the whole
PPU bus, and (on a Famicom) the audio. Everything else, from bank switching to
extra RAM, extra nametables, scanline counters and extra sound chips, is on the
cartridge.

Paths: a bare `Name.wiki` is `reference/nesdev-wiki/Name.wiki` (NESdev wiki
raw source, snapshot 2026-10-05); `nesdev-forum/`, `docs/` and `src/` are under
`reference/`. Each source's tier is in [validation.md](validation.md); timing
detail is in [timing.md](timing.md), quirks and contradictions in
[undocumented-behavior.md](undocumented-behavior.md), cartridges in
[cartridge.md](cartridge.md).

## The machines (NTSC first)

The board is built for NTSC. PAL and Dendy are rows in the same table from the
start, so that adding them later is data, not a refactor.

| Machine | CPU | PPU | Reset button resets | Controllers | Cartridge audio | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| Famicom HVC-001 (RF) | RP2A03 (letterless) → G | 2C02 | CPU only | hardwired; pad II has a microphone, no Start/Select; every read cycle clocks a pad | through the cartridge (pins 45 → 46) | **1** |
| AV Famicom HVC-101 | RP2A03G/H | 2C02G/H | CPU only (UNVERIFIED for this model) | detachable NES-type pads; a run of back-to-back reads clocks once | through the cartridge | 1 |
| NES-001 (front loader) | RP2A03G | 2C02G | **CPU and PPU** (through the CIC) | detachable; run of reads clocks once | none (expansion port pin 3 only, by modification) | **1 (reference model)** |
| NES-101 (top loader) | RP2A03G/H | 2C02G/H | CPU only | detachable | none | 1 |
| PAL NES | RP2A07 | 2C07 | CPU and PPU | as NES | none | later |
| Dendy (UMC clones) | UA6527P | UA6538 | — | Famicom-style | — | later |
| Vs. UniSystem | RP2A03 (letterless: no tonal noise) | RP2C03B, RP2C04-0001 to -0004 or RC2C05-01 to -04, as the game's ROMs need (RGB) | CPU and PPU (the watchdog's reset) | two sticks on the mainboard's shift registers, coins, a service button, 8 DIP switches | none | **built** (2026-11-11; "The Vs. System" below) |
| Vs. DualSystem | two of each | two | both sides | four sticks | none | **first pass** (`dual.py`: the two sides coupled an instruction at a time) |
| PlayChoice-10 | RP2A03G | 2C03 (RGB) | | | | later (adds a Z80: z80-python) |

Sources: `Family_Computer.wiki`, `PPU_power_up_state.wiki` l.49/76,
`Controller_reading.wiki`, `DMA.wiki` "Register conflicts", `Expansion_port.wiki`,
`CPU_variants.wiki`, `PPU_variants.wiki`. AccuracyCoin, the strongest
hardware-corrected suite, targets "an NTSC console with an RP2A03G CPU and
RP2C02G PPU" (`src/AccuracyCoin/README.md` l.4); so do Visual 2A03/2C02 and
PPUSim. **The reference model is NES-001 with RP2A03G + RP2C02G**, and the
Famicom differences are fields on it. A cartridge runs on the Famicom unless its header
names PAL or Dendy (`System.machine_for`): it runs every cartridge, and Famicom
games that write the PPU in the first frame hang on the NES-001 (C72). The
judges' test ROMs still run on the NES-001, the console they were measured on.

Fields the machine table needs (each with its source in a comment, as
sms-python does):

- `cpu_variant` (2A03 letterless / E / G / H, 2A07), `ppu_variant` (2C02
  letterless … G, H; 2C07; 2C03/04/05);
- `reset_resets_ppu`;
- `joypad_oe_per_cycle` (RF Famicom: every read cycle clocks the pad);
- `famicom_audio_through_cart`;
- `dmc_unexpected_reload_bug` (late RP2A03G and H, `DMA.wiki` "Bugs");
- power-on parameters: APU get/put parity (1 of 2), RAM fill, CPU registers
  (usually 0, measured noisy: undocumented-behavior.md), the palette (blargg's
  console's). The CPU/PPU alignment is not one: the board models blargg's
  third synchronization only (timing.md).

## Clocks

| | NTSC NES/Famicom | PAL NES | Dendy |
| --- | --- | --- | --- |
| Master clock | 21.477272 MHz (236.25/11) | 26.601712 MHz | 26.601712 MHz |
| CPU | ÷12 → 1.789773 MHz | ÷16 → 1.662607 MHz | ÷15 → 1.773448 MHz |
| PPU dot | ÷4 | ÷5 | ÷5 |
| PPU dots per CPU cycle | 3 | 3.2 | 3 |
| Lines per frame, dots per line | 262 × 341 | 312 × 341 | 312 × 341 |
| CPU cycles per frame | 29780.5 (odd frames 1 dot short with rendering on) | 33247.5 | 35464 |
| Frame rate | 60.0988 Hz | 50.0070 Hz | 50.0070 Hz |

`CPU.wiki` "Frequencies", `Cycle_reference_chart.wiki`. The APU counts in
**APU cycles = 2 CPU cycles**, whose halves are called *get* and *put*
(`APU_Frame_Counter.wiki`; `DMA.wiki` "Cadence"). Use one timeline in **master
clock ticks** (CPU cycle = 12, dot = 4): the cartridge protocol in
[cartridge.md](cartridge.md) needs it, and it makes PAL's 3.2 ratio exact.

## The CPU side

### Memory map

| Range | Device | Notes |
| --- | --- | --- |
| $0000–$07FF | 2 KiB RAM | |
| $0800–$1FFF | mirrors of RAM | AccuracyCoin "RAM mirroring" |
| $2000–$2007 | PPU registers | |
| $2008–$3FFF | mirrors of $2000–$2007 every 8 bytes | |
| $4000–$4013 | APU (write only; reads are open bus) | |
| $4014 | OAM DMA (write) | |
| $4015 | APU status; the read is **internal to the 2A03** | the only internal readable register: the cartridge does not see it, and it does not update open bus |
| $4016 | write: OUT0–2 latch; read: joypad 1 (+ Famicom microphone) | |
| $4017 | write: APU frame counter; read: joypad 2 | |
| $4018–$401A | APU test registers, only with the TEST pin high | `CPU_Test_Mode.wiki` |
| $401C–$401F | unused timer remnant | `2A03.wiki` |
| $4020–$FFFF | cartridge | the 2A03 decodes its registers fully, so everything else is the cartridge's |

`CPU_memory_map.wiki`, `2A03.wiki`. The cartridge sees **every** CPU read and
write except $4015 reads (MMC5 snoops $2000–$2006 and $4014; MMC1 needs every
write to see consecutive cycles).

### Open bus (a board responsibility)

Keep one `data_bus` byte. Every read value except a $4015 read, every write
value and every DMA read updates it; an undriven read returns it, masked per
register. `LDA abs` of an undriven address returns the operand's high byte;
indexed modes return the *base* high byte (`Open_bus_behavior.wiki`;
AccuracyCoin "Open Bus", README l.93–102).

- $4015: bit 5 is open bus, from "the last cycle that did not read $4015"
  (`APU.wiki` l.204–205).
- $4016/$4017: bits 7–5 are always open bus (usually $40, so reads are $40/$41;
  Paperboy needs exactly $41). Which of D1–D4 read 0 and which are open bus
  depends on the console model (`Controller_reading.wiki` table).

### Controllers ($4016/$4017)

- Write $4016: bits 2–0 become OUT2–OUT0; OUT0 is the strobe to both ports.
  "OUT2-0 … are updated every APU cycle" (`Expansion_port.wiki` l.43): the
  strobe reaches the pads at the next get -> put transition (AccuracyCoin
  "Controller Strobing" 3/4, milestone 4).
- Read: D0–D4 come inverted from the port lines. The 4021 shift register in
  the pad shifts at the end of the /OE pulse. Standard pad order: A, B, Select,
  Start, Up, Down, Left, Right, then 1s on official pads. While the strobe is
  high every read returns A.
- **Back-to-back reads differ by model**: on the NES-001 and AV Famicom a run of
  consecutive read cycles of the same port clocks the pad once; on the RF
  Famicom each read cycle clocks it (hardware-captured by Fiskbit, cited in
  `DMA.wiki`; AccuracyCoin "Controller Clocking" codes 1 and 2). This decides
  what RMW dummy reads and DMA re-reads of $4016 do.
- Famicom: $4016 D0 = pad I, D1 = expansion-port pad, **D2 = the microphone on
  pad II** (an immediate level, read through $4016, not $4017); $4017 D0 = pad
  II, D1–D4 = expansion port (Famicom Zapper on D3/D4) (`Standard_controller.wiki`,
  `Controller_reading.wiki`, `Zapper.wiki`).
- **Other devices** (`peripherals.py`, 2026-11-07): each answers one of two
  protocols, a controller-port device (OUT0, its /OE, D0–D4) or an
  expansion-port device (OUT0–2, both /OEs). Built, each from its wiki page:
  the NES Four Score and the Hori 4 Players Adapter (two pads' reports, then an
  address's signature), the "simple" Famicom adapters, the Zapper (NES on a
  port, Famicom on the expansion port; light from the picture as the beam passes
  the aimed pixel, a capacitor model fitted to Zap Ruder's 26/24/19 lines), the
  Arkanoid Vaus (both versions; the conversion timed from OUT0's rise), the
  Power Pad, the Family Trainer and Tap-tap Mats, the Family BASIC Keyboard
  (without its data recorder) and Konami's Hyper Shot. `System.plug` puts in a
  cartridge's device from NES 2.0 byte 15 or nes20db's `<expansion>`;
  `System.machine_for` picks the NES for one only its ports take (Four Score,
  Power Pad, NES Vaus, two Zappers). Since added: the Super NES Mouse and
  controller (through adapters), the Subor Keyboard (MAME's `suborkey.cpp`,
  BSD-3: no wiki page) with the Subor, Macro Winners/Mega Book and Yuxing mice,
  the Hori Track (its port and trailing bits UNVERIFIED), the ASCII Turbo File,
  the Family BASIC Data Recorder (the bit stream as emitted, as the wiki
  advises) and *Arkanoid II*'s second Vaus; then the tail: Bandai's Hyper Shot,
  the Partytap, Exciting Boxing's punching bag, the Coconuts pachinko dial, the
  Jissen Mahjong panel, the Oeka Kids tablet (its page calls itself possibly
  wrong; the MCU's handshake delay is not modelled), the Famicom 3D System's
  eye signal, the port test controller, and R.O.B., which reads the picture the
  board draws (its hands on pad 2 are the player's). The Vs. System's sticks
  and light gun are its mainboard's (`vs.py`, "The Vs. System" below). Not
  built: the IGS Battle Box (its
  EEPROM's commands are not on its page), the other Chinese keyboards (no
  description anywhere), the Miracle Piano (MIDI), Doremikko, the Barcode
  Battler, Top Rider and the *Arkanoid II* prototype controller.

### Power-up and reset (CPU)

- Power: A = X = Y = 0, S = $FD after the reset sequence, I set, P = $34 as
  pushed (`CPU_power_up_state.wiki`, measured on an RP2A03G; blargg
  `cpu_reset`). AccuracyCoin later found noise in these registers at power on
  on many consoles (README l.829): make them power-on parameters.
- Reset: A, X, Y unchanged, I set, S −= 3 with the three stack writes
  suppressed (reads instead). 6502-python's `request_reset()` already does this
  (`_control.py` `_accept_reset`).
- RAM is undefined at power and unchanged by reset.
- APU: $4015 = 0 at power and reset; $4017 = $00 at power, rewritten with its
  last value at reset (blargg `apu_reset`; Brad Taylor disagrees). See
  undocumented-behavior.md.

### The Vs. System

`Vs._System.wiki` (specification tier), MAME's `vsnes.cpp` (BSD-3,
emulator-derived; pinned as `mame-nes/vsnes.cpp`), `NES_2.0.wiki` "Vs. System
Type". An arcade mainboard with two consoles side by side; a UniSystem cabinet
uses one side. It is a row of `machine.py` per PPU (`System.machine_for` picks
it from NES 2.0 byte 13 or nes20db's `<vs ppu=>` when the console type is 1)
and one object, `vs.VsMainboard`, standing where a Famicom's expansion-port
device does:

| | Famicom | Vs. System |
| --- | --- | --- |
| CPU | RP2A03G | RP2A03, letterless: `$400E` bit 7 does nothing, noise period 15 is 2046, reset leaves the frame counter alone |
| PPU | RP2C02G, composite | RGB: a 3-bit-per-channel colour ROM (`video.RGB_DAC`, five tables), emphasis drives a channel to full, no skipped dot on odd frames, no OAM corruption; the RC2C05s swap `$2000`/`$2001` and return an identifier in `$2002` D4-D0 |
| `$4016` read | D0 pad I, D1 expansion, D2 microphone, D5-D7 open bus | D0 right stick, D1 0, D2 service button, D3-D4 DIP switches 1-2, D5-D6 coin acceptors 1-2, D7 the side (0 primary, 1 secondary) |
| `$4017` read | D0 pad II, D1-D4 expansion | D0 left stick, D1 0, D2-D7 DIP switches 3-8 |
| `$4016` write | OUT0-2 to the pads and the expansion port | OUT0 strobes the sticks; OUT1 is the other side's /IRQ and the RAM's owner (DualSystem); OUT2 chooses the CHR socket (mapper 99; Gumshoe's PRG bank too) |
| `$4020-$5FFF` | cartridge | the coin counter's latch (D0; a read writes open bus to it); a daughterboard's protection chip may answer reads |
| `$6000-$7FFF` | cartridge | 2 KiB of mainboard RAM, mirrored, battery-backed, shared by the two sides |
| Nametables | 2 KiB, the cartridge wires A10 | 4 KiB, always four screens |
| Program | a cartridge | six EPROM sockets (mapper 99) or a daughterboard: MMC1, UxROM, Sunsoft-3, VRC1, Namco 108 (mappers 1, 2, 67, 75, 206) |

A coin is a contact closed for about 50 ms on the board's clock
(`System.insert_coin`); the sticks report as controllers do, with the panel's
buttons 1-4 where Select and Start sit (`vs.panel` puts player 1 on the stick
the game reads: NES 2.0 devices $04 and $05); the light gun reports through
`$4016`'s shift register (`vs.VsZapper`, device $07). A DualSystem game is `dual.VsDualSystem`: two `System`s, one on
each side's row, wired by the shared RAM, the cross interrupt and the watchdog
(validation.md "The Vs. DualSystem"). What is not modelled, and
the contradictions between the wiki and the two emulators, are in
[undocumented-behavior.md](undocumented-behavior.md) (C75-C81) and
[validation.md](validation.md) "The Vs. System".

## The PPU side

### Registers ($2000–$2007, mirrored to $3FFF)

| Reg | | Semantics |
| --- | --- | --- |
| $2000 PPUCTRL | W | NMI enable (7), EXT master/slave (6), 8×16 sprites (5), BG table $1000 (4), 8×8 sprite table $1000 (3), VRAM increment 32 (2), nametable select → t bits 10–11 (1–0) |
| $2001 PPUMASK | W | emphasis B/G/R (7/6/5; **R and G swapped on 2C07 and Dendy**), sprites on (4), BG on (3), sprites in left 8 px (2), BG in left 8 px (1), greyscale (0: palette AND $30) |
| $2002 PPUSTATUS | R | VBL (7), sprite-0 hit (6), overflow (5), bits 4–0 = the I/O latch. Reading clears VBL and w |
| $2003 OAMADDR | W | forced to 0 on dots 257–320 of rendering lines |
| $2004 OAMDATA | RW | write: OAM[addr], addr++. Read: no increment; byte 2 bits 2–4 read 0. Readable on 2C02G/H only |
| $2005 PPUSCROLL | W×2 | 1st: t[4:0] = d[7:3], x = d[2:0]; 2nd: t[14:12] = d[2:0], t[9:5] = d[7:3] |
| $2006 PPUADDR | W×2 | 1st: t[13:8] = d[5:0], t[14] = 0; 2nd: t[7:0] = d, then v = t 2 dots after the access point (PPUSim; `ppu.DELAYS`) |
| $2007 PPUDATA | RW | access v (a write lands 3 dots after the access point), then v += 1 or 32 a dot after that; **during rendering** an access increments coarse X and Y together instead |

`PPU_registers.wiki`, `PPU_scrolling.wiki`. The internal registers (loopy's
names) are v (15-bit current address), t (temporary), x (3-bit fine X) and w
(the write toggle shared by $2005 and $2006). Layout `yyy NN YYYYY XXXXX`.

**Read buffer**: a $2007 read returns the buffer and refills it from v. Palette
reads ($3F00–$3FFF) return palette data at once (bits 7–6 from the I/O latch,
after the greyscale AND) and fill the buffer with the nametable byte
"underneath" (`PPU_registers.wiki`; blargg `vram_access`, `palette_ram`).

### PPU memory map (14-bit bus)

- $0000–$1FFF pattern tables: the cartridge.
- $2000–$2FFF nametables: the cartridge decides through CIRAM /CE and CIRAM
  A10 (H/V arrangement, single screen, four screen, or its own RAM/ROM).
  $3000–$3EFF mirror them as the cartridge decodes.
- $3F00–$3FFF palette RAM (internal): 32 × 6 bits, mirrored every 32;
  $3F10/$14/$18/$1C are the same cells as $3F00/$04/$08/$0C. Palette writes put
  the address on the bus but do not assert /WR.
- OAM: 256 bytes primary (DRAM) + 32 bytes secondary.

### The bus is the design

The PPU is modelled **dot by dot**, 341 × 262, and every PPU bus access
(nametable, attribute, pattern low and high, the garbage nametable fetches of
the sprite phase, the dummy tile-$FF fetches of empty sprite slots, and the
address changes a $2006 write or $2007 access causes outside rendering) goes
through the cartridge connector. MMC3 counts rises of A12; MMC5 counts three
equal nametable reads; MMC2/MMC4 latch on particular pattern reads. A
scanline renderer cannot feed them without hacks. The dot schedule is in
[timing.md](timing.md).

### Output format

Per pixel the board emits the **6-bit palette value plus the 3 emphasis bits**
(the "9-bit `eeellcccc`" input of the NESdev NTSC reference code,
`NTSC_video.wiki`). Turning that into RGB is the frontend's job: the 2C02 has
no RGB anywhere; it generates composite video directly, and no canonical colour
exists for an index (`PPU_palettes.wiki` lists four sources of variation). The
frontend default should be the pally-generated `2C02G_U_wiki.pal` (made from
lidnariq's measured voltages; MIT-0), with FirebrandX's "Composite Direct"
capture as the hardware comparison (open item: the site refused our fetcher).
RGB PPUs (2C03/04/05) use a 3-bit-per-channel DAC table and, for 2C04, a
scrambled palette per chip (`PPU_palettes.wiki`): the picture format is the
same, and `video.rgb_palette` turns it into the chip's colours
(`video.machine_palette` chooses by machine).

## The APU

| Addr | Bits | Meaning |
| --- | --- | --- |
| $4000/$4004 | `DDLC VVVV` | pulse duty, length halt = envelope loop, constant volume, volume/period |
| $4001/$4005 | `EPPP NSSS` | sweep enable, period, negate, shift |
| $4002/$4006 | `TTTT TTTT` | timer low |
| $4003/$4007 | `LLLL LTTT` | length index, timer high; restarts envelope and sequencer phase |
| $4008 | `CRRR RRRR` | triangle: linear control (= length halt), linear reload |
| $400A/$400B | | triangle timer; $400B loads length, sets the linear reload flag (no phase reset) |
| $400C | `--LC VVVV` | noise envelope |
| $400E | `M--- PPPP` | noise mode (short), period index |
| $400F | `LLLL L---` | noise length, envelope restart |
| $4010 | `IL-- RRRR` | DMC IRQ enable (0 clears the DMC IRQ flag), loop, rate |
| $4011 | `-DDD DDDD` | DMC output level |
| $4012 | | sample address = $C000 + 64·A |
| $4013 | | sample length = 16·L + 1 |
| $4015 W | `---D NT21` | channel enables; clears the DMC IRQ flag |
| $4015 R | `IF-D NT21` | DMC IRQ, frame IRQ, DMC active, length > 0; clears the frame IRQ flag; bit 5 open bus |
| $4017 W | `MI-- ----` | frame counter: 5-step mode, IRQ inhibit |

`APU.wiki`, `2A03.wiki`. Pulse 1 and 2 differ only in sweep negate (ones' vs
two's complement). Pulse and noise and DMC timers tick every APU cycle, the
triangle's every CPU cycle. The DMC fetches its sample bytes by DMA, which
stalls the CPU ([timing.md](timing.md)). The tables (length, noise, DMC rate),
the frame counter and the mixer formula are in [timing.md](timing.md) and
[undocumented-behavior.md](undocumented-behavior.md).

**Mixing**: blargg's hardware-fitted non-linear formula,

```
pulse_out = 95.88 / (8128 / (p1 + p2) + 100)
tnd_out   = 159.79 / (1 / (t/8227 + n/12241 + d/22638) + 100)
```

(`docs/blargg-apu_ref.txt` l.640–690; `APU_Mixer.wiki`), mixed at CPU rate and
box-filtered to the host rate the way sms-python's `psg.py` does, then a
per-console analogue stage labelled "fitted" (the published filter corners
disagree with their own measurements: undocumented-behavior.md).

**Expansion audio** (Famicom only: the 2A03's output goes into the cartridge on
pin 45 and comes back on pin 46): VRC6, VRC7, Namco 163, Sunsoft 5B, MMC5, FDS.
Two of these are chips the family will want as shared cores: the **VRC7 is a
YM2413 (OPLL) variant**, judged by Nuked-OPLL's `opll_type_ds1001`, and shares a
core with sms-python's FM unit; the **5B is a YM2149 (AY-3-8910 family)**, an
arcade-wide chip. The others stay in the cartridge package. Measured mix levels
per chip are in undocumented-behavior.md.

## Suggested module shape

A suggestion, as in sms-python; the requirements are in
[handoff-brief.md](handoff-brief.md).

| Module | What |
| --- | --- |
| `machine.py` | the machine table above, as data |
| `board.py` | the CPU bus decode, open bus, $4016/$4017, the master-clock scheduler that advances the PPU and APU inside each bus callback, DMA inside `read_byte` |
| `ppu.py` | the dot-level 2C02: registers, fetch schedule, sprite evaluation, frame events, pixel output |
| `apu.py` | the five channels, frame counter, mixer; a pin-shaped interface so it can become its own core |
| `cartridge/` | the connector protocol, the iNES/NES 2.0 loader, nes20db lookup, one module per mapper family |
| `system.py`, `state.py`, `debug.py`, `trace.py`, `frontend.py` | the family's tooling, as sms-python has them |
