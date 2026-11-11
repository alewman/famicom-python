#!/usr/bin/env python3
"""One coin, one start button, the same DIP switches: a Vs. game's inputs for both sides.

A Vs. System game shows its attract mode until a coin drops, and Mesen2 (a
detector, docs/validation.md) has its own DIP switch defaults and its own way
of inserting coins. For a comparison both sides must see the same $4016 and
$4017, read for read. So the inputs are a :class:`Script` on the CPU's cycle
count, which the two sides share exactly (a read of $4016 falls on the same
cycle number in both: measured, ``scripts/vs_judge.py --probe``):

- the board gets it through its own mainboard (``vs.VsMainboard``: DIP
  switches, a coin pulse placed on the master clock) and sticks whose buttons
  follow the cycle count (:class:`ScriptedStick`);
- Mesen2 gets it from a Lua read callback on $4016/$4017 that *replaces* the
  byte Mesen2 would return with the mainboard's as Vs._System.wiki draws it
  (:func:`lua`): serial data from a shift register the script keeps (latched
  while a $4016 write's bit 0 is high, shifted by each read), the service
  button, the DIP switches, the coin contact, the side.

So Mesen2 judges the CPU, the PPU and the ROM banking of a run; what the port
bits *are* is the wiki's and MAME's word, not Mesen2's (its own power-on values
are printed by ``--probe``: all DIP switches off, D7 = 0; the board's D7 is the
row's ``vs_side``, C75, and the script gives Mesen2 the same).

Frames come back as RGB: Mesen2 colours a Vs. game through its own table for
the game's PPU, whatever user palette it is given, so the two pictures are
compared as DAC levels, three bits a channel (:func:`dac_levels`): the palette
tables are judged with the picture.

    python scripts/vs_judge.py --probe IMAGE      # Mesen2's own first port reads
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from mesen_run import ALPHABET, ROOT, decode_frames, run_mesen

from famicom_python.joypad import SELECT, START, UP, A
from famicom_python.machine import Machine
from famicom_python.system import System
from famicom_python.video import RGB_DAC
from famicom_python.vs import COIN_SECONDS, VS_ZAPPER, VsStick

#: CPU cycles in a frame of an RGB PPU (no skipped dot): 341 * 262 / 3.
FRAME = 341 * 262 / 3
CPU_HZ = 236.25e6 / 11 / 12
COIN_CYCLES = round(COIN_SECONDS * CPU_HZ)


def at(frame: float) -> int:
    """The CPU cycle count at which frame ``frame`` begins, about."""
    return round(frame * FRAME)


@dataclass(frozen=True)
class Script:
    """A game's inputs, in CPU cycles since power.

    ``coins``: when a coin's contact closes (acceptor 1, $4016 D5), for 50 ms.
    ``presses``: (port, buttons, from, until), ``joypad`` bits on the stick of
    $4016 (port 0) or $4017.
    """

    dip: int = 0
    coins: tuple[int, ...] = ()
    presses: tuple[tuple[int, int, int, int], ...] = ()


#: The default: two coins (some games' default coinage wants no more), then the
#: panel's button 1 (a one-player game) twice, then button A on both sticks.
PLAY = Script(
    coins=(at(240), at(270)),
    presses=(
        (0, SELECT, at(400), at(408)),
        (0, SELECT, at(520), at(528)),
        (0, A, at(640), at(650)),
        (1, A, at(640), at(650)),
    ),
)
ATTRACT = Script()


class ScriptedStick(VsStick):
    """A stick whose buttons are a :class:`Script`'s at the board's cycle count."""

    def __init__(self, board, port: int, script: Script, held: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(held)
        self._board = board
        self._presses = [p[1:] for p in script.presses if p[0] == port]

    @property
    def buttons(self) -> int:
        cycle = self._board.cycles
        pressed = 0
        for buttons, start, end in self._presses:
            if start <= cycle < end:
                pressed |= buttons
        return pressed

    @buttons.setter
    def buttons(self, value: int) -> None:
        pass


def held_bits(system: System) -> tuple[int, int]:
    """The report bits a game's cabinet holds on: the protection jumper of
    hardware types 4 and 6 (vs.VsStick), the Vs. Zapper's "Up" with no light
    and no trigger (vs.VsZapper)."""
    board = system.loaded.image.board
    if board.expansion == VS_ZAPPER:
        return UP, 0
    jumper = START if board.vs_hardware in (4, 6) else 0
    return jumper, jumper


def side_of(machine: Machine) -> int:
    """$4016 D7 of ``machine``'s side of the mainboard."""
    return int(machine.vs_side == "secondary")


def apply(system: System, script: Script) -> None:
    """Give the board ``script``."""
    board = system.board
    held = held_bits(system)
    board.pads = [ScriptedStick(board, port, script, held[port]) for port in (0, 1)]
    vs = board.vs
    vs.dip = script.dip
    for cycle in script.coins:
        vs.insert_coin(0, at=cycle * board.cycle_ticks)


def judged_machine(machine: Machine) -> Machine:
    """``machine`` on Mesen2's power-on (scripts/mesen_lockstep.py ``MACHINE``)."""
    return replace(
        machine, power_on=replace(machine.power_on, ppustatus=0x00, ppu_dot=4, dmc_timer=213)
    )


# -- Mesen2's side -----------------------------------------------------------

PORTS_LUA = """
local dip, side = %(dip)d, %(side)d
local coins = {%(coins)s}
local presses = {%(presses)s}
local held = {[0] = %(held0)d, [1] = %(held1)d}
local shift = {[0] = 0, [1] = 0}
local strobe = false
local function cycle() return emu.getState()["cpu.cycleCount"] end
local function buttons(port, now)
  local pressed = held[port]
  for _, p in ipairs(presses) do
    if p[1] == port and p[3] <= now and now < p[4] then pressed = pressed | p[2] end
  end
  return pressed
end
emu.addMemoryCallback(function(address, value)
  if address ~= 0x4016 then return end
  local high = (value & 1) == 1
  if high or strobe then
    local now = cycle()
    shift[0], shift[1] = buttons(0, now), buttons(1, now)
  end
  strobe = high
end, emu.callbackType.write, 0x4016, 0x4016)
emu.addMemoryCallback(function(address, value)
  local port = address - 0x4016
  local now = cycle()
  local bit
  if strobe then
    shift[port] = buttons(port, now)
    bit = shift[port] & 1
  else
    bit = shift[port] & 1
    shift[port] = (shift[port] >> 1) | 0x80
  end
  if port == 1 then return bit | (dip & 0xFC) end
  local byte = bit | ((dip & 3) << 3) | (side << 7)
  for _, start in ipairs(coins) do
    if start <= now and now < start + %(coin)d then byte = byte | 0x20 end
  end
  return byte
end, emu.callbackType.read, 0x4016, 0x4017)
"""

# A frame as DAC levels (each channel of Mesen2's colour to its nearest of
# eight, 0oRGB), two characters a pixel, in the numbered lines
# scripts/mesen_run.py's ``run_mesen(collect=...)`` gathers and
# ``decode_frames`` reads. (Whole colours would be four characters, and a frame
# then outruns the 500 lines the script log keeps.)
LEVEL_FRAMES_LUA = """
local wanted, frame, last = {%s}, 0, %d
local alphabet = "ALPHABET"
local digit = {}
for i = 1, 64 do digit[i - 1] = alphabet:sub(i, i) end
local function level(c) return (c * 14 + 255) // 510 end
emu.addEventCallback(function()
  frame = frame + 1
  if wanted[frame] then
    local buffer = emu.getScreenBuffer()
    local parts = {}
    for i = 1, #buffer do
      local v = buffer[i]
      parts[i] = digit[level((v >> 16) & 255)]
        .. digit[level((v >> 8) & 255) << 3 | level(v & 255)]
    end
    local all = table.concat(parts)
    local count = 0
    for at = 1, #all, 280 do
      emu.log("L" .. frame .. "." .. count .. " " .. all:sub(at, at + 279))
      count = count + 1
    end
    emu.log("E" .. frame .. " " .. count)
  end
  if frame == last then emu.log("DONE") end
end, emu.eventType.endFrame)
""".replace("ALPHABET", ALPHABET)


def lua(script: Script, held: tuple[int, int], side: int = 0) -> str:
    """The Lua that makes Mesen2's $4016/$4017 the mainboard's under ``script``."""
    return PORTS_LUA % {
        "dip": script.dip,
        "side": side,
        "coins": ", ".join(str(c) for c in script.coins),
        "presses": ", ".join("{{{}, {}, {}, {}}}".format(*press) for press in script.presses),
        "held0": held[0],
        "held1": held[1],
        "coin": COIN_CYCLES,
    }


def dac_levels(chip: str) -> list[int]:
    """The board's 512 picture values as an RGB PPU's DAC levels, 0oRGB
    (video.rgb_palette without the scaling)."""
    levels = []
    for emphasis in range(8):
        force = (7 << 6 if emphasis & 1 else 0) | (7 << 3 if emphasis & 2 else 0)
        force |= 7 if emphasis & 4 else 0
        levels += [value | force for value in RGB_DAC[chip]]
    return levels


def mesen_level_frames(
    rom: Path,
    frames: list[int],
    script: Script,
    held: tuple[int, int],
    home: Path,
    ppu_reset_at_power: bool = True,
    side: int = 0,
    seconds: float = 900,
) -> dict[int, list[int]]:
    """Mesen2's frames ``frames`` of ``rom`` under ``script``, as DAC levels."""
    text = lua(script, held, side) + LEVEL_FRAMES_LUA % (
        ", ".join(f"[{f}]=true" for f in frames),
        max(frames),
    )
    lines: dict[str, str] = {}
    run_mesen(
        rom,
        lua=text.encode(),
        lua_name="vs.lua",
        seconds=seconds,
        home=home,
        until="DONE",
        for_comparison=True,
        ppu_reset_at_power=ppu_reset_at_power,
        collect=lines,
        oam_row_corruption=False,  # the RGB PPUs have none (C76)
    )
    return decode_frames(lines)


PROBE_LUA = """
local n, frames = 0, 0
emu.addMemoryCallback(function(address, value)
  n = n + 1
  if n <= 8 then
    emu.log(string.format("read $%04X = $%02X at cycle %d", address, value,
      emu.getState()["cpu.cycleCount"]))
  end
end, emu.callbackType.read, 0x4016, 0x4017)
emu.addEventCallback(function()
  frames = frames + 1
  if frames == 60 then emu.log("DONE") end
end, emu.eventType.endFrame)
"""


def probe(rom: Path) -> None:
    """Mesen2's own first reads of $4016/$4017, and the board's, with their cycles."""
    machine = judged_machine(System.machine_for(rom))
    system = System.from_rom(rom, machine)
    seen: list[str] = []

    def observe(kind: str, address: int, value: int, t: int) -> None:
        if kind == "read" and address in (0x4016, 0x4017) and len(seen) < 8:
            seen.append(f"read ${address:04X} = ${value:02X} at cycle {system.board.cycles}")

    system.board.bus_observers.append(observe)
    system.run_frames(60)
    print("the board:", *seen, sep="\n  ")
    with tempfile.TemporaryDirectory(prefix="mesen-home-") as home:
        _, log, _ = run_mesen(
            rom,
            lua=PROBE_LUA.encode(),
            seconds=60,
            home=Path(home),
            until="DONE",
            for_comparison=True,
            ppu_reset_at_power=machine.ppu_reset_at_power,
            oam_row_corruption=False,
        )
    print("Mesen2:", *[line for line in log.splitlines() if line.startswith("read")], sep="\n  ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--probe", type=Path, metavar="IMAGE", required=True)
    args = parser.parse_args()
    probe(args.probe)
    return 0


if __name__ == "__main__":
    assert ROOT
    sys.exit(main())
