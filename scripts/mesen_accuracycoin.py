#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run AccuracyCoin on Mesen2 or MesenCE and print what it fails.

    [MESEN_CORE=...] python scripts/mesen_accuracycoin.py [--frames N]

Presses Start on the page index, as scripts/accuracycoin.py does on the board, lets
all the tests run, and reads the result bytes at $0400-$04FF. The emulators are detectors;
this says which of AccuracyCoin's hardware answers they get right, with the same
settings as the frame comparisons. Run as a separate program only: the family's
mesen2-runner, ``$EMU_TOOLS_GPL/tools/mesen2/run.py --machine nes --lua``
(scripts/mesen2_tool.py; exit status 3 without it), whose script log this reads.
``MESEN_CORE`` names another library (MesenCE's, say). OBSERVED, never hardware.
"""

from __future__ import annotations

import argparse
import time

import mesen2_tool
from mesen2_tool import ROOT

from famicom_python.testrom import accuracycoin_tests

HOME = ROOT / "tests" / "test_roms" / "AccuracyCoin"

LUA = """
local frame, last = 0, %d
emu.addEventCallback(function()
  if frame >= 60 and frame < 66 then emu.setInput({start = true}, 0) end
end, emu.eventType.inputPolled)
emu.addEventCallback(function()
  frame = frame + 1
  if frame == last then
    for line = 0, 15 do
      local parts = {}
      for i = 0, 15 do
        local value = emu.read(0x400 + line * 16 + i, emu.memType.nesMemory)
        parts[#parts + 1] = string.format("%%02x", value)
      end
      emu.log("L" .. line .. " " .. table.concat(parts))
    end
    emu.log("DONE")
  end
end, emu.eventType.endFrame)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=int, default=20000)
    parser.add_argument("--seconds", type=float, default=280)
    args = parser.parse_args()
    began = time.monotonic()
    log = mesen2_tool.run_lua(
        HOME / "AccuracyCoin.nes", LUA % args.frames, args.frames, timeout=args.seconds, check=False
    )
    wall = time.monotonic() - began
    lines = dict(line.partition(" ")[::2] for line in log if line.startswith("L"))
    if "DONE" not in log or any(f"L{n}" not in lines for n in range(16)):
        print("no result:", "\n".join(log[-10:]))
        return
    data = bytes.fromhex("".join(lines[f"L{n}"] for n in range(16)))
    tests = accuracycoin_tests((HOME / "AccuracyCoin.asm").read_text())
    passed = 0
    for test in tests:
        value = data[test.address & 0xFF]
        if value != 0xFF and value & 3 == 1:
            passed += 1
        else:
            print(f"{test.page} / {test.name}: ${value:02X}")
    print(f"{passed} of {len(tests)} pass; {wall:.0f} s wall")


if __name__ == "__main__":
    main()
