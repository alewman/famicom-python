#!/usr/bin/env python3
"""Record MAME 0.285's per-instruction 2A03 trace and register log for an NES cartridge.

Runs the recipe in docs/mame-oracle.md in a fresh directory (default
``tests/mame_traces/<driver>-<cart stem>``, gitignored) and leaves ``error.log``
there. The NES drivers need no BIOS; nothing is read from a romset.

    python scripts/mame_trace.py nes tests/test_roms/nes-test-roms/other/nestest.nes --nestest
    python scripts/mame_trace.py nes tests/test_roms/nes-test-roms/ppu_vbl_nmi/ppu_vbl_nmi.nes --seconds 4
    python scripts/mame_trace.py nes path/to/rom.nes --no-trace --seconds 60      # result only, fast
    python scripts/mame_trace.py nes AccuracyCoin.nes --no-trace --seconds 120 --press 120:Start:6

``error.log`` then holds, in execution order:

- one line per instruction, before it executes:
  ``PC A X Y P SP totalcycles beamy beamx frame`` (hex, then decimal).
  P is MAME's internal P: bit 4 (B) and bit 5 always read 1, so mask with $CF
  before comparing. SP carries the page ($1FD). beamy/beamx are MAME's
  *screen* raster position, not the PPU's scanline/dot (docs/mame-oracle.md);
- ``R addr value totalcycles`` / ``W addr value totalcycles`` for every CPU
  access to $2000-$2007 and $4000-$4017 (including the 256 ``W 2004`` that MAME's
  instantaneous OAM DMA performs), stamped with the *instruction's start*
  cycle, not the bus cycle.

With ``--status`` (default on) a frame notifier writes ``status.txt``: blargg's
$6000 protocol (status byte, ``DE B0 61`` signature, text at $6004) once a second.
MAME saves a final snapshot at exit under ``snap/<driver>/``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAME = "/usr/games/mame"

# Every NES-family driver in nintendo/nes.cpp names the RP2A03 ":maincpu" and
# the 2C0x ":ppu"; the APU is ":maincpu:nesapu". None needs a BIOS for -cart
# (famitwin and fds do, for the disk system only).
DRIVERS = {
    "nes": "RP2A03G + 2C02, NTSC",
    "famicom": "RP2A03G + 2C02, NTSC, Famicom controllers + expansion port",
    "famicomo": "RP2A03 (pre-G) + 2C02, NTSC",
    "nespal": "RP2A03G re-clocked for PAL + 2C07",
    "dendy": "RP2A03G at the UMC clone clock + PPU_PALC",
}
CPU_TAG = ":maincpu"
JOYPAD = ":ctrl1:joypad:JOYPAD"
BUTTONS = ("A", "B", "Select", "Start", "Up", "Down", "Left", "Right")

# A logerror action silently drops lines past 14 values (found on the Z80
# boards); 10 here. Two watchpoints per range: one read, one write.
TRACE_LUA = """\
local dbg = manager.machine.debugger
dbg.visible_cpu = manager.machine.devices["{cpu}"]
dbg:command('trace cpu.trace,,noloop,{{logerror "%X %X %X %X %X %X %d %d %d %d\\\\n",\
pc,a,x,y,p,sp,totalcycles,beamy,beamx,frame}}')
dbg:command('wpset 2000,8,r,1,{{logerror "R %X %X %d\\\\n",wpaddr,wpdata,totalcycles; g}}')
dbg:command('wpset 2000,8,w,1,{{logerror "W %X %X %d\\\\n",wpaddr,wpdata,totalcycles; g}}')
dbg:command('wpset 4000,18,r,1,{{logerror "R %X %X %d\\\\n",wpaddr,wpdata,totalcycles; g}}')
dbg:command('wpset 4000,18,w,1,{{logerror "W %X %X %d\\\\n",wpaddr,wpdata,totalcycles; g}}')
{nestest}dbg:command("go")
"""

# nestest's "automation" entry: run from $C000 once the reset sequence has
# finished. Setting PC from Lua before the first instruction skips MAME's reset
# microcode (S stays $00), so redirect at the reset vector instead. The trace
# line printed for that first instruction still shows the vector's address.
NESTEST_LUA = "dbg:command('bpset {vector:X},1,{{pc=C000; g}}')\n"

# Notifier subscriptions are unsubscribed when garbage-collected: keep them in
# globals, or the callbacks silently stop after about a second.
STATUS_LUA = """\
local prog = manager.machine.devices["{cpu}"].spaces["program"]
local pad = manager.machine.ioport.ports["{joypad}"]
local presses = {{ {presses} }}
local frames = 0
local log = io.open("status.txt", "w")
status_sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  for _, p in ipairs(presses) do
    if frames == p[1] then pad.fields["P1 " .. p[2]]:set_value(1) end
    if frames == p[1] + p[3] then pad.fields["P1 " .. p[2]]:clear_value() end
  end
  if frames % 60 == 0 then
    local text = {{}}
    for a = 0x6004, 0x6FFF do
      local c = prog:read_u8(a)
      if c == 0 then break end
      text[#text + 1] = string.char(c)
    end
    log:write(string.format("frame %d status %02X sig %02X %02X %02X text %s\\n", frames,
      prog:read_u8(0x6000), prog:read_u8(0x6001), prog:read_u8(0x6002), prog:read_u8(0x6003),
      (table.concat(text):gsub("\\n", " / "))))
    log:flush()
  end
end)
"""


def reset_vector(image: bytes) -> int:
    """The reset vector of a headered iNES image (last PRG bank's $FFFC)."""
    if image[:4] != b"NES\x1a":
        raise SystemExit("not an iNES image")
    prg = image[4] * 0x4000
    start = 16 + (512 if image[6] & 4 else 0)
    top = image[start + prg - 4 : start + prg - 2]
    return top[0] | top[1] << 8


def parse_press(spec: str) -> tuple[int, str, int]:
    frame, button, *hold = spec.split(":")
    if button not in BUTTONS:
        raise argparse.ArgumentTypeError(f"button must be one of {BUTTONS}")
    return int(frame), button, int(hold[0]) if hold else 6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("driver", choices=sorted(DRIVERS))
    parser.add_argument("cart", type=Path, help="headered .nes image")
    parser.add_argument("--seconds", type=int, default=2, help="emulated seconds")
    parser.add_argument("--nestest", action="store_true", help="start nestest at $C000")
    parser.add_argument("--no-trace", action="store_true", help="no debugger: status only")
    parser.add_argument(
        "--press",
        type=parse_press,
        action="append",
        default=[],
        metavar="FRAME:BUTTON[:FRAMES]",
        help="press a P1 button",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--mame", default=MAME)
    args = parser.parse_args()
    cart = args.cart.resolve()
    out = (args.out or ROOT / "tests" / "mame_traces" / f"{args.driver}-{cart.stem}").resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copyfile(cart, out / cart.name)
    image = (out / cart.name).read_bytes()
    lua = ""
    if not args.no_trace:
        nestest = NESTEST_LUA.format(vector=reset_vector(image)) if args.nestest else ""
        lua += TRACE_LUA.format(cpu=CPU_TAG, nestest=nestest)
    presses = ", ".join(f'{{{f}, "{b}", {h}}}' for f, b, h in args.press)
    lua += STATUS_LUA.format(cpu=CPU_TAG, joypad=JOYPAD, presses=presses)
    (out / "trace.lua").write_text(lua, encoding="utf-8")
    version = subprocess.run(
        [args.mame, "-version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    debug = [] if args.no_trace else ["-debug", "-debugger", "none"]
    began = time.monotonic()
    # error.log lands in the working directory, not under -homepath.
    subprocess.run(
        [args.mame, args.driver, "-cart", cart.name,
         "-homepath", str(out), "-snapshot_directory", "snap",
         "-video", "none", "-sound", "none", "-nothrottle",
         "-noreadconfig", "-skip_gameinfo", *debug, "-log",
         "-seconds_to_run", str(args.seconds), "-autoboot_script", str(out / "trace.lua")],
        cwd=out, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    wall = time.monotonic() - began
    instructions = reads = writes = 0
    with (out / "error.log").open("rb") as log:
        for line in log:
            if line.startswith(b"R "):
                reads += 1
            elif line.startswith(b"W "):
                writes += 1
            elif line[:1].isalnum() and line.count(b" ") == 9:
                instructions += 1
    status = (out / "status.txt").read_text(encoding="utf-8").splitlines()
    print(
        f"MAME {version}, {args.driver}, {args.seconds} s emulated in {wall:.1f} s: {out / 'error.log'}"
    )
    if not args.no_trace:
        print(
            f"  {instructions:,} instructions, {reads:,} register reads, {writes:,} register writes"
        )
    if status and " sig DE B0 61 " in status[-1]:
        print(f"  blargg $6000: {status[-1]}")
    return 0 if args.no_trace or instructions else 1


if __name__ == "__main__":
    sys.exit(main())
