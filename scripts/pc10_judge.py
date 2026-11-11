#!/usr/bin/env python3
"""The same buttons at the same CPU cycles: a PlayChoice-10 game's inputs for both sides.

Mesen2 (a detector, docs/validation.md) runs a PlayChoice-10 image as its game
board alone: an NES with the RP2C03's colours, the INST ROM and the PROM
ignored. That is the board's ``playchoice`` row without its supervisor
(``System``), so the two can be compared frame for frame, and to get past a
title screen both need the same buttons on the same reads. As
``scripts/vs_judge.py`` does for the Vs. System, the inputs are a
:class:`vs_judge.Script` on the CPU's cycle count:

- the board's panel registers follow the cycle count (:class:`ScriptedPad`,
  a ``playchoice.PlayChoicePad``: player 2 has no Start or Select);
- Mesen2's ``$4016``/``$4017`` reads have their D0 *replaced*, read for read,
  by a Lua model of a shift register that the script keeps (:func:`lua`):
  loaded while a ``$4016`` write's bit 0 is high, shifted by each read, 1 after
  eight bits. D1-D7 stay Mesen2's (a gun game's D3 and D4 are held at
  "no light, no trigger" on both).

So Mesen2 judges the CPU, the PPU, the mapper and the colours; the panel's
wiring is the schematic's word, not Mesen2's.
"""

from __future__ import annotations

from vs_judge import Script, at

from famicom_python.joypad import SELECT, START, A
from famicom_python.playchoice import PlayChoiceGun, PlayChoicePad
from famicom_python.system import System

#: Start twice (a title screen, then a menu), then A on both players' buttons,
#: then Start again: enough to leave most title screens.
PLAY = Script(
    presses=(
        (0, START, at(300), at(308)),
        (0, START, at(420), at(428)),
        (0, A, at(540), at(550)),
        (1, A, at(540), at(550)),
        (0, START, at(660), at(668)),
    ),
)
ATTRACT = Script()


class ScriptedPad(PlayChoicePad):
    """A panel register whose buttons are a script's at the board's cycle count."""

    def __init__(self, board, port: int, script: Script) -> None:  # type: ignore[no-untyped-def]
        super().__init__(select_start=not port)
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


def apply(system: System, script: Script) -> None:
    """Give the board ``script``."""
    board = system.board
    pads = [ScriptedPad(board, port, script) for port in (0, 1)]
    if isinstance(board.pads[1], PlayChoiceGun):
        board.pads[1].pad = pads[1]  # the gun stays beside player 2's register
        pads[1] = board.pads[1]
    board.pads = pads


PORTS_LUA = """
local presses = {%(presses)s}
local wired = {[0] = 0xFF, [1] = %(wired1)d}
local shift = {[0] = 0, [1] = 0}
local strobe = false
local function cycle() return emu.getState()["cpu.cycleCount"] end
local function buttons(port, now)
  local pressed = 0
  for _, p in ipairs(presses) do
    if p[1] == port and p[3] <= now and now < p[4] then pressed = pressed | p[2] end
  end
  return pressed & wired[port]
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
  local bit
  if strobe then
    shift[port] = buttons(port, cycle())
    bit = shift[port] & 1
  else
    bit = shift[port] & 1
    shift[port] = (shift[port] >> 1) | 0x80
  end
  if port == 1 and %(gun)s then return (value & 0xE6) | 0x08 | bit end
  return (value & 0xFE) | bit
end, emu.callbackType.read, 0x4016, 0x4017)
"""


def lua(script: Script, gun: bool = False) -> str:
    """The Lua that makes D0 of Mesen2's $4016/$4017 the panel's under ``script``;
    ``gun``: $4017's D3 and D4 too, a gun that sees no light and is not fired
    (as the board's with nothing aimed)."""
    return PORTS_LUA % {
        "gun": "true" if gun else "false",
        "presses": ", ".join("{{{}, {}, {}, {}}}".format(*press) for press in script.presses),
        "wired1": 0xFF & ~(SELECT | START),
    }
