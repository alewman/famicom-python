#!/usr/bin/env python3
"""A Vs. game's attract screens against MAME's ``vsnes`` driver (a second detector).

MAME 0.285 (``/usr/games/mame``; vsnes.cpp is BSD-3) runs the sets the images
were assembled from (``scripts/vs_images.py``; its ``manifest.json`` names each
image's set and MAME's default DIP switches). Headless, a Lua script saves the
screen at chosen frames, and the board's frames near each are compared with it
as DAC levels, three bits a channel: MAME colours an RGB PPU from its own
palette ROM dump (``rp2c0x.pal``), so this judges the board's palette tables
and its picture by a detector that shares no code with Mesen2.

MAME is not cycle-accurate here and counts frames its own way, so the board's
frames within ``--window`` either side are tried and the closest reported; an
attract screen that stands still for a second matches exactly or not at all.
No coin is inserted: MAME and the board time one differently.

A DualSystem image (``--dual``) is judged on both screens, MAME's ``screen1``
against the primary side and ``screen2`` against the secondary, the two sides'
DIP switches MAME's ``DSW0`` and ``DSW1``; a frame's difference is the two
screens' together. *Raid on Bungeling Bay* is a one-screen set in MAME (its
second CPU is not emulated there): MAME's screen against the board's secondary
side, where the game runs.

    python scripts/vs_mame.py --images DIR [--only REGEX] [--frames 180,420,900]

Nothing it writes is committed (``--out``, a directory outside the repository).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import multiprocessing
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vs_judge import dac_levels  # noqa: E402

from famicom_python.dual import VsDualSystem, is_dual  # noqa: E402
from famicom_python.ppu import HEIGHT  # noqa: E402
from famicom_python.system import System  # noqa: E402
from famicom_python.video import write_png  # noqa: E402

DEFAULT_ROMS = Path("/data/emu/source/myrient.erista.me/files/MAME/ROMs (non-merged)")
PIXELS = 256 * 240

LUA = """
local wanted, frame, last = {%s}, 0, %d
sub = emu.add_machine_frame_notifier(function()
  frame = frame + 1
  if wanted[frame] then
    for number = 1, %d do
      local pixels = manager.machine.screens[":screen" .. number]:pixels()
      local out = io.open("frame" .. frame .. "." .. number .. ".bin", "wb")
      out:write(pixels)
      out:close()
    end
  end
  if frame == last then manager.machine:exit() end
end)
"""


def levels_of(rgb: int) -> int:
    """A 0xRRGGBB colour as DAC levels 0oRGB."""
    return (
        round((rgb >> 16 & 0xFF) * 7 / 255) << 6
        | round((rgb >> 8 & 0xFF) * 7 / 255) << 3
        | round((rgb & 0xFF) * 7 / 255)
    )


def mame_frames(
    name: str, roms: Path, frames: list[int], screens: int = 1, seconds: float = 600
) -> dict:
    """{frame: DAC levels per pixel, screen after screen} of MAME's set
    ``name``, default DIP switches."""
    with tempfile.TemporaryDirectory(prefix="mame-vs-") as home:
        work = Path(home)
        lua = LUA % (", ".join(f"[{f}]=true" for f in frames), max(frames), screens)
        (work / "run.lua").write_text(lua)
        command = [
            "mame", name, "-rompath", str(roms), "-homepath", ".", "-video", "none",
            "-sound", "none", "-nothrottle", "-noreadconfig", "-skip_gameinfo",
            "-nvram_directory", "nvram", "-cfg_directory", "cfg",
            "-autoboot_script", "run.lua",
        ]  # fmt: skip
        with contextlib.suppress(subprocess.TimeoutExpired):  # no frames: reported as such
            subprocess.run(command, cwd=work, capture_output=True, timeout=seconds, check=False)
        pictures = {}
        for frame in frames:
            paths = [work / f"frame{frame}.{n}.bin" for n in range(1, screens + 1)]
            if all(path.exists() for path in paths):
                pictures[frame] = [
                    levels_of(int.from_bytes(data[i : i + 3], "little"))
                    for data in (path.read_bytes() for path in paths)
                    for i in range(0, 4 * PIXELS, 4)
                ]
    return pictures


class Cabinet:
    """One image running, UniSystem or DualSystem: its frames as DAC levels."""

    def __init__(self, rom: Path, dips: dict) -> None:
        self.dual = is_dual(rom)
        if self.dual:
            self.system = VsDualSystem.from_rom(rom)
            self.sides = list(self.system.sides)
            self.machine = self.system.machine
        else:
            self.machine = System.machine_for(rom)
            self.system = System.from_rom(rom, self.machine)
            self.system.plug()
            self.sides = [self.system]
        for side, tag in zip(self.sides, ("DSW0", "DSW1"), strict=False):
            side.board.vs.dip = dips.get(tag, 0)
        #: The sides whose screens are judged.
        self.shown = self.sides
        if self.dual and self.sides[0].loaded.image.board.vs_hardware == 6:
            self.sides[1].board.vs.dip = dips.get("DSW0", 0)
            self.shown = self.sides[1:]
        self.levels = dac_levels(self.machine.timing.palette)

    def frame(self, number: int) -> list[int]:
        """Run to frame ``number`` and return its picture(s), finished."""
        self.system.run_frames(number - self.sides[0].board.ppu.frame)
        ppu = self.sides[0].board.ppu
        while not HEIGHT <= ppu.line < ppu.prerender_line:
            self.system.step()
        levels = self.levels
        return [levels[v & 0x1FF] for side in self.shown for v in side.board.ppu.picture]


def check(job: tuple) -> dict:
    record, images, roms, frames, window, out = job
    rom = images / record["file"]
    cabinet = Cabinet(rom, record["dips"])
    screens = len(cabinet.shown)
    theirs = mame_frames(record["set"], roms, frames, screens)
    ppu = cabinet.machine.ppu_variant
    result = {"rom": record["file"], "set": record["set"], "ppu": ppu, "frames": []}
    ours: dict[int, list[int]] = {}
    for frame in frames:
        if frame not in theirs:
            result["frames"].append({"frame": frame, "error": "MAME gave no frame"})
            continue
        want = theirs[frame]
        best = None
        for candidate in range(max(1, frame - window), frame + window + 1):
            if candidate not in ours:
                ours[candidate] = cabinet.frame(candidate)
            diff = sum(a != b for a, b in zip(ours[candidate], want, strict=True))
            if best is None or diff < best[1]:
                best = (candidate, diff)
        assert best is not None
        entry = {"frame": frame, "ours": best[0], "diff": best[1], "colours": len(set(want))}
        result["frames"].append(entry)
        if best[1]:
            colour = [bytes(round(255 * (v >> s & 7) / 7) for s in (6, 3, 0)) for v in range(512)]
            picture = b"".join(
                b"\xff\x00\xff" if a != b else colour[b]
                for a, b in zip(ours[best[0]], want, strict=True)
            )
            write_png(out / f"{rom.stem}.mame.f{frame}.png", picture, 256, 240 * screens)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", type=Path, required=True, help="scripts/vs_images.py's --out")
    parser.add_argument("--roms", type=Path, default=DEFAULT_ROMS)
    parser.add_argument("--only", help="regular expression on the image's name")
    parser.add_argument("--frames", default="180,420,900")
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--dual", action="store_true", help="the DualSystem images instead")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if ROOT in args.out.resolve().parents:
        parser.error("--out must lie outside the repository")
    args.out.mkdir(parents=True, exist_ok=True)
    frames = sorted(int(f) for f in args.frames.split(","))
    manifest = json.loads((args.images / "manifest.json").read_text())
    records = [
        r
        for r in manifest
        if (r["vs_hardware"] >= 5) == args.dual
        and (not args.only or re.search(args.only, r["file"]))
    ]
    results = []
    jobs = [(r, args.images, args.roms, frames, args.window, args.out) for r in records]
    with multiprocessing.get_context("spawn").Pool(args.jobs) as pool:
        for result in pool.imap(check, jobs):
            results.append(result)
            summary = ", ".join(
                f"f{e['frame']}: {e.get('diff', e.get('error'))}" for e in result["frames"]
            )
            print(f"{result['rom']:55} {result['set']:14} {result['ppu']:12} {summary}", flush=True)
    (args.out / ("mame-dual.json" if args.dual else "mame.json")).write_text(
        json.dumps(results, indent=1) + "\n"
    )
    same = sum(all(e.get("diff") == 0 for e in r["frames"]) for r in results)
    print(f"{same} of {len(results)} images match MAME at every frame")
    return 0


if __name__ == "__main__":
    sys.exit(main())
