#!/usr/bin/env python3
"""Probe ROMs for the provenance audit (wave 2, item 3): one behaviour each, on the board and on
Mesen2 run as a closed box.

docs/provenance.md lists single behaviours the board first took from reading Mesen2's
source. Each probe here is a small program written for this audit from the NESdev wiki's
register descriptions; it exercises one behaviour and leaves its answers in work RAM
($0400-$07FF, $03FF = $A5 when finished). The same image runs on the board and on Mesen2's
library (scripts/mesen_run.py, the hand-built MesenCore.so: Mesen2 2.1.1), which is driven,
never read, and the answers are printed side by side. A Mesen2 answer is a closed-box
observation of a detector, not hardware.

    python scripts/provenance_probes.py [NAME ...] [--keep DIR]
    python scripts/provenance_probes.py --fds-ready

``--fds-ready`` boots a licensed disk (NO_INTRO_DIR, and the BIOS as ``fds_bios`` finds it)
on both and times the drive's spin-up from the BIOS's own $4025 writes and $4032 reads.

Needs ca65 and ld65 (cc65) on PATH, or named by the CA65 and LD65 environment variables.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from mesen_run import ROOT, run_mesen

from famicom_python.system import System

HOME = ROOT / "tests" / "mame_traces" / "mesen-home"
RESULTS, LENGTH, DONE = 0x0400, 0x400, 0x03FF

COMMON = """
.segment "CODE"
reset:
    sei
    cld
    ldx #$FF
    txs
    lda #$40
    sta $4017           ; no frame IRQ
    lda #0
    sta $2000
    sta $2001
    bit $2002
@v1: bit $2002
    bpl @v1
@v2: bit $2002
    bpl @v2
    jsr probe
    lda #$A5
    sta $03FF
@done: jmp @done
nmi: rti
ff: .byte $FF           ; a PRG byte of $FF: a write here passes AND-type bus conflicts

; ppuread: A = high byte, X = low byte of a PPU address; returns in A the byte there
; (two reads of PPUDATA: the first only fills the buffer).
ppuread:
    sta $2006
    stx $2006
    lda $2007
    lda $2007
    rts

; ppuonce: one PPUDATA read at A:X (the PPU reads that address once).
ppuonce:
    sta $2006
    stx $2006
    lda $2007
    rts

.segment "VECTORS"
    .word nmi, reset, irq
"""

LINKER = """
MEMORY { ROM: start = $E000, size = $2000, fill = yes, fillval = $FF; }
SEGMENTS {
    CODE: load = ROM, type = ro;
    VECTORS: load = ROM, type = ro, start = $FFFA;
}
"""


@dataclass
class Probe:
    name: str
    mapper: int
    submapper: int
    prg_kib: int
    chr_kib: int
    source: str
    expect: str
    chr_fill: str = "page1k"  # first byte of each 1 KiB CHR page = its number
    prg_marks: bool = False  # first byte of each 8 KiB PRG bank = its number
    extra_header: dict[int, int] = field(default_factory=dict)
    reset_after: bool = False  # Mesen2 and the board press reset once when $03FE = $81


PROBES = [
    Probe(
        "185-power-on",
        185,
        4,
        32,
        8,
        """
irq: rti
probe:
    lda #$00
    ldx #$00
    jsr ppuread         ; before any write: the latch's power-on state
    sta $0400
    lda #1              ; submapper 4: CS = 0 enables, 1 disables
    sta ff
    lda #$00
    ldx #$00
    jsr ppuread
    sta $0401
    lda #0
    sta ff
    lda #$00
    ldx #$00
    jsr ppuread
    sta $0402
    rts
""",
        "$0400 the CHR byte at $0000 read before any write ($A5, the mark: enabled;"
        " $01 = undriven, disabled), $0401 after writing 1 (disabled), $0402 after 0",
        chr_fill="185",
    ),
    Probe(
        "mmc5-exram-blanking",
        5,
        0,
        32,
        8,
        """
irq: rti
probe:
    lda #2
    sta $5104
    lda #$77
    sta $5C00
    sta $5C01
    sta $5C02
    lda #0              ; mode 0, rendering off: a write outside rendering
    sta $5104
    lda #$33
    sta $5C00
    lda #1              ; mode 1
    sta $5104
    lda #$44
    sta $5C01
    lda #3              ; mode 3 (read only)
    sta $5104
    lda #$55
    sta $5C02
    lda #2
    sta $5104
    lda $5C00
    sta $0400
    lda $5C01
    sta $0401
    lda $5C02
    sta $0402
    rts
""",
        "ExRAM after writes while not rendering, each cell first $77 in mode 2: $0400 mode 0"
        " ($00 stored 0, $77 ignored, $33 written), $0401 mode 1 ($44 written), $0402 mode 3",
    ),
    Probe(
        "n163-counter-disabled",
        19,
        0,
        32,
        8,
        """
irq: rti
wait:                   ; about 1,280 CPU cycles
    ldx #0
@w: dex
    bne @w
    rts
probe:
    lda #$10
    sta $5000           ; counter = $0010, disabled
    lda #$00
    sta $5800
    jsr wait
    lda $5000
    sta $0400
    lda $5800
    sta $0401
    lda #$10
    sta $5000
    lda #$80            ; enabled
    sta $5800
    jsr wait
    lda $5000
    sta $0402
    lda $5800
    sta $0403
    and #$7F            ; disable, keeping the high bits
    sta $5800
    lda $5000
    sta $0404
    jsr wait
    lda $5000
    sta $0405
    lda $5800
    sta $0406
    rts
""",
        "$0400/$0401 the counter after ~1,280 cycles disabled from $0010 ($10 $00: held);"
        " $0402/$0403 the same enabled; $0404, $0405/$0406 after disabling again",
    ),
    Probe(
        "fcg-test-then-decrement",
        16,
        4,
        128,
        128,
        """
irq:
    pha
    lda #0
    sta $600A           ; stop counting, acknowledge
    inc $0410
    pla
    rti
probe:
    lda #0
    sta $600A
    sta $600B           ; FCG: the counter itself
    sta $600C
    sta $0410
    cli
    lda #1
    sta $600A           ; enable while it holds 0
    nop
    nop
    nop
    nop
    sei
    lda $0410
    sta $0400
    ldy #0
@next:                  ; counter = $100 + Y, Y = 0-8: polls until the IRQ
    lda #0
    sta $600A
    sta $0410
    tya
    sta $600B
    lda #1
    sta $600C
    cli
    ldx #0
    lda #1
    sta $600A
@poll:
    inx
    lda $0410
    beq @poll
    sei
    txa
    sta $0401,y
    iny
    cpy #9
    bne @next
    rts
""",
        "$0400 = IRQs within ~10 cycles of enabling at a count of 0 (1: tested before the"
        " decrement); $0401-$0409 the poll count to the IRQ for counts $100-$108 (9 cycles"
        " a poll: equal rows mean equal timing to the cycle)",
    ),
    Probe(
        "208-protection",
        208,
        0,
        128,
        8,
        """
irq: rti
probe:
    ldx #0
@l: stx $5000
    lda #$00
    sta $5800
    lda #$FF
    sta $5801
    lda $5800
    sta $0400,x
    lda $5801
    sta $0500,x
    inx
    bne @l
    rts
""",
        "$0400+i: register 0 read back after index i and data $00 (the table entry);"
        " $0500+i: register 1 after index i and data $FF",
    ),
    Probe(
        "165-latch-ranges",
        165,
        0,
        128,
        32,
        """
irq: rti
probe:
    lda #0              ; R0 = 4 KiB page 1, R1 = page 2, R2 = page 3, R4 = page 4
    sta $8000
    lda #4
    sta $8001
    lda #1
    sta $8000
    lda #8
    sta $8001
    lda #2
    sta $8000
    lda #12
    sta $8001
    lda #4
    sta $8000
    lda #16
    sta $8001
    lda #$0F
    sta $10             ; $10 = the high byte of the half (0F, then 1F)
    lda #$00
    sta $12             ; $12/$13 the result pointer
    lda #$04
    sta $13
half:
    lda #$C0
    sta $14             ; $14 = A, the address under test (low byte)
@a: lda #$C0
    sta $15             ; $15 = B, the address read first
    lda #0
    sta $16             ; $16 = this row's 8 result bits being gathered
@b: lda $10
    ldx $15
    jsr ppuonce         ; read B once
    lda $10
    ldx $14
    jsr ppuonce         ; then A once
    lda $10
    and #$10            ; then the half's first byte: which page is in
    ldx #0
    jsr ppuread
    and #$0F            ; page mark: 1/3 for latch 0, 2/4 for latch 1
    lsr a               ; carry = latch 0 (pages 1 and 3 are odd)
    rol $16
    inc $15
    lda $15
    and #7
    bne @b
    ldy #0
    lda $16
    sta ($12),y
    inc $12
    bne @c
    inc $13
@c: lda $15
    bne @b2
    inc $14
    bne @a
    lda $10
    cmp #$1F
    beq @end
    lda #$1F
    sta $10
    jmp half
@b2: lda #0
    sta $16
    jmp @b
@end: rts
""",
        "64 x 64 bits per half ($0400 half 0, $0600 half 1): row A (address $xFC0+row),"
        " bit for B ($xFC0+column, MSB first), 1 = latch 0 after reading B then A",
        chr_fill="165",
    ),
    Probe(
        "45-power-on",
        45,
        0,
        128,
        256,
        """
irq: rti
check:                  ; CHR at $0000-$1C00 by 1 KiB and PRG bank 6/7 into ($12),y
    ldy #0
@k: tya
    asl a
    asl a
    ldx #0
    jsr ppuread
    sta ($12),y
    iny
    cpy #8
    bne @k
    lda #2              ; R2 = $85: the 1 KiB bank at $1000 (CHR-AND $F keeps it)
    sta $8000
    lda #$85
    sta $8001
    lda #$10
    ldx #0
    jsr ppuread
    sta ($12),y
    iny
    lda #6              ; R6 = $0D: the PRG bank at $8000 (PRG-AND keeps it)
    sta $8000
    lda #$0D
    sta $8001
    lda $8000
    sta ($12),y
    rts
probe:
    lda #$00
    sta $12
    lda $03F0
    cmp #$5A
    beq @after
    lda #$04
    sta $13
    jsr check
    lda #$10            ; outer registers away from their reset values: CHR OR $10,
    sta $6000           ; PRG OR 4, CHR-AND none, PRG-AND 32 KiB (the code stays in)
    lda #$04
    sta $6000
    lda #$00
    sta $6000
    lda #$3C
    sta $6000
    lda #$5A
    sta $03F0
    lda #$81            ; ask for a reset
    sta $03FE
@wait: jmp @wait
@after:
    lda #$05
    sta $13
    lda #2              ; undo the probe's own MMC3 writes, which a reset keeps
    sta $8000
    lda #4
    sta $8001
    lda #6
    sta $8000
    lda #0
    sta $8001
    jsr check
    rts
""",
        "$0400-$0407 the 1 KiB CHR pages seen at $0000-$1C00 from power-on (00 01 02 03 04"
        " 05 06 07: registers 0, 2, 4, 5, 6, 7), $0408 the page after R2 = $85 ($85: CHR-AND"
        " keeps 8 bits), $0409 the PRG bank after R6 = $0D; $0500-$0509 the same after a"
        " reset that follows outer writes",
        prg_marks=True,
        reset_after=True,
    ),
]


def tool(name: str) -> str:
    found = os.environ.get(name.upper()) or shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found: put cc65 on PATH or set {name.upper()}")
    return found


def chr_data(probe: Probe) -> bytes:
    data = bytearray(probe.chr_kib * 1024)
    if probe.chr_fill == "185":
        data[0], data[1] = 0xA5, 0x3C  # a mark that undriven CHR ($01) cannot give
    elif probe.chr_fill == "165":
        for page in range(len(data) // 0x1000):
            data[page * 0x1000] = 0xB0 | page
    else:
        for page in range(len(data) // 0x400):
            data[page * 0x400] = page & 0xFF
    return bytes(data)


def build(probe: Probe, work: Path) -> Path:
    source = work / f"{probe.name}.s"
    source.write_text(COMMON + '\n.segment "CODE"\n' + probe.source)
    (work / "probe.cfg").write_text(LINKER)
    obj, code = work / f"{probe.name}.o", work / f"{probe.name}.bin"
    subprocess.run([tool("ca65"), str(source), "-o", str(obj)], check=True)
    config = str(work / "probe.cfg")
    subprocess.run([tool("ld65"), "-C", config, str(obj), "-o", str(code)], check=True)
    image = code.read_bytes()
    prg = bytearray(b"\xff" * (probe.prg_kib * 1024))
    for bank in range(len(prg) // 0x2000):
        if probe.prg_marks:
            prg[bank * 0x2000] = bank
    for block in range(0, len(prg), 0x8000):  # the code ends every 32 KiB
        end = min(block + 0x8000, len(prg))
        prg[end - 0x2000 : end] = image
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = probe.prg_kib // 16
    header[5] = probe.chr_kib // 8
    header[6] = (probe.mapper & 0x0F) << 4
    header[7] = (probe.mapper & 0xF0) | 0x08  # NES 2.0
    header[8] = (probe.submapper << 4) | (probe.mapper >> 8)
    for offset, value in probe.extra_header.items():
        header[offset] = value
    rom = work / f"{probe.name}.nes"
    rom.write_bytes(bytes(header) + bytes(prg) + chr_data(probe))
    return rom


def on_board(rom: Path, frames: int = 120) -> bytes:
    system = System.from_rom(rom)
    ram = system.board.ram
    reset_done = False
    for _ in range(frames):
        system.run_frames(1)
        if ram[0x3FE] == 0x81 and not reset_done:
            ram[0x3FE] = 0
            reset_done = True
            system.reset()
        if ram[DONE] == 0xA5:
            break
    return bytes(ram[RESULTS : RESULTS + LENGTH])


MESEN_LUA = """
local mem = emu.memType.nesDebug
local reset_done = false
emu.addEventCallback(function()
  if emu.read(0x3FE, mem) == 0x81 and not reset_done then
    reset_done = true
    emu.write(0x3FE, 0, mem)
    emu.reset()
    return
  end
  if emu.read(0x3FF, mem) == 0xA5 then
    for row = 0, 63 do
      local parts = {}
      for i = 0, 15 do
        parts[#parts + 1] = string.format("%02X", emu.read(0x400 + row * 16 + i, mem))
      end
      emu.log("R" .. row .. " " .. table.concat(parts))
    end
    emu.log("DONE")
  end
end, emu.eventType.endFrame)
"""


def on_mesen(rom: Path) -> bytes | None:
    lines: dict[str, str] = {}
    _, log, _ = run_mesen(
        rom,
        lua=MESEN_LUA.encode(),
        lua_name="probe.lua",
        seconds=20,
        home=HOME,
        until="DONE",
        for_comparison=True,
    )
    for line in log.splitlines():
        key, _, text = line.partition(" ")
        if key.startswith("R") and key[1:].isdigit():
            lines[key] = text
    if len(lines) < 64:
        return None
    return bytes.fromhex("".join(lines[f"R{row}"] for row in range(64)))


def dump(data: bytes, length: int) -> str:
    return " ".join(f"{b:02X}" for b in data[:length])


FDS_GAME = (
    "Nintendo - Family Computer Disk System (FDS)/"
    "Zelda no Densetsu - The Hyrule Fantasy (Japan).zip"
)
FDS_LUA = """
local frame, last32, n = 0, -1, 0
local function cycle() return emu.getState()["cpu.cycleCount"] end
emu.addEventCallback(function()
  frame = frame + 1
  if frame == 400 then emu.log("DONE") end
end, emu.eventType.endFrame)
emu.addMemoryCallback(function(address, value)
  if n < 400 then emu.log(string.format("W %02X %d", value, cycle())); n = n + 1 end
end, emu.callbackType.write, 0x4025)
emu.addMemoryCallback(function(address, value)
  if value ~= last32 and n < 400 then
    emu.log(string.format("R %02X %d", value, cycle())); last32 = value; n = n + 1
  end
end, emu.callbackType.read, 0x4032)
"""


def spin_up(events: list[tuple[str, int, int]]) -> int | None:
    """Cycles from the last scan start ($4025 D0 1 then 0) to the first $4032 read with D1 clear."""
    start, previous = None, 1
    for kind, value, cycle in events:
        if kind == "W":
            if previous & 1 and not value & 1:
                start = cycle
            previous = value
        elif not value & 2 and start is not None:
            return cycle - start
    return None


def fds_ready() -> None:
    """How long after the scan starts the drive reports ready, on Mesen2 and on the board."""
    from mesen_lockstep import mesen_path

    from famicom_python.cartridge import fds_bios

    game = Path(os.environ.get("NO_INTRO_DIR", "No-Intro")) / FDS_GAME
    (HOME / "Firmware").mkdir(parents=True, exist_ok=True)
    (HOME / "Firmware" / "disksys.rom").write_bytes(fds_bios())
    _, log, _ = run_mesen(
        mesen_path(game),
        lua=FDS_LUA.encode(),
        lua_name="fds.lua",
        seconds=120,
        home=HOME,
        until="DONE",
        for_comparison=True,
    )
    theirs = []
    for line in log.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] in ("W", "R"):
            theirs.append((parts[0], int(parts[1], 16), int(parts[2])))
    system = System.from_rom(game)
    cart, ours = system.cartridge, []
    write, read = cart.cpu_write, cart.cpu_read

    def logged_write(address: int, value: int, t: int) -> None:
        if address == 0x4025:
            ours.append(("W", value, system.cycles))
        write(address, value, t)

    def logged_read(address: int, t: int) -> int | None:
        value = read(address, t)
        if address == 0x4032 and value is not None:
            ours.append(("R", value & 0xFF, system.cycles))
        return value

    cart.cpu_write, cart.cpu_read = logged_write, logged_read
    system.run_frames(400)
    print(f"== fds-ready: {game.name}, CPU cycles from scan start to the first ready $4032 read")
    print(f"   board : {spin_up(ours)}")
    print(f"   Mesen2: {spin_up(theirs)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*")
    parser.add_argument("--keep", type=Path, help="write the images and answers here")
    parser.add_argument("--no-mesen", action="store_true")
    parser.add_argument("--fds-ready", action="store_true", help="the FDS drive's spin-up instead")
    args = parser.parse_args()
    if args.fds_ready:
        fds_ready()
        return 0
    chosen = [p for p in PROBES if not args.names or p.name in args.names]
    HOME.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        work = args.keep or Path(temporary)
        work.mkdir(parents=True, exist_ok=True)
        for probe in chosen:
            rom = build(probe, work)
            ours = on_board(rom)
            theirs = None if args.no_mesen else on_mesen(rom)
            (work / f"{probe.name}.board.bin").write_bytes(ours)
            if theirs is not None:
                (work / f"{probe.name}.mesen2.bin").write_bytes(theirs)
            print(f"== {probe.name}: {probe.expect}")
            agree = theirs is not None and ours == theirs
            print(f"   board : {dump(ours, 16)}")
            print(f"   Mesen2: {dump(theirs, 16) if theirs else '(no answer)'}")
            print(f"   all {LENGTH} bytes {'agree' if agree else 'DIFFER'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
