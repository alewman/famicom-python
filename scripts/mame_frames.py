#!/usr/bin/env python3
"""Frames from mame_nes, a MAME fork that passes all of AccuracyCoin, as a detector.

mame_nes runs headless as a binary only (validation.md). Lua hands over each wanted frame as
32-bit pixels. MAME gives colours, not palette indices, so the board's picture is painted
with ``COLOURS``, mame_nes's colour for each 9-bit value, measured with a ROM that
shows each as a blank screen; values of one colour ($0D and $1D, say) count as equal.
``MAME_NES`` names the binary. Its frame numbers are Mesen2's.

    MAME_NES=... python scripts/compat_sweep.py --detector mame --slack 3 --list LIST
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

MAME_NES = Path(os.environ.get("MAME_NES", "/data/emu/mame-nes-theklap/nes.tip"))
PIXELS = 256 * 240

COLOURS = json.loads((Path(__file__).parent / "mame_nes_colours.json").read_text())["colours"]
ALIGNMENT = 1  # of 0-3: its CPU/PPU alignment; left alone it is random each run

#: ``%s``: the frames wanted, as Lua table entries; ``%d``: the last.
LUA = """
local wanted, frame, last = {%s}, 0, %d
sub = emu.add_machine_frame_notifier(function()
  frame = frame + 1
  if wanted[frame] then
    local pixels = manager.machine.screens[":screen"]:pixels()
    local out = io.open("frame" .. frame .. ".bin", "wb")
    out:write(pixels)
    out:close()
  end
  if frame == last then manager.machine:exit() end
end)
"""


def config(alignment: int) -> str:
    return (
        '<?xml version="1.0"?>\n<mameconfig version="10"><system name="nes"><input>\n'
        f'<port tag=":PPUALIGN" type="CONFIG" mask="7" defvalue="4" value="{alignment}"/>\n'
        "</input></system></mameconfig>\n"
    )


def mame_frames(rom: Path, frames: list[int], seconds: float = 600) -> dict[int, list[int]]:
    """{frame: colours (0xRRGGBB)}; a dump mame_nes refuses gives none. ``rom`` is a .nes file."""
    with tempfile.TemporaryDirectory(prefix="mame-nes-") as home:
        work = Path(home)
        (work / "cfg").mkdir()
        (work / "cfg" / "nes.cfg").write_text(config(ALIGNMENT))
        lua = LUA % (", ".join(f"[{f}]=true" for f in frames), max(frames))
        (work / "run.lua").write_text(lua)
        subprocess.run(
            [str(MAME_NES), "nes", "-cart", str(rom.resolve()), "-homepath", ".",
             "-cfg_directory", "cfg", "-video", "none", "-sound", "none", "-nothrottle",
             "-noreadconfig", "-skip_gameinfo", "-autoboot_script", "run.lua"],
            cwd=work, capture_output=True, timeout=seconds, check=False,
        )  # fmt: skip
        pictures = {}
        for frame in frames:
            path = work / f"frame{frame}.bin"
            if path.exists():
                data = path.read_bytes()
                pictures[frame] = [
                    int.from_bytes(data[i : i + 3], "little") for i in range(0, 4 * PIXELS, 4)
                ]
    return pictures
