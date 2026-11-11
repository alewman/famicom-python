#!/usr/bin/env python3
"""A PlayChoice-10 cabinet's two screens against MAME's ``playch10`` driver.

MAME 0.285 (``/usr/games/mame``; playch10.cpp is BSD-3) runs the sets the
images were assembled from (``scripts/pc10_images.py``; its ``manifest.json``
names each image's set and MAME's default DIP switches), with the BIOS, the
Z80 and both screens. The board's cabinet (``supervisor.PlayChoice``: the same
BIOS, the image's INST ROM and PROM) gets the same script, and both screens
are compared at chosen moments:

- the **menu screen** (MAME's ``top``) pixel for pixel as RGB: both colour it
  from the same three PROMs by the same weights, so equal means the BIOS drew
  the same characters in the same colours. MAME draws thirty rows and the
  schematic shows twenty-eight (C83): the comparison is of all thirty
  (``Supervisor.picture((0, 240))``), and what MAME has in the two rows the
  hardware blanks is counted separately (``hidden``);
- the **game screen** (``bottom``) as the RP2C03's DAC levels, three bits a
  channel, as ``scripts/vs_mame.py`` does; black while /DISP MASK is low.

**The script** (``--script play``), in sixtieths of a second since power, as
MAME counts frames: nothing until the BIOS's ten-second wait is over and its
menu is up (frame 700: the menu and the game's attract mode); a coin at 760
(frame 860: the time bought, the game dark); the cabinet's Enter button at 940
(frame 1100: the game's instructions above, the game started below); the
panel's Start at 1150 (frame 1400: the game under the player's Start).
``--script time`` sets the timer's DIP switches to 60 units a second (SW2 =
$05), buys 300 units and enters: frame 1100 has the time running, and five
seconds on it is gone: frame 1500 shows what each does with the game.

The two do not count time alike: MAME's Z80 is interrupted 60 times a second
and the board's 60.21 (C83), and MAME steps its 2A03 differently. So the
board's screens are tried at every sixtieth within ``--window`` of each
moment, the game's picture taken at the end of its frame, and the closest
reported, each screen its own (they run on separate clocks); a still screen
matches exactly or not at all.

    python scripts/pc10_mame.py --images DIR --out DIR [--only REGEX] [--script play]

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
from vs_mame import DEFAULT_ROMS, PIXELS, levels_of  # noqa: E402

from famicom_python.joypad import START  # noqa: E402
from famicom_python.ppu import HEIGHT  # noqa: E402
from famicom_python.supervisor import ENTER, Z80_HZ, PlayChoice, load_bios  # noqa: E402
from famicom_python.video import write_png  # noqa: E402

COIN = (760, 766, ":BIOS", "Coin 1")
ENTER_KEY = (940, 946, ":BIOS", "Enter")
#: name: (SW2 override or None, [(from, until, port, field)], frames judged)
SCRIPTS = {
    "play": (None, [COIN, ENTER_KEY, (1150, 1156, ":P1", "Start")], [700, 860, 1100, 1400]),
    "time": (0x05, [COIN, ENTER_KEY], [1100, 1500]),
}

LUA = """
local wanted, frame, last = {%(wanted)s}, 0, %(last)d
local presses = {%(presses)s}
local sw2 = %(sw2)s
local ports = manager.machine.ioport.ports
sub = emu.add_machine_frame_notifier(function()
  frame = frame + 1
  if frame == 1 and sw2 then
    for _, field in pairs(ports[":SW2"].fields) do
      field.user_value = sw2 & field.mask
    end
  end
  for _, p in ipairs(presses) do
    if frame == p[1] then ports[p[3]].fields[p[4]]:set_value(1) end
    if frame == p[2] then ports[p[3]].fields[p[4]]:set_value(0) end
  end
  if wanted[frame] then
    for _, tag in ipairs({"top", "bottom"}) do
      local out = io.open("frame" .. frame .. "." .. tag .. ".bin", "wb")
      out:write(manager.machine.screens[":" .. tag]:pixels())
      out:close()
    end
  end
  if frame == last then manager.machine:exit() end
end)
"""


def mame_screens(name: str, roms: Path, script: str, seconds: float = 600) -> dict:
    """{frame: (top as 0xRRGGBB per pixel, bottom as DAC levels)} of MAME's
    set ``name`` under ``script``, MAME's default DIP switches (and BIOS:
    the dual-monitor one)."""
    sw2, presses, frames = SCRIPTS[script]
    with tempfile.TemporaryDirectory(prefix="mame-pc10-") as home:
        work = Path(home)
        lua = LUA % {
            "wanted": ", ".join(f"[{f}]=true" for f in frames),
            "last": max(frames),
            "presses": ", ".join(
                f'{{{a}, {b}, "{port}", "{field}"}}' for a, b, port, field in presses
            ),
            "sw2": "nil" if sw2 is None else str(sw2),
        }
        (work / "run.lua").write_text(lua)
        command = [
            "mame", name, "-rompath", str(roms), "-homepath", ".", "-video", "none",
            "-sound", "none", "-nothrottle", "-noreadconfig", "-skip_gameinfo",
            "-nvram_directory", "nvram", "-cfg_directory", "cfg",
            "-autoboot_script", "run.lua",
        ]  # fmt: skip
        with contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run(command, cwd=work, capture_output=True, timeout=seconds, check=False)
        screens = {}
        for frame in frames:
            paths = [work / f"frame{frame}.{tag}.bin" for tag in ("top", "bottom")]
            if all(path.exists() for path in paths):
                top, bottom = (path.read_bytes() for path in paths)
                screens[frame] = (
                    [int.from_bytes(top[i : i + 3], "little") for i in range(0, 4 * PIXELS, 4)],
                    [
                        levels_of(int.from_bytes(bottom[i : i + 3], "little"))
                        for i in range(0, 4 * PIXELS, 4)
                    ],
                )
    return screens


class Cabinet:
    """The board's cabinet under a script: its two screens at a sixtieth."""

    def __init__(self, rom: Path, dips: dict, script: str) -> None:
        self.machine = PlayChoice.from_rom(rom, load_bios())
        sw2, presses, _ = SCRIPTS[script]
        self.machine.supervisor.dip = [
            dips.get("SW1", 0),
            dips.get("SW2", 0) if sw2 is None else sw2,
        ]
        self.presses = presses
        self.levels = dac_levels(self.machine.machine.timing.palette)
        self.sixtieth = 0

    def _inputs(self, sixtieth: int) -> None:
        machine = self.machine
        for start, end, port, field in self.presses:
            if sixtieth == start:
                if field == "Coin 1":
                    machine.insert_coin(0)
                elif field == "Enter":
                    machine.supervisor.buttons |= ENTER
                elif port == ":P1":
                    machine.game.board.pads[0].buttons |= START
            if sixtieth == end and port == ":P1":
                machine.game.board.pads[0].buttons &= ~START
            if sixtieth == end and field == "Enter":
                machine.supervisor.buttons &= ~ENTER

    def screens(self, sixtieth: int) -> tuple[list[int], list[int]]:
        """Run to ``sixtieth`` and return (top as 0xRRGGBB, bottom as DAC
        levels), the game's frame finished."""
        machine = self.machine
        supervisor = machine.supervisor
        while self.sixtieth < sixtieth:
            self.sixtieth += 1
            self._inputs(self.sixtieth)
            machine.run_seconds(self.sixtieth / 60 - supervisor.t / Z80_HZ)
        ppu = machine.game.board.ppu
        while not HEIGHT <= ppu.line < ppu.prerender_line:
            machine.step()
        rgb = supervisor.picture((0, HEIGHT))
        top = [int.from_bytes(rgb[i : i + 3], "big") for i in range(0, 3 * PIXELS, 3)]
        levels = self.levels
        return top, [levels[v & 0x1FF] for v in machine.game_picture()]


def check(job: tuple) -> dict:
    record, images, roms, script, window, out = job
    rom = images / record["file"]
    frames = SCRIPTS[script][2]
    theirs = mame_screens(record["set"], roms, script)
    cabinet = Cabinet(rom, record["dips"], script)
    result = {"rom": record["file"], "set": record["set"], "script": script, "frames": []}
    ours: dict[int, tuple[list[int], list[int]]] = {}
    for frame in frames:
        if frame not in theirs:
            result["frames"].append({"frame": frame, "error": "MAME gave no frame"})
            continue
        top, bottom = theirs[frame]
        # Each screen against the board's closest sixtieth, separately: the
        # two run on their own clocks, and MAME's menu screen on another (C83).
        best: list[tuple[int, int]] = []
        for screen, want in enumerate((top, bottom)):
            found = None
            for candidate in range(frame - window, frame + window + 1):
                if candidate not in ours:
                    ours[candidate] = cabinet.screens(candidate)
                diff = sum(a != b for a, b in zip(ours[candidate][screen], want, strict=True))
                if found is None or diff < found[1]:
                    found = (candidate, diff)
            assert found is not None
            best.append(found)
        entry = {
            "frame": frame,
            "ours": [best[0][0], best[1][0]],
            "top": best[0][1],
            "bottom": best[1][1],
            "top_colours": len(set(top)),
            "bottom_colours": len(set(bottom)),
            # What MAME draws in the rows the schematic's blank hides (C83).
            "hidden": sum(pixel != 0 for pixel in top[: 16 * 256]),
            "state": {
                "in_reset": cabinet.machine.in_reset,
                "stopped": cabinet.machine.stopped,
                "shown": cabinet.machine.game_shown,
            },
        }
        result["frames"].append(entry)
        if best[0][1] or best[1][1]:
            mine = (ours[best[0][0]][0], ours[best[1][0]][1])
            colour = [bytes(round(255 * (v >> s & 7) / 7) for s in (6, 3, 0)) for v in range(512)]
            picture = b"".join(
                b"\xff\x00\xff" if a != b else b.to_bytes(3, "big")
                for a, b in zip(mine[0], top, strict=True)
            ) + b"".join(
                b"\xff\x00\xff" if a != b else colour[b]
                for a, b in zip(mine[1], bottom, strict=True)
            )
            write_png(out / f"{rom.stem}.{script}.f{frame}.png", picture, 256, 480)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", type=Path, required=True, help="scripts/pc10_images.py's --out")
    parser.add_argument("--roms", type=Path, default=DEFAULT_ROMS)
    parser.add_argument("--only", help="regular expression on the image's name")
    parser.add_argument("--script", choices=sorted(SCRIPTS), default="play")
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if ROOT in args.out.resolve().parents:
        parser.error("--out must lie outside the repository")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.images / "manifest.json").read_text())
    records = [r for r in manifest if not args.only or re.search(args.only, r["file"])]
    jobs = [(r, args.images, args.roms, args.script, args.window, args.out) for r in records]
    results = []
    with multiprocessing.get_context("spawn").Pool(args.jobs) as pool:
        for result in pool.imap(check, jobs):
            results.append(result)
            summary = ", ".join(
                f"f{e['frame']}: " + (e["error"] if "error" in e else f"{e['top']}/{e['bottom']}")
                for e in result["frames"]
            )
            print(f"{result['rom']:55} {result['set']:10} {summary}", flush=True)
    (args.out / f"mame-{args.script}.json").write_text(json.dumps(results, indent=1) + "\n")
    same = sum(
        all(e.get("top") == 0 and e.get("bottom") == 0 for e in r["frames"]) for r in results
    )
    print(f"{same} of {len(results)} images match MAME on both screens at every frame")
    return 0


if __name__ == "__main__":
    sys.exit(main())
